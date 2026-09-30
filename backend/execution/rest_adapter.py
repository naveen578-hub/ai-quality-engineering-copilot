from __future__ import annotations

import json
import asyncio
import ipaddress
import os
import socket
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from backend.models.schemas import ExecutionEvidence, ExecutionResult, RestExecutionRequest


def _json_path(payload: Any, path: str) -> Any:
    value = payload
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


async def _target_is_allowed(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return False
    if os.getenv("QE_ALLOW_PRIVATE_REST_TARGETS", "").lower() == "true":
        return True
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
        )
    except OSError:
        return False
    return bool(addresses) and all(ipaddress.ip_address(item[4][0].split("%", 1)[0]).is_global for item in addresses)


async def execute_rest(request: RestExecutionRequest) -> ExecutionResult:
    started = time.perf_counter()
    name = f"{request.method} {request.url}"
    try:
        if not await _target_is_allowed(request.url):
            return ExecutionResult(engine="rest", status="blocked", name=name, error="REST target must be an HTTP(S) public host. Private targets require explicit QE_ALLOW_PRIVATE_REST_TARGETS=true configuration.", critical=request.critical)
        async with httpx.AsyncClient(follow_redirects=False, timeout=30) as client:
            response = await client.request(request.method, request.url, headers=request.headers, json=request.body)
        content_type = response.headers.get("content-type", "")
        payload: Any = None
        if "json" in content_type:
            try:
                payload = response.json()
            except ValueError:
                payload = None
        has_status_assertion = any(assertion.kind == "status_code" for assertion in request.assertions)
        failures = [] if response.status_code < 400 or has_status_assertion else [f"Unexpected HTTP status {response.status_code}"]
        evidence = [ExecutionEvidence(kind="http", name="status_code", value=str(response.status_code))]
        for assertion in request.assertions:
            if assertion.kind == "status_code":
                actual = str(response.status_code)
                passed = actual == assertion.expected
            elif assertion.kind == "text_contains":
                actual = response.text
                passed = assertion.expected.casefold() in actual.casefold()
            else:
                path, separator, expected_value = assertion.expected.partition("=")
                actual_value = _json_path(payload, path)
                actual = json.dumps(actual_value, default=str)
                passed = bool(separator) and str(actual_value) == expected_value
            evidence.append(ExecutionEvidence(kind="assertion", name=assertion.kind, value=f"expected={assertion.expected}; actual={actual[:300]}"))
            if not passed:
                failures.append(f"{assertion.kind} expected {assertion.expected}, got {actual[:300]}")
        return ExecutionResult(engine="rest", status="failed" if failures else "passed", name=name, duration_ms=(time.perf_counter() - started) * 1000, error="; ".join(failures) if failures else None, evidence=evidence, critical=request.critical)
    except Exception as exc:
        return ExecutionResult(engine="rest", status="error", name=name, duration_ms=(time.perf_counter() - started) * 1000, error=str(exc), critical=request.critical)