import { useState } from "react";
import type { SqlValidation } from "../types";
import { generateSqlValidations } from "../api/client";

export function SqlValidationPanel() {
  const [requirementText, setRequirementText] = useState("");
  const [tableName, setTableName] = useState("");
  const [columnName, setColumnName] = useState("");
  const [requirementId, setRequirementId] = useState("REQ-001");
  const [validations, setValidations] = useState<SqlValidation[]>([]);
  const [unmatchedNote, setUnmatchedNote] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!requirementText.trim()) return;
    setIsLoading(true);
    setError(null);
    setUnmatchedNote(null);
    try {
      const res = await generateSqlValidations({
        requirement_text: requirementText.trim(),
        table_name: tableName.trim() || undefined,
        column_name: columnName.trim() || undefined,
        requirement_id: requirementId.trim() || "REQ-001",
      });
      setValidations(res.validations);
      setUnmatchedNote(res.unmatched_note);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Generation failed.");
      setValidations([]);
    } finally {
      setIsLoading(false);
    }
  }

  function copySql(sql: string, index: number) {
    navigator.clipboard.writeText(sql).then(() => {
      setCopiedIndex(index);
      setTimeout(() => setCopiedIndex(null), 1500);
    });
  }

  return (
    <div className="sql-validation-panel">
      <form className="requirement-input" onSubmit={handleSubmit}>
        <div className="field-row">
          <label htmlFor="sql-req-id">Requirement ID</label>
          <input id="sql-req-id" type="text" value={requirementId} onChange={(e) => setRequirementId(e.target.value)} />
          <label htmlFor="sql-table">Table name</label>
          <input
            id="sql-table"
            type="text"
            value={tableName}
            onChange={(e) => setTableName(e.target.value)}
            placeholder="clearance_cases"
            required
          />
          <label htmlFor="sql-column">Column name(s) (optional)</label>
          <input
            id="sql-column"
            type="text"
            value={columnName}
            onChange={(e) => setColumnName(e.target.value)}
            placeholder="case_id, common_intake_id"
          />
        </div>

        <label htmlFor="sql-req-text">Requirement text (stating a data constraint)</label>
        <textarea
          id="sql-req-text"
          rows={4}
          value={requirementText}
          onChange={(e) => setRequirementText(e.target.value)}
          placeholder="e.g. Member ID search shall accept alphanumeric IDs between 8 and 12 characters."
        />

        <button type="submit" disabled={isLoading || !requirementText.trim()}>
          {isLoading ? "Analyzing..." : "Generate SQL validation queries"}
        </button>
      </form>

      {error && <div className="error-banner">{error}</div>}

      {unmatchedNote && <p className="hint-text">{unmatchedNote}</p>}

      {validations.map((v, i) => (
        <div className="sql-card" key={i}>
          <div className="sql-card-header">
            <span className="badge badge-boundary">{v.rule_detected}</span>
            <span className="citation-tag">{v.requirement_reference}</span>
            <button type="button" className="small-button" onClick={() => copySql(v.sql, i)}>
              {copiedIndex === i ? "Copied!" : "Copy SQL"}
            </button>
          </div>
          <p className="sql-description">{v.description}</p>
          <pre className="sql-code">{v.sql}</pre>
        </div>
      ))}
    </div>
  );
}
