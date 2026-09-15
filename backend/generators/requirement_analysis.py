"""
Detects likely duplicate and likely conflicting requirements across all
indexed documents.

Both are heuristics, clearly labeled as such rather than presented as
ground truth — this is meant to flag candidates for a human reviewer, not
to make an authoritative call:

- Duplicates: cosine similarity between requirement chunk embeddings above
  a threshold. Two requirements phrased differently but describing the same
  behavior will usually score high here.
- Conflicts: two requirements that share a substantial amount of vocabulary
  (so they're plausibly about the same subject) where one contains a
  negation/prohibition term ("shall not", "must not", "prohibited", "denied")
  and the other doesn't. This catches the common "REQ says X, another REQ
  says not-X" pattern; it will not catch conflicts phrased without a clear
  negation word, and it can false-positive on genuinely complementary
  requirements (e.g. an access-grant rule paired with its own denial rule)
  — flagged pairs should be reviewed, not auto-resolved.
"""
from __future__ import annotations

import math
import re
from itertools import combinations
from typing import Dict, List

from backend.models.schemas import ConflictPair, DuplicatePair, RequirementAnalysisResponse
from backend.rag import store
from backend.rag.embeddings import embed_texts

DUPLICATE_SIMILARITY_THRESHOLD = 0.7
CONFLICT_SHARED_TERM_THRESHOLD = 0.3
NEGATION_TERMS = {"not", "no", "never", "denied", "deny", "prohibited", "forbidden", "cannot", "must not", "shall not"}
STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "by", "with", "is", "are",
    "shall", "will", "system", "user", "users", "be", "that", "this", "as", "must", "req",
}
_WORD_RE = re.compile(r"[a-z0-9]+")
_LEADING_REQ_MARKER = re.compile(r"^\s*REQ-[A-Za-z0-9_.-]+\s*[:\-]\s*", re.IGNORECASE)


def _tokens(text: str) -> set:
    # Strip the leading "REQ-101:" marker before tokenizing — it's boilerplate,
    # not requirement content, and would otherwise inflate overlap between any
    # two requirements just because they're both labeled "REQ-something".
    text = _LEADING_REQ_MARKER.sub("", text)
    words = _WORD_RE.findall(text.lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 2}


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _has_negation(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in NEGATION_TERMS)


def analyze_requirements() -> RequirementAnalysisResponse:
    documents = store.list_documents()

    # Pull every requirement-tagged chunk's text, deduplicated by requirement id
    # (a requirement could theoretically appear in more than one uploaded file;
    # we just take the first occurrence for analysis).
    requirement_texts: Dict[str, str] = {}
    for doc in documents:
        for chunk in store.get_document_chunks(doc["document_id"]):
            if chunk["requirement_id"] and chunk["requirement_id"] not in requirement_texts:
                requirement_texts[chunk["requirement_id"]] = chunk["text"]

    req_ids = sorted(requirement_texts.keys())
    if len(req_ids) < 2:
        return RequirementAnalysisResponse(duplicates=[], conflicts=[])

    texts = [requirement_texts[r] for r in req_ids]
    embeddings = embed_texts(texts, endpoint="requirements/analysis")
    token_sets = [_tokens(t) for t in texts]

    duplicates: List[DuplicatePair] = []
    conflicts: List[ConflictPair] = []

    for i, j in combinations(range(len(req_ids)), 2):
        sim = _cosine(embeddings[i], embeddings[j])
        if sim >= DUPLICATE_SIMILARITY_THRESHOLD:
            duplicates.append(
                DuplicatePair(
                    requirement_id_a=req_ids[i],
                    requirement_id_b=req_ids[j],
                    similarity=round(sim, 4),
                    text_a=texts[i],
                    text_b=texts[j],
                )
            )
            continue  # a near-duplicate pair isn't also flagged as a conflict

        union = token_sets[i] | token_sets[j]
        shared = token_sets[i] & token_sets[j]
        overlap_ratio = (len(shared) / len(union)) if union else 0.0

        if overlap_ratio >= CONFLICT_SHARED_TERM_THRESHOLD and (_has_negation(texts[i]) != _has_negation(texts[j])):
            conflicts.append(
                ConflictPair(
                    requirement_id_a=req_ids[i],
                    requirement_id_b=req_ids[j],
                    shared_terms=sorted(shared),
                    text_a=texts[i],
                    text_b=texts[j],
                    reason=(
                        "These requirements share substantial subject-matter vocabulary, but only one "
                        "contains a negation/denial term — review whether they contradict each other."
                    ),
                )
            )

    return RequirementAnalysisResponse(duplicates=duplicates, conflicts=conflicts)
