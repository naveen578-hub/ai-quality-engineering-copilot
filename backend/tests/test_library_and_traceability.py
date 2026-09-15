import os

import pytest

os.environ.pop("OPENAI_API_KEY", None)

# NOTE: this file used to set its own CHROMA_PERSIST_DIR/QE_COPILOT_DB_PATH
# and rmtree/remove them at teardown. Centralized in conftest.py now — see
# the comment there for why per-file paths didn't actually give isolation.

from backend.models import db  # noqa: E402
from backend.rag import store  # noqa: E402

SAMPLE_DOC = (
    b"REQ-101: The system shall allow an authorized user with regular FEP access to view "
    b"a patient's record.\n\n"
    b"REQ-102: An authorized user with regular FEP access is permitted to view a patient's "
    b"record after signing in.\n\n"  # near-duplicate of REQ-101
    b"REQ-103: Users without FEP access shall be denied access to a patient's FEP record.\n\n"
    b"REQ-104: Member ID search shall accept alphanumeric IDs between 8 and 12 characters."
)

SAMPLE_TEST_CASE = {
    "id": "TC-900",
    "title": "Verify FEP record view",
    "type": "positive",
    "priority": "high",
    "preconditions": ["User is authenticated"],
    "steps": ["Sign in", "Open patient record"],
    "expected_result": "Record is displayed",
    "requirement_reference": "REQ-101",
    "source_chunk": "REQ-101: The system shall allow...",
}


@pytest.fixture(autouse=True)
def reset_db_between_tests():
    db.reset()
    store.reset()
    yield


# ---- Save / list / update / delete ----


def test_save_and_list_test_cases(client):
    resp = client.post("/api/v1/test-cases", json={"test_cases": [SAMPLE_TEST_CASE]})
    assert resp.status_code == 200
    saved = resp.json()
    assert len(saved) == 1
    assert saved[0]["status"] == "draft"
    assert saved[0]["db_id"] > 0

    resp = client.get("/api/v1/test-cases")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_update_test_case_content_and_approve(client):
    saved = client.post("/api/v1/test-cases", json={"test_cases": [SAMPLE_TEST_CASE]}).json()
    db_id = saved[0]["db_id"]

    resp = client.patch(f"/api/v1/test-cases/{db_id}", json={"title": "Edited title", "status": "approved"})
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["title"] == "Edited title"
    assert updated["status"] == "approved"
    assert updated["updated_at"] >= updated["created_at"]


def test_update_nonexistent_test_case_returns_404(client):
    resp = client.patch("/api/v1/test-cases/99999", json={"status": "approved"})
    assert resp.status_code == 404


def test_delete_test_case(client):
    saved = client.post("/api/v1/test-cases", json={"test_cases": [SAMPLE_TEST_CASE]}).json()
    db_id = saved[0]["db_id"]

    resp = client.delete(f"/api/v1/test-cases/{db_id}")
    assert resp.status_code == 204

    resp = client.get("/api/v1/test-cases")
    assert resp.json() == []


def test_filter_test_cases_by_status(client):
    saved = client.post("/api/v1/test-cases", json={"test_cases": [SAMPLE_TEST_CASE]}).json()
    client.patch(f"/api/v1/test-cases/{saved[0]['db_id']}", json={"status": "approved"})

    approved = client.get("/api/v1/test-cases", params={"status": "approved"}).json()
    drafts = client.get("/api/v1/test-cases", params={"status": "draft"}).json()
    assert len(approved) == 1
    assert len(drafts) == 0


# ---- Export ----


def test_export_csv_and_json(client):
    client.post("/api/v1/test-cases", json={"test_cases": [SAMPLE_TEST_CASE]})

    csv_resp = client.get("/api/v1/export/csv")
    assert csv_resp.status_code == 200
    assert "TC-900" in csv_resp.text
    assert csv_resp.headers["content-type"].startswith("text/csv")

    json_resp = client.get("/api/v1/export/json")
    assert json_resp.status_code == 200
    body = json_resp.json()
    assert body["test_cases"][0]["id"] == "TC-900"


# ---- Traceability matrix ----


def test_traceability_matrix_reflects_uploads_and_saved_test_cases(client):
    store.reset()
    client.post("/api/v1/documents", files={"file": ("reqs.txt", SAMPLE_DOC, "text/plain")})
    client.post("/api/v1/test-cases", json={"test_cases": [SAMPLE_TEST_CASE]})  # covers REQ-101, type=positive

    resp = client.get("/api/v1/traceability-matrix")
    assert resp.status_code == 200
    matrix = resp.json()

    rows_by_id = {r["requirement_id"]: r for r in matrix["rows"]}
    assert "REQ-101" in rows_by_id
    assert "REQ-104" in rows_by_id

    req101 = rows_by_id["REQ-101"]
    assert req101["test_case_count"] == 1
    assert "positive" in req101["covered_types"]
    assert "negative" in req101["missing_types"]

    req104 = rows_by_id["REQ-104"]
    assert req104["test_case_count"] == 0
    assert req104["missing_types"] == ["positive", "negative", "boundary", "api", "regression"]

    # 1 of 4 requirements has any test case coverage
    assert matrix["coverage_percent"] == 25.0


# ---- Duplicate / conflict detection ----


def test_requirement_analysis_flags_duplicate_and_conflict(client):
    store.reset()
    client.post("/api/v1/documents", files={"file": ("reqs2.txt", SAMPLE_DOC, "text/plain")})

    resp = client.get("/api/v1/requirements/analysis")
    assert resp.status_code == 200
    body = resp.json()

    dup_pairs = {frozenset((d["requirement_id_a"], d["requirement_id_b"])) for d in body["duplicates"]}
    assert frozenset({"REQ-101", "REQ-102"}) in dup_pairs

    conflict_pairs = {frozenset((c["requirement_id_a"], c["requirement_id_b"])) for c in body["conflicts"]}
    assert any(frozenset({"REQ-101", "REQ-103"}) == p or frozenset({"REQ-102", "REQ-103"}) == p for p in conflict_pairs)
