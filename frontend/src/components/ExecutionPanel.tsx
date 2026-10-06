import { useState } from "react";
import { executeRest, executeSql, ingestTestRun } from "../api/client";
import type { ExecutionResult } from "../types";

export function ExecutionPanel({ results, onResults, canWrite }: {
  results: ExecutionResult[];
  onResults: (results: ExecutionResult[]) => void;
  canWrite: boolean;
}) {
  const [url, setUrl] = useState("");
  const [restTestKey, setRestTestKey] = useState("");
  const [method, setMethod] = useState<"GET" | "POST" | "PUT" | "PATCH" | "DELETE">("GET");
  const [expectedStatus, setExpectedStatus] = useState("200");
  const [query, setQuery] = useState("SELECT 1 AS connectivity_check");
  const [sqlTestKey, setSqlTestKey] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function runRest(event: React.FormEvent) {
    event.preventDefault();
    setRunning(true);
    setError(null);
    try {
      const response = await executeRest({ url, method, assertions: [{ kind: "status_code", expected: expectedStatus }], critical: true });
      const result = response.results[0];
      if (result) await ingestTestRun(crypto.randomUUID(), result, restTestKey.trim());
      onResults([...results, ...response.results]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "REST execution failed.");
    } finally {
      setRunning(false);
    }
  }

  async function runSql(event: React.FormEvent) {
    event.preventDefault();
    setRunning(true);
    setError(null);
    try {
      const response = await executeSql({ query, critical: true });
      const result = response.results[0];
      if (result) await ingestTestRun(crypto.randomUUID(), result, sqlTestKey.trim());
      onResults([...results, ...response.results]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "SQL execution failed.");
    } finally {
      setRunning(false);
    }
  }

  return <section className="execution-panel">
    <div className="panel-heading"><div><h2>Execute QA checks</h2><p>Run REST checks and read-only SQL against the configured application database.</p></div><span className="mode-pill mode-llm">Normalized results</span></div>
    {!canWrite && <p className="hint-text">Your viewer role can inspect reports but cannot execute checks.</p>}
    {error && <div className="error-banner">{error}</div>}
    <div className="execution-adapters">
      <form className="execution-form" onSubmit={runRest}>
        <h3>REST / API</h3>
        <label>Stable test key<input required value={restTestKey} onChange={(event) => setRestTestKey(event.target.value)} placeholder="e.g. api.health.status" /></label>
        <label>Endpoint URL<input type="url" required value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://api.example.com/health" /></label>
        <div className="field-row"><label>Method<select value={method} onChange={(event) => setMethod(event.target.value as typeof method)}>{["GET", "POST", "PUT", "PATCH", "DELETE"].map((value) => <option key={value}>{value}</option>)}</select></label><label>Expected status<input type="number" value={expectedStatus} onChange={(event) => setExpectedStatus(event.target.value)} /></label></div>
        <button type="submit" disabled={!canWrite || running || !url.trim() || !restTestKey.trim()}>{running ? "Running..." : "Run REST check"}</button>
      </form>
      <form className="execution-form" onSubmit={runSql}>
        <h3>Read-only SQL</h3>
        <label>Stable test key<input required value={sqlTestKey} onChange={(event) => setSqlTestKey(event.target.value)} placeholder="e.g. sql.validation.connectivity" /></label>
        <label>Single SELECT statement<textarea rows={4} value={query} onChange={(event) => setQuery(event.target.value)} spellCheck={false} /></label>
        <p className="hint-text">Write statements, DDL, pragmas, comments, and multi-statement SQL are blocked.</p>
        <button type="submit" disabled={!canWrite || running || !query.trim() || !sqlTestKey.trim()}>{running ? "Running..." : "Run SQL check"}</button>
      </form>
    </div>
    {results.length > 0 && <div className="execution-results"><h3>Execution history</h3>{results.map((result, index) => <article className={`visual-check visual-check-${result.status === "passed" ? "pass" : result.status === "blocked" ? "warning" : "fail"}`} key={`${result.engine}-${index}`}><div><span className="badge">{result.engine}</span><strong>{result.status.toUpperCase()} · {result.name}</strong><small>{result.duration_ms.toFixed(1)} ms</small></div>{result.error && <p>{result.error}</p>}{result.evidence.map((item, evidenceIndex) => <small key={`${item.name}-${evidenceIndex}`}>{item.name}: {item.value}</small>)}</article>)}</div>}
  </section>;
}