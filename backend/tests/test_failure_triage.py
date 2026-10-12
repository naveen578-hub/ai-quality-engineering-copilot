import pytest

from backend.generators.failure_triage import classify_failure
from backend.models import db
from backend.models.schemas import FailureTriageRecord


@pytest.fixture
def synthetic_failures():
    cases = [
        ("account status", "Expected: ACTIVE but was: SUSPENDED", None, None, [], "product_defect"),
        ("balance total", "expected=120, actual=95", None, None, [], "product_defect"),
        ("approval state", 'Expected "approved" but got "pending"', None, None, [], "product_defect"),
        ("flag value", "expected true but was false", None, None, [], "product_defect"),
        ("search control", "assertion failed", "org.openqa.selenium.NoSuchElementException: #search", None, [], "automation_issue"),
        ("submit control", "assertion failed", "ElementNotInteractableException: submit", None, [], "automation_issue"),
        ("menu item", "assertion failed", "at clickMenu (NoSuchElementException)", None, [], "automation_issue"),
        ("date picker", "assertion failed", "ElementNotInteractableException: input[name=date]", None, [], "automation_issue"),
        ("catalog service", "assertion failed", "Connection refused: catalog.internal:8080", None, [], "environment_failure"),
        ("profile request", "assertion failed", "Read timed out while calling profile service", None, [], "environment_failure"),
        ("payment response", "assertion failed", "HTTP 503 from payment gateway", None, [], "environment_failure"),
        ("search response", "assertion failed", "response status_code=504", None, [], "environment_failure"),
        ("member lookup", "assertion failed", 'NullPointerException: "memberId" is null', None, ["memberId"], "test_data_problem"),
        ("account lookup", "assertion failed", "NullPointerException while reading account_id", None, ["account_id"], "test_data_problem"),
        ("session setup", "assertion failed", "NullPointerException: sessionToken missing", None, ["sessionToken"], "test_data_problem"),
        ("date setup", "assertion failed", "NullPointerException in dateOfBirth parser", None, ["dateOfBirth"], "test_data_problem"),
        ("visual check", "The page looked unusual", None, "Screenshot differed from expectation", [], "unclassified"),
    ]
    return [
        {
            "test_name": name,
            "failed_assertion": assertion,
            "stack_trace": stack,
            "error_message": error,
            "known_flaky_fields": known_fields,
            "expected_classification": expected,
        }
        for name, assertion, stack, error, known_fields, expected in cases
    ]


def test_classifier_covers_signatures_and_refuses_ambiguous_input(synthetic_failures):
    for failure in synthetic_failures:
        expected = failure["expected_classification"]
        record = FailureTriageRecord(
            **{key: value for key, value in failure.items() if key != "expected_classification"}
        )
        result = classify_failure(record)
        assert result["classification"] == expected
        if expected == "unclassified":
            assert result["evidence_snippet"] is None
            assert result["confidence"] == 0
        else:
            source = "\n".join(
                value for value in (record.failed_assertion, record.error_message, record.stack_trace) if value
            )
            assert result["evidence_snippet"] in source
            assert result["confidence"] > 0


def test_classifier_refuses_conflicting_signatures_and_partial_field_matches():
    conflicting = FailureTriageRecord(
        test_name="conflicting failure",
        failed_assertion="Expected: ACTIVE but was: SUSPENDED",
        stack_trace="HTTP 503 while loading the account",
    )
    partial_field = FailureTriageRecord(
        test_name="partial field match",
        failed_assertion="assertion failed",
        stack_trace="NullPointerException while reading memberId",
        known_flaky_fields=["id"],
    )

    assert classify_failure(conflicting)["classification"] == "unclassified"
    assert classify_failure(conflicting)["evidence_snippet"] is None
    assert classify_failure(partial_field)["classification"] == "unclassified"


def test_triage_results_persist_in_sqlite(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "triage.db"))
    with db._connect() as connection:
        connection.execute(
            "INSERT INTO test_run_batches (run_batch_id, payload_hash, recorded_at) VALUES (?, ?, ?)",
            ("batch", "hash", "2026-01-01T00:00:00+00:00"),
        )
        cursor = connection.execute(
            """INSERT INTO test_runs
               (test_key, engine, status, duration_ms, run_batch_id, recorded_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("suite.checkout", "playwright", "failed", 100, "batch", "2026-01-01T00:00:00+00:00"),
        )
        run_id = cursor.lastrowid

    result_ids = db.save_failure_triage_results([{
        "test_run_id": run_id,
        "classification": classify_failure(FailureTriageRecord(
            test_name="checkout",
            failed_assertion="Expected: PAID but was: PENDING",
        ))["classification"],
        "confidence": 0.82,
        "evidence_snippet": "Expected: PAID but was: PENDING",
    }])

    assert len(result_ids) == 1
    with db._connect() as connection:
        row = connection.execute(
            "SELECT test_run_id, classification, confidence, evidence_snippet FROM triage_results WHERE id = ?",
            (result_ids[0],),
        ).fetchone()
    assert tuple(row) == (run_id, "product_defect", 0.82, "Expected: PAID but was: PENDING")


def test_triage_batch_classifies_and_verifies_exact_evidence(client, synthetic_failures):
    db.reset()
    payload_failures = [
        {key: value for key, value in failure.items() if key != "expected_classification"}
        for failure in synthetic_failures
    ]

    response = client.post("/api/v1/triage", json={"failures": payload_failures})

    assert response.status_code == 200, response.text
    results = response.json()["results"]
    assert len(results) == 17
    assert [item["classification"] for item in results] == [
        failure["expected_classification"] for failure in synthetic_failures
    ]
    for failure, result in zip(payload_failures, results):
        evidence = result["evidence_snippet"]
        supplied_text = "\n".join(
            value for value in (failure["failed_assertion"], failure["error_message"], failure["stack_trace"]) if value
        )
        if result["classification"] == "unclassified":
            assert evidence is None
            assert result["confidence"] == 0
        else:
            assert evidence
            assert evidence in supplied_text
            assert result["confidence"] > 0

    with db._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM triage_results").fetchone()[0] == 17


def test_triage_enriches_from_saved_run_and_rejects_unknown_run(client):
    db.reset()
    case_response = client.post(
        "/api/v1/test-cases",
        json={
            "test_cases": [{
                "id": "TC-TRIAGE",
                "title": "Verify member status",
                "type": "positive",
                "priority": "high",
                "steps": ["Look up member"],
                "expected_result": "Member status is ACTIVE",
                "requirement_reference": "REQ-MEMBER-STATUS",
            }]
        },
    )
    assert case_response.status_code == 200, case_response.text
    case_id = case_response.json()[0]["db_id"]
    ingested = client.post(
        "/api/v1/test-runs/ingest",
        json={
            "run_batch_id": "triage-linked-run",
            "results": [{
                "test_case_db_id": case_id,
                "engine": "playwright",
                "status": "failed",
                "error_summary": "expected ACTIVE but was INACTIVE",
            }],
        },
    )
    assert ingested.status_code == 200, ingested.text
    with db._connect() as connection:
        run_id = connection.execute("SELECT id FROM test_runs").fetchone()[0]

    linked = client.post(
        "/api/v1/triage",
        json={"failures": [{
            "test_run_id": run_id,
            "test_name": "member status",
            "failed_assertion": "Expected: ACTIVE but was: INACTIVE",
        }]},
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["results"][0]["requirement_reference"] == "REQ-MEMBER-STATUS"

    missing = client.post(
        "/api/v1/triage",
        json={"failures": [{
            "test_run_id": 999999,
            "test_name": "unknown run",
            "failed_assertion": "assertion failed",
        }]},
    )
    assert missing.status_code == 422


def test_triage_requires_authentication(unauthenticated_client):
    response = unauthenticated_client.post(
        "/api/v1/triage",
        json={"failures": [{
            "test_name": "unauthenticated request",
            "failed_assertion": "assertion failed",
        }]},
    )
    assert response.status_code == 401


def test_triage_denies_viewer_role(client, viewer_headers):
    client.headers.update(viewer_headers)
    response = client.post(
        "/api/v1/triage",
        json={"failures": [{
            "test_name": "viewer request",
            "failed_assertion": "assertion failed",
        }]},
    )
    assert response.status_code == 403