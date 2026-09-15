"""
Text -> vector embeddings, in three tiers:

1. "llm": OpenAI's text-embedding-3-small, when OPENAI_API_KEY is set.
2. "local": a real (if small) local semantic embedding model —
   all-MiniLM-L6-v2 via chromadb's own bundled ONNX runtime — when no API
   key is configured. This is the middle ground between "no API key" and
   "OpenAI required": genuine semantic embeddings, no account, no per-call
   cost, and no new heavy dependency (chromadb already depends on
   onnxruntime; this reuses that rather than adding sentence-transformers/
   torch on top of it). The model (~80MB) downloads once on first use and
   is cached under ~/.cache/chroma — that's the one thing this tier needs
   that "mock" doesn't: network access the first time it runs.
3. "mock": a deterministic hashed bag-of-words vector, used when neither of
   the above is available or configured — no network, no download, no
   dependency beyond the stdlib. This is what keeps the app (and the test
   suite, and CI) fully offline-capable, since a fresh clone with no API
   key and no network still needs to demo end to end.

Selection is automatic (see embedding_mode()) unless overridden via
QE_COPILOT_EMBEDDING_MODE=mock|local — "mock" is set explicitly by the test
suite and CI (see backend/tests/conftest.py, .github/workflows/ci.yml) so
tests stay fast, deterministic, and don't depend on network access or a
~80MB download on a cold CI runner.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import threading
import time
import warnings
from typing import List, Optional

from backend.generators.llm_client import LLMCallError, is_configured, is_retryable_llm_error
from backend.observability.usage import record_llm_call, track_mock_call
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

MOCK_EMBEDDING_DIM = 256
_TOKEN_RE = re.compile(r"[a-z0-9]+")

_FORCED_MODE = os.getenv("QE_COPILOT_EMBEDDING_MODE", "").strip().lower() or None  # "mock" | "local" | None (auto)

_local_fn = None
_local_load_failed = False
_local_init_lock = threading.Lock()


def _get_local_embedding_fn():
    """Lazily loads chromadb's bundled local ONNX embedding model. Sticky
    failure: if it can't load once (no network on first run, etc.), don't
    retry on every subsequent call — fall back to mock mode for the rest of
    the process lifetime and say so once, loudly, rather than silently
    retrying a slow failure on every request."""
    global _local_fn, _local_load_failed
    if _local_fn is not None or _local_load_failed:
        return _local_fn

    with _local_init_lock:
        if _local_fn is not None or _local_load_failed:
            return _local_fn
        try:
            from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

            _local_fn = ONNXMiniLM_L6_V2()
        except Exception as exc:  # noqa: BLE001 — any failure here should degrade gracefully, not crash
            warnings.warn(
                f"Local embedding model could not be loaded ({exc}); falling back to mock embeddings "
                "for this process. This usually means no network access was available for the one-time "
                "model download. Set OPENAI_API_KEY for real embeddings, or ignore this if mock mode is fine.",
                stacklevel=2,
            )
            _local_load_failed = True
    return _local_fn


def embedding_mode() -> str:
    if _FORCED_MODE == "mock":
        return "mock"
    if is_configured() and _FORCED_MODE != "local":
        return "llm"
    if _get_local_embedding_fn() is not None:
        return "local"
    return "mock"


def embed_texts(texts: List[str], endpoint: str = "embeddings") -> List[List[float]]:
    mode = embedding_mode()
    if mode == "llm":
        return _embed_with_openai(texts, endpoint)
    if mode == "local":
        with track_mock_call(endpoint, mode="local"):
            return _embed_with_local_model(texts)
    with track_mock_call(endpoint, mode="mock"):
        return [_mock_embed(t) for t in texts]


def _embed_with_local_model(texts: List[str]) -> List[List[float]]:
    fn = _get_local_embedding_fn()
    vectors = fn(texts)
    return [v.tolist() if hasattr(v, "tolist") else list(v) for v in vectors]


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
    retry=retry_if_exception(is_retryable_llm_error),
    reraise=True,
)
def _create_embeddings(client, **kwargs):
    """Isolated so it can be retried on transient errors and unit-tested by
    monkeypatching this exact function."""
    return client.embeddings.create(**kwargs)


def _embed_with_openai(texts: List[str], endpoint: str) -> List[List[float]]:
    from openai import OpenAI

    client = OpenAI()
    model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    start = time.perf_counter()
    try:
        resp = _create_embeddings(client, model=model, input=texts)
    except Exception as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        record_llm_call(endpoint, model, prompt_tokens=0, completion_tokens=0, latency_ms=latency_ms)
        if is_retryable_llm_error(exc):
            raise LLMCallError(f"Embedding call failed after retries: {exc}") from exc
        raise

    latency_ms = (time.perf_counter() - start) * 1000
    prompt_tokens = resp.usage.prompt_tokens if resp.usage else 0
    record_llm_call(endpoint, model, prompt_tokens=prompt_tokens, completion_tokens=0, latency_ms=latency_ms)

    return [item.embedding for item in resp.data]


def _mock_embed(text: str) -> List[float]:
    tokens = _TOKEN_RE.findall(text.lower())
    vector = [0.0] * MOCK_EMBEDDING_DIM

    for token in tokens:
        bucket = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % MOCK_EMBEDDING_DIM
        vector[bucket] += 1.0

    norm = math.sqrt(sum(v * v for v in vector))
    if norm > 0:
        vector = [v / norm for v in vector]
    return vector
