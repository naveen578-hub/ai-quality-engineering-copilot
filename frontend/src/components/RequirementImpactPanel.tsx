import { useEffect, useState } from "react";
import { fetchRequirementImpacts, setRequirementImpactReviewed } from "../api/client";
import type { RequirementImpactReport } from "../types";

interface Props {
  canReview: boolean;
}

export function RequirementImpactPanel({ canReview }: Props) {
  const [report, setReport] = useState<RequirementImpactReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      setReport(await fetchRequirementImpacts());
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load requirement changes.");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function toggleReviewed(impactId: number, reviewed: boolean) {
    try {
      await setRequirementImpactReviewed(impactId, reviewed);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update review state.");
    }
  }

  if (error) return <div className="error-banner" role="alert">{error}</div>;
  if (!report) return <p className="empty-state">Loading requirement changes...</p>;

  const pendingCount = report.impacts.filter((impact) => !impact.reviewed).length;
  return (
    <section className="impact-panel">
      <div className="panel-heading">
        <div>
          <h2>Requirement change impact</h2>
          <p>Compare uploads by filename and requirement ID. Review markers do not change test-case approval.</p>
        </div>
        <span className="coverage-badge">{pendingCount} needs review</span>
      </div>

      {report.impacts.length === 0 ? (
        <p className="empty-state">No requirement changes to review. Upload a newer version of a requirements document to compare it.</p>
      ) : (
        <div className="impact-list">
          {report.impacts.map((impact) => (
            <article className={`finding-card impact-card ${impact.reviewed ? "impact-reviewed" : ""}`} key={impact.impact_id}>
              <div className="finding-header">
                <span className="citation-tag">{impact.requirement_id}</span>
                <span className={`impact-kind impact-${impact.change_type}`}>{impact.change_type}</span>
                <span className="chunk-score">{impact.filename}</span>
              </div>
              {impact.old_text && <p className="impact-text"><strong>Previous:</strong> {impact.old_text}</p>}
              {impact.new_text && <p className="impact-text"><strong>Current:</strong> {impact.new_text}</p>}
              <div className="impact-cases">
                <strong>{impact.affected_test_cases.length} linked test case{impact.affected_test_cases.length === 1 ? "" : "s"}</strong>
                {impact.affected_test_cases.length === 0 ? (
                  <p>No saved test cases currently reference this requirement.</p>
                ) : (
                  <ul>
                    {impact.affected_test_cases.map((testCase) => (
                      <li key={testCase.db_id}>{testCase.id}: {testCase.title} <span>({testCase.status})</span></li>
                    ))}
                  </ul>
                )}
              </div>
              {canReview && (
                <button type="button" className="small-button" onClick={() => toggleReviewed(impact.impact_id, !impact.reviewed)}>
                  {impact.reviewed ? "Reopen review" : "Mark reviewed"}
                </button>
              )}
            </article>
          ))}
        </div>
      )}

      {report.unlinked_test_cases.length > 0 && (
        <section className="unlinked-cases">
          <h3>Test cases without a current requirement match</h3>
          <p className="hint-text">These references do not match any requirement ID in the latest uploaded document versions.</p>
          <ul>
            {report.unlinked_test_cases.map((testCase) => (
              <li key={testCase.db_id}>{testCase.id}: {testCase.title} <span>({testCase.requirement_reference}; {testCase.status})</span></li>
            ))}
          </ul>
        </section>
      )}
    </section>
  );
}
