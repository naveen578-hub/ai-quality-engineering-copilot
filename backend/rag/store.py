"""
Thin wrapper around a ChromaDB persistent collection.

Kept separate from the chunking/embedding logic so the storage backend can
be swapped later (the project plan calls for Postgres + pgvector down the
line) without touching anything upstream.
"""
from __future__ import annotations

import os
import threading
import uuid
from typing import Dict, List, Optional

import chromadb

from backend.rag.embeddings import embed_texts

COLLECTION_NAME = "requirement_chunks"
_CHROMA_DIR = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma")

_client: Optional[chromadb.ClientAPI] = None
_collection = None
# FastAPI runs sync endpoint functions in a thread pool, so two requests can
# call _get_collection() at nearly the same instant on a cold start (this is
# exactly what React's StrictMode double-invoked mount effect does in dev).
# chromadb's own PersistentClient/SharedSystemClient init is not safe against
# that race — without this lock, two threads can both see `_collection is
# None`, both call chromadb.PersistentClient() concurrently, and one of them
# hits a KeyError deep inside chromadb's internal system registry. Confirmed
# via a real Playwright run against a cold server, not a hypothetical.
_init_lock = threading.Lock()


def _get_collection():
    global _client, _collection
    if _collection is None:
        with _init_lock:
            if _collection is None:  # re-check: another thread may have finished while we waited
                os.makedirs(_CHROMA_DIR, exist_ok=True)
                _client = chromadb.PersistentClient(path=_CHROMA_DIR)
                # cosine distance suits both the OpenAI embeddings and our normalized mock vectors
                _collection = _client.get_or_create_collection(
                    name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
                )
    return _collection


def add_document_chunks(
    document_id: str,
    filename: str,
    chunk_texts: List[str],
    chunk_requirement_ids: List[Optional[str]],
) -> List[str]:
    """Embeds and stores chunks for one document. Returns the chunk ids assigned."""
    if not chunk_texts:
        return []

    collection = _get_collection()
    embeddings = embed_texts(chunk_texts, endpoint="documents (ingest)")
    chunk_ids = [f"{document_id}::chunk-{i}" for i in range(len(chunk_texts))]

    metadatas = [
        {
            "document_id": document_id,
            "source_filename": filename,
            "chunk_index": i,
            "requirement_id": req_id or "",
        }
        for i, req_id in enumerate(chunk_requirement_ids)
    ]

    collection.add(ids=chunk_ids, embeddings=embeddings, documents=chunk_texts, metadatas=metadatas)
    return chunk_ids


def query(query_text: str, top_k: int = 3, document_id: Optional[str] = None) -> List[Dict]:
    collection = _get_collection()
    if collection.count() == 0:
        return []

    [query_embedding] = embed_texts([query_text], endpoint="generate-test-cases/from-documents (retrieval)")
    where = {"document_id": document_id} if document_id else None

    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, max(collection.count(), 1)),
        where=where,
    )

    matches: List[Dict] = []
    ids = result.get("ids", [[]])[0]
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]

    for chunk_id, text, meta, distance in zip(ids, documents, metadatas, distances):
        # Chroma returns cosine *distance*; convert to a 0-1 "similarity-ish" score for display.
        score = max(0.0, 1.0 - distance / 2.0)
        matches.append(
            {
                "chunk_id": chunk_id,
                "text": text,
                "requirement_id": meta.get("requirement_id") or None,
                "source_filename": meta.get("source_filename", ""),
                "document_id": meta.get("document_id", ""),
                "score": round(score, 4),
            }
        )
    return matches


def list_documents() -> List[Dict]:
    collection = _get_collection()
    if collection.count() == 0:
        return []

    all_rows = collection.get(include=["metadatas"])
    by_doc: Dict[str, Dict] = {}
    for meta in all_rows["metadatas"]:
        doc_id = meta.get("document_id", "unknown")
        entry = by_doc.setdefault(
            doc_id,
            {"document_id": doc_id, "filename": meta.get("source_filename", ""), "chunk_count": 0, "requirement_ids": set()},
        )
        entry["chunk_count"] += 1
        if meta.get("requirement_id"):
            entry["requirement_ids"].add(meta["requirement_id"])

    documents = []
    for entry in by_doc.values():
        entry["requirement_ids"] = sorted(entry["requirement_ids"])
        documents.append(entry)
    return documents


def new_document_id() -> str:
    return f"doc-{uuid.uuid4().hex[:10]}"


def get_document_chunks(document_id: str) -> List[Dict]:
    """Returns every chunk belonging to one document, in original chunk order."""
    collection = _get_collection()
    if collection.count() == 0:
        return []

    rows = collection.get(where={"document_id": document_id}, include=["documents", "metadatas"])
    chunks = [
        {
            "chunk_id": chunk_id,
            "text": text,
            "requirement_id": meta.get("requirement_id") or None,
            "source_filename": meta.get("source_filename", ""),
            "document_id": meta.get("document_id", ""),
            "chunk_index": meta.get("chunk_index", 0),
        }
        for chunk_id, text, meta in zip(rows["ids"], rows["documents"], rows["metadatas"])
    ]
    return sorted(chunks, key=lambda c: c["chunk_index"])


def reset() -> None:
    """Wipes the collection. Used by tests and the (future) admin 'clear demo data' action.
    Safe to call even if the collection was never created or was already
    deleted (e.g. two reset() calls back to back) — chromadb raises
    NotFoundError in that case, which is exactly the state we want anyway."""
    global _collection
    with _init_lock:
        if _client is not None:
            try:
                _client.delete_collection(COLLECTION_NAME)
            except Exception:
                pass  # already gone — that's the desired end state
        _collection = None
