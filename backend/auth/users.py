"""
User account operations, layered on top of backend/models/db.py.

Seeding: on first startup with zero users in the table, one admin account is
created from QE_COPILOT_ADMIN_USERNAME / QE_COPILOT_ADMIN_PASSWORD (falling
back to demo defaults for local/portfolio use). This means the app is usable
immediately after cloning, but a real deployment should set those env vars
to something real before first run — the demo defaults are printed as a
warning, not silently used.
"""
from __future__ import annotations

import os
import warnings
from typing import Optional

from backend.auth.security import hash_password, verify_password
from backend.models import db
from backend.models.schemas import Role, UserOut

DEMO_ADMIN_USERNAME = "admin"
DEMO_ADMIN_PASSWORD = "changeme123"  # noqa: S105 — intentional, documented demo-only default


class AuthError(Exception):
    pass


def create_user(username: str, password: str, role: Role) -> UserOut:
    existing = db.get_user_by_username(username)
    if existing is not None:
        raise AuthError(f"Username '{username}' is already taken.")
    password_hash = hash_password(password)
    user_id = db.create_user(username, password_hash, role.value)
    row = db.get_user_by_username(username)
    return UserOut(id=user_id, username=username, role=Role(row["role"]), created_at=row["created_at"])


def authenticate(username: str, password: str) -> Optional[UserOut]:
    row = db.get_user_by_username(username)
    if row is None or not verify_password(password, row["password_hash"]):
        return None
    return UserOut(id=row["id"], username=row["username"], role=Role(row["role"]), created_at=row["created_at"])


def get_user(username: str) -> Optional[UserOut]:
    row = db.get_user_by_username(username)
    if row is None:
        return None
    return UserOut(id=row["id"], username=row["username"], role=Role(row["role"]), created_at=row["created_at"])


def list_users() -> list[UserOut]:
    return [UserOut(id=r["id"], username=r["username"], role=Role(r["role"]), created_at=r["created_at"]) for r in db.list_users()]


def seed_default_admin_if_empty() -> None:
    if db.user_count() > 0:
        return

    username = os.getenv("QE_COPILOT_ADMIN_USERNAME", DEMO_ADMIN_USERNAME)
    password = os.getenv("QE_COPILOT_ADMIN_PASSWORD", DEMO_ADMIN_PASSWORD)

    create_user(username, password, Role.admin)

    if password == DEMO_ADMIN_PASSWORD:
        warnings.warn(
            f"No users existed, so a demo admin account was created (username='{username}', "
            "password='changeme123'). Set QE_COPILOT_ADMIN_USERNAME/QE_COPILOT_ADMIN_PASSWORD "
            "before deploying anywhere real.",
            stacklevel=2,
        )
