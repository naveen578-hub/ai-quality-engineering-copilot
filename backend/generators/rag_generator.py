"""
Phase 2 generator: retrieves relevant requirement chunks from ChromaDB,
then generates test cases grounded in that retrieved context.

Guardrail note (citation verification): we never trust the LLM's own claim
about which requirement a test case came from *by taking its word for the
citation text itself*. What the model CAN influence is which of the
retrieved chunks (already real, already verified to exist) a given test
case is most associated with — see "source_label" below — but the actual
requirement_reference/source_chunk stamped onto the output always comes
from a real RetrievedChunk we hold, never from text the model wrote.

Per-test-case citation (not just "everything cites the top chunk"): when
more than one chunk is retrieved, different test cases can legitimately be
about different requirements (e.g. one about granting access, another
about denying it). Two ways a test case ends up tied to a specific chunk:
1. LLM mode: the model is asked to tag each test case with a "source_label"
   matching one of the bracketed excerpt labels in the prompt. If that
   label matches a real retrieved chunk, we use it. If it's missing or
   doesn't match anything we actually retrieved, we fall back to (2).
2. Round-robin fallback: test case i cites retrieved_chunks[i % N]. This is
   also the *only* mechanism in mock mode (no LLM to ask), and it's what
   keeps mock-mode content and citation consistent with each other — see
   backend/generators/test_case_generator.py's `subjects` parameter, which
   templates each mock test case from its own assigned chunk's text rather
   than always the top chunk's.
"""
from __future__ import annotations

import json
from typing import List, Optional

from pydantic import ValidationError

from backend.generators.llm_client import call_llm_for_json, is_configured
from backend.generators.test_case_generator import DEFAULT_TYPES, _first_sentence, _mock_generate
from backend.models.schemas import (
    GenerateTestCasesRequest,
    RagGenerateRequest,
    RagGenerateResponse,
    RetrievedChunk,
    TestCase,
    TestCaseType,
)
from backend.observability.usage import track_mock_call
from backend.rag import store

SYSTEM_PROMPT = """You are a senior QA engineer generating software test cases from retrieved
requirement excerpts. Return ONLY a JSON object with this exact shape, no prose, no markdown fences:

{
  "test_cases": [
    {
      "id": "TC-001",
      "title": "string",
      "type": "positive | negative | boundary | api | regression",
      "priority": "high | medium | low",
      "preconditions": ["string", ...],
      "steps": ["string", ...],
      "expected_result": "string",
      "requirement_reference": "string",
      "source_label": "string"
    }
  ]
}

Rules:
- Base every test case only on the retrieved excerpts provided. If they don't fully cover a
  test type, generate the most reasonable test case you can that stays consistent with them.
- Generate exactly one test case for each requested test type, in the order requested.
- Each retrieved excerpt below is prefixed with a bracketed label, e.g. "[REQ-002] ...". Set
  "source_label" to the label of whichever single excerpt that specific test case is most
  based on — different test cases MAY have different labels if they're about different
  excerpts. Copy the label text exactly as given; do not invent a new one.
- "requirement_reference" should also equal that same label (it will be double-checked
  programmatically against the real excerpts either way, so this is a courtesy, not load-bearing).
- Steps must be concrete and actionable, written from a tester's point of view.
- Never invent PII; use generic placeholder names/data only.
- Do not include any text outside the JSON object.
"""


class RagGenerationError(RuntimeError):
    pass


def generate_from_rag(request: RagGenerateRequest) -> RagGenerateResponse:
    matches = store.query(request.query, top_k=request.top_k, document_id=request.document_id)

    if not matches:
        raise RagGenerationError(
            "No documents have been indexed yet (or none matched this query). "
            "Upload a requirements document first via POST /api/v1/documents."
        )

    retrieved_chunks = [RetrievedChunk(**m) for m in matches]
    types = request.test_types or DEFAULT_TYPES

    context = "\n\n---\n\n".join(
        f"[{c.requirement_id or c.chunk_id}] {c.text}" for c in retrieved_chunks
    )

    test_cases, source_labels = _generate_test_cases_from_context(request.query, context, retrieved_chunks, types)

    # --- Citation verification guardrail: every citation traces to a chunk we actually retrieved ---
    verified: List[TestCase] = []
    for i, tc in enumerate(test_cases):
        claimed_label = source_labels[i] if i < len(source_labels) else None
        chunk = _resolve_chunk(claimed_label, retrieved_chunks, fallback_index=i)
        verified.append(
            tc.model_copy(
                update={
                    "requirement_reference": chunk.requirement_id or chunk.chunk_id,
                    "source_chunk": chunk.text[:600],
                }
            )
        )

    return RagGenerateResponse(test_cases=verified, retrieved_chunks=retrieved_chunks)


def _resolve_chunk(claimed_label: Optional[str], retrieved_chunks: List[RetrievedChunk], fallback_index: int) -> RetrievedChunk:
    if claimed_label:
        for chunk in retrieved_chunks:
            if claimed_label == (chunk.requirement_id or chunk.chunk_id):
                return chunk
    # No usable claim (mock mode, missing field, or a label that doesn't match
    # anything we actually retrieved) — round-robin across retrieved chunks
    # rather than defaulting every test case to the same top chunk.
    return retrieved_chunks[fallback_index % len(retrieved_chunks)]


def _generate_test_cases_from_context(
    query: str,
    context: str,
    retrieved_chunks: List[RetrievedChunk],
    types: List[TestCaseType],
) -> tuple[List[TestCase], List[Optional[str]]]:
    """Returns (test_cases, source_labels) — source_labels[i] is the model's
    claimed excerpt label for test_cases[i] (LLM mode only; None in mock
    mode, since there's no model to ask). The caller resolves these against
    real retrieved chunks; this function never determines the final citation
    itself."""
    if is_configured():
        user_prompt = (
            f"User's request: {query}\n\n"
            f"Retrieved requirement excerpts:\n\"\"\"\n{context}\n\"\"\"\n\n"
            f"Generate test cases of these types, one each, in this order: "
            f"{', '.join(t.value for t in types)}."
        )
        try:
            raw = call_llm_for_json(SYSTEM_PROMPT, user_prompt, endpoint="generate-test-cases/from-documents")
            from backend.models.schemas import TestCaseResponse

            raw_items = raw.get("test_cases", [])
            response = TestCaseResponse.model_validate(raw)
            labels = [item.get("source_label") for item in raw_items]
            return response.test_cases, labels
        except (ValidationError, json.JSONDecodeError) as exc:
            raise RagGenerationError(f"LLM returned a response that didn't match the schema: {exc}") from exc

    # Mock mode: no model to ask for a source label, so every test case gets
    # None here — the caller's round-robin fallback handles differentiation.
    # Content generation still needs to match that same round-robin
    # assignment (see module docstring), so each type's mock subject is
    # drawn from ITS OWN eventual chunk, not always the top one.
    n = len(retrieved_chunks)
    subjects = [_first_sentence(retrieved_chunks[i % n].text) for i in range(len(types))]
    top_chunk = retrieved_chunks[0]
    mock_request = GenerateTestCasesRequest(
        requirement_text=top_chunk.text[:2000],
        requirement_id=top_chunk.requirement_id or "REQ-UNSPECIFIED",
        test_types=types,
    )
    with track_mock_call("generate-test-cases/from-documents"):
        test_cases = _mock_generate(mock_request, types, subjects=subjects).test_cases
    return test_cases, [None] * len(test_cases)
