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


def test_session_cookie_is_secure_in_production_and_not_in_development() -> None:
    # Derived from the environment on purpose: shipping production with a cookie
    # that travels over plain HTTP must not depend on somebody remembering a
    # flag in a deployment file.
    assert build_settings(app_env="production").session_cookie_is_secure is True
    assert build_settings(app_env="development").session_cookie_is_secure is False


def test_an_explicit_cookie_secure_setting_wins_over_the_environment() -> None:
    assert build_settings(
        app_env="development", session_cookie_secure=True
    ).session_cookie_is_secure
    assert not build_settings(
        app_env="production", session_cookie_secure=False
    ).session_cookie_is_secure


@pytest.mark.parametrize("ttl", [0, 721])
def test_the_session_lifetime_must_stay_within_sane_bounds(ttl: int) -> None:
    with pytest.raises(ValidationError):
        build_settings(session_ttl_hours=ttl)


def test_the_session_lifetime_defaults_to_one_working_day() -> None:
    assert build_settings().session_ttl_hours == 12
