import { useRef, useState } from "react";
import type { EndpointSummary, TestCase } from "../types";
import { generateApiTestCases, uploadOpenApiSpec } from "../api/client";
import { TestCaseTable } from "./TestCaseTable";

export function OpenApiPanel() {
  const [specId, setSpecId] = useState<string | null>(null);
  const [filename, setFilename] = useState<string | null>(null);
  const [endpoints, setEndpoints] = useState<EndpointSummary[]>([]);
  const [selectedEndpoints, setSelectedEndpoints] = useState<Set<string>>(new Set());
  const [testCases, setTestCases] = useState<TestCase[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function handleFileSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setIsUploading(true);
    setError(null);
    try {
      const res = await uploadOpenApiSpec(file);
      setSpecId(res.spec_id);
      setFilename(res.filename);
      setEndpoints(res.endpoints);
      setSelectedEndpoints(new Set(res.endpoints.map((e) => e.endpoint_id)));
      setTestCases([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  function toggleEndpoint(id: string) {
    setSelectedEndpoints((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  async function handleGenerate() {
    if (!specId || selectedEndpoints.size === 0) return;
    setIsGenerating(true);
    setError(null);
    try {
      const res = await generateApiTestCases({
        spec_id: specId,
        endpoint_ids: [...selectedEndpoints],
        max_endpoints: 50,
      });
      setTestCases(res.test_cases);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Generation failed.");
    } finally {
      setIsGenerating(false);
    }
  }

  return (
    <div className="openapi-panel">
      <div className="document-panel">
        <div className="document-panel-header">
          <h2>OpenAPI / Swagger spec</h2>
          <label className="upload-button">
            {isUploading ? "Uploading..." : "Upload spec (JSON or YAML)"}
            <input
              ref={fileInputRef}
              type="file"
              accept=".json,.yaml,.yml"
              onChange={handleFileSelected}
              disabled={isUploading}
              hidden
            />
          </label>
        </div>

        {error && <div className="error-banner">{error}</div>}

        {!filename ? (
          <p className="empty-state">
            Upload an OpenAPI/Swagger spec to generate API test cases directly from its
            paths, parameters, and security requirements — no LLM needed.
          </p>
        ) : (
          <>
            <p className="hint-text">
              {filename} — {endpoints.length} endpoint{endpoints.length !== 1 ? "s" : ""} found.
            </p>
            <ul className="endpoint-list">
              {endpoints.map((ep) => (
                <li key={ep.endpoint_id}>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={selectedEndpoints.has(ep.endpoint_id)}
                      onChange={() => toggleEndpoint(ep.endpoint_id)}
                    />
                    <span className="citation-tag">{ep.endpoint_id}</span>
                    {ep.summary && <span className="endpoint-summary"> — {ep.summary}</span>}
                    {ep.requires_auth && <span className="badge badge-api">auth</span>}
                  </label>
                </li>
              ))}
            </ul>
            <button type="button" onClick={handleGenerate} disabled={isGenerating || selectedEndpoints.size === 0}>
              {isGenerating ? "Generating..." : "Generate API test cases"}
            </button>
          </>
        )}
      </div>

      <TestCaseTable testCases={testCases} />
    </div>
  );
}
