from backend.models import db
from backend.rag import store


def _upload(client, text: bytes):
    return client.post("/api/v1/documents", files={"file": ("requirements.txt", text, "text/plain")})


def test_requirement_revision_impact_and_review_does_not_change_approval(client):
    db.reset()
    store.reset()
    original = (
        b"REQ-001: The system shall allow an authorized user to search records.\n\n"
        b"REQ-002: Search shall return results within 2 seconds."
    )
    first_upload = _upload(client, original)
    assert first_upload.status_code == 200
    assert first_upload.json()["impact_count"] == 0

    case = {
        "id": "TC-001",
        "title": "Search records",
        "type": "positive",
        "priority": "high",
        "preconditions": [],
        "steps": ["Search for a record"],
        "expected_result": "Matching record is returned",
        "requirement_reference": "REQ-001",
        "source_chunk": None,
    }
    saved_case = client.post("/api/v1/test-cases", json={"test_cases": [case]}).json()[0]
    client.patch(f"/api/v1/test-cases/{saved_case['db_id']}", json={"status": "approved"})

    revised = (
        b"REQ-001: The system shall allow an authorized user to search records by ID.\n\n"
        b"REQ-003: Search shall return an error for an unknown ID."
    )
    second_upload = _upload(client, revised)
    assert second_upload.status_code == 200
    assert second_upload.json()["impact_count"] == 3

    report = client.get("/api/v1/requirement-impacts").json()
    by_id = {impact["requirement_id"]: impact for impact in report["impacts"]}
    assert {impact["change_type"] for impact in report["impacts"]} == {"modified", "removed", "added"}
    assert by_id["REQ-001"]["affected_test_cases"][0]["db_id"] == saved_case["db_id"]
    assert by_id["REQ-001"]["affected_test_cases"][0]["status"] == "approved"
    assert by_id["REQ-003"]["affected_test_cases"] == []

    review = client.patch(f"/api/v1/requirement-impacts/{by_id['REQ-001']['impact_id']}/review", json={"reviewed": True})
    assert review.status_code == 200
    assert review.json()["reviewed"] is True
    assert client.get("/api/v1/test-cases").json()[0]["status"] == "approved"


def test_new_upload_supersedes_prior_impact_snapshot(client):
    db.reset()
    store.reset()
    baseline = _upload(client, b"REQ-010: The service shall return a result.")
    assert baseline.json()["impact_count"] == 0
    response = _upload(client, b"REQ-010: The service shall return a result within 1 second.")
    assert response.status_code == 200
    impacts = client.get("/api/v1/requirement-impacts").json()["impacts"]
    assert len(impacts) == 1
    assert impacts[0]["requirement_id"] == "REQ-010"
    assert impacts[0]["change_type"] == "modified"


def test_document_without_requirement_ids_does_not_mark_previous_requirements_removed(client):
    db.reset()
    store.reset()
    baseline = _upload(client, b"REQ-020: The service shall return a result.")
    assert baseline.json()["impact_count"] == 0
    response = _upload(client, b"A paragraph without a recognized requirement marker.")
    assert response.status_code == 200
    assert response.json()["impact_count"] == 0
    report = client.get("/api/v1/requirement-impacts").json()
    assert report["impacts"] == []


def test_requirement_id_rename_is_reported_as_remove_plus_add(client):
    db.reset()
    store.reset()
    baseline = _upload(client, b"REQ-030: The service shall return a result.")
    assert baseline.json()["impact_count"] == 0

    renamed = _upload(client, b"REQ-031: The service shall return a result.")
    assert renamed.status_code == 200
    assert renamed.json()["impact_count"] == 2
    impacts = client.get("/api/v1/requirement-impacts").json()["impacts"]
    changes = {impact["requirement_id"]: impact["change_type"] for impact in impacts}
    assert changes == {"REQ-030": "removed", "REQ-031": "added"}