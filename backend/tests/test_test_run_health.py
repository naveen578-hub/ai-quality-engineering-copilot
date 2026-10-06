from backend.models import db


CASE = {
    "id": "TC-001",
    "title": "Verify account search",
    "type": "positive",
    "priority": "high",
    "preconditions": [],
    "steps": ["Search for an account"],
    "expected_result": "The account is returned",
    "requirement_reference": "REQ-001",
    "source_chunk": None,
}


def _ingest(client, batch_id: str, identity: dict, statuses: list[str]):
    results = [
        {
            **identity,
            "engine": "playwright" if "test_case_db_id" in identity else "manual",
            "status": status,
            "duration_ms": 250,
        }
        for status in statuses
    ]
    return client.post("/api/v1/test-runs/ingest", json={"run_batch_id": batch_id, "results": results})


def _ingest_history(client, prefix: str, identity: dict, statuses: list[str]):
    return [
        _ingest(client, f"{prefix}-{index}", identity, [status])
        for index, status in enumerate(statuses)
    ]


def _reset():
    db.reset()


def test_insufficient_data_has_no_metrics(client):
    _reset()
    saved = client.post("/api/v1/test-cases", json={"test_cases": [CASE]}).json()[0]
    responses = _ingest_history(client, "under-minimum", {"test_case_db_id": saved["db_id"]}, ["passed"] * 4)
    assert all(response.status_code == 200 for response in responses)

    health = client.get("/api/v1/test-runs/health").json()[0]
    assert health["classification"] == "insufficient_data"
    assert health["pass_rate"] is None
    assert health["flip_count"] is None
    assert health["current_streak_count"] is None


def test_alternating_results_are_classified_as_flaky(client):
    _reset()
    responses = _ingest_history(client, "alternating", {"test_key": "checkout.submit"}, ["passed", "failed", "passed", "failed", "passed"])
    assert all(response.status_code == 200 for response in responses)

    health = client.get("/api/v1/test-runs/health/key/checkout.submit").json()["health"]
    assert health["classification"] == "flaky"
    assert health["pass_rate"] == 0.6
    assert health["flip_count"] == 4
    assert health["current_streak_status"] == "passed"
    assert health["current_streak_count"] == 1


def test_consistently_failing_results_are_failing_not_flaky(client):
    _reset()
    responses = _ingest_history(client, "always-fails", {"test_key": "payments.capture"}, ["failed"] * 5)
    assert all(response.status_code == 200 for response in responses)

    health = client.get("/api/v1/test-runs/health/key/payments.capture").json()["health"]
    assert health["classification"] == "failing"
    assert health["pass_rate"] == 0
    assert health["flip_count"] == 0


def test_case_identity_and_similar_test_key_never_merge(client):
    _reset()
    saved = client.post("/api/v1/test-cases", json={"test_cases": [CASE]}).json()[0]
    case_run = _ingest(client, "saved-case-run", {"test_case_db_id": saved["db_id"]}, ["passed"])
    keyed_run = _ingest(client, "external-key-run", {"test_key": "TC-001"}, ["failed"])
    assert case_run.status_code == keyed_run.status_code == 200

    health_rows = client.get("/api/v1/test-runs/health").json()
    assert len(health_rows) == 2
    assert {row["identity_type"] for row in health_rows} == {"test_case", "test_key"}
    case_detail = client.get(f"/api/v1/test-runs/health/test-case/{saved['db_id']}").json()
    key_detail = client.get("/api/v1/test-runs/health/key/TC-001").json()
    assert len(case_detail["history"]) == len(key_detail["history"]) == 1
    assert case_detail["history"][0]["status"] == "passed"
    assert key_detail["history"][0]["status"] == "failed"


def test_batch_ingestion_is_idempotent_and_conflicting_retry_is_rejected(client):
    _reset()
    payload = {
        "run_batch_id": "retry-me",
        "results": [{"test_key": "suite.alpha", "engine": "manual", "status": "passed", "duration_ms": 12}],
    }
    first = client.post("/api/v1/test-runs/ingest", json=payload)
    retry = client.post("/api/v1/test-runs/ingest", json=payload)
    changed = {
        **payload,
        "results": [{"test_key": "suite.alpha", "engine": "manual", "status": "failed", "duration_ms": 12}],
    }
    conflict = client.post("/api/v1/test-runs/ingest", json=changed)

    assert first.status_code == retry.status_code == 200
    assert first.json()["idempotent_replay"] is False
    assert retry.json()["idempotent_replay"] is True
    assert conflict.status_code == 409
    assert len(client.get("/api/v1/test-runs/health/key/suite.alpha").json()["history"]) == 1


def test_batch_replay_is_idempotent_when_result_order_changes(client):
    _reset()
    results = [
        {"test_key": "suite.alpha", "engine": "manual", "status": "passed"},
        {"test_key": "suite.beta", "engine": "manual", "status": "failed"},
    ]
    first = client.post("/api/v1/test-runs/ingest", json={"run_batch_id": "unordered", "results": results})
    retry = client.post("/api/v1/test-runs/ingest", json={"run_batch_id": "unordered", "results": list(reversed(results))})
    assert first.status_code == retry.status_code == 200
    assert retry.json()["idempotent_replay"] is True
    assert len(client.get("/api/v1/test-runs/health").json()) == 2


def test_blocked_and_skipped_runs_are_not_decisive(client):
    _reset()
    statuses = ["passed", "failed", "passed", "blocked", "skipped", "failed", "passed"]
    responses = _ingest_history(client, "mixed", {"test_key": "suite.mixed"}, statuses)
    assert all(response.status_code == 200 for response in responses)

    health = client.get("/api/v1/test-runs/health/key/suite.mixed").json()["health"]
    assert health["total_run_count"] == 7
    assert health["decisive_run_count"] == 5
    assert health["classification"] == "flaky"


def test_ingest_rejects_unknown_saved_case_id(client):
    _reset()
    response = _ingest(client, "unknown-case", {"test_case_db_id": 987654}, ["passed"])
    assert response.status_code == 422


def test_batch_rejects_duplicate_identity(client):
    _reset()
    payload = {
        "run_batch_id": "duplicate-identity",
        "results": [
            {"test_key": "suite.same", "engine": "manual", "status": "passed"},
            {"test_key": "suite.same", "engine": "manual", "status": "failed"},
        ],
    }
    response = client.post("/api/v1/test-runs/ingest", json=payload)
    assert response.status_code == 422
