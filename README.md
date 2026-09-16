# AI Quality Engineering Copilot

An AI-assisted tool that turns software requirements into structured, traceable
test cases (positive, negative, boundary, API, regression), with citations back
to the source requirement. Built as a portfolio project demonstrating applied
RAG + LLM engineering for QE workflows, using only synthetic healthcare-style
sample data.

> **Status: Phases 1–4 functionally complete, including both Phase 2
> follow-ups.** Document upload, RAG with per-test-case chunk citations, a
> real local embedding model tier (no API key needed), a reviewable
> test-case library, requirements traceability, duplicate/conflict
> detection, OpenAPI-driven API test generation, SQL validation query
> generation, authentication/RBAC, PII masking, retry/usage tracking, an
> automated RAG evaluation harness, and Docker/CI configuration are all in
> place. Backend tests (61), an evaluation harness, and a live-browser e2e
> suite (21 checks) all pass. Docker Compose has been built and smoke-tested
> with both containers healthy. Public demo deployment is a manual step (see
> [Roadmap](#roadmap)).

## What works right now

- **Backend** — `POST /api/v1/generate-test-cases` takes requirement text and
  returns 5 test cases (one of each type: positive, negative, boundary, api,
  regression) as validated JSON. `GET /health` reports whether the service is
  running against a real LLM (`mode: "llm"`) or the deterministic mock
  generator (`mode: "mock"`).
- **Mock mode by default.** If `OPENAI_API_KEY` isn't set, the backend still
  returns valid, schema-correct test cases via a rule-based fallback generator,
  so anyone cloning this repo can run the full stack immediately with no key.
- **Frontend** — a requirement textarea (with a one-click sample requirement),
  checkboxes to pick which test-case types to generate, a results table with
  color-coded type badges, and a citation column tying each row back to its
  `requirement_reference`. Once RAG lands in Phase 2, that column will also
  show the source chunk snippet — the field (`source_chunk`) is already in
  the schema and the UI, just unpopulated until then.
- **CSV export**, pulled forward from Phase 3 into the MVP UI since the
  top-level spec calls for it in Version 1: a button downloads the current
  results table as an RFC-4180-escaped CSV.
- **Document upload** (`POST /api/v1/documents`) — accepts PDF, DOCX, or
  plain text. Extracts text (PyMuPDF / python-docx), chunks it — one chunk
  per requirement where `REQ-###:` markers are present, paragraph-windowed
  with overlap otherwise — embeds every chunk, and stores it in a persistent
  ChromaDB collection. `GET /api/v1/documents` lists what's indexed.
- **Retrieval-grounded generation** (`POST /api/v1/generate-test-cases/from-documents`)
  — takes a natural-language query, retrieves the top-k most relevant chunks
  across all uploaded documents, and generates test cases from that context.
  **Citation verification guardrail:** the model's own claimed citation is
  never trusted — every returned test case's `requirement_reference` and
  `source_chunk` are programmatically overwritten with the actual
  top-retrieved chunk's id and text, so a citation always points at real,
  stored content.
- **Mock embeddings, same philosophy as mock generation.** With no
  `OPENAI_API_KEY`, embeddings are produced by a deterministic hashed
  bag-of-words vector instead of a real semantic model — not accurate
  retrieval, but real enough to demonstrate ranking (see it prefer the
  actually-relevant chunk in the test suite) with zero external dependencies.
- Frontend has a mode toggle: paste requirement text directly (Phase 1
  flow), or switch to "Generate from uploaded documents" to upload files,
  enter a query, and see both the retrieved chunks and the generated test
  cases with real citations.
- 10 passing Pytest tests (backend) covering schema validity, type
  filtering, input validation, upload for all three file types, retrieval
  ranking, and citation verification. Frontend typechecks clean and builds
  with `vite build`.

## Phase 3: library, traceability, duplicate/conflict detection

- **Save / approve / edit workflow.** Any generated batch of test cases can
  be saved into a persistent library (SQLite — see note below) via
  `POST /api/v1/test-cases`. From there, `PATCH /api/v1/test-cases/{id}`
  edits content or moves status between `draft` / `approved` / `rejected`,
  and `DELETE /api/v1/test-cases/{id}` removes one. The frontend's Library
  tab exposes all of this: click a title to edit it inline, approve/reject
  buttons, and a status filter.
- **Requirements-traceability matrix** (`GET /api/v1/traceability-matrix`)
  — cross-references every requirement seen across all uploaded documents
  against *saved* test cases (not just generated-but-unsaved ones), showing
  which of the five test-case types exist for each requirement, which are
  missing, and an overall coverage percentage.
- **Duplicate/conflict detection** (`GET /api/v1/requirements/analysis`) —
  heuristic-based, and documented as such rather than presented as ground
  truth: duplicates are flagged by embedding cosine similarity above a
  threshold; conflicts are flagged when two requirements share substantial
  vocabulary (so they're plausibly about the same subject) but only one
  contains a negation/denial term (e.g. one requirement grants access, the
  paired one denies it). Both are meant to surface candidates for a human
  reviewer — see `backend/generators/requirement_analysis.py` for exactly
  what is and isn't caught, including known false-positive/negative cases.
- **CSV and JSON export of the saved library** (`GET /api/v1/export/csv`,
  `GET /api/v1/export/json`), filterable by status — this is the
  server-side counterpart to the client-side "export what's on screen" CSV
  button from Phase 1.
- 8 additional passing Pytest tests covering the save/edit/approve/delete
  lifecycle, status filtering, both export formats, traceability-matrix
  correctness (including a requirement that's fully covered and two that
  aren't), and duplicate/conflict detection against a small synthetic set
  with a real near-duplicate pair and a real access-grant/access-denial
  conflict pair (18 backend tests total).

**Note on persistence:** the saved-test-case library uses SQLite via the
stdlib (`backend/models/db.py`), not the Postgres called for in the
project's target architecture. This is a deliberate simplification to keep
Phase 3 runnable with zero setup; swapping the backend is isolated to that
one file and doesn't touch the API routes or generators above it.

## Phase 3 (continued): OpenAPI-driven API tests and SQL validation

- **API test generation from OpenAPI/Swagger** (`POST /api/v1/openapi/specs`
  to upload a JSON or YAML spec, `POST /api/v1/openapi/generate-test-cases`
  to generate) — parses paths, methods, parameters (including min/max and
  required flags), request bodies, response codes, and security
  requirements, then generates one positive case per endpoint plus
  negative/boundary/auth-negative cases wherever the spec actually supports
  them (e.g. a boundary case only appears if a parameter has a min/max).
  Template-based, not LLM-based — the spec already states the facts, so
  there's nothing to infer, and it works with zero API key.
- **SQL validation query generation** (`POST /api/v1/sql-validations/generate`)
  — turns a requirement's stated data constraint into a SQL query that finds
  *violating* rows. Mock mode is pattern-based (length ranges, min length,
  uniqueness, required/non-null, allowed-value lists, event thresholds like
  lockout-after-N-attempts) and deliberately returns nothing rather than a
  guessed query when it doesn't recognize a concrete, checkable constraint —
  an incorrect validation query someone might actually run is worse than no
  query. Every generated query flags its column-name guess as a heuristic to
  verify against the real schema.
- 13 additional passing tests (31 backend tests through this point) covering
  OpenAPI parsing, all four API test-case kinds, unknown-spec/endpoint error
  handling, and all six recognized SQL patterns plus the "nothing matched"
  case.

## A real concurrency bug, found and fixed

While verifying this phase with an actual headless-browser click-through
(see below) rather than just curl, document upload intermittently returned
`500 Internal Server Error` on a cold server. Root cause: `backend/rag/store.py`
lazily initializes the ChromaDB client/collection on first use, and FastAPI
runs sync endpoint functions in a thread pool — so two near-simultaneous
requests (React 18 StrictMode double-invokes effects in dev, which is
exactly what triggered it) could both see "not initialized yet" and call
`chromadb.PersistentClient()` concurrently, racing inside chromadb's
internal system registry and raising a `KeyError` (or, in one run, an
`AttributeError` deep in chromadb's Rust bindings teardown — same race,
different symptom).

Fixed with a double-checked-locking pattern around the lazy init
(`backend/rag/store.py`). `backend/tests/test_store_concurrency.py`
reproduces the race directly with a thread pool against a cold store —
confirmed to fail on the old code and pass on the fixed code before being
committed, rather than just asserted to be fixed.

## Phase 4: authentication, RBAC, PII masking, retry/usage tracking

- **Authentication + role-based access control.** JWT bearer tokens
  (`POST /api/v1/auth/login`, form-encoded per OAuth2 convention so it works
  with the `/docs` Swagger "Authorize" button). Three roles: `viewer`
  (read-only), `tester` (viewer + generate/upload/save-as-draft), `admin`
  (tester + approve, delete, manage users, view cost data). A demo admin
  account (`admin` / `changeme123`) is seeded automatically on first startup
  if no users exist — change `QE_COPILOT_ADMIN_USERNAME` /
  `QE_COPILOT_ADMIN_PASSWORD` before deploying anywhere real. The frontend
  has a full login screen, a user badge + sign-out in the header, and
  admin-only Users/Usage tabs; buttons that a role can't use (approve,
  delete, generate) are disabled client-side in addition to the server
  enforcing it either way.
- **PII masking.** `backend/guardrails/pii.py` detects SSNs, credit-card
  numbers, emails, and phone numbers via regex and masks them *before*
  anything is embedded, stored, or sent to an LLM — wired into document
  ingestion, with redaction counts returned in the upload response.
- **Retry + error handling.** Both the chat-completion and embeddings OpenAI
  calls use `tenacity` for exponential-backoff retry on rate limits,
  timeouts, connection errors, and 5xx responses.
- **Usage tracking.** Every LLM and mock-mode generation call logs endpoint,
  tokens, latency, and estimated cost to SQLite, aggregated behind the
  admin-only `GET /api/v1/observability/usage` and the Usage tab. Cost
  figures are explicitly illustrative demo rates (`backend/observability/pricing.py`),
  not billing-accurate.

**Two real bugs found and fixed while building this, both with a
before/after test proving the fix:**

1. `backend/models/db.py`'s schema grew to three `CREATE TABLE` statements,
   but the code still called `conn.execute()`, which sqlite only allows for
   a single statement — every DB-touching call crashed. Fixed with
   `conn.executescript()`.
2. A genuine test-isolation bug, not just an auth side-effect: several test
   files independently set `CHROMA_PERSIST_DIR`/`QE_COPILOT_DB_PATH`,
   assuming per-file isolated directories — but `backend/rag/store.py`'s
   client is a process-wide singleton bound at first import, so those files
   were silently sharing one directory. Some files' `shutil.rmtree()`
   teardown was deleting that shared directory out from under another
   file's still-live ChromaDB client mid-suite, corrupting it. Fixed by
   centralizing one shared test directory in `backend/tests/conftest.py`
   and switching all cleanup to `store.reset()`/`db.reset()` (proper API
   calls) instead of filesystem deletion. Confirmed stable across 5 repeated
   full-suite runs and a reversed file execution order, not just one lucky pass.

13 new tests directly exercise the auth/RBAC boundaries (not just "does the
endpoint work" — does a viewer actually get 403 trying to generate, does a
tester actually get 403 trying to approve, does only admin succeed) — 46
backend tests total. The Playwright e2e script now logs in first and adds
checks for the Users and Usage tabs and sign-out — 21 checks, all passing
on a genuinely fresh cold start (see below).

## Verified with a real browser, not just curl

`frontend/tests/e2e_check.py` is a Playwright script that drives the actual
running app in headless Chromium — log in, upload a document, generate test
cases both ways, save to the library, approve one, check the traceability
matrix, run duplicate/conflict analysis, upload an OpenAPI spec and generate
API tests, generate a SQL validation query, create a user and check the
usage dashboard (both admin-only), sign out — 21 checks end to end. Run it
with both servers up:

```bash
python3 -m playwright install chromium  # one-time
cd frontend && python3 tests/e2e_check.py
```

## Output contract

```json
{
  "test_cases": [
    {
      "id": "TC-001",
      "title": "Verify authorized user can view a regular FEP patient",
      "type": "positive",
      "priority": "high",
      "preconditions": ["User has regular FEP access"],
      "steps": [
        "Sign in to the application",
        "Search for a regular FEP patient",
        "Open the patient record"
      ],
      "expected_result": "The patient record is displayed successfully",
      "requirement_reference": "REQ-001"
    }
  ]
}
```

This is enforced by a Pydantic schema (`backend/models/schemas.py`), not just
documented convention — both the LLM path and the mock path are validated
against it before the API returns a response.

## Setup

```bash
git clone <this-repo>
cd ai-quality-engineering-copilot
cp .env.example .env          # optional: add OPENAI_API_KEY to use a real LLM
python3 -m venv .venv
. .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt

uvicorn backend.api.main:app --reload --port 8000
```

On first startup with no users in the database, a demo admin account is
seeded automatically (`admin` / `changeme123` — logged as a warning so it's
never silent). Every endpoint except `/health` and `/api/v1/auth/login`
requires a bearer token now, so log in first:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -d "username=admin&password=changeme123" | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
```

Try it:

```bash
curl -X POST http://localhost:8000/api/v1/generate-test-cases \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "requirement_text": "The system shall allow an authorized user with regular FEP access to search for a patient by member ID and view the patient record.",
        "requirement_id": "REQ-001"
      }'
```

Try the RAG flow:

```bash
# Upload a requirements document (synthetic sample provided in sample-data/)
curl -H "Authorization: Bearer $TOKEN" -F "file=@sample-data/sample_requirement.txt" http://localhost:8000/api/v1/documents

# See what's indexed
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/documents

# Generate test cases grounded in the most relevant retrieved chunk(s)
curl -X POST http://localhost:8000/api/v1/generate-test-cases/from-documents \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "member ID length validation", "top_k": 2}'
```

Try the library / traceability / analysis endpoints (Phase 3):

```bash
# Save a batch of generated test cases (paste the "test_cases" array from any
# generate response above)
curl -X POST http://localhost:8000/api/v1/test-cases \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"test_cases": [...]}'

curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/traceability-matrix
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/requirements/analysis
curl -H "Authorization: Bearer $TOKEN" "http://localhost:8000/api/v1/export/csv?status=approved"
```

Try OpenAPI-driven API tests and SQL validation generation:

```bash
# Upload a synthetic OpenAPI spec, then generate API test cases from it
SPEC_ID=$(curl -s -H "Authorization: Bearer $TOKEN" -F "file=@sample-data/sample_openapi.yaml" http://localhost:8000/api/v1/openapi/specs | python3 -c "import json,sys; print(json.load(sys.stdin)['spec_id'])")
curl -X POST http://localhost:8000/api/v1/openapi/generate-test-cases \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"spec_id\": \"$SPEC_ID\"}"

# Generate a SQL validation query from a requirement's data constraint
curl -X POST http://localhost:8000/api/v1/sql-validations/generate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"requirement_text": "Member ID search shall accept alphanumeric IDs between 8 and 12 characters.", "table_name": "patients"}'

# Admin-only: LLM/embedding usage, tokens, and estimated cost
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/observability/usage
```

Interactive API docs: `http://localhost:8000/docs` (use the "Authorize"
button with your token to try protected endpoints from the Swagger UI).

### Frontend

In a second terminal, with the backend above still running:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The dev server proxies `/api` and `/health` to
`localhost:8000` (see `frontend/vite.config.ts`), so no CORS setup is needed
locally. Click "Use sample requirement" to try it without typing anything.

## Tests

```bash
pip install -r backend/requirements.txt
python -m pytest backend/tests -v
```

```bash
cd frontend
npm install
npx tsc -b        # typecheck
npm run build     # production build
```

## RAG evaluation

`evaluation/run_rag_eval.py` measures retrieval quality (Hit@1, Hit@3, MRR)
against a golden set of queries (`evaluation/golden_set.py`) tied to the
checked-in sample requirement doc, and separately confirms the citation-
verification guardrail holds end to end through the real generation
pipeline — not just structurally, but by actually generating test cases for
every golden query and checking each one's citation against a real
retrieved chunk.

```bash
python evaluation/run_rag_eval.py                              # uses whatever embedding_mode() auto-selects
QE_COPILOT_EMBEDDING_MODE=mock python evaluation/run_rag_eval.py   # force a specific tier
QE_COPILOT_EMBEDDING_MODE=local python evaluation/run_rag_eval.py
```

Both the mock (hashed bag-of-words) and local (real ONNX MiniLM) tiers
currently score **Hit@1: 83.3%, Hit@3: 100%, MRR: 0.917** on the 6-query
golden set (3 close-vocabulary, 3 deliberately paraphrased) — tied, not the
"local is obviously better" result you might expect, just with a different
single miss each. Reported honestly rather than rounded up: this 3-document
golden set has so much shared vocabulary across all three requirements
("FEP access", "member ID", "patient record" all appear repeatedly) that
it's a genuinely hard retrieval task regardless of embedding quality, and
too small to show a meaningful gap either way. A larger, more topically
diverse corpus would be a fairer test of local's real advantage — paraphrase
handling — and is a reasonable next step if this matters to you. Citation
verification passes 100% of the time by design — it's a programmatic
guarantee (see "citation verification guardrail" above), so that check is a
regression guard, not a probabilistic quality score; both checks also run
as part of the normal test suite (`backend/tests/test_rag_evaluation.py`)
and in CI (forced to mock — see below).

## Embedding modes

Three tiers, auto-selected by `backend/rag/embeddings.py`:

| Mode | When | Requires | Notes |
|---|---|---|---|
| `llm` | `OPENAI_API_KEY` is set | OpenAI account | `text-embedding-3-small`, real cost per call |
| `local` | no API key, model loads OK | network on first run only | all-MiniLM-L6-v2 via chromadb's bundled ONNX runtime — no new dependency, no account, no per-call cost, ~80MB one-time download cached under `~/.cache/chroma` |
| `mock` | local model unavailable, or forced | nothing | deterministic hashed bag-of-words, fully offline |

Override with `QE_COPILOT_EMBEDDING_MODE=local` or `=mock` to force a tier
regardless of what would otherwise be auto-selected. The test suite and CI
force `mock` explicitly (see `backend/tests/conftest.py` and
`.github/workflows/ci.yml`) so they stay fast, deterministic, and don't
depend on network access or a cold-start model download.

If the local model fails to load (most likely: no network for the one-time
download), the app logs a warning and falls back to mock mode rather than
crashing — verified with a test that simulates the failure
(`backend/tests/test_embedding_modes.py`), not just asserted to work.

The current embedding tier is visible in the frontend header (second pill,
next to the generation mode) and via `GET /health`'s `embedding_mode` field.

## Docker

```bash
cp .env.example .env    # fill in QE_COPILOT_JWT_SECRET at minimum — see below
docker compose up --build
```

Frontend on `http://localhost:3000` (nginx, reverse-proxying `/api` and
`/health` to the backend container), backend on `http://localhost:8000`.
`QE_COPILOT_JWT_SECRET` has no insecure fallback in `docker-compose.yml`
(unlike the app's own dev-only default) — generate one with
`openssl rand -hex 32` and put it in `.env` before running, or Compose will
refuse to start the backend service.

**Verification status:** Both images were built with `docker compose build`,
then started with `docker compose up -d`. The backend and frontend containers
reported healthy; `/health` returned mock/local embedding status and the
frontend returned HTTP 200 on port 3000. The frontend healthcheck uses the
IPv4 loopback address to avoid an Alpine `wget` IPv6 localhost mismatch.

## Visual QA Compare

The authenticated **Visual QA Compare** tab compares a Figma frame export with
a live URL at a chosen viewport. Upload a PNG/JPEG exported from Figma, enter
the page URL, and provide the target width and height. The deterministic report
includes:

- viewport and reference-size mismatches
- mean pixel difference for the shared screenshot area
- expected text and numeric-value checks against live page text
- optional flyout visibility/content checks using a CSS selector
- optional pagination-state checks using a CSS selector and expected page text

Live capture uses Playwright Chromium in the backend container. The result is
an engineering signal, not a claim of semantic equivalence: screenshots must
use the same viewport and pixel density, and selector-based checks require the
developer to identify the relevant UI elements. An optional vision-model layer
(OpenAI, Claude, or another provider) can be added later for semantic layout
explanations; it is deliberately not required for the baseline comparison.

Previously verified before Docker was available:
- `backend/requirements.txt` installs cleanly and the full 61-test backend
  suite passes in a genuinely fresh Python virtualenv (the same
  dependency-resolution step `docker build` performs for the backend image).
  This is also how a real, non-hypothetical bug got caught: the pinned
  FastAPI version in `requirements.txt` (0.115.0) was months older than
  what this environment happens to have installed system-wide, and exposed
  a genuine version-compatibility issue in one route declaration (a
  `response_model` assertion around a `204 No Content` DELETE endpoint) that
  every prior test run had been silently passing over. Fixed and confirmed
  passing against both the pinned and the newer version.
- `frontend`: `npm ci` from a completely empty `node_modules`, followed by
  `npm run build`, both run cleanly and produce the same output as the
  Dockerfile's build stage would.
- `docker-compose.yml`, the CI workflow, and the nginx config were all
  syntax-validated (YAML parsing caught and fixed a real bug: an unquoted
  colon inside an error message broke YAML parsing).


## Project structure

```
ai-quality-engineering-copilot/
├── backend/
│   ├── api/            # FastAPI app + routes
│   ├── auth/           # JWT security, user accounts, role-based access dependencies
│   ├── generators/     # Prompting, LLM client (retry-wrapped), mock fallback generator
│   ├── guardrails/     # PII detection/masking
│   ├── observability/  # LLM usage/cost/latency tracking
│   ├── models/         # Pydantic schemas + db.py (SQLite: test cases, users, usage log)
│   ├── rag/            # extractor, chunker, embeddings, ChromaDB store, ingest, OpenAPI parser
│   ├── Dockerfile
│   └── tests/          # Pytest suite (61 tests: generation, RAG, library/traceability,
│                       #   API/SQL gen, concurrency regression, auth/RBAC boundaries,
│                       #   PII guardrail, RAG eval, embedding-mode fallback)
├── frontend/            # React + TypeScript UI (login-gated, role-aware)
│   ├── Dockerfile       # multi-stage: npm build -> nginx
│   ├── nginx.conf
│   └── tests/e2e_check.py  # Playwright end-to-end script (real headless browser, 21 checks)
├── sample-data/         # Synthetic requirement examples — no real company data
├── evaluation/          # Golden-set RAG retrieval + citation-verification eval harness
├── .github/workflows/ci.yml  # CI: backend tests + eval harness, frontend typecheck/build
├── docker-compose.yml
├── .dockerignore
└── .env.example
```

## Roadmap

### Phase 1: MVP
- [x] Repo + project structure
- [x] FastAPI backend with one working endpoint
- [x] LLM-backed structured test case generation (with mock fallback)
- [x] React results table + type selection + CSV export (Day 3–4)
- [x] PDF/Word upload + text extraction (Day 5)

### Phase 2: RAG
- [x] PDF/Word/text upload + extraction (Day 5)
- [x] Chunking + embeddings + ChromaDB retrieval (Day 6)
- [x] Citations tying each test case to a verified source chunk (Day 6)
- [x] Per-test-case chunk citation — different test cases in the same batch can
      cite different retrieved chunks (LLM mode: model tags each test case
      with which excerpt it's based on, verified against real retrieved
      chunks; mock mode: round-robin across retrieved chunks, with content
      generation following the same assignment so title and citation stay
      consistent). See `backend/generators/rag_generator.py`.
- [x] Real local embedding model as a middle ground between "no API key" and
      "OpenAI required" — see [Embedding modes](#embedding-modes) below.

### Phase 3: Professional features
- [x] OpenAPI/Swagger-driven API test generation
- [x] SQL validation query generation
- [x] Duplicate/conflicting requirement detection (heuristic, documented limits)
- [x] Requirements-traceability matrix
- [x] CSV/JSON export (client-side for on-screen results; server-side for the saved library)
- [x] Approve/edit workflow for generated tests (save, inline edit, approve/reject, delete)

### Phase 4: Production-readiness
- [x] AuthN/RBAC (JWT, viewer/tester/admin, enforced server-side and reflected client-side)
- [x] PII/PHI masking for sensitive data (SSN, credit card, email, phone — before storage/LLM)
- [x] Retry/error handling for LLM + embedding calls (tenacity, exponential backoff)
- [x] Token/latency/cost tracking (custom SQLite-backed usage log + admin dashboard,
      not Langfuse as originally planned — see note below)
- [x] Automated RAG evaluation suite (retrieval Hit@1/Hit@3/MRR + end-to-end citation
      verification, runnable standalone and as part of the test suite/CI)
- [x] Docker + GitHub Actions CI (Docker images built and Compose smoke-tested with
  healthy backend/frontend containers)
- [ ] Public demo deployment (synthetic data only) — the one item that genuinely requires
      a human with cloud/hosting credentials; see note below

**Note on Langfuse:** the original plan called for Langfuse specifically.
What's built instead is a minimal custom equivalent (endpoint, tokens,
latency, estimated cost, all queryable via `/api/v1/observability/usage`)
that needs no external service or account to run — appropriate for a
portfolio demo, but a real deployment wanting trace-level LLM observability
(not just aggregate counters) should swap this for actual Langfuse.

**Note on public deployment:** this is the one remaining roadmap item that
can't be completed by writing more code — it requires an account on a real
hosting provider (Render, Fly.io, a cloud VM, etc.) and a human decision
about where to put it and what it should cost to run. The Docker setup
above is meant to make that step as close to "clone, set secrets, deploy"
as possible once it's smoke-tested for real.

## Responsible AI & security notes

- No real company requirements, patient data, internal APIs, or proprietary
  test data are used anywhere in this repo — only synthetic examples inspired
  by general healthcare workflows.
- The mock generator never fabricates PII; both prompt instructions and the
  fallback templates use placeholder data only.
- **PII masking**: SSNs, credit card numbers, emails, and phone numbers are
  detected and masked before anything is embedded, stored, or sent to an
  LLM. Wired into document ingestion and every user-supplied text field that
  reaches a generator — direct-text generation
  (`POST /api/v1/generate-test-cases`), the RAG query field
  (`POST /api/v1/generate-test-cases/from-documents`), and SQL validation
  generation (`POST /api/v1/sql-validations/generate`). See
  `backend/guardrails/pii.py` for exactly which patterns are covered — it's
  a regex-based guardrail for a handful of high-confidence patterns, not a
  general PII classifier.
- **Citation verification**: every RAG-generated test case's citation is
  programmatically overwritten with the actual top-retrieved chunk's id and
  text after generation — the model can influence content, but never what
  it claims to cite (`backend/generators/rag_generator.py`).
- **Authentication/RBAC**: three roles (viewer/tester/admin) enforced
  server-side on every protected endpoint via a single `require_roles()`
  dependency, with the frontend reflecting (not just relying on) those
  boundaries. No endpoint trusts a role claimed by an old JWT without
  re-checking the live database — see `backend/auth/dependencies.py`.
- **Known gaps, stated plainly rather than glossed over:** no rate limiting
  on the auth endpoints (a real deployment should add one against
  brute-force login attempts); no audit log of who approved/deleted what;
  the demo admin password is a well-known default until someone changes it
  (loudly warned about at startup, but the warning doesn't stop it from
  working).
