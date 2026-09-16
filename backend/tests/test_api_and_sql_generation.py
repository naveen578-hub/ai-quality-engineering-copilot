import json
import os

import pytest

os.environ.pop("OPENAI_API_KEY", None)

from backend.rag import openapi_store  # noqa: E402

SAMPLE_OPENAPI_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Synthetic Patient API", "version": "1.0.0"},
    "security": [{"bearerAuth": []}],
    "paths": {
        "/patients/{memberId}": {
            "get": {
                "operationId": "getPatient",
                "summary": "Fetch a patient record by member ID",
                "parameters": [
                    {
                        "name": "memberId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string", "minimum": 8, "maximum": 12},
                    }
                ],
                "responses": {"200": {"description": "OK"}, "404": {"description": "Not found"}},
            }
        },
        "/patients": {
            "post": {
                "operationId": "createPatient",
                "summary": "Create a patient record",
                "requestBody": {"required": True, "content": {"application/json": {}}},
                "responses": {"201": {"description": "Created"}, "400": {"description": "Bad request"}},
            }
        },
    },
}


@pytest.fixture(autouse=True)
def reset_openapi_store():
    openapi_store.reset()
    yield


# ---- OpenAPI upload + parsing ----


def test_upload_openapi_spec_parses_endpoints(client):
    resp = client.post(
        "/api/v1/openapi/specs",
        files={"file": ("patients.json", json.dumps(SAMPLE_OPENAPI_SPEC).encode(), "application/json")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["endpoint_count"] == 2
    endpoint_ids = {e["endpoint_id"] for e in body["endpoints"]}
    assert endpoint_ids == {"GET /patients/{memberId}", "POST /patients"}
    assert all(e["requires_auth"] for e in body["endpoints"])  # global security applies


def test_upload_rejects_non_openapi_json(client):
    resp = client.post(
        "/api/v1/openapi/specs",
        files={"file": ("not_a_spec.json", b'{"hello": "world"}', "application/json")},
    )
    assert resp.status_code == 422


def test_list_openapi_specs(client):
    client.post(
        "/api/v1/openapi/specs",
        files={"file": ("patients.json", json.dumps(SAMPLE_OPENAPI_SPEC).encode(), "application/json")},
    )
    resp = client.get("/api/v1/openapi/specs")
    assert resp.status_code == 200
    specs = resp.json()
    assert len(specs) == 1
    assert specs[0]["endpoint_count"] == 2


# ---- API test generation from spec ----


def test_generate_api_test_cases_covers_positive_negative_boundary_auth(client):
    upload = client.post(
        "/api/v1/openapi/specs",
        files={"file": ("patients.json", json.dumps(SAMPLE_OPENAPI_SPEC).encode(), "application/json")},
    ).json()

    resp = client.post(
        "/api/v1/openapi/generate-test-cases",
        json={"spec_id": upload["spec_id"], "endpoint_ids": ["GET /patients/{memberId}"]},
    )
    assert resp.status_code == 200
    test_cases = resp.json()["test_cases"]

    types = {tc["type"] for tc in test_cases}
    # GET /patients/{memberId} has a required path param with min/max -> expect
    # positive, negative (missing required), and boundary cases, plus auth negative.
    assert "api" in types
    assert "negative" in types
    assert "boundary" in types
    assert all(tc["requirement_reference"].startswith("OpenAPI: GET /patients/{memberId}") for tc in test_cases)


def test_generate_api_test_cases_unknown_spec_returns_404(client):
    resp = client.post("/api/v1/openapi/generate-test-cases", json={"spec_id": "spec-doesnotexist"})
    assert resp.status_code == 404


def test_generate_api_test_cases_unknown_endpoint_id_returns_422(client):
    upload = client.post(
        "/api/v1/openapi/specs",
        files={"file": ("patients.json", json.dumps(SAMPLE_OPENAPI_SPEC).encode(), "application/json")},
    ).json()
    resp = client.post(
        "/api/v1/openapi/generate-test-cases",
        json={"spec_id": upload["spec_id"], "endpoint_ids": ["DELETE /nonexistent"]},
    )
    assert resp.status_code == 422


# ---- SQL validation generation (mock/pattern mode) ----


@pytest.mark.parametrize(
    "requirement_text,expected_rule",
    [
        ("Member ID shall be between 8 and 12 characters.", "length_range"),
        ("Password must have a minimum of 10 characters.", "minimum_length"),
        ("Email address shall be unique across all accounts.", "uniqueness"),
        ("Last name is required and shall not be empty.", "required_not_null"),
        ("Status shall be one of: active, inactive, pending.", "allowed_values"),
        ("Account shall be locked after 5 consecutive failed login attempts.", "event_threshold"),
    ],
)
def test_sql_validation_recognizes_common_patterns(client, requirement_text, expected_rule):
    resp = client.post(
        "/api/v1/sql-validations/generate",
        json={"requirement_text": requirement_text, "table_name": "records_test", "requirement_id": "REQ-900"},
    )
    assert resp.status_code == 200
    body = resp.json()
    rules = {v["rule_detected"] for v in body["validations"]}
    assert expected_rule in rules
    for v in body["validations"]:
        assert v["sql"].strip().upper().startswith("--") or v["sql"].strip().upper().startswith("SELECT")
        assert "SELECT" in v["sql"].upper()
        assert v["requirement_reference"] == "REQ-900"


def test_sql_validation_returns_note_when_no_pattern_matches(client):
    resp = client.post(
        "/api/v1/sql-validations/generate",
        json={"requirement_text": "The system shall provide a pleasant user experience.", "table_name": "records_test", "requirement_id": "REQ-901"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["validations"] == []
    assert body["unmatched_note"] is not None


def test_sql_validation_uses_explicit_columns_and_table_for_uniqueness(client):
    resp = client.post(
        "/api/v1/sql-validations/generate",
        json={
            "requirement_text": "Every Clearance case must have a unique case_id and common_intake_id.",
            "table_name": "clearance_cases",
            "requirement_id": "REQ-001",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert [v["rule_detected"] for v in body["validations"]] == ["uniqueness", "uniqueness"]
    assert "every_clearance_case" not in " ".join(v["sql"] for v in body["validations"])
    assert all("FROM clearance_cases" in v["sql"] for v in body["validations"])
    assert "case_id" in body["validations"][0]["sql"]
    assert "common_intake_id" in body["validations"][1]["sql"]


def test_sql_validation_does_not_guess_prose_subject_as_column(client):
    resp = client.post(
        "/api/v1/sql-validations/generate",
        json={"requirement_text": "Every Clearance case must be unique.", "table_name": "records_test"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["validations"] == []
    assert "column_name" in body["unmatched_note"]


def test_sql_validation_applies_each_constraint_only_to_its_stated_columns(client):
    resp = client.post(
        "/api/v1/sql-validations/generate",
        json={
            "requirement_text": (
                "case_id and common_intake_id must be unique; patient_id must be present."
            ),
            "table_name": "clearance_cases",
            "column_name": "case_id, common_intake_id, patient_id",
            "requirement_id": "REQ-001",
        },
    )
    assert resp.status_code == 200
    validations = resp.json()["validations"]
    assert [v["rule_detected"] for v in validations] == [
        "uniqueness",
        "uniqueness",
        "required_not_null",
    ]
    assert "FROM clearance_cases" in validations[0]["sql"]
    assert "case_id" in validations[0]["sql"]
    assert "common_intake_id" in validations[1]["sql"]
    assert "patient_id" in validations[2]["sql"]
    assert "IS NULL" in validations[2]["sql"]
    assert "TRIM(patient_id) = ''" in validations[2]["sql"]
    assert "patient_id, COUNT" not in validations[0]["sql"]


def test_sql_validation_requires_an_actual_table_name(client):
    resp = client.post(
        "/api/v1/sql-validations/generate",
        json={"requirement_text": "case_id must be unique.", "column_name": "case_id"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["validations"] == []
    assert "actual database table name" in body["unmatched_note"]


def test_help_chat_answers_signin_questions_without_authentication(client):
    resp = client.post(
        "/api/v1/help/chat",
        json={"question": "I forgot my password", "surface": "signin"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "administrator" in body["answer"]
    assert body["suggestions"]


def test_help_chat_uses_workspace_role_and_area_context(client):
    resp = client.post(
        "/api/v1/help/chat",
        json={
            "question": "Why is my button disabled?",
            "surface": "workspace",
            "active_area": "sql",
            "role": "viewer",
        },
    )
    assert resp.status_code == 200
    assert "read-only" in resp.json()["answer"]


def test_visual_compare_rejects_non_http_live_urls(client):
    resp = client.post(
        "/api/v1/visual-compare",
        files={"reference": ("figma.png", b"not-an-image", "image/png")},
        data={"url": "file:///tmp/page.html", "viewport_width": "1440", "viewport_height": "900"},
    )
    assert resp.status_code == 422
    assert "http://" in resp.json()["detail"]
