"""Heuristic test health scoring over the latest decisive outcomes."""
from __future__ import annotations

import os
from typing import Optional

from backend.models.schemas import TestHealthClassification, TestHealthSummary, TestRunStatus

WINDOW_SIZE = 20
DEFAULT_MIN_RUNS = 5
FLAKY_MIN_FLIPS = 3


def minimum_decisive_runs() -> int:
    try:
        return max(1, min(WINDOW_SIZE, int(os.getenv("QE_COPILOT_TEST_HEALTH_MIN_RUNS", DEFAULT_MIN_RUNS))))
    except ValueError:
        return DEFAULT_MIN_RUNS


def score_test_health(identity: dict, history: list[dict], min_runs: Optional[int] = None) -> TestHealthSummary:
    threshold = min_runs if min_runs is not None else minimum_decisive_runs()
    decisive = [
        row for row in history
        if row["status"] in {TestRunStatus.passed.value, TestRunStatus.failed.value}
    ][:WINDOW_SIZE]
    base = {
        "identity_type": identity["identity_type"],
        "test_case_db_id": identity.get("test_case_db_id"),
        "test_key": identity.get("test_key"),
        "test_case_public_id": identity.get("test_case_public_id"),
        "name": identity["name"],
        "total_run_count": identity["total_run_count"],
        "decisive_run_count": len(decisive),
    }
    if len(decisive) < threshold:
        return TestHealthSummary(
            **base,
            classification=TestHealthClassification.insufficient_data,
        )

    outcomes = [row["status"] for row in reversed(decisive)]
    pass_rate = sum(status == TestRunStatus.passed.value for status in outcomes) / len(outcomes)
    flips = sum(previous != current for previous, current in zip(outcomes, outcomes[1:]))
    streak_status = outcomes[-1]
    streak_count = 0
    for outcome in reversed(outcomes):
        if outcome != streak_status:
            break
        streak_count += 1

    if 0.1 < pass_rate < 0.9 and flips >= FLAKY_MIN_FLIPS:
        classification = TestHealthClassification.flaky
    elif pass_rate <= 0.1:
        classification = TestHealthClassification.failing
    elif pass_rate >= 0.9:
        classification = TestHealthClassification.stable
    else:
        classification = TestHealthClassification.inconclusive

    return TestHealthSummary(
        **base,
        pass_rate=round(pass_rate, 4),
        flip_count=flips,
        current_streak_status=TestRunStatus(streak_status),
        current_streak_count=streak_count,
        classification=classification,
    )