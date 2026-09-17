import type { TestCase, VisualCompareResponse } from "../types";

function escapeHtml(value: string): string {
  return value.replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
  })[character] ?? character);
}

function downloadHtml(filename: string, title: string, body: string): void {
  const html = `<!doctype html><html><head><meta charset="utf-8"><title>${escapeHtml(title)}</title><style>body{font:15px system-ui,sans-serif;max-width:1100px;margin:40px auto;padding:0 24px;color:#1a2027}h1{margin-bottom:4px}h2{margin-top:28px;border-bottom:1px solid #dbe0e5;padding-bottom:8px}.meta{color:#6b7684}.card{border:1px solid #dbe0e5;border-left:4px solid #1f7a6c;border-radius:5px;padding:14px;margin:12px 0}.fail{border-left-color:#a4392f}.warning{border-left-color:#b3762c}table{width:100%;border-collapse:collapse}th,td{text-align:left;vertical-align:top;border-bottom:1px solid #dbe0e5;padding:9px}code{font-family:ui-monospace,monospace;background:#eef1f4;padding:2px 4px;border-radius:3px}ul{margin-top:6px}</style></head><body>${body}</body></html>`;
  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function downloadTestCaseReport(testCases: TestCase[]): void {
  const rows = testCases.map((testCase) => `<tr><td>${escapeHtml(testCase.id)}</td><td>${escapeHtml(testCase.title)}</td><td>${escapeHtml(testCase.type)}</td><td>${escapeHtml(testCase.priority)}</td><td><ul>${testCase.steps.map((step) => `<li>${escapeHtml(step)}</li>`).join("")}</ul></td><td>${escapeHtml(testCase.expected_result)}</td><td><code>${escapeHtml(testCase.requirement_reference)}</code></td></tr>`).join("");
  downloadHtml(`qa-test-report-${new Date().toISOString().slice(0, 10)}.html`, "QA Test Case Report", `<h1>QA Test Case Report</h1><p class="meta">Generated ${new Date().toLocaleString()} · ${testCases.length} test cases</p><h2>Test cases</h2><table><thead><tr><th>ID</th><th>Title</th><th>Type</th><th>Priority</th><th>Steps</th><th>Expected result</th><th>Citation</th></tr></thead><tbody>${rows}</tbody></table>`);
}

export function downloadVisualReport(result: VisualCompareResponse): void {
  const checks = result.checks.map((check) => `<article class="card ${escapeHtml(check.status)}"><strong>${escapeHtml(check.label)}</strong><p>${escapeHtml(check.detail)}</p>${check.expected ? `<div>Expected: <code>${escapeHtml(check.expected)}</code></div>` : ""}${check.actual ? `<div>Actual: <code>${escapeHtml(check.actual)}</code></div>` : ""}</article>`).join("");
  const limitations = result.limitations.map((limitation) => `<li>${escapeHtml(limitation)}</li>`).join("");
  downloadHtml(`visual-qa-report-${new Date().toISOString().slice(0, 10)}.html`, "Visual QA Comparison Report", `<h1>Visual QA Comparison Report</h1><p class="meta">${escapeHtml(result.url)} · Generated ${new Date().toLocaleString()}</p><h2>Summary</h2><p><strong>${result.pixel_difference_percent}%</strong> mean pixel difference</p><p>Reference: ${result.reference_width}×${result.reference_height} · Live viewport: ${result.viewport_width}×${result.viewport_height}</p><h2>Checks</h2>${checks}<h2>Limitations</h2><ul>${limitations}</ul>`);
}