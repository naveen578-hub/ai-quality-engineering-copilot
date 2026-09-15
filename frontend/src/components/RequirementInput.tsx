import { useState } from "react";
import type { TestCaseType } from "../types";
import { ALL_TEST_TYPES } from "../types";

interface Props {
  onGenerate: (requirementText: string, requirementId: string, types: TestCaseType[]) => void;
  isLoading: boolean;
}

const SAMPLE_REQUIREMENT =
  "The system shall allow an authorized user with regular FEP access to search " +
  "for a patient by member ID and view the patient's record. Access must be " +
  "denied to users without FEP access.";

export function RequirementInput({ onGenerate, isLoading }: Props) {
  const [requirementText, setRequirementText] = useState("");
  const [requirementId, setRequirementId] = useState("REQ-001");
  const [selectedTypes, setSelectedTypes] = useState<Set<TestCaseType>>(
    new Set(ALL_TEST_TYPES)
  );

  function toggleType(t: TestCaseType) {
    setSelectedTypes((prev) => {
      const next = new Set(prev);
      if (next.has(t)) {
        next.delete(t);
      } else {
        next.add(t);
      }
      return next;
    });
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!requirementText.trim() || selectedTypes.size === 0) return;
    onGenerate(requirementText.trim(), requirementId.trim() || "REQ-001", [
      ...selectedTypes,
    ]);
  }

  return (
    <form className="requirement-input" onSubmit={handleSubmit}>
      <div className="field-row">
        <label htmlFor="req-id">Requirement ID</label>
        <input
          id="req-id"
          type="text"
          value={requirementId}
          onChange={(e) => setRequirementId(e.target.value)}
          placeholder="REQ-001"
        />
      </div>

      <label htmlFor="req-text">Requirement text</label>
      <textarea
        id="req-text"
        rows={6}
        value={requirementText}
        onChange={(e) => setRequirementText(e.target.value)}
        placeholder="Paste or type a requirement here..."
      />
      <button
        type="button"
        className="link-button"
        onClick={() => setRequirementText(SAMPLE_REQUIREMENT)}
      >
        Use sample requirement
      </button>

      <fieldset className="type-checkboxes">
        <legend>Test case types to generate</legend>
        {ALL_TEST_TYPES.map((t) => (
          <label key={t} className="checkbox-label">
            <input
              type="checkbox"
              checked={selectedTypes.has(t)}
              onChange={() => toggleType(t)}
            />
            {t}
          </label>
        ))}
      </fieldset>

      <button
        type="submit"
        disabled={isLoading || !requirementText.trim() || selectedTypes.size === 0}
      >
        {isLoading ? "Generating..." : "Generate test cases"}
      </button>
    </form>
  );
}
