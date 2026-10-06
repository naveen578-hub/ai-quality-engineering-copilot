import { useEffect, useState } from "react";
import { fetchTestHealth, fetchTestHealthDetail } from "../api/client";
import type { TestHealthDetail, TestHealthSummary } from "../types";

const classifications = ["all", "flaky", "failing", "stable", "inconclusive", "insufficient_data"] as const;

export function TestHealthPanel() {
  const [rows, setRows] = useState<TestHealthSummary[]>([]);
  const [selected, setSelected] = useState<TestHealthSummary | null>(null);
  const [detail, setDetail] = useState<TestHealthDetail | null>(null);
  const [filter, setFilter] = useState<(typeof classifications)[number]>("all");
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      const health = await fetchTestHealth();
      setRows(health);
      setError(null);
      if (selected) {
        const current = health.find((row) => row.identity_type === selected.identity_type &&
          (row.identity_type === "test_case" ? row.test_case_db_id === selected.test_case_db_id : row.test_key === selected.test_key));
        if (current) {
          setSelected(current);
          setDetail(await fetchTestHealthDetail(current));
        } else {
          setSelected(null);
          setDetail(null);
        }
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load test health.");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function selectTest(row: TestHealthSummary) {
    setSelected(row);
    setDetail(null);
    try {
      setDetail(await fetchTestHealthDetail(row));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load test history.");
    }
  }

  const visibleRows = filter === "all" ? rows : rows.filter((row) => row.classification === filter);
  return (
    <section className="test-health-panel">
      <div className="panel-heading">
        <div><h2>Test health</h2><p>Heuristic signals from the latest 20 passed/failed runs. Blocked, error, and skipped outcomes remain in history but do not score.</p></div>
        <button type="button" className="small-button" onClick={refresh}>Refresh</button>
      </div>
      {error && <div className="error-banner" role="alert">{error}</div>}
      <div className="status-filter-row" aria-label="Filter by test health">
        {classifications.map((classification) => (
          <button key={classification} type="button" className={filter === classification ? "tab-active" : ""} onClick={() => setFilter(classification)}>
            {classification.replace(/_/g, " ")}
          </button>
        ))}
      </div>
      {visibleRows.length === 0 ? (
        <p className="empty-state">No run history for this filter yet. Execute a check with a stable test key or ingest a CI batch.</p>
      ) : (
        <div className="test-case-table-wrapper" tabIndex={0}>
          <table className="test-case-table">
            <thead><tr><th>Identity</th><th>Health</th><th>Pass rate</th><th>Flips</th><th>Current streak</th><th>Runs</th></tr></thead>
            <tbody>{visibleRows.map((row) => {
              const key = `${row.identity_type}:${row.test_case_db_id ?? row.test_key}`;
              const selectedKey = selected ? `${selected.identity_type}:${selected.test_case_db_id ?? selected.test_key}` : "";
              return <tr key={key} className={key === selectedKey ? "health-row-selected" : ""}>
                <td><button type="button" className="health-identity" onClick={() => selectTest(row)}>{row.test_case_public_id ? `${row.test_case_public_id} · ` : ""}{row.name}</button><small>{row.identity_type === "test_case" ? "saved test case" : row.test_key}</small></td>
                <td><span className={`health-classification health-${row.classification}`}>{row.classification.replace(/_/g, " ")}</span></td>
                <td>{row.pass_rate === null ? "—" : `${(row.pass_rate * 100).toFixed(0)}%`}</td>
                <td>{row.flip_count ?? "—"}</td>
                <td>{row.current_streak_count === null ? "—" : `${row.current_streak_status} × ${row.current_streak_count}`}</td>
                <td>{row.decisive_run_count}/{row.total_run_count} scored</td>
              </tr>;
            })}</tbody>
          </table>
        </div>
      )}
      {selected && detail && <section className="health-history">
        <h3>Run history · {selected.test_case_public_id ?? selected.test_key}</h3>
        <div className="test-case-table-wrapper" tabIndex={0}>
          <table className="test-case-table">
            <thead><tr><th>Recorded</th><th>Engine</th><th>Result</th><th>Duration</th><th>Batch context</th><th>Error summary</th></tr></thead>
            <tbody>{detail.history.map((run) => <tr key={run.id}>
              <td>{new Date(run.recorded_at).toLocaleString()}</td><td>{run.engine}</td><td>{run.status}</td><td>{run.duration_ms} ms</td>
              <td>{run.batch_failure_count}/{run.batch_result_count} failed/error</td><td>{run.error_summary ?? "—"}</td>
            </tr>)}</tbody>
          </table>
        </div>
      </section>}
    </section>
  );
}
