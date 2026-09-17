import type { TestCase } from "../types";
import { downloadTestCaseReport } from "../utils/qaReport";

interface Props {
  testCases: TestCase[];
  onSaveToLibrary?: () => void;
  isSaving?: boolean;
}

const CSV_HEADERS = [
  "id",
  "title",
  "type",
  "priority",
  "preconditions",
  "steps",
  "expected_result",
  "requirement_reference",
  "source_chunk",
] as const;

function csvEscape(value: string): string {
  // Wrap in quotes and escape internal quotes if the value contains a comma,
  // quote, or newline — standard RFC 4180 behavior.
  if (/[",\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

function toCsv(testCases: TestCase[]): string {
  const rows = testCases.map((tc) =>
    CSV_HEADERS.map((key) => {
      const value = tc[key];
      if (Array.isArray(value)) return csvEscape(value.join(" | "));
      return csvEscape(value ? String(value) : "");
    }).join(",")
  );
  return [CSV_HEADERS.join(","), ...rows].join("\n");
}

function downloadCsv(testCases: TestCase[]) {
  const csv = toCsv(testCases);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `test-cases-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

const TYPE_BADGE_CLASS: Record<TestCase["type"], string> = {
  positive: "badge badge-positive",
  negative: "badge badge-negative",
  boundary: "badge badge-boundary",
  api: "badge badge-api",
  regression: "badge badge-regression",
};

export function TestCaseTable({ testCases, onSaveToLibrary, isSaving }: Props) {
  if (testCases.length === 0) return null;

  return (
    <div className="test-case-table-wrapper">
      <div className="table-header-row">
        <h2>{testCases.length} test case{testCases.length !== 1 ? "s" : ""} generated</h2>
        <div className="library-actions">
          {onSaveToLibrary && (
            <button onClick={onSaveToLibrary} disabled={isSaving}>
              {isSaving ? "Saving..." : "Save to library"}
            </button>
          )}
          <button onClick={() => downloadCsv(testCases)}>Export CSV</button>
          <button onClick={() => downloadTestCaseReport(testCases)}>Export QA report</button>
        </div>
      </div>

      <table className="test-case-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Title</th>
            <th>Type</th>
            <th>Priority</th>
            <th>Preconditions</th>
            <th>Steps</th>
            <th>Expected Result</th>
            <th>Citation</th>
          </tr>
        </thead>
        <tbody>
          {testCases.map((tc) => (
            <tr key={tc.id}>
              <td>{tc.id}</td>
              <td>{tc.title}</td>
              <td>
                <span className={TYPE_BADGE_CLASS[tc.type]}>{tc.type}</span>
              </td>
              <td>{tc.priority}</td>
              <td>
                <ul>
                  {tc.preconditions.map((p, i) => (
                    <li key={i}>{p}</li>
                  ))}
                </ul>
              </td>
              <td>
                <ol>
                  {tc.steps.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ol>
              </td>
              <td>{tc.expected_result}</td>
              <td className="citation-cell">
                <span className="citation-tag" title={tc.source_chunk ?? undefined}>
                  {tc.requirement_reference}
                </span>
                {tc.source_chunk && (
                  <p className="citation-snippet">&ldquo;{tc.source_chunk}&rdquo;</p>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
