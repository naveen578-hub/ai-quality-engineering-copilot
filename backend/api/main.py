"""
AI QE Copilot — backend entrypoint (Phase 1: Minimum Viable Product).

Run locally:
    uvicorn backend.api.main:app --reload --port 8000

Then:
    curl -X POST http://localhost:8000/api/v1/generate-test-cases \
      -H "Content-Type: application/json" \
      -d '{"requirement_text": "The system shall allow an authorized user to search for a patient by member ID and view the patient record.", "requirement_id": "REQ-001"}'
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.security import OAuth2PasswordRequestForm

from backend.auth.dependencies import ADMIN_ONLY, ANY_ROLE, WRITE_ROLES, get_current_user, require_roles
from backend.auth.security import create_access_token
from backend.auth.users import AuthError, authenticate, create_user, list_users, seed_default_admin_if_empty
from backend.generators.api_test_generator import generate_api_test_cases
from backend.generators.export import to_csv, to_json
from backend.generators.llm_client import is_configured
from backend.generators.rag_generator import RagGenerationError, generate_from_rag
from backend.generators.requirement_analysis import analyze_requirements
from backend.generators.sql_validation_generator import SqlGenerationError, generate_sql_validations
from backend.generators.test_case_generator import GenerationError, generate_test_cases
from backend.generators.traceability import build_traceability_matrix
from backend.guardrails.pii import scan_and_mask
from backend.models import db
from backend.models.schemas import (
    ApiTestGenerateRequest,
    CreateUserRequest,
    DocumentSummary,
    DocumentUploadResponse,
    EndpointSummary,
    GenerateTestCasesRequest,
    HealthResponse,
    HelpChatRequest,
    HelpChatResponse,
    OpenApiSpecSummary,
    OpenApiUploadResponse,
    PersistedTestCase,
    RagGenerateRequest,
    RagGenerateResponse,
    RequirementAnalysisResponse,
    Role,
    SaveTestCasesRequest,
    SqlValidationRequest,
    SqlValidationResponse,
    TestCaseResponse,
    TestCaseStatus,
    TokenResponse,
    TraceabilityMatrix,
    UpdateTestCaseRequest,
    UsageSummary,
    UserOut,
    VisualCompareResponse,
)
from backend.observability.usage import get_usage_summary
from backend.rag import openapi_store, store
from backend.rag.extractor import ExtractionError
from backend.rag.ingest import ingest_document
from backend.rag.openapi_parser import OpenApiParseError, parse_spec

from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan(app: FastAPI):
    seed_default_admin_if_empty()
    yield


app = FastAPI(
    title="AI QE Copilot API",
    description="Generates structured, traceable test cases from software requirements.",
    version="0.1.0",
    lifespan=_lifespan,
)

# Wide open for local dev / portfolio demo. Tighten this before any real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/v1/help/chat", response_model=HelpChatResponse, tags=["help"])
def help_chat(payload: HelpChatRequest) -> HelpChatResponse:
    """Answers product-usage questions without exposing application data or secrets."""
    from backend.generators.help_chat import answer_help_question

    return answer_help_question(payload)


@app.post(
    "/api/v1/visual-compare",
    response_model=VisualCompareResponse,
    tags=["visual-compare"],
    dependencies=[Depends(require_roles(*WRITE_ROLES))],
)
async def visual_compare(
    reference: UploadFile = File(...),
    url: str = Form(...),
    viewport_width: int = Form(..., ge=320, le=3840),
    viewport_height: int = Form(..., ge=240, le=2160),
    expected_text: str = Form(default=""),
    numeric_values: str = Form(default=""),
    flyout_selector: Optional[str] = Form(default=None),
    expected_flyout_text: Optional[str] = Form(default=None),
    pagination_selector: Optional[str] = Form(default=None),
    expected_page: Optional[str] = Form(default=None),
) -> VisualCompareResponse:
    from backend.generators.visual_compare import compare_visual_reference

    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="The live URL must start with http:// or https://.")
    reference_bytes = await reference.read()
    if not reference_bytes:
        raise HTTPException(status_code=400, detail="The Figma reference image is empty.")
    try:
        return compare_visual_reference(
            reference_bytes,
            url,
            viewport_width,
            viewport_height,
            expected_text,
            numeric_values,
            flyout_selector,
            expected_flyout_text,
            pagination_selector,
            expected_page,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Visual comparison failed: {exc}") from exc


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    from backend.rag.embeddings import embedding_mode

    return HealthResponse(
        status="ok",
        mode="llm" if is_configured() else "mock",
        embedding_mode=embedding_mode(),
    )


# ---- Phase 4: authentication ----


@app.post("/api/v1/auth/login", response_model=TokenResponse, tags=["auth"])
def login(form_data: OAuth2PasswordRequestForm = Depends()) -> TokenResponse:
    user = authenticate(form_data.username, form_data.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Incorrect username or password", headers={"WWW-Authenticate": "Bearer"})
    token = create_access_token(subject=user.username, role=user.role.value)
    return TokenResponse(access_token=token, role=user.role, username=user.username)


@app.get("/api/v1/auth/me", response_model=UserOut, tags=["auth"])
def get_me(current_user: UserOut = Depends(get_current_user)) -> UserOut:
    return current_user


@app.post("/api/v1/auth/users", response_model=UserOut, tags=["auth"], dependencies=[Depends(require_roles(*ADMIN_ONLY))])
def create_new_user(payload: CreateUserRequest) -> UserOut:
    try:
        return create_user(payload.username, payload.password, payload.role)
    except AuthError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v1/auth/users", response_model=List[UserOut], tags=["auth"], dependencies=[Depends(require_roles(*ADMIN_ONLY))])
def get_all_users() -> List[UserOut]:
    return list_users()


@app.post(
    "/api/v1/generate-test-cases",
    response_model=TestCaseResponse,
    tags=["generation"],
    dependencies=[Depends(require_roles(*WRITE_ROLES))],
)
def generate_test_cases_endpoint(payload: GenerateTestCasesRequest) -> TestCaseResponse:
    """
    Phase 1 core endpoint: takes raw requirement text (no RAG yet — that's Phase 2)
    and returns positive/negative/boundary/api/regression test cases as validated JSON.
    """
    masked_text, _counts = scan_and_mask(payload.requirement_text)
    payload = payload.model_copy(update={"requirement_text": masked_text})
    try:
        return generate_test_cases(payload)
    except GenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ---- Phase 2: documents + RAG ----

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB


@app.post(
    "/api/v1/documents",
    response_model=DocumentUploadResponse,
    tags=["documents"],
    dependencies=[Depends(require_roles(*WRITE_ROLES))],
)
async def upload_document(file: UploadFile = File(...)) -> DocumentUploadResponse:
    """
    Extracts text, chunks it (requirement-aware where "REQ-###:" markers are
    present, paragraph-based otherwise), embeds each chunk, and stores it in
    ChromaDB so it can be retrieved by /api/v1/generate-test-cases/from-documents.
    Any PII-shaped content (SSNs, emails, phone numbers, credit-card numbers)
    is masked before anything is embedded or stored — see backend/guardrails/pii.py.
    """
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 20 MB).")
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        return ingest_document(file.filename or "unnamed", content)
    except ExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get(
    "/api/v1/documents",
    response_model=List[DocumentSummary],
    tags=["documents"],
    dependencies=[Depends(require_roles(*ANY_ROLE))],
)
def list_documents() -> List[DocumentSummary]:
    return [DocumentSummary(**d) for d in store.list_documents()]


@app.post(
    "/api/v1/generate-test-cases/from-documents",
    response_model=RagGenerateResponse,
    tags=["generation"],
    dependencies=[Depends(require_roles(*WRITE_ROLES))],
)
def generate_test_cases_from_documents(payload: RagGenerateRequest) -> RagGenerateResponse:
    """
    Phase 2 endpoint: retrieves the most relevant chunks for `query` from
    previously uploaded documents, generates test cases grounded in them,
    and returns both the test cases and the chunks that were retrieved —
    every returned test case's citation is verified against a real stored chunk.
    """
    masked_query, _counts = scan_and_mask(payload.query)
    payload = payload.model_copy(update={"query": masked_query})
    try:
        return generate_from_rag(payload)
    except RagGenerationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---- Phase 3: persistence, approval workflow, traceability, duplicate detection ----


@app.post(
    "/api/v1/test-cases",
    response_model=List[PersistedTestCase],
    tags=["library"],
    dependencies=[Depends(require_roles(*WRITE_ROLES))],
)
def save_test_cases(payload: SaveTestCasesRequest) -> List[PersistedTestCase]:
    """Persists a batch of generated test cases (e.g. everything currently shown
    in the results table) into the reviewable library, as drafts."""
    return db.save_test_cases(payload.test_cases, document_id=payload.document_id)


@app.get(
    "/api/v1/test-cases",
    response_model=List[PersistedTestCase],
    tags=["library"],
    dependencies=[Depends(require_roles(*ANY_ROLE))],
)
def list_saved_test_cases(
    status: Optional[TestCaseStatus] = Query(default=None),
    requirement_reference: Optional[str] = Query(default=None),
    document_id: Optional[str] = Query(default=None),
) -> List[PersistedTestCase]:
    return db.list_test_cases(status=status, requirement_reference=requirement_reference, document_id=document_id)


@app.patch("/api/v1/test-cases/{db_id}", response_model=PersistedTestCase, tags=["library"])
def update_saved_test_case(
    db_id: int,
    payload: UpdateTestCaseRequest,
    current_user: UserOut = Depends(require_roles(*WRITE_ROLES)),
) -> PersistedTestCase:
    """Edits a saved test case's content, and/or its status (approve/reject).
    Moving a test case to 'approved' specifically requires the admin role —
    testers can edit content and mark things rejected, but sign-off is an
    admin action."""
    if payload.status == TestCaseStatus.approved and current_user.role != Role.admin:
        raise HTTPException(status_code=403, detail="Only admins can approve a test case.")

    updated = db.update_test_case(db_id, payload)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"No saved test case with id {db_id}")
    return updated


@app.delete(
    "/api/v1/test-cases/{db_id}",
    status_code=204,
    response_model=None,
    tags=["library"],
    dependencies=[Depends(require_roles(*ADMIN_ONLY))],
)
def delete_saved_test_case(db_id: int) -> None:
    if not db.delete_test_case(db_id):
        raise HTTPException(status_code=404, detail=f"No saved test case with id {db_id}")


@app.get(
    "/api/v1/traceability-matrix",
    response_model=TraceabilityMatrix,
    tags=["library"],
    dependencies=[Depends(require_roles(*ANY_ROLE))],
)
def traceability_matrix() -> TraceabilityMatrix:
    """Cross-references every requirement seen across uploaded documents against
    saved test cases, showing which test-case types exist and which are missing."""
    return build_traceability_matrix()


@app.get(
    "/api/v1/requirements/analysis",
    response_model=RequirementAnalysisResponse,
    tags=["library"],
    dependencies=[Depends(require_roles(*ANY_ROLE))],
)
def requirement_analysis() -> RequirementAnalysisResponse:
    """Flags likely-duplicate and likely-conflicting requirements across all
    indexed documents. Heuristic-based — see backend/generators/requirement_analysis.py
    for exactly what is and isn't detected."""
    return analyze_requirements()


@app.get("/api/v1/export/csv", tags=["library"], dependencies=[Depends(require_roles(*ANY_ROLE))])
def export_csv(status: Optional[TestCaseStatus] = Query(default=None)) -> Response:
    test_cases = db.list_test_cases(status=status)
    csv_body = to_csv(test_cases)
    return Response(
        content=csv_body,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=test-cases.csv"},
    )


@app.get("/api/v1/export/json", tags=["library"], dependencies=[Depends(require_roles(*ANY_ROLE))])
def export_json(status: Optional[TestCaseStatus] = Query(default=None)) -> Response:
    test_cases = db.list_test_cases(status=status)
    json_body = to_json(test_cases)
    return Response(
        content=json_body,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=test-cases.json"},
    )


# ---- Phase 3: OpenAPI-driven API test generation ----

MAX_SPEC_BYTES = 5 * 1024 * 1024  # 5 MB


@app.post(
    "/api/v1/openapi/specs",
    response_model=OpenApiUploadResponse,
    tags=["api-tests"],
    dependencies=[Depends(require_roles(*WRITE_ROLES))],
)
async def upload_openapi_spec(file: UploadFile = File(...)) -> OpenApiUploadResponse:
    content = await file.read()
    if len(content) > MAX_SPEC_BYTES:
        raise HTTPException(status_code=413, detail="Spec file too large (max 5 MB).")
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        endpoints = parse_spec(file.filename or "spec.json", content)
    except OpenApiParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    spec_id = openapi_store.add_spec(file.filename or "spec.json", endpoints)
    return OpenApiUploadResponse(
        spec_id=spec_id,
        filename=file.filename or "spec.json",
        endpoint_count=len(endpoints),
        endpoints=[
            EndpointSummary(
                endpoint_id=ep.endpoint_id, method=ep.method, path=ep.path, summary=ep.summary, requires_auth=ep.requires_auth
            )
            for ep in endpoints
        ],
    )


@app.get(
    "/api/v1/openapi/specs",
    response_model=List[OpenApiSpecSummary],
    tags=["api-tests"],
    dependencies=[Depends(require_roles(*ANY_ROLE))],
)
def list_openapi_specs() -> List[OpenApiSpecSummary]:
    return [OpenApiSpecSummary(**s) for s in openapi_store.list_specs()]


@app.post(
    "/api/v1/openapi/generate-test-cases",
    response_model=TestCaseResponse,
    tags=["api-tests"],
    dependencies=[Depends(require_roles(*WRITE_ROLES))],
)
def generate_api_tests(payload: ApiTestGenerateRequest) -> TestCaseResponse:
    spec = openapi_store.get_spec(payload.spec_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"No uploaded spec with id {payload.spec_id}")

    endpoints = spec["endpoints"]
    if payload.endpoint_ids:
        wanted = set(payload.endpoint_ids)
        endpoints = [ep for ep in endpoints if ep.endpoint_id in wanted]
        if not endpoints:
            raise HTTPException(status_code=422, detail="None of the requested endpoint_ids were found in this spec.")

    endpoints = endpoints[: payload.max_endpoints]
    test_cases = generate_api_test_cases(endpoints, spec["filename"])
    return TestCaseResponse(test_cases=test_cases)


# ---- Phase 3: SQL validation query generation ----


@app.post(
    "/api/v1/sql-validations/generate",
    response_model=SqlValidationResponse,
    tags=["sql-validations"],
    dependencies=[Depends(require_roles(*WRITE_ROLES))],
)
def generate_sql_validation_queries(payload: SqlValidationRequest) -> SqlValidationResponse:
    masked_text, _counts = scan_and_mask(payload.requirement_text)
    payload = payload.model_copy(update={"requirement_text": masked_text})
    try:
        return generate_sql_validations(payload)
    except SqlGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ---- Phase 4: observability ----


@app.get("/api/v1/observability/usage", response_model=UsageSummary, tags=["observability"], dependencies=[Depends(require_roles(*ADMIN_ONLY))])
def usage_summary() -> UsageSummary:
    """Aggregated LLM/embedding call counts, tokens, estimated cost, and
    latency, broken down by endpoint. Admin-only since cost data is
    operationally sensitive."""
    return get_usage_summary()
