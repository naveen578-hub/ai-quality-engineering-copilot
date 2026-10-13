from backend.models import db


def _ingest(client, batch_id, results):
    response = client.post(
        "/api/v1/test-runs/ingest",
        json={"run_batch_id": batch_id, "results": results},
    )
    assert response.status_code == 200, response.text


def _test_result(test_key, status, duration_ms=100):
    return {
        "test_key": test_key,
        "engine": "manual",
        "status": status,
        "duration_ms": duration_ms,
    }


def _analysis_by_key(client):
    response = client.post("/api/v1/flaky-tests/analyze")
    assert response.status_code == 200, response.text
    return {row["test_key"]: row for row in response.json()["results"]}


def test_stable_pass_and_consistent_failure_have_zero_flakiness(client):
    db.reset()
    for index in range(6):
        _ingest(
            client,
            f"stable-{index}",
            [
                _test_result("stable.passing", "passed"),
                _test_result("stable.failing", "error"),
                _test_result("stable.blocked", "blocked"),
            ],
        )

    results = _analysis_by_key(client)
    assert results["stable.passing"]["flakiness_score"] == 0
    assert results["stable.passing"]["failure_rate"] == 0
    assert results["stable.failing"]["flakiness_score"] == 0
    assert results["stable.failing"]["failure_rate"] == 1
    assert "error=6" in results["stable.failing"]["cause_detail"]
    assert results["stable.blocked"]["failure_rate"] == 1
    assert "blocked=6" in results["stable.blocked"]["cause_detail"]


def test_timing_correlated_flakes_are_detected(client):
    db.reset()
    for index in range(6):
        status = "passed" if index % 2 == 0 else "failed"
        duration = 200 if status == "passed" else 900
        _ingest(client, f"timing-{index}", [_test_result("timing.test", status, duration)])

    result = _analysis_by_key(client)["timing.test"]
    assert result["analysis_status"] == "scored"
    assert result["flakiness_score"] == 1
    assert result["failure_rate"] == 0.5
    assert result["flip_rate"] == 1
    assert result["suspected_cause"] == "timing_synchronization"
    assert "passed=200" in result["cause_detail"]
    assert "not_passed=900" in result["cause_detail"]


def test_batch_sibling_failures_identify_environment_dependent_flakes(client):
    db.reset()
    for index in range(6):
        target_status = "passed" if index % 2 == 0 else "error"
        sibling_statuses = ["passed"] * 4 if target_status == "passed" else ["failed", "blocked", "error", "passed"]
        results = [_test_result("environment.test", target_status)]
        results.extend(
            _test_result(f"sibling.{sibling_index}", status)
            for sibling_index, status in enumerate(sibling_statuses)
        )
        _ingest(client, f"environment-{index}", results)

    result = _analysis_by_key(client)["environment.test"]
    assert result["flakiness_score"] == 1
    assert result["suspected_cause"] == "environment_dependent"
    assert "target not-passed=0.75" in result["cause_detail"]
    assert "target passed baseline=0.0" in result["cause_detail"]


def test_intermittent_failure_without_cause_signal_is_unclassified(client):
    db.reset()
    for index in range(6):
        status = "passed" if index % 2 == 0 else "failed"
        _ingest(client, f"ambiguous-{index}", [_test_result("ambiguous.test", status)])

    result = _analysis_by_key(client)["ambiguous.test"]
    assert result["flakiness_score"] == 1
    assert result["suspected_cause"] == "unclassified"
    assert "Neither cause heuristic fired" in result["cause_detail"]


def test_skipped_runs_do_not_satisfy_minimum_sample_size(client):
    db.reset()
    for index, status in enumerate(["passed", "failed", "passed", "skipped", "skipped"]):
        _ingest(client, f"skipped-{index}", [_test_result("low-sample.test", status)])

    result = _analysis_by_key(client)["low-sample.test"]
    assert result["analysis_status"] == "insufficient_data"
    assert result["sample_size"] == 3
    assert result["flakiness_score"] is None
    assert result["failure_rate"] is None
    assert "skipped excluded=2" in result["cause_detail"]


def test_error_and_failed_composition_stays_visible_in_cause_detail(client):
    db.reset()
    for index in range(6):
        status = "passed" if index % 2 == 0 else "error"
        other_status = "passed" if index % 2 == 0 else "failed"
        _ingest(
            client,
            f"composition-{index}",
            [
                _test_result("composition.error", status),
                _test_result("composition.failed", other_status),
            ],
        )

    results = _analysis_by_key(client)
    assert results["composition.error"]["flakiness_score"] == results["composition.failed"]["flakiness_score"]
    assert "error=3" in results["composition.error"]["cause_detail"]
    assert "failed=3" in results["composition.failed"]["cause_detail"]


def test_scores_are_persisted_and_viewer_can_read_but_not_analyze(client, viewer_headers):
    db.reset()
    for index in range(5):
        status = "passed" if index % 2 == 0 else "failed"
        _ingest(client, f"read-score-{index}", [_test_result("readable.test", status)])

    analyzed = client.post("/api/v1/flaky-tests/analyze")
    assert analyzed.status_code == 200
    assert len(db.list_flakiness_scores()) == 1
    repeated = client.post("/api/v1/flaky-tests/analyze")
    assert repeated.status_code == 200
    assert len(db.list_flakiness_scores()) == 1

    client.headers.update(viewer_headers)
    scores = client.get("/api/v1/flaky-tests/scores")
    forbidden = client.post("/api/v1/flaky-tests/analyze")
    assert scores.status_code == 200
    assert scores.json()["results"][0]["test_key"] == "readable.test"
    assert forbidden.status_code == 403


def test_saved_case_and_matching_external_key_keep_distinct_score_identities(client):
    db.reset()
    saved_response = client.post(
        "/api/v1/test-cases",
        json={"test_cases": [{
            "id": "TC-SHARED",
            "title": "Saved test identity",
            "type": "positive",
            "priority": "medium",
            "steps": ["Run test"],
            "expected_result": "Pass",
            "requirement_reference": "REQ-IDENTITY",
        }]},
    )
    assert saved_response.status_code == 200, saved_response.text
    case_db_id = saved_response.json()[0]["db_id"]

    for index in range(5):
        _ingest(
            client,
            f"identity-{index}",
            [
                {
                    "test_case_db_id": case_db_id,
                    "engine": "manual",
                    "status": "passed",
                    "duration_ms": 100,
                },
                _test_result("TC-SHARED", "failed" if index % 2 else "passed"),
            ],
        )

    analyzed = client.post("/api/v1/flaky-tests/analyze")
    assert analyzed.status_code == 200, analyzed.text
    assert len(analyzed.json()["results"]) == 2
    all_scores = client.get("/api/v1/flaky-tests/scores").json()["results"]
    assert len(all_scores) == 2
    case_score = client.get(f"/api/v1/flaky-tests/scores?test_case_db_id={case_db_id}").json()["results"]
    key_score = client.get("/api/v1/flaky-tests/scores?test_key=TC-SHARED").json()["results"]
    assert len(case_score) == len(key_score) == 1
    assert case_score[0]["test_case_db_id"] == case_db_id
    assert key_score[0]["test_key"] == "TC-SHARED"


def test_analysis_rejects_invalid_identity_pair_for_score_filter(client):
    response = client.get("/api/v1/flaky-tests/scores?test_case_db_id=1&test_key=some.test")
    assert response.status_code == 422