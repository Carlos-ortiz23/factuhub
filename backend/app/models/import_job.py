"""One upload: what was read, what was imported, and what failed.

The row is created before parsing starts. A failed import that leaves no trace
is impossible to support ("why did my file do nothing?") and impossible to
retry. The original file is kept in private storage, so retry does not need the
client to send it again.

`request_sha256` covers the file hash plus the mapping and options. The same
bytes interpreted differently (a corrected decimal separator, for instance) are
a new, legitimate import; the same bytes with the same interpretation are a
duplicate and are refused before doing any work.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    desc,
    text,
)
from sqlalchemy import Enum as SaEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, UuidPrimaryKeyMixin

FILE_NAME_MAX_LENGTH = 255
HASH_LENGTH = 64
STORAGE_KEY_MAX_LENGTH = 255
CONTENT_TYPE_MAX_LENGTH = 120
ERROR_SUMMARY_MAX_LENGTH = 1000


class ImportSourceType(StrEnum):
    """What the file contains, which decides where its rows go."""

    BANK_STATEMENT = "bank_statement"
    LEDGER_EXPORT = "ledger_export"
    API_SYNC = "api_sync"


class ImportStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


SOURCE_VALUES = tuple(item.value for item in ImportSourceType)
STATUS_VALUES = tuple(item.value for item in ImportStatus)
SOURCES_SQL_LIST = ", ".join(f"'{value}'" for value in SOURCE_VALUES)
STATUSES_SQL_LIST = ", ".join(f"'{value}'" for value in STATUS_VALUES)


class ImportJob(Base, UuidPrimaryKeyMixin, CreatedAtMixin):
    """The audit trail of one file ingestion."""

    __tablename__ = "import_jobs"

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    bank_account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("bank_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_type: Mapped[ImportSourceType] = mapped_column(
        SaEnum(
            ImportSourceType,
            name="import_source_type",
            native_enum=False,
            create_constraint=False,
            length=32,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )

    file_name: Mapped[str] = mapped_column(String(FILE_NAME_MAX_LENGTH), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(HASH_LENGTH), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(HASH_LENGTH), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(STORAGE_KEY_MAX_LENGTH), nullable=False)
    content_type: Mapped[str] = mapped_column(String(CONTENT_TYPE_MAX_LENGTH), nullable=False)

    status: Mapped[ImportStatus] = mapped_column(
        SaEnum(
            ImportStatus,
            name="import_status",
            native_enum=False,
            create_constraint=False,
            length=20,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        server_default=ImportStatus.PENDING.value,
    )

    rows_read: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    rows_imported: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_summary: Mapped[str | None] = mapped_column(
        String(ERROR_SUMMARY_MAX_LENGTH), nullable=True
    )

    #: Stored so a retry uses exactly the interpretation the client asked for.
    mapping_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    options_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "bank_account_id",
            "source_type",
            "file_sha256",
            "request_sha256",
            name="uq_import_jobs_request",
        ),
        CheckConstraint(f"source_type IN ({SOURCES_SQL_LIST})", name="source_is_known"),
        CheckConstraint(f"status IN ({STATUSES_SQL_LIST})", name="status_is_known"),
        CheckConstraint("rows_read >= 0", name="rows_read_is_not_negative"),
        CheckConstraint("rows_imported >= 0", name="rows_imported_is_not_negative"),
        Index(
            "ix_import_jobs_organization_id_created_at",
            "organization_id",
            desc("created_at"),
        ),
        Index("ix_import_jobs_bank_account_id", "bank_account_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"ImportJob(id={self.id!r}, file_name={self.file_name!r}, status={self.status.value!r})"
        )
