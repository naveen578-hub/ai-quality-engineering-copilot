"""
Tests for backend/rag/embeddings.py's three-tier mode selection
(llm/local/mock) and, critically, that a failure to load the local model
degrades gracefully to mock rather than crashing.
"""
import os

import pytest

os.environ.pop("OPENAI_API_KEY", None)


@pytest.fixture(autouse=True)
def reset_embeddings_module_state():
    """embeddings.py's local-model singleton, its "sticky failure" flag, and
    _FORCED_MODE are all module-level state bound once at import time —
    conftest.py sets QE_COPILOT_EMBEDDING_MODE=mock for the whole test
    session (see its own comment for why), which freezes _FORCED_MODE to
    "mock" before these tests even run. Deleting the env var inside a test
    does NOT retroactively change that already-bound constant, so tests that
    need to simulate "no override" patch the module attribute directly."""
    import backend.rag.embeddings as embeddings_module

    original_fn = embeddings_module._local_fn
    original_failed = embeddings_module._local_load_failed
    original_forced_mode = embeddings_module._FORCED_MODE
    yield
    embeddings_module._local_fn = original_fn
    embeddings_module._local_load_failed = original_failed
    embeddings_module._FORCED_MODE = original_forced_mode


def test_forced_mock_mode_overrides_everything(monkeypatch):
    import backend.rag.embeddings as embeddings_module

    embeddings_module._FORCED_MODE = "mock"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-key-for-this-test-only")

    assert embeddings_module.embedding_mode() == "mock"


def test_auto_mode_prefers_llm_when_api_key_present(monkeypatch):
    import backend.rag.embeddings as embeddings_module

    embeddings_module._FORCED_MODE = None
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-key-for-this-test-only")

    assert embeddings_module.embedding_mode() == "llm"


def test_local_model_load_failure_falls_back_to_mock_without_crashing(monkeypatch):
    import backend.rag.embeddings as embeddings_module

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    embeddings_module._FORCED_MODE = None
    embeddings_module._local_fn = None
    embeddings_module._local_load_failed = False

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated: no network access for model download")

    monkeypatch.setattr("chromadb.utils.embedding_functions.ONNXMiniLM_L6_V2", _boom, raising=True)

    with pytest.warns(UserWarning, match="Local embedding model could not be loaded"):
        mode = embeddings_module.embedding_mode()

    assert mode == "mock"

    # And the actual embed call still works — this is the point of the
    # fallback: a broken local model degrades the app, it doesn't break it.
    vectors = embeddings_module.embed_texts(["fallback should still produce a usable vector"])
    assert len(vectors) == 1
    assert len(vectors[0]) == embeddings_module.MOCK_EMBEDDING_DIM


def test_local_model_load_failure_is_sticky_not_retried_every_call(monkeypatch):
    """Once the local model has failed to load, subsequent calls shouldn't
    keep retrying the (slow) failure on every single embed_texts() call."""
    import backend.rag.embeddings as embeddings_module

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    embeddings_module._FORCED_MODE = None
    embeddings_module._local_fn = None
    embeddings_module._local_load_failed = False

    call_count = 0

    def _boom(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("simulated failure")

    monkeypatch.setattr("chromadb.utils.embedding_functions.ONNXMiniLM_L6_V2", _boom, raising=True)

    with pytest.warns(UserWarning):
        embeddings_module.embed_texts(["first call"])
    embeddings_module.embed_texts(["second call"])
    embeddings_module.embed_texts(["third call"])

    assert call_count == 1, "the failing loader should only be attempted once, not on every call"
