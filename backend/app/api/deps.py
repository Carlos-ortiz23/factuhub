"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from app.db.session import get_session_factory


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
