"""
Automated RAG evaluation: how well does retrieval find the right requirement
for a query, and does the full generation pipeline still honor the citation-
verification guardrail end to end?

Two things are measured, deliberately kept separate:

1. Retrieval quality (Hit@1, Hit@3, MRR) against evaluation/golden_set.py.
   This is a real, meaningful metric — but note that in mock mode (no
   OPENAI_API_KEY), retrieval runs on a hashed bag-of-words embedding, not
   a real semantic one, so scores here are a floor, not a ceiling. Run this
   with a real API key configured to see what production-quality retrieval
   looks like; the mock-mode numbers mainly prove the harness itself works
   end to end with zero setup.

2. Citation verification (always expected to be 100%): for every golden
   query, generate test cases via the real RAG pipeline and confirm every
   returned test case's citation actually matches a real retrieved chunk.
   This isn't probabilistic — it's a programmatic guarantee in
   backend/generators/rag_generator.py — so this check existing at all is
   a regression guard, not a quality measurement: if it ever fails, someone
   broke the guardrail, not "got unlucky."

Usage:
    python evaluation/run_rag_eval.py
Exits non-zero if Hit@1 falls below MIN_HIT_AT_1, or if any citation fails
verification (that second condition should never trip in a passing build).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("CHROMA_PERSIST_DIR", "./data/chroma-eval")
os.environ.setdefault("QE_COPILOT_DB_PATH", "./data/qe_copilot-eval.db")

MIN_HIT_AT_1 = 0.5  # floor for mock-mode hashed embeddings; expect much higher with a real API key

from evaluation.golden_set import GOLDEN_SET  # noqa: E402


def run() -> int:
    from backend.generators.rag_generator import generate_from_rag
    from backend.models.schemas import RagGenerateRequest
    from backend.rag import store
    from backend.rag.embeddings import embedding_mode
    from backend.rag.ingest import ingest_document

    sample_path = os.path.join(os.path.dirname(__file__), "..", "sample-data", "sample_requirement.txt")
    with open(sample_path, "rb") as f:
        content = f.read()

    store.reset()
    ingest_document("sample_requirement.txt", content)

    mode = embedding_mode()
    print(f"Embedding mode: {mode}")
    print(f"Golden set size: {len(GOLDEN_SET)}\n")

    hits_at_1 = 0
    hits_at_3 = 0
    reciprocal_ranks = []
    citation_failures = []

    print(f"{'Query':<70} {'Expected':<10} {'Retrieved (top-3)':<30} {'Hit@1':<6}")
    print("-" * 120)

    for item in GOLDEN_SET:
        matches = store.query(item.query, top_k=3)
        retrieved_ids = [m["requirement_id"] for m in matches]

        hit1 = len(retrieved_ids) > 0 and retrieved_ids[0] == item.expected_requirement_id
        hit3 = item.expected_requirement_id in retrieved_ids

        hits_at_1 += int(hit1)
        hits_at_3 += int(hit3)

        if item.expected_requirement_id in retrieved_ids:
            rank = retrieved_ids.index(item.expected_requirement_id) + 1
            reciprocal_ranks.append(1.0 / rank)
        else:
            reciprocal_ranks.append(0.0)

        query_display = (item.query[:67] + "...") if len(item.query) > 70 else item.query
        print(f"{query_display:<70} {item.expected_requirement_id:<10} {str(retrieved_ids):<30} {'v' if hit1 else ''}")

        # ---- Citation verification, end to end through the real generation pipeline ----
        try:
            response = generate_from_rag(RagGenerateRequest(query=item.query, top_k=3))
            valid_refs = {m["requirement_id"] or m["chunk_id"] for m in matches}
            for tc in response.test_cases:
                # Per-test-case citations may point at any retrieved chunk, not
                # necessarily always the top one — the guarantee is "one of the
                # real retrieved chunks", never an invented one.
                if tc.requirement_reference not in valid_refs:
                    citation_failures.append((item.query, tc.id, tc.requirement_reference, valid_refs))
        except Exception as exc:  # noqa: BLE001 — this is a diagnostic script, report and continue
            citation_failures.append((item.query, "N/A", "generation raised", str(exc)))

    n = len(GOLDEN_SET)
    hit_at_1 = hits_at_1 / n
    hit_at_3 = hits_at_3 / n
    mrr = sum(reciprocal_ranks) / n

    print("\n" + "=" * 50)
    print("RETRIEVAL METRICS")
    print("=" * 50)
    print(f"Hit@1: {hit_at_1:.1%}  ({hits_at_1}/{n})")
    print(f"Hit@3: {hit_at_3:.1%}  ({hits_at_3}/{n})")
    print(f"MRR:   {mrr:.3f}")

    print("\n" + "=" * 50)
    print("CITATION VERIFICATION")
    print("=" * 50)
    if citation_failures:
        print(f"FAILED - {len(citation_failures)} test case(s) had an unverified citation:")
        for query, tc_id, got, expected in citation_failures:
            print(f"  - query={query!r} tc={tc_id} got={got!r} expected={expected!r}")
    else:
        print("PASSED - every generated test case's citation matched a real retrieved chunk.")

    store.reset()

    ok = hit_at_1 >= MIN_HIT_AT_1 and not citation_failures
    print(f"\nOverall: {'PASS' if ok else 'FAIL'}")
    if hit_at_1 < MIN_HIT_AT_1:
        print(f"  - Hit@1 {hit_at_1:.1%} is below the {MIN_HIT_AT_1:.0%} floor.")
    if citation_failures:
        print(f"  - {len(citation_failures)} citation verification failure(s).")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
