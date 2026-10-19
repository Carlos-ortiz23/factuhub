"""One company's stored credentials for one accounting provider.

The row never holds plaintext: `encrypted_credentials` is a Fernet token whose
plaintext is bound to this exact `(organization_id, provider)` pair by
`app.core.crypto.CredentialCipher`. Replacing credentials overwrites the token
and resets the observed status; it never inserts a second row that could
disagree with the first.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy import Enum as SaEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, UuidPrimaryKeyMixin

PROVIDER_MAX_LENGTH = 50
MODE_MAX_LENGTH = 20
STATUS_MAX_LENGTH = 20
LAST_ERROR_MAX_LENGTH = 500


class ProviderConnectionStatus(StrEnum):
    """What the last real check observed, not what we hope is true."""

    UNTESTED = "untested"
    CONNECTED = "connected"
    ERROR = "error"


STATUS_VALUES: tuple[str, ...] = tuple(status.value for status in ProviderConnectionStatus)
STATUSES_SQL_LIST = ", ".join(f"'{value}'" for value in STATUS_VALUES)

MODE_VALUES: tuple[str, ...] = ("api", "file_import")
MODES_SQL_LIST = ", ".join(f"'{value}'" for value in MODE_VALUES)


class ProviderCredential(Base, UuidPrimaryKeyMixin, CreatedAtMixin):
    """The encrypted credentials and the last observed connection status."""

    __tablename__ = "provider_credentials"

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(String(PROVIDER_MAX_LENGTH), nullable=False)
    mode: Mapped[str] = mapped_column(String(MODE_MAX_LENGTH), nullable=False, server_default="api")

    #: Fernet token. Never selected by list endpoints in a way that could reach
    #: a response; the service is the only reader.
    encrypted_credentials: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    status: Mapped[ProviderConnectionStatus] = mapped_column(
        SaEnum(
            ProviderConnectionStatus,
            name="provider_connection_status",
            native_enum=False,
            create_constraint=False,
            length=STATUS_MAX_LENGTH,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        server_default=ProviderConnectionStatus.UNTESTED.value,
    )

    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Sanitized reason, safe to show to the company. Never a credential.
    last_error: Mapped[str | None] = mapped_column(String(LAST_ERROR_MAX_LENGTH), nullable=True)

    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "provider",
            "mode",
            name="uq_provider_credentials_connection",
        ),
        CheckConstraint(f"status IN ({STATUSES_SQL_LIST})", name="status_is_known"),
        CheckConstraint(f"mode IN ({MODES_SQL_LIST})", name="mode_is_known"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"ProviderCredential(organization_id={self.organization_id!r}, "
            f"provider={self.provider!r}, status={self.status.value!r})"
        )
