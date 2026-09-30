from backend.models.schemas import ExecutionResult


def critical_failure_count(results: list[ExecutionResult]) -> int:
    return sum(1 for result in results if result.critical and result.status not in {"passed", "skipped"})