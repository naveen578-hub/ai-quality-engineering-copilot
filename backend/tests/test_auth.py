"""
Tests for Phase 4 auth: login, token validation, and role-based access
boundaries. Unlike the other test files (which use the admin-authenticated
`client` fixture as a default so they can focus on functional behavior),
these tests deliberately use `unauthenticated_client` and the per-role
header fixtures to verify the boundaries themselves.
"""
import os

os.environ.pop("OPENAI_API_KEY", None)

from backend.models import db  # noqa: E402

SAMPLE_TEST_CASE = {
    "id": "TC-001",
    "title": "Sample",
    "type": "positive",
    "priority": "high",
    "preconditions": ["Pre"],
    "steps": ["Step"],
    "expected_result": "Result",
    "requirement_reference": "REQ-001",
}


# ---- Login ----


def test_login_succeeds_with_seeded_admin(unauthenticated_client):
    from backend.tests.conftest import TEST_ADMIN_USERNAME

    # The seeded conftest admin has a throwaway password we don't know the
    # plaintext of at this scope in a realistic way, so this test creates
    # its own user with a known password instead of relying on conftest's.
    db.create_user("login_test_user", _hash("known-password-123"), "admin")
    resp = unauthenticated_client.post(
        "/api/v1/auth/login", data={"username": "login_test_user", "password": "known-password-123"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "admin"
    assert body["access_token"]


def _hash(password: str) -> str:
    from backend.auth.security import hash_password

    return hash_password(password)


def test_login_fails_with_wrong_password(unauthenticated_client):
    db.create_user("login_test_user2", _hash("correct-password"), "viewer")
    resp = unauthenticated_client.post(
        "/api/v1/auth/login", data={"username": "login_test_user2", "password": "wrong-password"}
    )
    assert resp.status_code == 401


def test_login_fails_for_unknown_user(unauthenticated_client):
    resp = unauthenticated_client.post("/api/v1/auth/login", data={"username": "nobody", "password": "whatever"})
    assert resp.status_code == 401


# ---- Unauthenticated access ----


def test_protected_endpoint_rejects_no_token(unauthenticated_client):
    resp = unauthenticated_client.get("/api/v1/documents")
    assert resp.status_code == 401


def test_protected_endpoint_rejects_garbage_token(unauthenticated_client):
    resp = unauthenticated_client.get(
        "/api/v1/documents", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert resp.status_code == 401


def test_health_does_not_require_auth(unauthenticated_client):
    resp = unauthenticated_client.get("/health")
    assert resp.status_code == 200


# ---- Role boundaries ----


def test_viewer_can_read_but_not_generate(unauthenticated_client, viewer_headers):
    read_resp = unauthenticated_client.get("/api/v1/documents", headers=viewer_headers)
    assert read_resp.status_code == 200

    write_resp = unauthenticated_client.post(
        "/api/v1/generate-test-cases",
        json={"requirement_text": "The system shall do something specific enough.", "requirement_id": "REQ-1"},
        headers=viewer_headers,
    )
    assert write_resp.status_code == 403


def test_tester_can_generate_but_not_delete(unauthenticated_client, tester_headers):
    generate_resp = unauthenticated_client.post(
        "/api/v1/generate-test-cases",
        json={"requirement_text": "The system shall do something specific enough.", "requirement_id": "REQ-1"},
        headers=tester_headers,
    )
    assert generate_resp.status_code == 200

    delete_resp = unauthenticated_client.delete("/api/v1/test-cases/1", headers=tester_headers)
    assert delete_resp.status_code == 403  # role check fires before the 404-vs-exists check


def test_only_admin_can_approve_a_test_case(unauthenticated_client, tester_headers, admin_headers):
    db.reset()
    saved = unauthenticated_client.post(
        "/api/v1/test-cases", json={"test_cases": [SAMPLE_TEST_CASE]}, headers=tester_headers
    ).json()
    db_id = saved[0]["db_id"]

    # Tester can edit content...
    edit_resp = unauthenticated_client.patch(
        f"/api/v1/test-cases/{db_id}", json={"title": "Edited by tester"}, headers=tester_headers
    )
    assert edit_resp.status_code == 200

    # ...but cannot approve.
    tester_approve_resp = unauthenticated_client.patch(
        f"/api/v1/test-cases/{db_id}", json={"status": "approved"}, headers=tester_headers
    )
    assert tester_approve_resp.status_code == 403

    # Admin can.
    admin_approve_resp = unauthenticated_client.patch(
        f"/api/v1/test-cases/{db_id}", json={"status": "approved"}, headers=admin_headers
    )
    assert admin_approve_resp.status_code == 200
    assert admin_approve_resp.json()["status"] == "approved"


def test_only_admin_can_delete(unauthenticated_client, tester_headers, admin_headers):
    db.reset()
    saved = unauthenticated_client.post(
        "/api/v1/test-cases", json={"test_cases": [SAMPLE_TEST_CASE]}, headers=tester_headers
    ).json()
    db_id = saved[0]["db_id"]

    tester_delete_resp = unauthenticated_client.delete(f"/api/v1/test-cases/{db_id}", headers=tester_headers)
    assert tester_delete_resp.status_code == 403

    admin_delete_resp = unauthenticated_client.delete(f"/api/v1/test-cases/{db_id}", headers=admin_headers)
    assert admin_delete_resp.status_code == 204


def test_only_admin_can_manage_users(unauthenticated_client, tester_headers, admin_headers):
    tester_resp = unauthenticated_client.post(
        "/api/v1/auth/users",
        json={"username": "should_fail", "password": "password123", "role": "viewer"},
        headers=tester_headers,
    )
    assert tester_resp.status_code == 403

    admin_resp = unauthenticated_client.post(
        "/api/v1/auth/users",
        json={"username": "created_by_admin", "password": "password123", "role": "viewer"},
        headers=admin_headers,
    )
    assert admin_resp.status_code == 200
    assert admin_resp.json()["role"] == "viewer"


def test_only_admin_can_view_usage_summary(unauthenticated_client, viewer_headers, tester_headers, admin_headers):
    for headers in (viewer_headers, tester_headers):
        resp = unauthenticated_client.get("/api/v1/observability/usage", headers=headers)
        assert resp.status_code == 403

    resp = unauthenticated_client.get("/api/v1/observability/usage", headers=admin_headers)
    assert resp.status_code == 200
    assert "total_calls" in resp.json()


def test_me_endpoint_reflects_token_identity(unauthenticated_client, admin_headers):
    from backend.tests.conftest import TEST_ADMIN_USERNAME

    resp = unauthenticated_client.get("/api/v1/auth/me", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == TEST_ADMIN_USERNAME
    assert body["role"] == "admin"
