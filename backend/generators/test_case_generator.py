"""
Phase 1 test case generator.

Design notes:
- The LLM is asked to return JSON matching TestCaseResponse exactly.
- We validate whatever comes back through Pydantic before it ever reaches
  the API layer, so a malformed LLM response becomes a clean 502, not a
  silently broken frontend table.
- When OPENAI_API_KEY isn't set (e.g. a reviewer cloning the repo without
  a key), we fall back to a deterministic rule-based generator so the
  endpoint still returns valid, schema-correct test cases. This keeps the
  portfolio demo runnable out of the box and is clearly labeled as mock mode.
"""
from __future__ import annotations

import json
import re
from typing import List, Optional

from pydantic import ValidationError

from backend.generators.llm_client import call_llm_for_json, is_configured
from backend.models.schemas import GenerateTestCasesRequest, TestCase, TestCaseResponse, TestCaseType
from backend.observability.usage import track_mock_call

DEFAULT_TYPES: List[TestCaseType] = [
    TestCaseType.positive,
    TestCaseType.negative,
    TestCaseType.boundary,
    TestCaseType.api,
    TestCaseType.regression,
]

SYSTEM_PROMPT = """You are a senior QA engineer generating software test cases from a requirement.
Return ONLY a JSON object with this exact shape, no prose, no markdown fences:

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
      "requirement_reference": "string"
    }
  ]
}

Rules:
- Generate exactly one test case for each requested test type, in the order requested.
- "requirement_reference" must equal the requirement id given to you.
- Steps must be concrete and actionable, written from a tester's point of view.
- Never invent PII; use generic placeholder names/data only.
- Do not include any text outside the JSON object.
"""


class GenerationError(RuntimeError):
    pass


def _build_user_prompt(req: GenerateTestCasesRequest, types: List[TestCaseType]) -> str:
    return (
        f"Requirement id: {req.requirement_id}\n"
        f"Requirement text:\n\"\"\"\n{req.requirement_text.strip()}\n\"\"\"\n\n"
        f"Generate test cases of these types, one each, in this order: "
        f"{', '.join(t.value for t in types)}."
    )


def generate_test_cases(req: GenerateTestCasesRequest) -> TestCaseResponse:
    types = req.test_types or DEFAULT_TYPES

    if is_configured():
        try:
            raw = call_llm_for_json(SYSTEM_PROMPT, _build_user_prompt(req, types), endpoint="generate-test-cases")
            return TestCaseResponse.model_validate(raw)
        except (ValidationError, json.JSONDecodeError) as exc:
            raise GenerationError(f"LLM returned a response that didn't match the schema: {exc}") from exc

    # ---- Mock mode: no OPENAI_API_KEY configured ----
    with track_mock_call("generate-test-cases"):
        return _mock_generate(req, types)


def _first_sentence(text: str) -> str:
    text = text.strip().replace("\n", " ")
    match = re.split(r"(?<=[.!?])\s", text, maxsplit=1)
    return match[0][:160] if match else text[:160]


def _build_templates(subject: str) -> dict:
    """One requirement's worth of templated content, per test type. Factored
    out of _mock_generate so the RAG generator (backend/generators/rag_generator.py)
    can build each test case from a *different* subject — one per retrieved
    chunk — rather than every test case in a batch being templated from the
    same single piece of text regardless of which chunk it ends up citing."""
    return {
        TestCaseType.positive: dict(
            title=f"Verify expected behavior for: {subject}",
            priority="high",
            preconditions=["User is authenticated", "Required test data exists"],
            steps=[
                "Set up preconditions described in the requirement",
                "Perform the primary action described in the requirement",
                "Observe the resulting system behavior",
            ],
            expected_result="The system behaves exactly as described in the requirement, with no errors.",
        ),
        TestCaseType.negative: dict(
            title=f"Verify system rejects invalid input for: {subject}",
            priority="high",
            preconditions=["User is authenticated"],
            steps=[
                "Attempt the primary action with invalid or missing required input",
                "Submit the action",
                "Observe how the system responds",
            ],
            expected_result="The system rejects the invalid input with a clear, actionable error message and no data is corrupted.",
        ),
        TestCaseType.boundary: dict(
            title=f"Verify boundary conditions for: {subject}",
            priority="medium",
            preconditions=["User is authenticated", "Boundary test data is available (min, max, min-1, max+1)"],
            steps=[
                "Provide input at the minimum allowed boundary",
                "Provide input at the maximum allowed boundary",
                "Provide input one unit outside each boundary",
            ],
            expected_result="Values at the boundary are accepted; values outside the boundary are rejected with an appropriate message.",
        ),
        TestCaseType.api: dict(
            title=f"Verify API contract for: {subject}",
            priority="high",
            preconditions=["Valid API credentials/token are available", "Test environment is reachable"],
            steps=[
                "Send a request to the relevant endpoint with a valid payload",
                "Inspect the HTTP status code and response schema",
                "Send the same request with an invalid payload and inspect the error response",
            ],
            expected_result="Valid requests return the documented status code and schema; invalid requests return a documented error response.",
        ),
        TestCaseType.regression: dict(
            title=f"Verify no regression introduced around: {subject}",
            priority="medium",
            preconditions=["Existing related features are in a known-good state"],
            steps=[
                "Re-run the core existing workflows related to this requirement",
                "Compare results against the last known-good baseline",
                "Confirm no previously passing functionality has broken",
            ],
            expected_result="All previously passing related workflows continue to pass unchanged.",
        ),
    }


def _mock_generate(
    req: GenerateTestCasesRequest, types: List[TestCaseType], subjects: Optional[List[str]] = None
) -> TestCaseResponse:
    """subjects, if given, must align 1:1 with `types` — each test case is
    templated from its own subject rather than one shared subject. Used by
    the RAG generator to keep each test case's content consistent with
    whichever chunk it ends up citing."""
    default_subject = _first_sentence(req.requirement_text) or "the described feature"
    req_id = req.requirement_id or "REQ-001"

    test_cases: List[TestCase] = []
    for idx, t in enumerate(types, start=1):
        subject = subjects[idx - 1] if subjects and idx - 1 < len(subjects) else default_subject
        tmpl = _build_templates(subject)[t]
        test_cases.append(
            TestCase(
                id=f"TC-{idx:03d}",
                title=tmpl["title"],
                type=t,
                priority=tmpl["priority"],
                preconditions=tmpl["preconditions"],
                steps=tmpl["steps"],
                expected_result=tmpl["expected_result"],
                requirement_reference=req_id,
            )
        )

    return TestCaseResponse(test_cases=test_cases)
