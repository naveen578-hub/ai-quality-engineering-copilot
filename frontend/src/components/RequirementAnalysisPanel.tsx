import { useEffect, useState } from "react";
import type { RequirementAnalysisResponse } from "../types";
import { fetchRequirementAnalysis } from "../api/client";

export function RequirementAnalysisPanel() {
  const [analysis, setAnalysis] = useState<RequirementAnalysisResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchRequirementAnalysis()
      .then(setAnalysis)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load analysis."));
  }, []);

  if (error) return <div className="error-banner">{error}</div>;
  if (!analysis) return <p className="empty-state">Scanning requirements...</p>;

  const nothingFound = analysis.duplicates.length === 0 && analysis.conflicts.length === 0;

  return (
    <div className="analysis-panel">
      <h2>Duplicate &amp; conflicting requirement detection</h2>
      <p className="hint-text">
        Heuristic-based, meant to flag candidates for human review — not an authoritative
        finding. See the README for exactly what is and isn't detected.
      </p>

      {nothingFound && (
        <p className="empty-state">
          No likely duplicates or conflicts found across indexed requirements (or fewer than
          two requirements are indexed).
        </p>
      )}

      {analysis.duplicates.length > 0 && (
        <>
          <h3>Likely duplicates</h3>
          {analysis.duplicates.map((d, i) => (
            <div className="finding-card" key={i}>
              <div className="finding-header">
                <span className="citation-tag">{d.requirement_id_a}</span>
                <span>↔</span>
                <span className="citation-tag">{d.requirement_id_b}</span>
                <span className="chunk-score">similarity {d.similarity.toFixed(2)}</span>
              </div>
              <p className="finding-text">{d.text_a}</p>
              <p className="finding-text">{d.text_b}</p>
            </div>
          ))}
        </>
      )}

      {analysis.conflicts.length > 0 && (
        <>
          <h3>Likely conflicts</h3>
          {analysis.conflicts.map((c, i) => (
            <div className="finding-card finding-conflict" key={i}>
              <div className="finding-header">
                <span className="citation-tag">{c.requirement_id_a}</span>
                <span>↔</span>
                <span className="citation-tag">{c.requirement_id_b}</span>
              </div>
              <p className="finding-reason">{c.reason}</p>
              <p className="finding-text">{c.text_a}</p>
              <p className="finding-text">{c.text_b}</p>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
