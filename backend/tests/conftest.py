"""Shared test fixtures.

The suite is hermetic by construction: unit tests need nothing, and tests that
touch PostgreSQL use the isolated test instance and are rolled back per test, so
no test can observe another test's rows. They skip with an explicit reason when
`TEST_DATABASE_URL` is not configured instead of failing misleadingly.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Return the isolated test database URL, or skip the test."""
    url = get_settings().test_database_url
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured; skipping database test")
    return url


@pytest.fixture(scope="session")
def migrated_test_database(test_database_url: str) -> str:
    """Bring the test database up to the latest migration, once per session."""
    previous = os.environ.get("ALEMBIC_DATABASE_URL")
    os.environ["ALEMBIC_DATABASE_URL"] = test_database_url
    try:
        config = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("ALEMBIC_DATABASE_URL", None)
        else:
            os.environ["ALEMBIC_DATABASE_URL"] = previous
    return test_database_url


@pytest.fixture(scope="session")
def db_engine(migrated_test_database: str) -> Iterator[Engine]:
    engine = create_engine(migrated_test_database, pool_pre_ping=True, future=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """A session inside a transaction that is always rolled back.

    `join_transaction_mode="create_savepoint"` lets a test that deliberately
    triggers a database error (an append-only violation, a check constraint)
    recover, and still leave the database exactly as it was.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
