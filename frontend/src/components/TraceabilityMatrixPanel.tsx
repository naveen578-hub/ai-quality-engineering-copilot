import { useEffect, useState } from "react";
import type { TraceabilityMatrix } from "../types";
import { fetchTraceabilityMatrix } from "../api/client";

export function TraceabilityMatrixPanel() {
  const [matrix, setMatrix] = useState<TraceabilityMatrix | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchTraceabilityMatrix()
      .then(setMatrix)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load matrix."));
  }, []);

  if (error) return <div className="error-banner">{error}</div>;
  if (!matrix) return <p className="empty-state">Loading traceability matrix...</p>;

  if (matrix.rows.length === 0) {
    return (
      <p className="empty-state">
        No requirements indexed yet. Upload a document under "Generate from uploaded
        documents" to populate this matrix.
      </p>
    );
  }

  return (
    <div className="traceability-panel">
      <div className="table-header-row">
        <h2>Requirements traceability matrix</h2>
        <span className="coverage-badge">{matrix.coverage_percent}% coverage</span>
      </div>
      <table className="test-case-table">
        <thead>
          <tr>
            <th>Requirement</th>
            <th>Source</th>
            <th>Test cases</th>
            <th>Approved</th>
            <th>Covered types</th>
            <th>Missing types</th>
          </tr>
        </thead>
        <tbody>
          {matrix.rows.map((row) => (
            <tr key={row.requirement_id}>
              <td className="citation-tag">{row.requirement_id}</td>
              <td>{row.source_filename ?? "—"}</td>
              <td>{row.test_case_count}</td>
              <td>{row.approved_count}</td>
              <td>
                {row.covered_types.map((t) => (
                  <span key={t} className={`badge badge-${t}`}>
                    {t}
                  </span>
                ))}
                {row.covered_types.length === 0 && <span className="empty-cell">none</span>}
              </td>
              <td>
                {row.missing_types.map((t) => (
                  <span key={t} className="badge badge-missing">
                    {t}
                  </span>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
