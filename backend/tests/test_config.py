"""Test suite for application settings.

These tests pin the configuration contract that the security section of the
specification depends on: secrets must never silently keep their placeholder
value in production, and the database URL must use the synchronous psycopg
driver that the SQLAlchemy engine expects.
"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings

VALID_SECRET = "a" * 64
VALID_DATABASE_URL = "postgresql+psycopg://user:pass@localhost:5432/db"


def build_settings(**overrides: object) -> Settings:
    """Build settings from explicit values, ignoring any local `.env` file."""
    values: dict[str, object] = {
        "app_secret_key": VALID_SECRET,
        "database_url": VALID_DATABASE_URL,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_defaults_to_development_environment() -> None:
    settings = build_settings()

    assert settings.app_env == "development"
    assert settings.app_debug is False


def test_allowed_hosts_accepts_comma_separated_env_value() -> None:
    settings = build_settings(app_allowed_hosts="localhost,127.0.0.1,api.example.com")

    assert settings.app_allowed_hosts == ["localhost", "127.0.0.1", "api.example.com"]


def test_database_url_must_use_psycopg_driver() -> None:
    with pytest.raises(ValidationError):
        build_settings(database_url="postgresql://user:pass@localhost:5432/db")


def test_placeholder_secret_is_rejected_in_production() -> None:
    with pytest.raises(ValidationError):
        build_settings(app_env="production", app_secret_key="change-me-run-openssl-rand-hex-32")


def test_short_secret_is_rejected() -> None:
    with pytest.raises(ValidationError):
        build_settings(app_secret_key="too-short")
