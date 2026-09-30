from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import time
from pathlib import Path

from backend.models.schemas import ExecutionEvidence, ExecutionResult, SqlExecutionRequest

_SELECT_ONLY = re.compile(r"^\s*SELECT\b", re.IGNORECASE)
_FORBIDDEN = re.compile(r"\b(ATTACH|DETACH|ALTER|CREATE|DELETE|DROP|INSERT|PRAGMA|REINDEX|REPLACE|TRUNCATE|UPDATE|VACUUM)\b|--|/\*|;", re.IGNORECASE)


def _run_select(path: str, query: str) -> tuple[list[str], list[tuple[object, ...]]]:
    uri = f"file:{os.path.abspath(path)}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        cursor = connection.execute(query)
        columns = [description[0] for description in cursor.description or []]
        rows = cursor.fetchmany(100)
        cursor.close()
        return columns, rows
    finally:
        connection.close()


async def execute_sql(request: SqlExecutionRequest) -> ExecutionResult:
    started = time.perf_counter()
    path = os.getenv("QE_COPILOT_SQL_VALIDATION_DB_PATH", "./data/validation.db")
    if not _SELECT_ONLY.match(request.query) or _FORBIDDEN.search(request.query) or request.query.count(";"):
        return ExecutionResult(engine="sql", status="blocked", name="read-only SQL validation", duration_ms=0, error="Only one read-only SELECT statement is allowed.", critical=request.critical)
    if path != ":memory:" and not Path(path).is_file():
        return ExecutionResult(
            engine="sql",
            status="blocked",
            name="read-only SQL validation",
            duration_ms=(time.perf_counter() - started) * 1000,
            error=f"Validation database is not configured at {path}. Configure QE_COPILOT_SQL_VALIDATION_DB_PATH with a separate SQLite database file.",
            critical=request.critical,
        )
    try:
        columns, rows = await asyncio.to_thread(_run_select, path, request.query)
        evidence = [ExecutionEvidence(kind="sql", name="columns", value=json.dumps(columns)), ExecutionEvidence(kind="sql", name="rows", value=json.dumps([list(row) for row in rows], default=str))]
        return ExecutionResult(engine="sql", status="passed", name="read-only SQL validation", duration_ms=(time.perf_counter() - started) * 1000, evidence=evidence, critical=request.critical)
    except Exception as exc:
        return ExecutionResult(engine="sql", status="error", name="read-only SQL validation", duration_ms=(time.perf_counter() - started) * 1000, error=str(exc), critical=request.critical)