import os

# Ensure mock mode regardless of the host environment's .env, so CI is deterministic.
os.environ.pop("OPENAI_API_KEY", None)

from backend.models.schemas import TestCaseResponse  # noqa: E402

SAMPLE_REQUIREMENT = (
    "The system shall allow an authorized user with regular FEP access to search "
    "for a patient by member ID and view the patient's record. Access must be "
    "denied to users without FEP access."
)


def test_health_reports_mock_mode(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["mode"] == "mock"


def test_generate_test_cases_returns_valid_schema(client):
    resp = client.post(
        "/api/v1/generate-test-cases",
        json={"requirement_text": SAMPLE_REQUIREMENT, "requirement_id": "REQ-001"},
    )
    assert resp.status_code == 200

    # Round-trip through the Pydantic model to prove the response is schema-valid,
    # not just "some JSON that happens to look right".
    parsed = TestCaseResponse.model_validate(resp.json())

    assert len(parsed.test_cases) == 5
    types = {tc.type.value for tc in parsed.test_cases}
    assert types == {"positive", "negative", "boundary", "api", "regression"}

    for tc in parsed.test_cases:
        assert tc.requirement_reference == "REQ-001"
        assert tc.steps
        assert tc.expected_result


def test_generate_test_cases_respects_requested_subset(client):
    resp = client.post(
        "/api/v1/generate-test-cases",
        json={
            "requirement_text": SAMPLE_REQUIREMENT,
            "requirement_id": "REQ-002",
            "test_types": ["positive", "negative"],
        },
    )
    assert resp.status_code == 200
    parsed = TestCaseResponse.model_validate(resp.json())
    assert [tc.type.value for tc in parsed.test_cases] == ["positive", "negative"]


def test_generate_test_cases_rejects_too_short_requirement(client):
    resp = client.post("/api/v1/generate-test-cases", json={"requirement_text": "too short"})
    assert resp.status_code == 422
