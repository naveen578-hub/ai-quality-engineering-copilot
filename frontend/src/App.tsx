import { useEffect, useState } from "react";
import { RequirementInput } from "./components/RequirementInput";
import { TestCaseTable } from "./components/TestCaseTable";
import { DocumentPanel } from "./components/DocumentPanel";
import { RagQueryInput } from "./components/RagQueryInput";
import { RetrievedChunksPanel } from "./components/RetrievedChunksPanel";
import { LibraryPanel } from "./components/LibraryPanel";
import { TraceabilityMatrixPanel } from "./components/TraceabilityMatrixPanel";
import { RequirementAnalysisPanel } from "./components/RequirementAnalysisPanel";
import { OpenApiPanel } from "./components/OpenApiPanel";
import { SqlValidationPanel } from "./components/SqlValidationPanel";
import { LoginForm } from "./components/LoginForm";
import { UsersPanel } from "./components/UsersPanel";
import { UsagePanel } from "./components/UsagePanel";
import { HelpChat } from "./components/HelpChat";
import { VisualComparePanel } from "./components/VisualComparePanel";
import { useAuth } from "./auth/AuthContext";
import {
  checkHealth,
  generateTestCases,
  generateTestCasesFromDocuments,
  saveTestCases,
} from "./api/client";
import type { DocumentSummary, RetrievedChunk, TestCase, TestCaseType } from "./types";
import "./index.css";

type GenerateSubMode = "paste" | "documents";
type TopLevelTab = "generate" | "visual-compare" | "library" | "traceability" | "analysis" | "api-tests" | "sql" | "users" | "usage";

export default function App() {
  const { user, isLoading, logout } = useAuth();

  if (isLoading) {
    return (
      <div className="app">
        <p className="empty-state">Loading...</p>
      </div>
    );
  }

  if (!user) {
    return <><LoginForm /><HelpChat surface="signin" /></>;
  }

  return <AuthenticatedApp username={user.username} role={user.role} onLogout={logout} />;
}

function AuthenticatedApp({
  username,
  role,
  onLogout,
}: {
  username: string;
  role: string;
  onLogout: () => void;
}) {
  const isAdmin = role === "admin";
  const canWrite = role === "tester" || role === "admin";

  const tabs: Array<{ id: TopLevelTab; label: string }> = [
    { id: "generate", label: "Generate" },
    { id: "visual-compare", label: "Visual QA Compare" },
    { id: "library", label: "Library" },
    { id: "traceability", label: "Traceability Matrix" },
    { id: "analysis", label: "Duplicate/Conflict Analysis" },
    { id: "api-tests", label: "API Tests (OpenAPI)" },
    { id: "sql", label: "SQL Validations" },
    ...(isAdmin ? [{ id: "users" as TopLevelTab, label: "Users" }, { id: "usage" as TopLevelTab, label: "Usage" }] : []),
  ];

  const [activeTab, setActiveTab] = useState<TopLevelTab>("generate");
  const [inputMode, setInputMode] = useState<GenerateSubMode>("paste");
  const [testCases, setTestCases] = useState<TestCase[]>([]);
  const [retrievedChunks, setRetrievedChunks] = useState<RetrievedChunk[]>([]);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"llm" | "mock" | "unknown">("unknown");
  const [embeddingMode, setEmbeddingMode] = useState<"llm" | "local" | "mock" | "unknown">("unknown");

  useEffect(() => {
    checkHealth()
      .then((h) => {
        setMode(h.mode);
        setEmbeddingMode(h.embedding_mode);
      })
      .catch(() => {
        setMode("unknown");
        setEmbeddingMode("unknown");
      });
  }, []);

  async function handleGenerate(
    requirementText: string,
    requirementId: string,
    types: TestCaseType[]
  ) {
    setIsLoading(true);
    setError(null);
    setSaveMessage(null);
    try {
      const res = await generateTestCases({
        requirement_text: requirementText,
        requirement_id: requirementId,
        test_types: types,
      });
      setTestCases(res.test_cases);
      setRetrievedChunks([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setTestCases([]);
    } finally {
      setIsLoading(false);
    }
  }

  async function handleRagGenerate(query: string, topK: number, types: TestCaseType[]) {
    setIsLoading(true);
    setError(null);
    setSaveMessage(null);
    try {
      const res = await generateTestCasesFromDocuments({ query, top_k: topK, test_types: types });
      setTestCases(res.test_cases);
      setRetrievedChunks(res.retrieved_chunks);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setTestCases([]);
      setRetrievedChunks([]);
    } finally {
      setIsLoading(false);
    }
  }

  async function handleSaveToLibrary() {
    setIsSaving(true);
    setSaveMessage(null);
    try {
      const saved = await saveTestCases({ test_cases: testCases });
      setSaveMessage(`Saved ${saved.length} test case${saved.length !== 1 ? "s" : ""} to the library.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save to library.");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="app">
      <header>
        <div className="header-top-row">
          <h1>AI Quality Engineering Copilot</h1>
          <div className="user-badge">
            <span className="citation-tag">{username}</span>
            <span className={`status-pill status-${role === "admin" ? "approved" : "draft"}`}>{role}</span>
            <button type="button" className="small-button" onClick={onLogout}>
              Sign out
            </button>
          </div>
        </div>
        <p className="subtitle">
          Turn requirements into structured, traceable test cases.
          {mode !== "unknown" && (
            <span className={`mode-pill mode-${mode}`}>
              {mode === "llm" ? "LLM mode" : "Mock mode (no API key configured)"}
            </span>
          )}
          {embeddingMode !== "unknown" && (
            <span className={`mode-pill mode-${embeddingMode === "mock" ? "mock" : "llm"}`}>
              embeddings:{" "}
              {embeddingMode === "llm" ? "OpenAI" : embeddingMode === "local" ? "local model" : "hashed (offline)"}
            </span>
          )}
        </p>
      </header>

      <nav className="top-level-tabs" role="tablist">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            className={activeTab === tab.id ? "tab-active" : ""}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <main>
        {activeTab === "generate" && (
          <>
            {!canWrite && (
              <p className="hint-text">
                Your role ({role}) can view generated results but not generate new ones — ask an
                admin to upgrade your account to tester or admin if you need to generate.
              </p>
            )}
            <div className="mode-toggle" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={inputMode === "paste"}
                className={inputMode === "paste" ? "tab-active" : ""}
                onClick={() => setInputMode("paste")}
              >
                Paste requirement text
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={inputMode === "documents"}
                className={inputMode === "documents" ? "tab-active" : ""}
                onClick={() => setInputMode("documents")}
              >
                Generate from uploaded documents
              </button>
            </div>

            {inputMode === "paste" ? (
              <RequirementInput onGenerate={handleGenerate} isLoading={isLoading || !canWrite} />
            ) : (
              <>
                <DocumentPanel onDocumentsChanged={setDocuments} />
                <RagQueryInput
                  onGenerate={handleRagGenerate}
                  isLoading={isLoading}
                  disabled={documents.length === 0 || !canWrite}
                />
              </>
            )}

            {error && <div className="error-banner">{error}</div>}
            {saveMessage && <div className="success-banner">{saveMessage}</div>}

            <RetrievedChunksPanel chunks={retrievedChunks} />
            <TestCaseTable
              testCases={testCases}
              onSaveToLibrary={canWrite ? handleSaveToLibrary : undefined}
              isSaving={isSaving}
            />
          </>
        )}

        {activeTab === "visual-compare" && <VisualComparePanel />}

        {activeTab === "library" && <LibraryPanel />}
        {activeTab === "traceability" && <TraceabilityMatrixPanel />}
        {activeTab === "analysis" && <RequirementAnalysisPanel />}
        {activeTab === "api-tests" && <OpenApiPanel />}
        {activeTab === "sql" && <SqlValidationPanel />}
        {activeTab === "users" && isAdmin && <UsersPanel />}
        {activeTab === "usage" && isAdmin && <UsagePanel />}
      </main>

      <footer>
        <p>
          Portfolio project — synthetic healthcare-style sample data only. No real
          requirements, patient data, or proprietary content.
        </p>
      </footer>
      <HelpChat surface="workspace" role={role as "viewer" | "tester" | "admin"} activeArea={activeTab} />
    </div>
  );
}
