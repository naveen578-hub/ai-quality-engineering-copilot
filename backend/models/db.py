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
import hashlib
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, List, Optional

from backend.models.schemas import (
    PersistedTestCase,
    TestCase,
    TestCaseStatus,
    TestRunIngestRequest,
    UpdateTestCaseRequest,
)

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

CREATE TABLE IF NOT EXISTS requirement_documents (
    document_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    filename_key TEXT NOT NULL,
    revision INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_requirement_documents_filename ON requirement_documents(filename_key, revision DESC);

CREATE TABLE IF NOT EXISTS requirement_snapshots (
    document_id TEXT NOT NULL,
    requirement_id TEXT NOT NULL,
    requirement_text TEXT NOT NULL,
    PRIMARY KEY (document_id, requirement_id)
);

CREATE TABLE IF NOT EXISTS requirement_impacts (
    impact_id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename_key TEXT NOT NULL,
    filename TEXT NOT NULL,
    requirement_id TEXT NOT NULL,
    change_type TEXT NOT NULL,
    old_text TEXT,
    new_text TEXT,
    previous_document_id TEXT,
    current_document_id TEXT NOT NULL,
    reviewed INTEGER NOT NULL DEFAULT 0,
    reviewed_at TEXT,
    superseded INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (filename_key, requirement_id, current_document_id)
);
CREATE INDEX IF NOT EXISTS idx_requirement_impacts_active ON requirement_impacts(superseded, reviewed, impact_id DESC);

CREATE TABLE IF NOT EXISTS test_run_batches (
    run_batch_id TEXT PRIMARY KEY,
    payload_hash TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS test_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_case_db_id INTEGER REFERENCES test_cases(db_id) ON DELETE CASCADE,
    test_key TEXT,
    engine TEXT NOT NULL,
    status TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    run_batch_id TEXT NOT NULL REFERENCES test_run_batches(run_batch_id) ON DELETE CASCADE,
    error_summary TEXT,
    recorded_at TEXT NOT NULL,
    CHECK ((test_case_db_id IS NOT NULL AND test_key IS NULL) OR (test_case_db_id IS NULL AND test_key IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_test_runs_batch_case
ON test_runs(run_batch_id, test_case_db_id) WHERE test_case_db_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_test_runs_batch_key
ON test_runs(run_batch_id, test_key) WHERE test_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_test_runs_case_time ON test_runs(test_case_db_id, recorded_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_test_runs_key_time ON test_runs(test_key, recorded_at DESC, id DESC);
"""


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
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
        conn.execute("DELETE FROM requirement_impacts")
        conn.execute("DELETE FROM requirement_snapshots")
        conn.execute("DELETE FROM requirement_documents")
        conn.execute("DELETE FROM test_runs")
        conn.execute("DELETE FROM test_run_batches")


def record_requirement_revision(filename: str, document_id: str, requirements: dict[str, str]) -> int:
    filename_key = "/".join(part for part in filename.replace("\\", "/").casefold().split("/") if part)
    requirements = {
        key.strip().casefold(): (key.strip(), " ".join(value.split()))
        for key, value in requirements.items()
        if key.strip()
    }
    now = _now()
    with _connect() as conn:
        previous = conn.execute(
            "SELECT document_id, revision FROM requirement_documents WHERE filename_key = ? ORDER BY revision DESC LIMIT 1",
            (filename_key,),
        ).fetchone()
        previous_id = previous["document_id"] if previous else None
        previous_requirements = {}
        if previous_id:
            previous_requirements = {
                row["requirement_id"].casefold(): (row["requirement_id"], row["requirement_text"])
                for row in conn.execute(
                    "SELECT requirement_id, requirement_text FROM requirement_snapshots WHERE document_id = ?",
                    (previous_id,),
                ).fetchall()
            }

        revision = int(previous["revision"] + 1) if previous else 1
        conn.execute(
            "INSERT INTO requirement_documents (document_id, filename, filename_key, revision, created_at) VALUES (?, ?, ?, ?, ?)",
            (document_id, filename, filename_key, revision, now),
        )
        conn.executemany(
            "INSERT INTO requirement_snapshots (document_id, requirement_id, requirement_text) VALUES (?, ?, ?)",
            [(document_id, requirement_id, text) for requirement_id, text in requirements.values()],
        )
        if previous is None:
            return 0
        conn.execute("UPDATE requirement_impacts SET superseded = 1 WHERE filename_key = ?", (filename_key,))

        impact_count = 0
        for requirement_id in sorted(previous_requirements.keys() | requirements.keys()):
            old_record = previous_requirements.get(requirement_id)
            old_text = old_record[1] if old_record else None
            new_record = requirements.get(requirement_id)
            new_text = new_record[1] if new_record else None
            display_requirement_id = new_record[0] if new_record else old_record[0]
            if old_text is None:
                change_type = "added"
            elif new_text is None:
                change_type = "removed"
            elif " ".join(old_text.split()).casefold() != " ".join(new_text.split()).casefold():
                change_type = "modified"
            else:
                continue
            conn.execute(
                """INSERT INTO requirement_impacts
                   (filename_key, filename, requirement_id, change_type, old_text, new_text,
                    previous_document_id, current_document_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (filename_key, filename, display_requirement_id, change_type, old_text, new_text, previous_id, document_id, now),
            )
            impact_count += 1
    return impact_count


def requirement_impact_report() -> dict:
    with _connect() as conn:
        impact_rows = conn.execute(
            "SELECT * FROM requirement_impacts WHERE superseded = 0 ORDER BY impact_id DESC"
        ).fetchall()
        test_case_rows = conn.execute("SELECT * FROM test_cases ORDER BY db_id ASC").fetchall()
        known_requirements = {
            row["requirement_id"].casefold()
            for row in conn.execute(
                """SELECT s.requirement_id FROM requirement_snapshots s
                   JOIN requirement_documents d ON d.document_id = s.document_id
                   WHERE d.revision = (SELECT MAX(d2.revision) FROM requirement_documents d2 WHERE d2.filename_key = d.filename_key)"""
            ).fetchall()
        }

    cases_by_requirement: dict[str, list[dict]] = {}
    changed_requirement_ids = {row["requirement_id"].casefold() for row in impact_rows}
    unlinked_cases = []
    for row in test_case_rows:
        requirement_id = row["requirement_reference"].strip().casefold()
        if requirement_id in known_requirements:
            cases_by_requirement.setdefault(requirement_id, []).append(
                {"db_id": row["db_id"], "id": row["public_id"], "title": row["title"], "status": row["status"]}
            )
        elif known_requirements and requirement_id not in changed_requirement_ids:
            unlinked_cases.append(
                {
                    "db_id": row["db_id"], "id": row["public_id"], "title": row["title"],
                    "requirement_reference": row["requirement_reference"], "status": row["status"],
                }
            )

    impacts = []
    for row in impact_rows:
        impacts.append(
            {
                "impact_id": row["impact_id"],
                "filename": row["filename"],
                "requirement_id": row["requirement_id"],
                "change_type": row["change_type"],
                "old_text": row["old_text"],
                "new_text": row["new_text"],
                "previous_document_id": row["previous_document_id"],
                "current_document_id": row["current_document_id"],
                "reviewed": bool(row["reviewed"]),
                "reviewed_at": row["reviewed_at"],
                "affected_test_cases": cases_by_requirement.get(row["requirement_id"].casefold(), []),
            }
        )
    return {"impacts": impacts, "unlinked_test_cases": unlinked_cases}


def mark_requirement_impact_reviewed(impact_id: int, reviewed: bool = True) -> bool:
    with _connect() as conn:
        cursor = conn.execute(
            "UPDATE requirement_impacts SET reviewed = ?, reviewed_at = ? WHERE impact_id = ? AND superseded = 0",
            (int(reviewed), _now() if reviewed else None, impact_id),
        )
    return cursor.rowcount > 0


def ingest_test_run_batch(payload: TestRunIngestRequest) -> tuple[int, bool]:
    serialized = payload.model_dump(mode="json")
    serialized["results"] = sorted(
        serialized["results"],
        key=lambda result: (
            "case" if result["test_case_db_id"] is not None else "key",
            str(result["test_case_db_id"] if result["test_case_db_id"] is not None else result["test_key"]),
        ),
    )
    canonical = json.dumps(serialized, sort_keys=True, separators=(",", ":"))
    payload_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    recorded_at = _now()
    with _connect() as conn:
        existing = conn.execute(
            "SELECT payload_hash FROM test_run_batches WHERE run_batch_id = ?",
            (payload.run_batch_id,),
        ).fetchone()
        if existing:
            if existing["payload_hash"] != payload_hash:
                raise ValueError("run_batch_id already exists with a different payload")
            return len(payload.results), True

        for result in payload.results:
            if result.test_case_db_id is not None:
                exists = conn.execute(
                    "SELECT 1 FROM test_cases WHERE db_id = ?",
                    (result.test_case_db_id,),
                ).fetchone()
                if not exists:
                    raise ValueError(f"test_case_db_id {result.test_case_db_id} does not exist")

        conn.execute(
            "INSERT INTO test_run_batches (run_batch_id, payload_hash, recorded_at) VALUES (?, ?, ?)",
            (payload.run_batch_id, payload_hash, recorded_at),
        )
        conn.executemany(
            """INSERT INTO test_runs
               (test_case_db_id, test_key, engine, status, duration_ms, run_batch_id, error_summary, recorded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    result.test_case_db_id,
                    result.test_key,
                    result.engine.value,
                    result.status.value,
                    result.duration_ms,
                    payload.run_batch_id,
                    result.error_summary,
                    recorded_at,
                )
                for result in payload.results
            ],
        )
    return len(payload.results), False


def list_test_run_identities() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT test_case_db_id, test_key, COUNT(*) AS total_run_count
               FROM test_runs GROUP BY test_case_db_id, test_key
               ORDER BY COALESCE(test_case_db_id, 9223372036854775807), test_key"""
        ).fetchall()
        summaries = []
        for row in rows:
            if row["test_case_db_id"] is not None:
                case = conn.execute(
                    "SELECT db_id, public_id, title FROM test_cases WHERE db_id = ?",
                    (row["test_case_db_id"],),
                ).fetchone()
                if case is None:
                    continue
                summaries.append({
                    "identity_type": "test_case",
                    "test_case_db_id": case["db_id"],
                    "test_key": None,
                    "test_case_public_id": case["public_id"],
                    "name": case["title"],
                    "total_run_count": row["total_run_count"],
                })
            else:
                summaries.append({
                    "identity_type": "test_key",
                    "test_case_db_id": None,
                    "test_key": row["test_key"],
                    "test_case_public_id": None,
                    "name": row["test_key"],
                    "total_run_count": row["total_run_count"],
                })
        return summaries


def get_test_run_history(test_case_db_id: Optional[int] = None, test_key: Optional[str] = None) -> list[dict]:
    if (test_case_db_id is None) == (test_key is None):
        raise ValueError("provide exactly one test identity")
    identity_column = "test_case_db_id" if test_case_db_id is not None else "test_key"
    identity_value = test_case_db_id if test_case_db_id is not None else test_key
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT r.*, (SELECT COUNT(*) FROM test_runs all_runs WHERE all_runs.run_batch_id = r.run_batch_id) AS batch_result_count,
                       (SELECT COUNT(*) FROM test_runs failed_runs WHERE failed_runs.run_batch_id = r.run_batch_id
                          AND failed_runs.status IN ('failed', 'error')) AS batch_failure_count
                FROM test_runs r WHERE r.{identity_column} = ? ORDER BY r.recorded_at DESC, r.id DESC""",
            (identity_value,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_test_case_identity(test_case_db_id: int) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT db_id, public_id, title FROM test_cases WHERE db_id = ?",
            (test_case_db_id,),
        ).fetchone()
    if row is None:
        return None
    return {"test_case_db_id": row["db_id"], "test_case_public_id": row["public_id"], "name": row["title"]}


def reset_test_runs() -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM test_runs")
        conn.execute("DELETE FROM test_run_batches")


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
