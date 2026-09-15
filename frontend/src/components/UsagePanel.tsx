import { useEffect, useState } from "react";
import type { UsageSummary } from "../types";
import { fetchUsageSummary } from "../api/client";

export function UsagePanel() {
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchUsageSummary()
      .then(setSummary)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load usage."));
  }, []);

  if (error) return <div className="error-banner">{error}</div>;
  if (!summary) return <p className="empty-state">Loading usage data...</p>;

  return (
    <div className="usage-panel">
      <h2>LLM &amp; embedding usage</h2>
      <p className="hint-text">
        Estimated costs are illustrative demo-rate figures, not billing-accurate — see
        backend/observability/pricing.py.
      </p>

      <div className="usage-stat-row">
        <div className="usage-stat">
          <span className="usage-stat-value">{summary.total_calls}</span>
          <span className="usage-stat-label">total calls</span>
        </div>
        <div className="usage-stat">
          <span className="usage-stat-value">{summary.llm_calls}</span>
          <span className="usage-stat-label">LLM calls</span>
        </div>
        <div className="usage-stat">
          <span className="usage-stat-value">{summary.local_calls}</span>
          <span className="usage-stat-label">local model calls</span>
        </div>
        <div className="usage-stat">
          <span className="usage-stat-value">{summary.mock_calls}</span>
          <span className="usage-stat-label">mock calls</span>
        </div>
        <div className="usage-stat">
          <span className="usage-stat-value">{summary.total_tokens.toLocaleString()}</span>
          <span className="usage-stat-label">total tokens</span>
        </div>
        <div className="usage-stat">
          <span className="usage-stat-value">${summary.total_estimated_cost_usd.toFixed(4)}</span>
          <span className="usage-stat-label">est. cost</span>
        </div>
        <div className="usage-stat">
          <span className="usage-stat-value">{summary.avg_latency_ms.toFixed(0)}ms</span>
          <span className="usage-stat-label">avg latency</span>
        </div>
      </div>

      {summary.by_endpoint.length > 0 && (
        <table className="test-case-table">
          <thead>
            <tr>
              <th>Endpoint</th>
              <th>Calls</th>
              <th>Tokens</th>
              <th>Est. cost</th>
              <th>Avg latency</th>
            </tr>
          </thead>
          <tbody>
            {summary.by_endpoint.map((e) => (
              <tr key={e.endpoint}>
                <td>{e.endpoint}</td>
                <td>{e.call_count}</td>
                <td>{e.total_tokens.toLocaleString()}</td>
                <td>${e.estimated_cost_usd.toFixed(4)}</td>
                <td>{e.avg_latency_ms.toFixed(0)}ms</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
