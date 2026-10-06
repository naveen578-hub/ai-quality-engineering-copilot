// Mirrors backend/models/schemas.py — keep these two in sync by hand for now.
// (Once the API is stable, this is a good candidate to auto-generate via
// openapi-typescript from FastAPI's /openapi.json.)

export type TestCaseType = "positive" | "negative" | "boundary" | "api" | "regression";
export type Priority = "high" | "medium" | "low";

export interface TestCase {
  id: string;
  title: string;
  type: TestCaseType;
  priority: Priority;
  preconditions: string[];
  steps: string[];
  expected_result: string;
  requirement_reference: string;
  // Populated once RAG (Phase 2) is wired in.
  source_chunk?: string | null;
}

export interface TestCaseResponse {
  test_cases: TestCase[];
}

export interface GenerateTestCasesRequest {
  requirement_text: string;
  requirement_id?: string;
  test_types?: TestCaseType[];
}

export interface HealthResponse {
  status: string;
  mode: "llm" | "mock";
  embedding_mode: "llm" | "local" | "mock";
}

export const ALL_TEST_TYPES: TestCaseType[] = [
  "positive",
  "negative",
  "boundary",
  "api",
  "regression",
];

// ---- Phase 2: documents + RAG ----

export interface DocumentSummary {
  document_id: string;
  filename: string;
  chunk_count: number;
  requirement_ids: string[];
}

export interface DocumentChunkSummary {
  chunk_id: string;
  requirement_id: string | null;
  preview: string;
}

export interface DocumentUploadResponse {
  document: DocumentSummary;
  chunks: DocumentChunkSummary[];
  embedding_mode: "llm" | "mock";
  impact_count: number;
}

export interface RequirementImpactTestCase {
  db_id: number;
  id: string;
  title: string;
  status: TestCaseStatus;
}

export interface RequirementImpact {
  impact_id: number;
  filename: string;
  requirement_id: string;
  change_type: "added" | "modified" | "removed";
  old_text: string | null;
  new_text: string | null;
  previous_document_id: string | null;
  current_document_id: string;
  reviewed: boolean;
  reviewed_at: string | null;
  affected_test_cases: RequirementImpactTestCase[];
}

export interface UnlinkedTestCase {
  db_id: number;
  id: string;
  title: string;
  requirement_reference: string;
  status: TestCaseStatus;
}

export interface RequirementImpactReport {
  impacts: RequirementImpact[];
  unlinked_test_cases: UnlinkedTestCase[];
}

export interface TestRunIngestResponse {
  run_batch_id: string;
  accepted_count: number;
  idempotent_replay: boolean;
}

export type TestHealthClassification = "stable" | "flaky" | "failing" | "inconclusive" | "insufficient_data";
export type TestRunStatus = "passed" | "failed" | "blocked" | "error" | "skipped";

export interface TestHealthSummary {
  identity_type: "test_case" | "test_key";
  test_case_db_id: number | null;
  test_key: string | null;
  test_case_public_id: string | null;
  name: string;
  total_run_count: number;
  decisive_run_count: number;
  pass_rate: number | null;
  flip_count: number | null;
  current_streak_status: TestRunStatus | null;
  current_streak_count: number | null;
  classification: TestHealthClassification;
}

export interface TestRunHistoryItem {
  id: number;
  engine: "playwright" | "rest" | "sql" | "manual";
  status: TestRunStatus;
  duration_ms: number;
  run_batch_id: string;
  error_summary: string | null;
  recorded_at: string;
  batch_result_count: number;
  batch_failure_count: number;
}

export interface TestHealthDetail {
  health: TestHealthSummary;
  history: TestRunHistoryItem[];
}

export interface RetrievedChunk {
  chunk_id: string;
  text: string;
  requirement_id: string | null;
  source_filename: string;
  document_id: string;
  score: number;
}

export interface RagGenerateRequest {
  query: string;
  top_k?: number;
  test_types?: TestCaseType[];
  document_id?: string;
}

export interface RagGenerateResponse {
  test_cases: TestCase[];
  retrieved_chunks: RetrievedChunk[];
}

// ---- Phase 3: library, traceability, duplicate/conflict detection ----

export type TestCaseStatus = "draft" | "approved" | "rejected";

export interface PersistedTestCase extends TestCase {
  db_id: number;
  status: TestCaseStatus;
  document_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface SaveTestCasesRequest {
  test_cases: TestCase[];
  document_id?: string;
}

export interface UpdateTestCaseRequest {
  title?: string;
  priority?: TestCase["priority"];
  preconditions?: string[];
  steps?: string[];
  expected_result?: string;
  status?: TestCaseStatus;
}

export interface TraceabilityRow {
  requirement_id: string;
  source_filename: string | null;
  covered_types: TestCaseType[];
  missing_types: TestCaseType[];
  test_case_count: number;
  approved_count: number;
}

export interface TraceabilityMatrix {
  rows: TraceabilityRow[];
  coverage_percent: number;
}

export interface DuplicatePair {
  requirement_id_a: string;
  requirement_id_b: string;
  similarity: number;
  text_a: string;
  text_b: string;
}

export interface ConflictPair {
  requirement_id_a: string;
  requirement_id_b: string;
  shared_terms: string[];
  text_a: string;
  text_b: string;
  reason: string;
}

export interface RequirementAnalysisResponse {
  duplicates: DuplicatePair[];
  conflicts: ConflictPair[];
}

// ---- Phase 3: OpenAPI-driven API test generation ----

export interface EndpointSummary {
  endpoint_id: string;
  method: string;
  path: string;
  summary: string | null;
  requires_auth: boolean;
}

export interface OpenApiUploadResponse {
  spec_id: string;
  filename: string;
  endpoint_count: number;
  endpoints: EndpointSummary[];
}

export interface OpenApiSpecSummary {
  spec_id: string;
  filename: string;
  endpoint_count: number;
}

export interface ApiTestGenerateRequest {
  spec_id: string;
  endpoint_ids?: string[];
  max_endpoints?: number;
}

// ---- Phase 3: SQL validation query generation ----

export interface SqlValidationRequest {
  requirement_text: string;
  table_name?: string;
  column_name?: string;
  requirement_id?: string;
}

export interface HelpChatRequest {
  question: string;
  surface: "signin" | "workspace";
  active_area?: string;
  role?: Role;
}

export interface HelpChatResponse {
  answer: string;
  suggestions: string[];
  mode: string;
}

export interface VisualCheck {
  category: string;
  label: string;
  status: string;
  expected?: string | null;
  actual?: string | null;
  detail: string;
}

export interface VisualCompareResponse {
  url: string;
  viewport_width: number;
  viewport_height: number;
  reference_width: number;
  reference_height: number;
  pixel_difference_percent: number;
  checks: VisualCheck[];
  limitations: string[];
}

export interface ExecutionEvidence {
  kind: string;
  name: string;
  value?: string | null;
}

export interface ExecutionResult {
  engine: string;
  status: string;
  name: string;
  duration_ms: number;
  error?: string | null;
  evidence: ExecutionEvidence[];
  critical: boolean;
}

export interface ExecutionBatchResponse {
  results: ExecutionResult[];
  critical_failures: number;
}

export interface RestExecutionRequest {
  url: string;
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE" | "HEAD" | "OPTIONS";
  headers?: Record<string, string>;
  body?: Record<string, unknown>;
  assertions: Array<{ kind: "status_code" | "json_contains" | "text_contains"; expected: string }>;
  critical: boolean;
}

export interface SqlExecutionRequest {
  query: string;
  critical: boolean;
}

export interface SqlValidation {
  description: string;
  sql: string;
  rule_detected: string;
  requirement_reference: string;
}

export interface SqlValidationResponse {
  validations: SqlValidation[];
  unmatched_note: string | null;
}

// ---- Phase 4: authentication and roles ----

export type Role = "viewer" | "tester" | "admin";

export interface UserOut {
  id: number;
  username: string;
  role: Role;
  created_at: string;
}

export interface AuditEventOut {
  id: number;
  actor: string;
  action: string;
  target_type: string;
  target_id: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  role: Role;
  username: string;
}

export interface CreateUserRequest {
  username: string;
  password: string;
  role: Role;
}

// ---- Phase 4: observability ----

export interface UsageByEndpoint {
  endpoint: string;
  call_count: number;
  total_tokens: number;
  estimated_cost_usd: number;
  avg_latency_ms: number;
}

export interface UsageSummary {
  total_calls: number;
  llm_calls: number;
  local_calls: number;
  mock_calls: number;
  total_tokens: number;
  total_estimated_cost_usd: number;
  avg_latency_ms: number;
  by_endpoint: UsageByEndpoint[];
}
