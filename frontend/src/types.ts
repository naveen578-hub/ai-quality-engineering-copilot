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
