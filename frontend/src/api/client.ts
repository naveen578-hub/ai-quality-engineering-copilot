import type {
  ApiTestGenerateRequest,
  CreateUserRequest,
  DocumentSummary,
  DocumentUploadResponse,
  GenerateTestCasesRequest,
  HealthResponse,
  HelpChatRequest,
  HelpChatResponse,
  VisualCompareResponse,
  OpenApiSpecSummary,
  OpenApiUploadResponse,
  PersistedTestCase,
  RagGenerateRequest,
  RagGenerateResponse,
  RequirementAnalysisResponse,
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
} from "../types";

// In dev this is proxied to http://localhost:8000 by vite.config.ts.
// In production, set VITE_API_BASE_URL at build time to point at the real API.
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";
const TOKEN_STORAGE_KEY = "qe_copilot_token";

export function getAuthToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setAuthToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_STORAGE_KEY, token);
  else localStorage.removeItem(TOKEN_STORAGE_KEY);
}

// Set by AuthContext so a 401 from any request (expired/invalid token) can
// drop the app back to the login screen, not just fail silently mid-action.
type UnauthorizedHandler = () => void;
let unauthorizedHandler: UnauthorizedHandler | null = null;
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler;
}

/** Every authenticated request goes through this so the bearer token and
 * 401 handling live in exactly one place. */
async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const token = getAuthToken();
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (res.status === 401) {
    setAuthToken(null);
    unauthorizedHandler?.();
  }
  return res;
}

async function parseJsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      // response wasn't JSON; fall back to statusText above
    }
    throw new Error(`Request failed (${res.status}): ${detail}`);
  }
  return res.json() as Promise<T>;
}

function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function checkHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE}/health`);
  return parseJsonOrThrow<HealthResponse>(res);
}

// ---- Phase 4: authentication ----

export async function login(username: string, password: string): Promise<TokenResponse> {
  const form = new URLSearchParams();
  form.set("username", username);
  form.set("password", password);
  const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form.toString(),
  });
  return parseJsonOrThrow<TokenResponse>(res);
}

export async function getMe(): Promise<UserOut> {
  const res = await apiFetch("/api/v1/auth/me");
  return parseJsonOrThrow<UserOut>(res);
}

export async function createUser(payload: CreateUserRequest): Promise<UserOut> {
  const res = await apiFetch("/api/v1/auth/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJsonOrThrow<UserOut>(res);
}

export async function listUsers(): Promise<UserOut[]> {
  const res = await apiFetch("/api/v1/auth/users");
  return parseJsonOrThrow<UserOut[]>(res);
}

export async function generateTestCases(
  payload: GenerateTestCasesRequest
): Promise<TestCaseResponse> {
  const res = await apiFetch("/api/v1/generate-test-cases", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJsonOrThrow<TestCaseResponse>(res);
}

// ---- Phase 2: documents + RAG ----

export async function uploadDocument(file: File): Promise<DocumentUploadResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await apiFetch("/api/v1/documents", { method: "POST", body: form });
  return parseJsonOrThrow<DocumentUploadResponse>(res);
}

export async function listDocuments(): Promise<DocumentSummary[]> {
  const res = await apiFetch("/api/v1/documents");
  return parseJsonOrThrow<DocumentSummary[]>(res);
}

export async function generateTestCasesFromDocuments(
  payload: RagGenerateRequest
): Promise<RagGenerateResponse> {
  const res = await apiFetch("/api/v1/generate-test-cases/from-documents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJsonOrThrow<RagGenerateResponse>(res);
}

// ---- Phase 3: library, traceability, duplicate/conflict detection ----

export async function saveTestCases(payload: SaveTestCasesRequest): Promise<PersistedTestCase[]> {
  const res = await apiFetch("/api/v1/test-cases", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJsonOrThrow<PersistedTestCase[]>(res);
}

export async function listSavedTestCases(status?: TestCaseStatus): Promise<PersistedTestCase[]> {
  const params = status ? `?status=${encodeURIComponent(status)}` : "";
  const res = await apiFetch(`/api/v1/test-cases${params}`);
  return parseJsonOrThrow<PersistedTestCase[]>(res);
}

export async function updateSavedTestCase(
  dbId: number,
  updates: UpdateTestCaseRequest
): Promise<PersistedTestCase> {
  const res = await apiFetch(`/api/v1/test-cases/${dbId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  return parseJsonOrThrow<PersistedTestCase>(res);
}

export async function deleteSavedTestCase(dbId: number): Promise<void> {
  const res = await apiFetch(`/api/v1/test-cases/${dbId}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) {
    throw new Error(`Delete failed (${res.status})`);
  }
}

export async function fetchTraceabilityMatrix(): Promise<TraceabilityMatrix> {
  const res = await apiFetch("/api/v1/traceability-matrix");
  return parseJsonOrThrow<TraceabilityMatrix>(res);
}

export async function fetchRequirementAnalysis(): Promise<RequirementAnalysisResponse> {
  const res = await apiFetch("/api/v1/requirements/analysis");
  return parseJsonOrThrow<RequirementAnalysisResponse>(res);
}

/** Server-side export requires auth, so — unlike a plain <a href> — this
 * fetches with the bearer token attached and triggers the download from
 * the resulting blob. */
export async function downloadExport(format: "csv" | "json", status?: TestCaseStatus): Promise<void> {
  const params = status ? `?status=${encodeURIComponent(status)}` : "";
  const res = await apiFetch(`/api/v1/export/${format}${params}`);
  if (!res.ok) throw new Error(`Export failed (${res.status})`);
  const blob = await res.blob();
  triggerBlobDownload(blob, `test-cases.${format}`);
}

// ---- Phase 3: OpenAPI-driven API test generation ----

export async function uploadOpenApiSpec(file: File): Promise<OpenApiUploadResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await apiFetch("/api/v1/openapi/specs", { method: "POST", body: form });
  return parseJsonOrThrow<OpenApiUploadResponse>(res);
}

export async function listOpenApiSpecs(): Promise<OpenApiSpecSummary[]> {
  const res = await apiFetch("/api/v1/openapi/specs");
  return parseJsonOrThrow<OpenApiSpecSummary[]>(res);
}

export async function generateApiTestCases(payload: ApiTestGenerateRequest): Promise<TestCaseResponse> {
  const res = await apiFetch("/api/v1/openapi/generate-test-cases", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJsonOrThrow<TestCaseResponse>(res);
}

// ---- Phase 3: SQL validation query generation ----

export async function generateSqlValidations(payload: SqlValidationRequest): Promise<SqlValidationResponse> {
  const res = await apiFetch("/api/v1/sql-validations/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJsonOrThrow<SqlValidationResponse>(res);
}

export async function askHelp(payload: HelpChatRequest): Promise<HelpChatResponse> {
  const res = await apiFetch("/api/v1/help/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJsonOrThrow<HelpChatResponse>(res);
}

export async function compareVisual(payload: {
  reference: File;
  url: string;
  viewport_width: number;
  viewport_height: number;
  expected_text?: string;
  numeric_values?: string;
  flyout_selector?: string;
  expected_flyout_text?: string;
  pagination_selector?: string;
  expected_page?: string;
}): Promise<VisualCompareResponse> {
  const form = new FormData();
  form.append("reference", payload.reference);
  form.append("url", payload.url);
  form.append("viewport_width", String(payload.viewport_width));
  form.append("viewport_height", String(payload.viewport_height));
  for (const key of ["expected_text", "numeric_values", "flyout_selector", "expected_flyout_text", "pagination_selector", "expected_page"] as const) {
    if (payload[key]) form.append(key, payload[key] as string);
  }
  const res = await apiFetch("/api/v1/visual-compare", { method: "POST", body: form });
  return parseJsonOrThrow<VisualCompareResponse>(res);
}

// ---- Phase 4: observability ----

export async function fetchUsageSummary(): Promise<UsageSummary> {
  const res = await apiFetch("/api/v1/observability/usage");
  return parseJsonOrThrow<UsageSummary>(res);
}
