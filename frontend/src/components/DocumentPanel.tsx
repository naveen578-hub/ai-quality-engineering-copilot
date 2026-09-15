import { useCallback, useEffect, useRef, useState } from "react";
import type { DocumentSummary } from "../types";
import { listDocuments, uploadDocument } from "../api/client";

interface Props {
  onDocumentsChanged?: (docs: DocumentSummary[]) => void;
}

const ACCEPTED_EXTENSIONS = ".pdf,.docx,.txt,.md";

export function DocumentPanel({ onDocumentsChanged }: Props) {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const docs = await listDocuments();
      setDocuments(docs);
      onDocumentsChanged?.(docs);
    } catch {
      // Non-fatal — the upload form still works even if the initial list fetch fails.
    }
  }, [onDocumentsChanged]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleFileSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setIsUploading(true);
    setError(null);
    try {
      await uploadDocument(file);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  return (
    <div className="document-panel">
      <div className="document-panel-header">
        <h2>Uploaded requirement documents</h2>
        <label className="upload-button">
          {isUploading ? "Uploading..." : "Upload PDF / Word / text"}
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPTED_EXTENSIONS}
            onChange={handleFileSelected}
            disabled={isUploading}
            hidden
          />
        </label>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {documents.length === 0 ? (
        <p className="empty-state">
          No documents indexed yet. Upload a requirements PDF, Word doc, or text file to
          enable retrieval-grounded generation below.
        </p>
      ) : (
        <ul className="document-list">
          {documents.map((doc) => (
            <li key={doc.document_id}>
              <span className="doc-filename">{doc.filename}</span>
              <span className="doc-meta">
                {doc.chunk_count} chunk{doc.chunk_count !== 1 ? "s" : ""}
                {doc.requirement_ids.length > 0 && ` · ${doc.requirement_ids.join(", ")}`}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
