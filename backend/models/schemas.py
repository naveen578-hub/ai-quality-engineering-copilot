"""
Pydantic schemas shared across the API.

These define the exact contract the frontend (and any API consumer) can
rely on. Keeping this in one place means the LLM generator, the FastAPI
route, and the tests all validate against the same source of truth.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class TestCaseType(str, Enum):
    positive = "positive"
    negative = "negative"
    boundary = "boundary"
    api = "api"
    regression = "regression"


class Priority(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class TestCase(BaseModel):
    id: str = Field(..., description="Human-readable test case id, e.g. TC-001")
    title: str
    type: TestCaseType
    priority: Priority
    preconditions: List[str] = Field(default_factory=list)
    steps: List[str] = Field(..., min_length=1)
    expected_result: str
    requirement_reference: str = Field(
        ..., description="Which requirement (or chunk id, once RAG is added) this test case traces back to"
    )
    source_chunk: Optional[str] = Field(
        default=None,
        description="Verbatim snippet of the retrieved requirement chunk this test case was generated "
        "from. Populated only by the RAG-backed generation path (Phase 2); null for plain-text generation.",
    )

    @field_validator("steps")
    @classmethod
    def steps_not_empty_strings(cls, v: List[str]) -> List[str]:
        cleaned = [s.strip() for s in v if s and s.strip()]
        if not cleaned:
            raise ValueError("steps must contain at least one non-empty step")
        return cleaned


class TestCaseResponse(BaseModel):
    test_cases: List[TestCase]


class GenerateTestCasesRequest(BaseModel):
    requirement_text: str = Field(..., min_length=10, max_length=20000)
    requirement_id: Optional[str] = Field(
        default="REQ-001", description="Id to stamp onto requirement_reference for traceability"
    )
    test_types: Optional[List[TestCaseType]] = Field(
        default=None,
        description="Optional subset of test case types to generate. Defaults to all five types.",
    )


class HealthResponse(BaseModel):
    status: str
    mode: str
    embedding_mode: str = Field(
        default="mock", description="'llm' (OpenAI), 'local' (bundled ONNX model), or 'mock' (hashed bag-of-words)"
    )


# ---- Phase 2: documents + RAG ----


class DocumentChunkSummary(BaseModel):
    chunk_id: str
    requirement_id: Optional[str] = None
    preview: str = Field(..., description="First ~120 chars of the chunk, for display only")


class DocumentSummary(BaseModel):
    document_id: str
    filename: str
    chunk_count: int
    requirement_ids: List[str] = Field(default_factory=list)


class DocumentUploadResponse(BaseModel):
    document: DocumentSummary
    chunks: List[DocumentChunkSummary]
    embedding_mode: str = Field(..., description="'llm' (OpenAI embeddings) or 'mock' (hashing fallback)")
    pii_redactions: Dict[str, int] = Field(
        default_factory=dict, description="Counts of PII-shaped content masked before storage, by category"
    )


class RetrievedChunk(BaseModel):
    chunk_id: str
    text: str
    requirement_id: Optional[str] = None
    source_filename: str
    document_id: str
    score: float = Field(..., description="Similarity score, higher is more relevant (0-1, approximate)")


class RagGenerateRequest(BaseModel):
    query: str = Field(
        ..., min_length=3, max_length=2000, description="What to generate test cases about, e.g. a topic or requirement id"
    )
    top_k: int = Field(default=3, ge=1, le=10)
    test_types: Optional[List[TestCaseType]] = None
    document_id: Optional[str] = Field(
        default=None, description="Restrict retrieval to a single previously uploaded document"
    )


class RagGenerateResponse(BaseModel):
    test_cases: List[TestCase]
    retrieved_chunks: List[RetrievedChunk]


# ---- Phase 3: persistence, approval workflow, traceability, duplicate detection ----


class TestCaseStatus(str, Enum):
    draft = "draft"
    approved = "approved"
    rejected = "rejected"


class PersistedTestCase(TestCase):
    db_id: int
    status: TestCaseStatus = TestCaseStatus.draft
    document_id: Optional[str] = None
    created_at: str
    updated_at: str


class SaveTestCasesRequest(BaseModel):
    test_cases: List[TestCase]
    document_id: Optional[str] = None


class UpdateTestCaseRequest(BaseModel):
    title: Optional[str] = None
    priority: Optional[Priority] = None
    preconditions: Optional[List[str]] = None
    steps: Optional[List[str]] = None
    expected_result: Optional[str] = None
    status: Optional[TestCaseStatus] = None


class TraceabilityRow(BaseModel):
    requirement_id: str
    source_filename: Optional[str] = None
    covered_types: List[TestCaseType] = Field(default_factory=list)
    missing_types: List[TestCaseType] = Field(default_factory=list)
    test_case_count: int = 0
    approved_count: int = 0


class TraceabilityMatrix(BaseModel):
    rows: List[TraceabilityRow]
    coverage_percent: float = Field(..., description="% of indexed requirements with at least one test case")


class DuplicatePair(BaseModel):
    requirement_id_a: str
    requirement_id_b: str
    similarity: float
    text_a: str
    text_b: str


class ConflictPair(BaseModel):
    requirement_id_a: str
    requirement_id_b: str
    shared_terms: List[str]
    text_a: str
    text_b: str
    reason: str


class RequirementAnalysisResponse(BaseModel):
    duplicates: List[DuplicatePair]
    conflicts: List[ConflictPair]


# ---- Phase 3: OpenAPI-driven API test generation ----


class EndpointSummary(BaseModel):
    endpoint_id: str = Field(..., description="e.g. 'GET /patients/{id}'")
    method: str
    path: str
    summary: Optional[str] = None
    requires_auth: bool = False


class OpenApiUploadResponse(BaseModel):
    spec_id: str
    filename: str
    endpoint_count: int
    endpoints: List[EndpointSummary]


class OpenApiSpecSummary(BaseModel):
    spec_id: str
    filename: str
    endpoint_count: int


class ApiTestGenerateRequest(BaseModel):
    spec_id: str
    endpoint_ids: Optional[List[str]] = Field(
        default=None, description="Restrict generation to these endpoint_ids, e.g. ['GET /patients/{id}']. Omit for all."
    )
    max_endpoints: int = Field(default=10, ge=1, le=50)


# ---- Phase 3: SQL validation query generation ----


class SqlValidationRequest(BaseModel):
    requirement_text: str = Field(..., min_length=1, max_length=5000)
    table_name: Optional[str] = Field(default=None, description="Hint for which table the requirement's data lives in")
    column_name: Optional[str] = Field(
        default=None,
        description="Explicit column name, or comma-separated column names, to validate",
    )
    requirement_id: str = Field(default="REQ-001")


class SqlValidation(BaseModel):
    description: str
    sql: str
    rule_detected: str = Field(..., description="Which validation pattern was matched, e.g. 'length_range'")
    requirement_reference: str


class SqlValidationResponse(BaseModel):
    validations: List[SqlValidation]
    unmatched_note: Optional[str] = Field(
        default=None, description="Set when no known pattern matched the requirement text"
    )


# ---- In-product help assistant ----


class HelpChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    surface: str = Field(default="workspace", pattern="^(signin|workspace)$")
    active_area: Optional[str] = Field(default=None, max_length=80)
    role: Optional[str] = Field(default=None, max_length=20)


class HelpChatResponse(BaseModel):
    answer: str
    suggestions: List[str] = Field(default_factory=list)
    mode: str = "local"


class VisualCheck(BaseModel):
    category: str
    label: str
    status: str
    expected: Optional[str] = None
    actual: Optional[str] = None
    detail: str


class VisualCompareResponse(BaseModel):
    url: str
    viewport_width: int
    viewport_height: int
    reference_width: int
    reference_height: int
    pixel_difference_percent: float
    checks: List[VisualCheck]
    limitations: List[str] = Field(default_factory=list)


# ---- Phase 4: authentication and roles ----


class Role(str, Enum):
    viewer = "viewer"
    tester = "tester"
    admin = "admin"


class UserOut(BaseModel):
    id: int
    username: str
    role: Role
    created_at: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: Role
    username: str


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=200)
    role: Role = Role.tester


# ---- Phase 4: observability ----


class UsageByEndpoint(BaseModel):
    endpoint: str
    call_count: int
    total_tokens: int
    estimated_cost_usd: float
    avg_latency_ms: float


class UsageSummary(BaseModel):
    total_calls: int
    llm_calls: int
    local_calls: int
    mock_calls: int
    total_tokens: int
    total_estimated_cost_usd: float
    avg_latency_ms: float
    by_endpoint: List[UsageByEndpoint]


# ---- Phase 4: PII guardrail ----


class PiiRedactionSummary(BaseModel):
    redaction_counts: Dict[str, int] = Field(default_factory=dict)
