import { useState } from "react";
import type { TestCaseType } from "../types";
import { ALL_TEST_TYPES } from "../types";

interface Props {
  onGenerate: (query: string, topK: number, types: TestCaseType[]) => void;
  isLoading: boolean;
  disabled: boolean;
}

export function RagQueryInput({ onGenerate, isLoading, disabled }: Props) {
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(3);
  const [selectedTypes, setSelectedTypes] = useState<Set<TestCaseType>>(
    new Set(ALL_TEST_TYPES)
  );

  function toggleType(t: TestCaseType) {
    setSelectedTypes((prev) => {
      const next = new Set(prev);
      next.has(t) ? next.delete(t) : next.add(t);
      return next;
    });
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim() || selectedTypes.size === 0) return;
    onGenerate(query.trim(), topK, [...selectedTypes]);
  }

  return (
    <form className="requirement-input" onSubmit={handleSubmit}>
      <label htmlFor="rag-query">What should the test cases cover?</label>
      <input
        id="rag-query"
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="e.g. account lockout after failed login attempts"
        disabled={disabled}
      />

      <div className="field-row" style={{ marginTop: "0.75rem" }}>
        <label htmlFor="top-k">Chunks to retrieve</label>
        <input
          id="top-k"
          type="number"
          min={1}
          max={10}
          value={topK}
          onChange={(e) => setTopK(Number(e.target.value))}
          disabled={disabled}
        />
      </div>

      <fieldset className="type-checkboxes">
        <legend>Test case types to generate</legend>
        {ALL_TEST_TYPES.map((t) => (
          <label key={t} className="checkbox-label">
            <input
              type="checkbox"
              checked={selectedTypes.has(t)}
              onChange={() => toggleType(t)}
              disabled={disabled}
            />
            {t}
          </label>
        ))}
      </fieldset>

      <button type="submit" disabled={disabled || isLoading || !query.trim() || selectedTypes.size === 0}>
        {isLoading ? "Retrieving & generating..." : "Retrieve & generate test cases"}
      </button>
      {disabled && (
        <p className="hint-text">Upload at least one document above to enable this.</p>
      )}
    </form>
  );
}
