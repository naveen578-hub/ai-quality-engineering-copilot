"""
FastAPI dependencies for authentication and role-based access control.

Three roles, least to most privileged:
- viewer: read-only (GET endpoints).
- tester: viewer + generate/upload/save-as-draft actions.
- admin:  tester + approve test cases, delete, manage users.

`require_roles(...)` is the single gate every protected route declares; it
resolves the current user from the bearer token and checks membership in one
call, so a route either has no auth dependency (public: /health, /auth/login)
or exactly one `Depends(require_roles(...))`.
"""
from __future__ import annotations

from typing import Iterable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from backend.auth.security import TokenError, decode_access_token
from backend.auth.users import get_user
from backend.models.schemas import Role, UserOut

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login", auto_error=False)


def get_current_user(token: str | None = Depends(oauth2_scheme)) -> UserOut:
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_access_token(token)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    username = payload.get("sub")
    user = get_user(username) if username else None
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_roles(*allowed: Role):
    allowed_set = set(allowed)

    def _check(user: UserOut = Depends(get_current_user)) -> UserOut:
        if user.role not in allowed_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role.value}' is not permitted to perform this action "
                f"(requires one of: {', '.join(r.value for r in allowed_set)}).",
            )
        return user

    return _check


ANY_ROLE: Iterable[Role] = (Role.viewer, Role.tester, Role.admin)
WRITE_ROLES: Iterable[Role] = (Role.tester, Role.admin)
ADMIN_ONLY: Iterable[Role] = (Role.admin,)
