"""
Shared fixtures for the backend test suite.

Every protected endpoint requires a bearer token as of Phase 4 (auth/RBAC).
Rather than repeat login boilerplate in every test file, this seeds three
fixed test users (one per role) once per session and hands out a `client`
fixture that's pre-authenticated as admin — since most existing tests are
about functional behavior, not RBAC boundaries, and admin can reach
everything. Tests that specifically need to verify role restrictions (see
test_auth.py) use the `tester_headers` / `viewer_headers` fixtures directly,
or the `unauthenticated_client` fixture for the "no token at all" case.

Tokens are minted directly via create_access_token() rather than going
through the real /auth/login + bcrypt flow for every test — that flow is
covered explicitly by its own tests in test_auth.py, and re-hashing/
verifying a bcrypt password on every single test in the suite would be a
needless (bcrypt is intentionally slow) per-test cost.
"""
from __future__ import annotations

import os

os.environ.setdefault("QE_COPILOT_JWT_SECRET", "test-only-secret-do-not-use-in-prod")
os.environ.pop("OPENAI_API_KEY", None)
# Force mock embeddings for the whole test suite — without this, embeddings.py's
# "auto" mode would try to load a real local ONNX model (~80MB, one-time
# download) since no OPENAI_API_KEY is set here, which would make tests slow
# and dependent on network access on a cold run. Explicit > implicit for this.
os.environ["QE_COPILOT_EMBEDDING_MODE"] = "mock"
os.environ.pop("OPENAI_API_KEY", None)

# A single shared ChromaDB directory for the whole test session. This is
# deliberate, not an oversight: backend/rag/store.py's client/collection are
# process-wide singletons bound at first import, so multiple test files each
# setting their own CHROMA_PERSIST_DIR do NOT get isolated directories — they
# silently share whichever one was bound first. Prior to this fix, several
# test files also called shutil.rmtree() on "their" directory at teardown,
# which — since it was actually the shared directory — deleted it out from
# under another file's still-live client mid-suite and corrupted chromadb's
# internal state ("Error purging logs"). Every test file now uses this same
# directory and cleans up via store.reset()/db.reset() (proper API calls),
# never via filesystem deletion of a directory a live client still holds
# open.
os.environ.setdefault("CHROMA_PERSIST_DIR", "./data/chroma-test-shared")

import shutil

import pytest
from fastapi.testclient import TestClient

from backend.auth.security import create_access_token
from backend.auth.users import create_user, get_user
from backend.models.schemas import Role

TEST_ADMIN_USERNAME = "conftest_admin"
TEST_TESTER_USERNAME = "conftest_tester"
TEST_VIEWER_USERNAME = "conftest_viewer"
_SHARED_CHROMA_DIR = os.environ["CHROMA_PERSIST_DIR"]


@pytest.fixture(scope="session", autouse=True)
def _clean_shared_chroma_dir_once():
    """Wipe the shared test ChromaDB directory exactly once, before anything
    in the suite has bound a client to it. Nothing after this point should
    ever delete this directory while the session is running — individual
    tests clean up via store.reset() instead, which goes through chromadb's
    own API rather than pulling the filesystem out from under a live client."""
    shutil.rmtree(_SHARED_CHROMA_DIR, ignore_errors=True)
    yield
    shutil.rmtree(_SHARED_CHROMA_DIR, ignore_errors=True)


def _ensure_user(username: str, role: Role) -> None:
    if get_user(username) is None:
        create_user(username, "throwaway-test-password-123", role)


def _headers_for(username: str, role: Role) -> dict:
    token = create_access_token(subject=username, role=role.value)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _seed_test_users():
    """Runs before every test so these three accounts exist no matter what
    order tests run in or what any individual test does to the users table."""
    _ensure_user(TEST_ADMIN_USERNAME, Role.admin)
    _ensure_user(TEST_TESTER_USERNAME, Role.tester)
    _ensure_user(TEST_VIEWER_USERNAME, Role.viewer)


@pytest.fixture
def admin_headers() -> dict:
    return _headers_for(TEST_ADMIN_USERNAME, Role.admin)


@pytest.fixture
def tester_headers() -> dict:
    return _headers_for(TEST_TESTER_USERNAME, Role.tester)


@pytest.fixture
def viewer_headers() -> dict:
    return _headers_for(TEST_VIEWER_USERNAME, Role.viewer)


@pytest.fixture
def client(admin_headers) -> TestClient:
    """A TestClient pre-authenticated as admin — the default for existing
    functional tests that aren't specifically about RBAC boundaries."""
    from backend.api.main import app

    c = TestClient(app)
    c.headers.update(admin_headers)
    return c


@pytest.fixture
def unauthenticated_client() -> TestClient:
    from backend.api.main import app

    return TestClient(app)
