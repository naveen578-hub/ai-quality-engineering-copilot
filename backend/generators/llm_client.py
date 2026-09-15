"""
Thin wrapper around the OpenAI API.

Kept separate from the generator logic so that swapping providers later
(Azure OpenAI, Anthropic, a local model) only touches this file. Also where
Phase 4's retry/error-handling and usage-tracking guardrails live, since
every LLM call in the app funnels through call_llm_for_json.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from backend.observability.usage import record_llm_call

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


class LLMNotConfiguredError(RuntimeError):
    """Raised when no OPENAI_API_KEY is available. Callers should fall back to mock mode."""


class LLMCallError(RuntimeError):
    """Raised when the LLM call ultimately fails after retries are exhausted."""


def is_configured() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def is_retryable_llm_error(exc: BaseException) -> bool:
    """Shared by both the chat-completion and embeddings call paths (see
    backend/rag/embeddings.py) so retry behavior stays consistent across
    every OpenAI call the app makes."""
    # Imported lazily to avoid a hard dependency at module-import time in
    # environments that only ever run mock mode.
    from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError

    return isinstance(exc, (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError))


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
    retry=retry_if_exception(is_retryable_llm_error),
    reraise=True,
)
def _create_completion(client, **kwargs):
    """Isolated so it can be retried on transient errors and unit-tested by
    monkeypatching this exact function without touching the rest of the flow."""
    return client.chat.completions.create(**kwargs)


def call_llm_for_json(system_prompt: str, user_prompt: str, endpoint: str = "unknown") -> Dict[str, Any]:
    """
    Calls the chat completion endpoint with JSON mode enabled and returns
    the parsed dict.

    Raises:
        LLMNotConfiguredError: no OPENAI_API_KEY is set (callers should fall
            back to mock mode; this is not itself an error condition).
        LLMCallError: the call failed even after retrying transient errors
            (rate limits, timeouts, connection errors, 5xx).
        json.JSONDecodeError: the model returned invalid JSON (extremely
            unlikely with response_format=json_object, but not trusted blindly).

    Records latency, token usage, and estimated cost for every call —
    successful or not — to the usage log (backend/observability/usage.py),
    tagged with `endpoint` so /api/v1/observability/usage can break it down.
    """
    if not is_configured():
        raise LLMNotConfiguredError("OPENAI_API_KEY is not set")

    from openai import OpenAI

    client = OpenAI()
    start = time.perf_counter()
    try:
        completion = _create_completion(
            client,
            model=OPENAI_MODEL,
            response_format={"type": "json_object"},
            temperature=0.2,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        record_llm_call(endpoint, OPENAI_MODEL, prompt_tokens=0, completion_tokens=0, latency_ms=latency_ms)
        if is_retryable_llm_error(exc):
            raise LLMCallError(f"LLM call failed after retries: {exc}") from exc
        raise

    latency_ms = (time.perf_counter() - start) * 1000
    usage = completion.usage
    record_llm_call(
        endpoint,
        OPENAI_MODEL,
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
        latency_ms=latency_ms,
    )

    raw = completion.choices[0].message.content
    return json.loads(raw)
