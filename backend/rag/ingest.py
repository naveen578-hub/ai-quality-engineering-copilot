"""
Ties extraction, chunking, and storage together into one call for the
upload endpoint.
"""
from __future__ import annotations

from backend.models.schemas import DocumentChunkSummary, DocumentSummary, DocumentUploadResponse
from backend.guardrails.pii import scan_and_mask
from backend.rag import store
from backend.rag.chunker import chunk_document
from backend.rag.embeddings import embedding_mode
from backend.rag.extractor import extract_text


def ingest_document(filename: str, content: bytes) -> DocumentUploadResponse:
    raw_text = extract_text(filename, content)
    text, pii_counts = scan_and_mask(raw_text)
    chunks = chunk_document(text)

    if not chunks:
        raise ValueError("Document produced no usable chunks after extraction.")

    document_id = store.new_document_id()
    chunk_ids = store.add_document_chunks(
        document_id=document_id,
        filename=filename,
        chunk_texts=[c.text for c in chunks],
        chunk_requirement_ids=[c.requirement_id for c in chunks],
    )

    requirement_ids = sorted({c.requirement_id for c in chunks if c.requirement_id})

    summary = DocumentSummary(
        document_id=document_id,
        filename=filename,
        chunk_count=len(chunks),
        requirement_ids=requirement_ids,
    )
    chunk_summaries = [
        DocumentChunkSummary(
            chunk_id=chunk_ids[i],
            requirement_id=c.requirement_id,
            preview=(c.text[:120] + ("..." if len(c.text) > 120 else "")),
        )
        for i, c in enumerate(chunks)
    ]

    return DocumentUploadResponse(
        document=summary, chunks=chunk_summaries, embedding_mode=embedding_mode(), pii_redactions=pii_counts
    )
