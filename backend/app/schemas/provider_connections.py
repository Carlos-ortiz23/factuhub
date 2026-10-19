"""Contracts for a company's provider connections.

The request carries credentials; the response never does. Keeping them in
separate models is the simplest way to make that asymmetry impossible to forget:
there is no field in `ProviderConnectionResponse` capable of holding a secret.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models import ProviderConnectionStatus

#: Matching the service's limits so a huge payload is refused before it reaches
#: encryption.
MAX_CREDENTIAL_LENGTH = 512
MAX_FIELD_NAME_LENGTH = 50
MAX_CREDENTIAL_FIELDS = 10


class ConnectionCredentialsRequest(BaseModel):
    """The provider's documented credential fields, nothing else."""

    credentials: dict[str, str] = Field(min_length=1, max_length=MAX_CREDENTIAL_FIELDS)

    @field_validator("credentials")
    @classmethod
    def _bounded_fields(cls, value: dict[str, str]) -> dict[str, str]:
        for name, secret in value.items():
            if not name or len(name) > MAX_FIELD_NAME_LENGTH:
                raise ValueError("credential field names must be 1-50 characters")
            if len(secret) > MAX_CREDENTIAL_LENGTH:
                raise ValueError(
                    f"credential field '{name}' exceeds {MAX_CREDENTIAL_LENGTH} characters"
                )
        return value


class ProviderConnectionResponse(BaseModel):
    """What the company may see about its own connection."""

    provider: str
    provider_name: str
    mode: str
    status: ProviderConnectionStatus
    last_checked_at: datetime | None = None
    last_error: str | None = None


class ProviderConnectionListResponse(BaseModel):
    connections: list[ProviderConnectionResponse]
