from __future__ import annotations

import sqlite3
import asyncio
import json
import subprocess
import sys

import httpx

from backend.execution.rest_adapter import execute_rest
from backend.execution.results import critical_failure_count
from backend.execution.sql_adapter import execute_sql
from backend.models.schemas import ExecutionResult, RestAssertion, RestExecutionRequest, SqlExecutionRequest


def test_rest_adapter_normalizes_status_and_json_assertion(monkeypatch):
    monkeypatch.setenv("QE_ALLOW_PRIVATE_REST_TARGETS", "true")
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True}, request=request)

    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    def client_factory(**kwargs):
        return original_client(transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    result = asyncio.run(execute_rest(RestExecutionRequest(url="https://example.test", assertions=[RestAssertion(kind="status_code", expected="200"), RestAssertion(kind="json_contains", expected="ok=True")])))
    assert result.engine == "rest"
    assert result.status == "passed"


def test_rest_adapter_blocks_loopback_targets_by_default(monkeypatch):
    import os

    monkeypatch.delenv("QE_ALLOW_PRIVATE_REST_TARGETS", raising=False)
    result = asyncio.run(execute_rest(RestExecutionRequest(url="http://127.0.0.1:8000/health")))
    assert result.status == "blocked"
    assert "public host" in result.error


def test_rest_adapter_fails_unexpected_http_error(monkeypatch):
    monkeypatch.setenv("QE_ALLOW_PRIVATE_REST_TARGETS", "true")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable", request=request)

    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(transport=transport, **kwargs))
    result = asyncio.run(execute_rest(RestExecutionRequest(url="https://example.test")))
    assert result.status == "failed"
    assert "503" in result.error


def test_sql_adapter_allows_select_and_blocks_writes(tmp_path, monkeypatch):
    path = tmp_path / "checks.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE checks (id INTEGER, status TEXT)")
    connection.execute("INSERT INTO checks VALUES (1, 'ok')")
    connection.commit()
    connection.close()
    monkeypatch.setenv("QE_COPILOT_SQL_VALIDATION_DB_PATH", str(path))

    passed = asyncio.run(execute_sql(SqlExecutionRequest(query="SELECT status FROM checks")))
    blocked = asyncio.run(execute_sql(SqlExecutionRequest(query="UPDATE checks SET status='bad'")))
    assert passed.status == "passed"
    assert blocked.status == "blocked"


def test_sql_adapter_blocks_when_validation_database_is_not_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("QE_COPILOT_SQL_VALIDATION_DB_PATH", str(tmp_path / "missing.db"))
    result = asyncio.run(execute_sql(SqlExecutionRequest(query="SELECT 1")))
    assert result.status == "blocked"
    assert "not configured" in result.error


def test_critical_failure_count_ignores_noncritical_and_skipped_results():
    results = [
        ExecutionResult(engine="rest", status="failed", name="critical failure", critical=True),
        ExecutionResult(engine="sql", status="failed", name="advisory failure", critical=False),
        ExecutionResult(engine="playwright", status="skipped", name="skipped", critical=True),
    ]
    assert critical_failure_count(results) == 1


def test_ci_result_checker_exits_nonzero_only_for_critical_failures(tmp_path):
    result_file = tmp_path / "results.json"
    result_file.write_text(json.dumps({"results": [
        {"engine": "rest", "status": "failed", "name": "critical", "critical": True},
        {"engine": "sql", "status": "failed", "name": "advisory", "critical": False},
    ]}), encoding="utf-8")
    command = [sys.executable, "-m", "backend.execution.ci_checks", "--results", str(result_file)]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    assert completed.returncode == 1
    assert "Critical failures: 1" in completed.stdout

    result_file.write_text(json.dumps({"results": [
        {"engine": "sql", "status": "failed", "name": "advisory", "critical": False},
    ]}), encoding="utf-8")
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    assert completed.returncode == 0
    assert "Critical failures: 0" in completed.stdout