"""
Runs the same evaluation as evaluation/run_rag_eval.py, but as a pytest test
so it's part of the normal CI suite rather than something that has to be
remembered and run separately.
"""
import os
import sys

os.environ.pop("OPENAI_API_KEY", None)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

# NOTE: deliberately does NOT set its own CHROMA_PERSIST_DIR — see the
# comment in conftest.py for why that doesn't give real isolation anyway
# (backend/rag/store.py's client is a process-wide singleton) and was
# actively dangerous when multiple files tried to rmtree "their own"
# directory. This file uses the shared test directory conftest.py sets up,
# and cleans up via store.reset() (a real API call), not the filesystem.

import pytest  # noqa: E402

from evaluation.golden_set import GOLDEN_SET  # noqa: E402


@pytest.fixture(autouse=True)
def clean_eval_store():
    from backend.rag import store

    store.reset()
    yield


def _ingest_sample_doc():
    from backend.rag.ingest import ingest_document

    sample_path = os.path.join(REPO_ROOT, "sample-data", "sample_requirement.txt")
    with open(sample_path, "rb") as f:
        content = f.read()
    ingest_document("sample_requirement.txt", content)


def test_retrieval_hit_at_1_meets_floor():
    from backend.rag import store

    _ingest_sample_doc()

    hits = 0
    for item in GOLDEN_SET:
        matches = store.query(item.query, top_k=1)
        if matches and matches[0]["requirement_id"] == item.expected_requirement_id:
            hits += 1

    hit_at_1 = hits / len(GOLDEN_SET)
    # Same floor as evaluation/run_rag_eval.py — mock-mode hashed embeddings
    # are a floor, not a ceiling; this just guards against a real regression
    # (e.g. someone breaking chunking or the embedding function), not
    # against the mock embedding simply being approximate.
    assert hit_at_1 >= 0.5, f"Hit@1 dropped to {hit_at_1:.1%}, below the 50% floor"


def test_every_generated_citation_is_verified_across_golden_set():
    from backend.generators.rag_generator import generate_from_rag
    from backend.models.schemas import RagGenerateRequest
    from backend.rag import store

    _ingest_sample_doc()

    checked = 0
    for item in GOLDEN_SET:
        matches = store.query(item.query, top_k=3)
        if not matches:
            continue
        valid_refs = {m["requirement_id"] or m["chunk_id"] for m in matches}

        response = generate_from_rag(RagGenerateRequest(query=item.query, top_k=3))
        for tc in response.test_cases:
            # Per-test-case citations can point at any chunk that was actually
            # retrieved (not necessarily always the single top one) — the
            # guardrail is that it's always ONE OF the real retrieved chunks,
            # never an invented one.
            assert tc.requirement_reference in valid_refs, (
                f"Unverified citation for query {item.query!r}: "
                f"got {tc.requirement_reference!r}, valid options were {valid_refs!r}"
            )
            checked += 1

    assert checked > 0, "No test cases were actually checked — golden set or retrieval broke silently"
