"""Shared FastAPI dependencies."""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.cookies import CSRF_HEADER_NAME, csrf_cookie_name
from app.core.config import Settings
from app.db.session import get_session_factory
from app.models import User, UserSession
from app.services import auth as auth_service

#: Methods that do not change state and therefore do not need a CSRF token.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def get_db_session() -> Iterator[Session]:
    """Yield a database session for one request, always closing it afterwards.

    The session is not committed here: a request handler decides whether it
    completes a unit of work, so a failed handler can never leave a half-applied
    financial mutation behind.
    """
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def get_app_settings(request: Request) -> Settings:
    """Return the settings attached to the running application.

    Read from `app.state` instead of the module-level cache so a test or a
    factory-built app can be configured without touching the environment.
    """
    return request.app.state.settings


@dataclass(frozen=True, slots=True)
class AuthContext:
    """The authenticated user and the session that vouched for them."""

    user: User
    session: UserSession


def get_auth_context(
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> AuthContext:
    """Resolve the session cookie into an authenticated user.

    A missing, expired, revoked or orphaned session is the same 401: the client
    learns nothing about which of those it was.
    """
    token = request.cookies.get(settings.session_cookie_name)
    context = auth_service.resolve_session_context(db, token=token) if token else None
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    user, session_row = context
    return AuthContext(user=user, session=session_row)


def require_csrf(
    request: Request,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> None:
    """Reject a state-changing request that does not prove it can read the cookie.

    Three values must agree: the header, the cookie, and the token stored with
    the session. Comparing against the stored value is what makes an injected
    cookie from a sibling domain useless.
    """
    if request.method in SAFE_METHODS:
        return

    header_value = request.headers.get(CSRF_HEADER_NAME)
    cookie_value = request.cookies.get(csrf_cookie_name(settings))
    expected = context.session.csrf_token

    # Compared as bytes: `compare_digest` on str refuses non-ASCII input, and a
    # malformed header must be a 403, not a 500.
    header_matches = bool(header_value) and secrets.compare_digest(
        header_value.encode("utf-8"), expected.encode("utf-8")
    )
    cookie_matches = bool(cookie_value) and secrets.compare_digest(
        cookie_value.encode("utf-8"), expected.encode("utf-8")
    )

    if not (header_matches and cookie_matches):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token missing or invalid.",
        )
