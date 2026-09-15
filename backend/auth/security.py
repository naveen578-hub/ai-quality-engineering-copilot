"""
Password hashing and JWT issuance/verification.

SECRET_KEY must be overridden via env in any real deployment — the default
here is explicitly a dev-only placeholder and the app logs a warning if it's
still in use. Tokens are short-lived (default 60 min) since this is a
demo-scale app with no refresh-token flow; re-login is cheap.
"""
from __future__ import annotations

import os
import warnings
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import bcrypt
import jwt

DEV_DEFAULT_SECRET = "insecure-dev-only-secret-change-me"
SECRET_KEY = os.getenv("QE_COPILOT_JWT_SECRET", DEV_DEFAULT_SECRET)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("QE_COPILOT_TOKEN_EXPIRE_MINUTES", "60"))

if SECRET_KEY == DEV_DEFAULT_SECRET:
    warnings.warn(
        "QE_COPILOT_JWT_SECRET is not set — using an insecure default signing key. "
        "This is fine for local demo use only; set a real secret before deploying.",
        stacklevel=2,
    )


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Malformed hash (e.g. from a corrupted row) — treat as non-matching, not a crash.
        return False


def create_access_token(subject: str, role: str, expires_minutes: Optional[int] = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes or ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


class TokenError(ValueError):
    pass


def decode_access_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Invalid token") from exc
