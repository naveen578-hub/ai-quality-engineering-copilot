"""Dependency-free flakiness scoring over persisted test-run history."""
from __future__ import annotations

from statistics import median
from typing import Optional

from backend.models.schemas import FlakinessAnalysisStatus, FlakinessCause, TestRunStatus

MIN_EXECUTED_RUNS = 5
TIMING_RATIO_THRESHOLD = 1.5
ENVIRONMENT_PEER_RATE_THRESHOLD = 0.5
ENVIRONMENT_BASELINE_DELTA = 0.3
SKIPPED_STATUS = TestRunStatus.skipped.value
PASSED_STATUS = TestRunStatus.passed.value
NOT_PASSED_STATUSES = {
    TestRunStatus.failed.value,
    TestRunStatus.blocked.value,
    TestRunStatus.error.value,
}
COUNTED_STATUSES = (PASSED_STATUS, *sorted(NOT_PASSED_STATUSES))


def _status_detail(executed: list[dict], skipped_count: int) -> str:
    counts = {status: sum(row["status"] == status for row in executed) for status in COUNTED_STATUSES}
    composition = ", ".join(f"{status}={counts[status]}" for status in COUNTED_STATUSES)
    return f"Executed status counts: {composition}; skipped excluded={skipped_count}."


def _environment_signal(
    executed: list[dict],
    peer_rates: list[dict],
) -> tuple[bool, Optional[float], Optional[float]]:
    rates_by_run = {row["id"]: row["peer_failure_rate"] for row in peer_rates}
    failed_batch_rates = []
    passed_batch_rates = []
    for run in executed:
        peer_rate = rates_by_run.get(run["id"])
        if peer_rate is None:
            continue
        if run["status"] in NOT_PASSED_STATUSES:
            failed_batch_rates.append(peer_rate)
        elif run["status"] == PASSED_STATUS:
            passed_batch_rates.append(peer_rate)

    if not failed_batch_rates or not passed_batch_rates:
        return False, median(failed_batch_rates) if failed_batch_rates else None, median(passed_batch_rates) if passed_batch_rates else None

    failure_batch_rate = median(failed_batch_rates)
    baseline_batch_rate = median(passed_batch_rates)
    detected = (
        failure_batch_rate >= ENVIRONMENT_PEER_RATE_THRESHOLD
        and failure_batch_rate - baseline_batch_rate >= ENVIRONMENT_BASELINE_DELTA
    )
    return detected, failure_batch_rate, baseline_batch_rate


def score_flakiness(identity: dict, history: list[dict], peer_rates: list[dict]) -> dict:
    chronological = list(reversed(history))
    skipped_count = sum(row["status"] == SKIPPED_STATUS for row in chronological)
    executed = [row for row in chronological if row["status"] != SKIPPED_STATUS]
    detail = _status_detail(executed, skipped_count)
    base = {
        "test_case_db_id": identity.get("test_case_db_id"),
        "test_key": identity.get("test_key"),
        "test_name": identity["name"],
        "sample_size": len(executed),
        "suspected_cause": None,
    }

    if len(executed) < MIN_EXECUTED_RUNS:
        return {
            **base,
            "analysis_status": FlakinessAnalysisStatus.insufficient_data,
            "flakiness_score": None,
            "failure_rate": None,
            "flip_rate": None,
            "cause_detail": f"Need at least {MIN_EXECUTED_RUNS} executed runs. {detail}",
        }

    outcomes = [row["status"] == PASSED_STATUS for row in executed]
    failures = sum(not outcome for outcome in outcomes)
    failure_rate = failures / len(outcomes)
    pass_rate = 1.0 - failure_rate
    flips = sum(previous != current for previous, current in zip(outcomes, outcomes[1:]))
    flip_rate = flips / (len(outcomes) - 1)
    flakiness_score = flip_rate * min(failure_rate, pass_rate) * 2
    status_detail = detail

    if flakiness_score == 0:
        if failure_rate == 1:
            status_detail += " Outcomes are consistently not-passed, not intermittent."
        elif failure_rate == 0:
            status_detail += " Outcomes are consistently passed."
        else:
            status_detail += " No outcome transitions were observed."
        cause = None
    else:
        passed_durations = [row["duration_ms"] for row in executed if row["status"] == PASSED_STATUS]
        failed_durations = [row["duration_ms"] for row in executed if row["status"] in NOT_PASSED_STATUSES]
        passed_median = median(passed_durations) if passed_durations else None
        failed_median = median(failed_durations) if failed_durations else None
        timing_detected = (
            passed_median is not None
            and failed_median is not None
            and failed_median > passed_median * TIMING_RATIO_THRESHOLD
        )
        environment_detected, failing_peer_rate, passing_peer_baseline = _environment_signal(executed, peer_rates)

        signals = []
        if timing_detected:
            signals.append(FlakinessCause.timing_synchronization)
        if environment_detected:
            signals.append(FlakinessCause.environment_dependent)
        if len(signals) == 1:
            cause = signals[0]
        else:
            cause = FlakinessCause.unclassified

        status_detail += (
            f" Duration medians (ms): passed={passed_median}, not_passed={failed_median};"
            f" timing threshold={TIMING_RATIO_THRESHOLD}x."
        )
        if failing_peer_rate is not None or passing_peer_baseline is not None:
            status_detail += (
                f" Median sibling not-passed rate by target batch: target not-passed={failing_peer_rate},"
                f" target passed baseline={passing_peer_baseline};"
                f" environment thresholds={ENVIRONMENT_PEER_RATE_THRESHOLD} and +{ENVIRONMENT_BASELINE_DELTA}."
            )
        if len(signals) > 1:
            status_detail += " Timing and environment signals both fired, so cause remains unclassified."
        elif not signals:
            status_detail += " Neither cause heuristic fired; cause remains unclassified."

    return {
        **base,
        "analysis_status": FlakinessAnalysisStatus.scored,
        "flakiness_score": round(flakiness_score, 4),
        "failure_rate": round(failure_rate, 4),
        "flip_rate": round(flip_rate, 4),
        "suspected_cause": cause,
        "cause_detail": status_detail,
    }