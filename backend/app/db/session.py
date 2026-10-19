"""Database engine and session factory.

The engine is created lazily so that importing the application never requires a
reachable database, and so that tests can point the layer at an isolated
instance without reloading modules.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache(maxsize=4)
def get_engine(database_url: str | None = None) -> Engine:
    """Return a process-wide engine for the given URL (settings default)."""
    url = database_url or get_settings().database_url
    return create_engine(url, pool_pre_ping=True, future=True)


@lru_cache(maxsize=4)
def get_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    """Return a session factory bound to the given URL."""
    return sessionmaker(
        bind=get_engine(database_url),
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )


@contextmanager
def session_scope(database_url: str | None = None) -> Iterator[Session]:
    """Run a unit of work inside a transaction, rolling back on failure."""
    session = get_session_factory(database_url)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
