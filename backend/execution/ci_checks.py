"""Fast, dependency-light execution checks for CI."""
from __future__ import annotations

import asyncio
import argparse
import json
import os
import sqlite3
import tempfile

from backend.execution.sql_adapter import execute_sql
from backend.execution.results import critical_failure_count
from backend.models.schemas import ExecutionResult, SqlExecutionRequest


async def _run() -> int:
    with tempfile.TemporaryDirectory() as directory:
        database_path = os.path.join(directory, "checks.db")
        connection = sqlite3.connect(database_path)
        connection.execute("CREATE TABLE checks (id INTEGER PRIMARY KEY, status TEXT)")
        connection.execute("INSERT INTO checks (status) VALUES ('ok')")
        connection.commit()
        connection.close()
        previous_path = os.environ.get("QE_COPILOT_SQL_VALIDATION_DB_PATH")
        os.environ["QE_COPILOT_SQL_VALIDATION_DB_PATH"] = database_path
        try:
            passed = await execute_sql(SqlExecutionRequest(query="SELECT status FROM checks"))
            blocked = await execute_sql(SqlExecutionRequest(query="DELETE FROM checks", critical=False))
        finally:
            if previous_path is None:
                os.environ.pop("QE_COPILOT_SQL_VALIDATION_DB_PATH", None)
            else:
                os.environ["QE_COPILOT_SQL_VALIDATION_DB_PATH"] = previous_path
    results = [passed, blocked]
    failures = critical_failure_count(results)
    if passed.status != "passed" or blocked.status != "blocked" or failures:
        return 1
    print("Execution adapter smoke checks passed.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate QA execution results for CI.")
    parser.add_argument("--results", help="Path to a JSON file containing an ExecutionResult array or {\"results\": [...]} object")
    arguments = parser.parse_args()
    if arguments.results:
        with open(arguments.results, encoding="utf-8") as result_file:
            payload = json.load(result_file)
        result_items = payload.get("results", []) if isinstance(payload, dict) else payload
        results = [ExecutionResult.model_validate(item) for item in result_items]
        failures = critical_failure_count(results)
        print(f"Critical failures: {failures}")
        raise SystemExit(1 if failures else 0)
    raise SystemExit(asyncio.run(_run()))