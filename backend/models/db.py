"""
Lightweight persistence for generated test cases.

Deliberately SQLite via stdlib rather than Postgres: this is the "approve/edit
generated tests" and "traceability matrix" feature from Phase 3, and the
project's stated Phase-2-plus target is Postgres/pgvector. Swapping the
storage backend later only touches this file and its call sites — nothing
upstream (the generators, the API routes) needs to know or care.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, List, Optional

from backend.models.schemas import PersistedTestCase, TestCase, TestCaseStatus, UpdateTestCaseRequest

DB_PATH = os.getenv("QE_COPILOT_DB_PATH", "./data/qe_copilot.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS test_cases (
    db_id INTEGER PRIMARY KEY AUTOINCREMENT,
    public_id TEXT NOT NULL,
    title TEXT NOT NULL,
    type TEXT NOT NULL,
    priority TEXT NOT NULL,
    preconditions TEXT NOT NULL,      -- JSON array
    steps TEXT NOT NULL,              -- JSON array
    expected_result TEXT NOT NULL,
    requirement_reference TEXT NOT NULL,
    source_chunk TEXT,
    document_id TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint TEXT NOT NULL,
    mode TEXT NOT NULL,               -- 'llm', 'local', or 'mock'
    model TEXT,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms REAL NOT NULL DEFAULT 0,
    estimated_cost_usd REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS login_failures (
    username_key TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_failures_user_time ON login_failures(username_key, occurred_at);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_events_created ON audit_events(created_at DESC);
"""


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_model(row: sqlite3.Row) -> PersistedTestCase:
    return PersistedTestCase(
        db_id=row["db_id"],
        id=row["public_id"],
        title=row["title"],
        type=row["type"],
        priority=row["priority"],
        preconditions=json.loads(row["preconditions"]),
        steps=json.loads(row["steps"]),
        expected_result=row["expected_result"],
        requirement_reference=row["requirement_reference"],
        source_chunk=row["source_chunk"],
        document_id=row["document_id"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def save_test_cases(test_cases: List[TestCase], document_id: Optional[str] = None) -> List[PersistedTestCase]:
    now = _now()
    saved: List[PersistedTestCase] = []
    with _connect() as conn:
        for tc in test_cases:
            cur = conn.execute(
                """
                INSERT INTO test_cases
                    (public_id, title, type, priority, preconditions, steps, expected_result,
                     requirement_reference, source_chunk, document_id, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tc.id,
                    tc.title,
                    tc.type.value,
                    tc.priority.value,
                    json.dumps(tc.preconditions),
                    json.dumps(tc.steps),
                    tc.expected_result,
                    tc.requirement_reference,
                    tc.source_chunk,
                    document_id,
                    TestCaseStatus.draft.value,
                    now,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM test_cases WHERE db_id = ?", (cur.lastrowid,)).fetchone()
            saved.append(_row_to_model(row))
    return saved


def list_test_cases(
    status: Optional[TestCaseStatus] = None,
    requirement_reference: Optional[str] = None,
    document_id: Optional[str] = None,
) -> List[PersistedTestCase]:
    query = "SELECT * FROM test_cases WHERE 1=1"
    params: List[str] = []
    if status is not None:
        query += " AND status = ?"
        params.append(status.value)
    if requirement_reference is not None:
        query += " AND requirement_reference = ?"
        params.append(requirement_reference)
    if document_id is not None:
        query += " AND document_id = ?"
        params.append(document_id)
    query += " ORDER BY db_id ASC"

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_model(r) for r in rows]


def get_test_case(db_id: int) -> Optional[PersistedTestCase]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM test_cases WHERE db_id = ?", (db_id,)).fetchone()
    return _row_to_model(row) if row else None


def update_test_case(db_id: int, updates: UpdateTestCaseRequest) -> Optional[PersistedTestCase]:
    existing = get_test_case(db_id)
    if existing is None:
        return None

    fields = updates.model_dump(exclude_unset=True)
    if not fields:
        return existing

    set_clauses = []
    params: List[object] = []
    for key, value in fields.items():
        if key in ("preconditions", "steps"):
            value = json.dumps(value)
        elif key == "status":
            value = value.value if hasattr(value, "value") else value
        elif key == "priority":
            value = value.value if hasattr(value, "value") else value
        set_clauses.append(f"{key} = ?")
        params.append(value)

    set_clauses.append("updated_at = ?")
    params.append(_now())
    params.append(db_id)

    with _connect() as conn:
        conn.execute(f"UPDATE test_cases SET {', '.join(set_clauses)} WHERE db_id = ?", params)
        row = conn.execute("SELECT * FROM test_cases WHERE db_id = ?", (db_id,)).fetchone()
    return _row_to_model(row) if row else None


def delete_test_case(db_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM test_cases WHERE db_id = ?", (db_id,))
    return cur.rowcount > 0


def reset() -> None:
    """Wipes all persisted test cases. Used by tests."""
    with _connect() as conn:
        conn.execute("DELETE FROM test_cases")


# ---- Users (Phase 4: auth) ----


def create_user(username: str, password_hash: str, role: str) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
            (username, password_hash, role, _now()),
        )
        return cur.lastrowid


def get_user_by_username(username: str) -> Optional[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def list_users() -> List[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute("SELECT id, username, role, created_at FROM users ORDER BY id ASC").fetchall()


def user_count() -> int:
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]


def reset_users() -> None:
    """Used by tests."""
    with _connect() as conn:
        conn.execute("DELETE FROM users")


# ---- LLM usage tracking (Phase 4: observability) ----


def record_usage(
    endpoint: str,
    mode: str,
    model: Optional[str] = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    latency_ms: float = 0.0,
    estimated_cost_usd: float = 0.0,
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO llm_usage
                (endpoint, mode, model, prompt_tokens, completion_tokens, total_tokens,
                 latency_ms, estimated_cost_usd, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (endpoint, mode, model, prompt_tokens, completion_tokens, total_tokens, latency_ms, estimated_cost_usd, _now()),
        )


def list_usage(limit: int = 500) -> List[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute("SELECT * FROM llm_usage ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def reset_usage() -> None:
    """Used by tests."""
    with _connect() as conn:
        conn.execute("DELETE FROM llm_usage")


# ---- Login throttling and audit trail ----


def record_login_failure(username_key: str, occurred_at: str, window_start: str) -> int:
    with _connect() as conn:
        conn.execute("DELETE FROM login_failures WHERE occurred_at < ?", (window_start,))
        conn.execute(
            "INSERT INTO login_failures (username_key, occurred_at) VALUES (?, ?)",
            (username_key, occurred_at),
        )
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM login_failures WHERE username_key = ? AND occurred_at >= ?",
                (username_key, window_start),
            ).fetchone()[0]
        )


def clear_login_failures(username_key: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM login_failures WHERE username_key = ?", (username_key,))


def add_audit_event(
    actor: str,
    action: str,
    target_type: str,
    target_id: Optional[str] = None,
    details: Optional[dict] = None,
) -> int:
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO audit_events (actor, action, target_type, target_id, details_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (actor, action, target_type, target_id, json.dumps(details or {}, default=str), _now()),
        )
        return int(cursor.lastrowid)


def list_audit_events(limit: int = 200) -> List[sqlite3.Row]:
    bounded_limit = max(1, min(limit, 1000))
    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (bounded_limit,)
        ).fetchall()
