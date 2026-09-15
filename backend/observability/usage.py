"""
Thin layer over backend/models/db.py's llm_usage table: records individual
calls and aggregates them for the /api/v1/observability/usage endpoint.
"""
from __future__ import annotations

import time
from collections import defaultdict
from contextlib import contextmanager
from typing import Optional

from backend.models import db
from backend.models.schemas import UsageByEndpoint, UsageSummary
from backend.observability.pricing import estimate_cost


def record_llm_call(
    endpoint: str, model: str, prompt_tokens: int, completion_tokens: int, latency_ms: float
) -> None:
    total_tokens = prompt_tokens + completion_tokens
    cost = estimate_cost(model, prompt_tokens, completion_tokens)
    db.record_usage(
        endpoint=endpoint,
        mode="llm",
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        latency_ms=latency_ms,
        estimated_cost_usd=cost,
    )


def record_mock_call(endpoint: str, latency_ms: float, mode: str = "mock") -> None:
    db.record_usage(endpoint=endpoint, mode=mode, latency_ms=latency_ms)


@contextmanager
def track_mock_call(endpoint: str, mode: str = "mock"):
    """Wrap a non-LLM-API generation/embedding call to log its latency the
    same way a real LLM call's latency gets logged, so the usage dashboard
    reflects activity even when no API key is configured. `mode` is "mock"
    for the hashed bag-of-words fallback or "local" for the local ONNX
    embedding model (backend/rag/embeddings.py) — kept distinct so the usage
    dashboard can tell "no network/API used at all" apart from "ran a real,
    if smaller, embedding model locally"."""
    start = time.perf_counter()
    try:
        yield
    finally:
        record_mock_call(endpoint, (time.perf_counter() - start) * 1000, mode=mode)


def get_usage_summary() -> UsageSummary:
    rows = db.list_usage(limit=10_000)

    if not rows:
        return UsageSummary(
            total_calls=0, llm_calls=0, local_calls=0, mock_calls=0, total_tokens=0, total_estimated_cost_usd=0.0,
            avg_latency_ms=0.0, by_endpoint=[],
        )

    llm_calls = sum(1 for r in rows if r["mode"] == "llm")
    local_calls = sum(1 for r in rows if r["mode"] == "local")
    mock_calls = sum(1 for r in rows if r["mode"] == "mock")
    total_tokens = sum(r["total_tokens"] for r in rows)
    total_cost = sum(r["estimated_cost_usd"] for r in rows)
    avg_latency = sum(r["latency_ms"] for r in rows) / len(rows)

    by_endpoint_raw: dict = defaultdict(lambda: {"count": 0, "tokens": 0, "cost": 0.0, "latency_sum": 0.0})
    for r in rows:
        bucket = by_endpoint_raw[r["endpoint"]]
        bucket["count"] += 1
        bucket["tokens"] += r["total_tokens"]
        bucket["cost"] += r["estimated_cost_usd"]
        bucket["latency_sum"] += r["latency_ms"]

    by_endpoint = [
        UsageByEndpoint(
            endpoint=endpoint,
            call_count=b["count"],
            total_tokens=b["tokens"],
            estimated_cost_usd=round(b["cost"], 6),
            avg_latency_ms=round(b["latency_sum"] / b["count"], 2),
        )
        for endpoint, b in sorted(by_endpoint_raw.items())
    ]

    return UsageSummary(
        total_calls=len(rows),
        llm_calls=llm_calls,
        local_calls=local_calls,
        mock_calls=mock_calls,
        total_tokens=total_tokens,
        total_estimated_cost_usd=round(total_cost, 6),
        avg_latency_ms=round(avg_latency, 2),
        by_endpoint=by_endpoint,
    )
