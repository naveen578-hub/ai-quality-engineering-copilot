"""
Regression test for a real bug found via a live Playwright run: on a cold
server (no ChromaDB client initialized yet), two near-simultaneous requests
to any endpoint that touches the vector store could race inside
chromadb.PersistentClient() and raise a KeyError, because backend/rag/store.py's
lazy singleton init wasn't thread-safe and FastAPI runs sync endpoints in a
thread pool.

This reproduces that race directly with a thread pool hitting a fresh store,
rather than relying on timing through the full HTTP/browser stack.
"""
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

os.environ.pop("OPENAI_API_KEY", None)

# NOTE: this file used to set its own CHROMA_PERSIST_DIR and rmtree it at
# teardown. Centralized in conftest.py now — see the comment there. This
# file in particular is why the shared-directory bug mattered: it forces a
# cold singleton reset (store._client = None) and hammers it concurrently,
# so if a *different* test file's teardown had just rmtree'd the directory
# this one was silently sharing, the fresh client this test creates would
# be pointed at a half-deleted directory — which is exactly what caused the
# "Error purging logs" chromadb.errors.InternalError seen before this fix.


@pytest.fixture(autouse=True)
def clean_store():
    from backend.rag import store

    store.reset()
    yield


def test_concurrent_cold_start_does_not_raise():
    """
    Before the fix, firing many concurrent calls into _get_collection() on a
    cold store would intermittently raise KeyError from inside chromadb's
    SharedSystemClient. This drives that exact race directly.
    """
    from backend.rag import store

    # Force a fully cold module state, as if the server just started.
    store._client = None
    store._collection = None

    def hit():
        return store.list_documents()

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(hit) for _ in range(8)]
        results = [f.result() for f in futures]  # .result() re-raises any exception

    assert all(r == [] for r in results)


def test_concurrent_cold_start_via_api(client, monkeypatch):
    """Same race, but through the actual FastAPI app + TestClient, closer to
    what the browser test hit."""
    from backend.rag import store

    store._client = None
    store._collection = None

    def hit():
        resp = client.get("/api/v1/documents")
        return resp.status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(hit) for _ in range(8)]
        statuses = [f.result() for f in futures]

    assert all(s == 200 for s in statuses), statuses
