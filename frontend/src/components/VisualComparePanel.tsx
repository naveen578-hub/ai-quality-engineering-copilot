import { useRef, useState } from "react";
import { compareVisual } from "../api/client";
import type { VisualCompareResponse } from "../types";

export function VisualComparePanel() {
  const [reference, setReference] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [width, setWidth] = useState(1440);
  const [height, setHeight] = useState(900);
  const [expectedText, setExpectedText] = useState("");
  const [numbers, setNumbers] = useState("");
  const [flyoutSelector, setFlyoutSelector] = useState("");
  const [flyoutText, setFlyoutText] = useState("");
  const [paginationSelector, setPaginationSelector] = useState("");
  const [expectedPage, setExpectedPage] = useState("");
  const [result, setResult] = useState<VisualCompareResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!reference || !url.trim()) return;
    setIsLoading(true);
    setError(null);
    try {
      setResult(await compareVisual({ reference, url: url.trim(), viewport_width: width, viewport_height: height, expected_text: expectedText, numeric_values: numbers, flyout_selector: flyoutSelector, expected_flyout_text: flyoutText, pagination_selector: paginationSelector, expected_page: expectedPage }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Comparison failed.");
      setResult(null);
    } finally {
      setIsLoading(false);
    }
  }

  return <section className="visual-compare-panel">
    <div className="panel-heading"><div><h2>Visual QA Compare</h2><p>Compare a Figma frame with a live page at the same viewport.</p></div><span className="mode-pill mode-llm">Playwright + pixel diff</span></div>
    <form className="visual-compare-form" onSubmit={submit}>
      <label className="visual-upload">{reference ? reference.name : "Upload Figma screenshot"}<input ref={inputRef} type="file" accept="image/png,image/jpeg" onChange={(event) => setReference(event.target.files?.[0] ?? null)} hidden /></label>
      <label>Live URL<input type="url" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://your-app.example.com/page" required /></label>
      <div className="field-row"><label>Viewport width<input type="number" min={320} max={3840} value={width} onChange={(event) => setWidth(Number(event.target.value))} /></label><label>Viewport height<input type="number" min={240} max={2160} value={height} onChange={(event) => setHeight(Number(event.target.value))} /></label></div>
      <label>Expected text, one item per line<textarea rows={3} value={expectedText} onChange={(event) => setExpectedText(event.target.value)} placeholder="Dashboard\nWelcome back" /></label>
      <label>Expected numbers, one item per line<textarea rows={2} value={numbers} onChange={(event) => setNumbers(event.target.value)} placeholder="24\n$1,250" /></label>
      <div className="field-row"><label>Flyout selector<input value={flyoutSelector} onChange={(event) => setFlyoutSelector(event.target.value)} placeholder="[role=dialog]" /></label><label>Flyout text<input value={flyoutText} onChange={(event) => setFlyoutText(event.target.value)} placeholder="Filter options" /></label></div>
      <div className="field-row"><label>Pagination selector<input value={paginationSelector} onChange={(event) => setPaginationSelector(event.target.value)} placeholder=".pagination" /></label><label>Expected page<input value={expectedPage} onChange={(event) => setExpectedPage(event.target.value)} placeholder="Page 2 of 8" /></label></div>
      <button type="submit" disabled={isLoading || !reference || !url.trim()}>{isLoading ? "Comparing..." : "Compare live page"}</button>
    </form>
    {error && <div className="error-banner">{error}</div>}
    {result && <div className="visual-results"><div className="visual-summary"><strong>{result.pixel_difference_percent}%</strong><span>mean pixel difference</span><span>{result.reference_width}×{result.reference_height} reference · {result.viewport_width}×{result.viewport_height} live viewport</span></div><div className="visual-check-grid">{result.checks.map((check) => <article className={`visual-check visual-check-${check.status}`} key={`${check.category}-${check.label}`}><div><span className="badge">{check.category}</span><strong>{check.label}</strong></div><p>{check.detail}</p>{check.expected && <small>Expected: {check.expected}</small>}{check.actual && <small>Actual: {check.actual}</small>}</article>)}</div><ul className="hint-text">{result.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul></div>}
  </section>;
}