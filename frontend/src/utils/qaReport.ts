import type { ExecutionResult, TestCase, VisualCompareResponse } from "../types";

export function visualToExecutionResult(result: VisualCompareResponse): ExecutionResult {
  const failures = result.checks.filter((check) => check.status === "fail");
  return {
    engine: "playwright",
    status: failures.length ? "failed" : "passed",
    name: `Visual comparison: ${result.url}`,
    duration_ms: 0,
    error: failures.map((check) => check.detail).join("; ") || null,
    critical: true,
    evidence: [
      { kind: "visual", name: "pixel_difference_percent", value: String(result.pixel_difference_percent) },
      ...result.checks.map((check) => ({ kind: "visual_check", name: check.label, value: check.status })),
    ],
  };
}

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

export function downloadCombinedQaReport(input: { testCases?: TestCase[]; visual?: VisualCompareResponse; executionResults?: ExecutionResult[] }): void {
  const sections: string[] = ["<h1>QA Execution Report</h1><p class=\"meta\">Generated " + escapeHtml(new Date().toLocaleString()) + "</p>"];
  if (input.testCases?.length) {
    sections.push(`<h2>Generated test cases (${input.testCases.length})</h2><ul>${input.testCases.map((testCase) => `<li><strong>${escapeHtml(testCase.id)} ${escapeHtml(testCase.title)}</strong> — ${escapeHtml(testCase.expected_result)}</li>`).join("")}</ul>`);
  }
  if (input.visual) {
    sections.push(`<h2>Playwright visual comparison</h2><p>URL: ${escapeHtml(input.visual.url)} · Pixel difference: <strong>${input.visual.pixel_difference_percent}%</strong></p><ul>${input.visual.checks.map((check) => `<li><strong>${escapeHtml(check.status)}</strong> ${escapeHtml(check.label)} — ${escapeHtml(check.detail)}</li>`).join("")}</ul>`);
  }
  if (input.executionResults?.length) {
    sections.push(`<h2>Execution results</h2><table><thead><tr><th>Engine</th><th>Name</th><th>Status</th><th>Duration</th><th>Error</th></tr></thead><tbody>${input.executionResults.map((result) => `<tr><td>${escapeHtml(result.engine)}</td><td>${escapeHtml(result.name)}</td><td>${escapeHtml(result.status)}</td><td>${result.duration_ms.toFixed(1)} ms</td><td>${escapeHtml(result.error ?? "")}</td></tr>`).join("")}</tbody></table>`);
  }
  downloadHtml(`qa-execution-report-${new Date().toISOString().slice(0, 10)}.html`, "QA Execution Report", sections.join(""));
}