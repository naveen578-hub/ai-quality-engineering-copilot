import type { RetrievedChunk } from "../types";

interface Props {
  chunks: RetrievedChunk[];
}

export function RetrievedChunksPanel({ chunks }: Props) {
  if (chunks.length === 0) return null;

  return (
    <div className="retrieved-chunks-panel">
      <h3>Retrieved chunks (ranked by relevance)</h3>
      <ol>
        {chunks.map((c) => (
          <li key={c.chunk_id}>
            <div className="chunk-meta-row">
              <span className="citation-tag">{c.requirement_id ?? c.chunk_id}</span>
              <span className="chunk-source">{c.source_filename}</span>
              <span className="chunk-score">score {c.score.toFixed(2)}</span>
            </div>
            <p className="chunk-text">{c.text}</p>
          </li>
        ))}
      </ol>
    </div>
  );
}
