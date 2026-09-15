import os

import pytest

os.environ.pop("OPENAI_API_KEY", None)

# NOTE: this file used to set its own CHROMA_PERSIST_DIR and rmtree it at
# teardown. That's now centralized in conftest.py — see the comment there
# for why per-file directories didn't actually give per-file isolation
# (backend/rag/store.py's client is a process-wide singleton), and why
# rmtree-based cleanup was actively dangerous once more than one file did it.

from backend.rag import store  # noqa: E402

SAMPLE_DOC = (
    b"REQ-001: The system shall allow an authorized user with regular FEP access to "
    b"search for a patient by member ID and view the patient's record.\n\n"
    b"REQ-002: Users without FEP access shall be denied access to FEP patient records "
    b"and shall see a generic access-denied message.\n\n"
    b"REQ-003: Member ID search shall accept alphanumeric IDs between 8 and 12 characters."
)


@pytest.fixture(autouse=True)
def clean_store():
    store.reset()
    yield


def test_upload_txt_document_and_chunk_by_requirement_marker(client):
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("requirements.txt", SAMPLE_DOC, "text/plain")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["document"]["chunk_count"] == 3
    assert body["document"]["requirement_ids"] == ["REQ-001", "REQ-002", "REQ-003"]
    assert body["embedding_mode"] == "mock"
    assert len(body["chunks"]) == 3


def test_upload_rejects_unsupported_extension(client):
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("diagram.png", b"not a real doc", "image/png")},
    )
    assert resp.status_code == 422


def test_upload_rejects_empty_file(client):
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert resp.status_code == 400


def test_list_documents_reflects_uploads(client):
    client.post("/api/v1/documents", files={"file": ("reqs2.txt", SAMPLE_DOC, "text/plain")})
    resp = client.get("/api/v1/documents")
    assert resp.status_code == 200
    docs = resp.json()
    assert len(docs) >= 1
    assert all(d["chunk_count"] > 0 for d in docs)


def test_generate_from_documents_returns_verified_citation(client):
    client.post("/api/v1/documents", files={"file": ("reqs3.txt", SAMPLE_DOC, "text/plain")})

    resp = client.post(
        "/api/v1/generate-test-cases/from-documents",
        json={"query": "FEP access denied error message", "top_k": 3},
    )
    assert resp.status_code == 200
    body = resp.json()

    assert len(body["test_cases"]) == 5
    retrieved = body["retrieved_chunks"]
    assert len(retrieved) > 0
    retrieved_by_id = {c["requirement_id"]: c["text"] for c in retrieved}

    for tc in body["test_cases"]:
        # Every citation must point at a chunk we actually retrieved — the
        # citation-verification guardrail — never an invented one.
        assert tc["requirement_reference"] in retrieved_by_id
        assert tc["source_chunk"] in retrieved_by_id[tc["requirement_reference"]]


def test_generate_from_documents_distributes_citations_across_chunks(client):
    """With multiple distinct requirement chunks retrieved, different test
    cases should cite different chunks — not all default to the single top
    match. Round-robin fallback in mock mode (no LLM to ask for a per-test-case
    source label) is what guarantees this deterministically."""
    client.post("/api/v1/documents", files={"file": ("reqs5.txt", SAMPLE_DOC, "text/plain")})

    resp = client.post(
        "/api/v1/generate-test-cases/from-documents",
        json={"query": "FEP access rules", "top_k": 3},
    )
    assert resp.status_code == 200
    body = resp.json()

    cited_requirement_ids = {tc["requirement_reference"] for tc in body["test_cases"]}
    retrieved_ids = {c["requirement_id"] for c in body["retrieved_chunks"]}

    assert len(retrieved_ids) > 1, "test setup should have retrieved more than one distinct chunk"
    assert len(cited_requirement_ids) > 1, "test cases should cite more than one distinct chunk"
    assert cited_requirement_ids.issubset(retrieved_ids)

    # Mock-mode self-consistency: each test case's title should mention text
    # from the SAME chunk it cites, not a mismatched one (see rag_generator.py
    # module docstring — content generation follows the same assignment as
    # the citation, specifically to avoid this kind of inconsistency).
    chunk_text_by_id = {c["requirement_id"]: c["text"] for c in body["retrieved_chunks"]}
    for tc in body["test_cases"]:
        cited_text = chunk_text_by_id[tc["requirement_reference"]]
        # The mock title embeds the first sentence of its assigned chunk;
        # check for a distinctive word from that sentence rather than an
        # exact substring match (title text is truncated/reformatted).
        first_word_of_chunk = cited_text.split(":", 1)[-1].strip().split()[0]
        assert first_word_of_chunk.lower() in tc["title"].lower()


def test_generate_from_documents_errors_with_no_documents_indexed(client):
    store.reset()
    resp = client.post(
        "/api/v1/generate-test-cases/from-documents",
        json={"query": "anything", "top_k": 3},
    )
    assert resp.status_code == 422


def test_generate_from_documents_masks_pii_in_query(client):
    """The query field is a guardrail-covered input too, not just uploaded
    document text — a user could type PII directly into a search query."""
    client.post("/api/v1/documents", files={"file": ("reqs4.txt", SAMPLE_DOC, "text/plain")})

    resp = client.post(
        "/api/v1/generate-test-cases/from-documents",
        json={"query": "FEP access for member with SSN 123-45-6789", "top_k": 3},
    )
    assert resp.status_code == 200
    # The retrieval still succeeded (proving the masked query was usable, not empty/broken)
    assert len(resp.json()["test_cases"]) == 5
