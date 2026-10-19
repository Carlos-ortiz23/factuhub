"""Application configuration.

Configuration is read once and validated eagerly: a misconfigured deployment
must fail at startup, not on the first request that happens to need a secret.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# backend/app/core/config.py -> repository root
REPO_ROOT = Path(__file__).resolve().parents[3]

#: Placeholder shipped in `env.example`. Rejected outright in production.
PLACEHOLDER_SECRET = "change-me-run-openssl-rand-hex-32"

#: Minimum length for the application secret.
MIN_SECRET_LENGTH = 32

#: The engine talks to PostgreSQL through the synchronous psycopg 3 driver.
REQUIRED_DATABASE_SCHEME = "postgresql+psycopg"

Environment = Literal["development", "test", "production"]


class Settings(BaseSettings):
    """Validated application settings."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Environment = "development"
    app_debug: bool = False
    app_secret_key: SecretStr
    app_allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1"]
    )

    database_url: str
    test_database_url: str | None = None

    next_public_api_base_url: str = "http://localhost:8000"

    #: How long an issued session stays valid. One working day plus margin: an
    #: accountant reconciling a month-end close must not be signed out mid-task,
    #: and a stolen token must not stay useful indefinitely.
    session_ttl_hours: Annotated[int, Field(ge=1, le=720)] = 12

    #: Cookie name for the session token. Prefixed so it cannot be confused with
    #: a session cookie from another application on the same host.
    session_cookie_name: str = "factuhub_session"

    #: `None` means "decide from the environment": Secure everywhere except
    #: plain-HTTP local development, where a Secure cookie would simply never be
    #: sent and the bug would look like a broken login. Set explicitly to
    #: override.
    session_cookie_secure: bool | None = None

    world_office_base_url: str = "https://api.worldoffice.cloud"
    world_office_token: SecretStr | None = None
    world_office_company_id: str | None = None
    world_office_timeout_seconds: float = 30.0
    world_office_max_retries: int = 3

    local_storage_path: Path = Path("backend/var/storage")

    @field_validator("app_allowed_hosts", mode="before")
    @classmethod
    def _split_allowed_hosts(cls, value: object) -> object:
        """Accept both a real list and the comma-separated environment form."""
        if isinstance(value, str):
            return [host.strip() for host in value.split(",") if host.strip()]
        return value

    @field_validator("database_url", "test_database_url")
    @classmethod
    def _require_psycopg_driver(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(f"{REQUIRED_DATABASE_SCHEME}://"):
            raise ValueError(
                f"database URL must start with '{REQUIRED_DATABASE_SCHEME}://'; "
                "a bare 'postgresql://' URL would silently select a different driver"
            )
        return value

    @field_validator("app_secret_key")
    @classmethod
    def _require_long_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < MIN_SECRET_LENGTH:
            raise ValueError(f"APP_SECRET_KEY must be at least {MIN_SECRET_LENGTH} characters long")
        return value

    @model_validator(mode="after")
    def _reject_placeholder_secret_in_production(self) -> Settings:
        if (
            self.app_env == "production"
            and self.app_secret_key.get_secret_value() == PLACEHOLDER_SECRET
        ):
            raise ValueError("APP_SECRET_KEY still holds the template placeholder value")
        return self

    @property
    def session_cookie_is_secure(self) -> bool:
        """Whether the session cookie must carry the `Secure` flag.

        Deriving it from the environment by default means production cannot be
        shipped with a cookie that travels over plain HTTP just because nobody
        remembered to flip a flag.
        """
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.app_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
