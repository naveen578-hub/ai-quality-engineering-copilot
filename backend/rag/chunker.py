"""
Splits extracted document text into chunks for embedding + retrieval.

Two strategies, in priority order:

1. Requirement-aware: if the text contains explicit requirement markers
   like "REQ-001:" or "REQ-001 -", each chunk is exactly one requirement's
   text. This gives the cleanest possible citations, since a chunk *is*
   a requirement.
2. Paragraph fallback: for documents with no such markers, split on blank
   lines into paragraphs, then greedily pack paragraphs into ~target_size
   character windows with overlap, so no chunk straddles a huge distance
   of unrelated context.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

REQUIREMENT_MARKER = re.compile(r"(?m)^\s*(REQ-[A-Za-z0-9_.-]+)\s*[:\-]\s*")

TARGET_CHUNK_SIZE = 800
CHUNK_OVERLAP = 120


@dataclass
class Chunk:
    text: str
    requirement_id: Optional[str]
    chunk_index: int


def chunk_document(text: str) -> List[Chunk]:
    text = text.strip()
    if not text:
        return []

    marker_matches = list(REQUIREMENT_MARKER.finditer(text))
    if marker_matches:
        return _chunk_by_requirement_marker(text, marker_matches)
    return _chunk_by_paragraph(text)


def _chunk_by_requirement_marker(text: str, matches: List[re.Match]) -> List[Chunk]:
    chunks: List[Chunk] = []
    for i, match in enumerate(matches):
        req_id = match.group(1)
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunks.append(Chunk(text=chunk_text, requirement_id=req_id, chunk_index=i))
    return chunks


def _chunk_by_paragraph(text: str) -> List[Chunk]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    chunks: List[Chunk] = []
    current = ""
    for para in paragraphs:
        candidate = f"{current}\n\n{para}".strip() if current else para
        if len(candidate) <= TARGET_CHUNK_SIZE or not current:
            current = candidate
        else:
            chunks.append(Chunk(text=current, requirement_id=None, chunk_index=len(chunks)))
            # Start the next chunk with a small overlap tail from the previous one,
            # so retrieval doesn't lose context right at a chunk boundary.
            overlap_tail = current[-CHUNK_OVERLAP:]
            current = f"{overlap_tail}\n\n{para}".strip()

    if current:
        chunks.append(Chunk(text=current, requirement_id=None, chunk_index=len(chunks)))

    return chunks
