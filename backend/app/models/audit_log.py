"""Append-only audit trail."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, desc, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

ACTION_MAX_LENGTH = 100
ENTITY_TYPE_MAX_LENGTH = 100

#: Column name in the database. The attribute cannot be called `metadata`
#: because that name belongs to SQLAlchemy's declarative `MetaData`.
METADATA_COLUMN_NAME = "metadata"


class AuditLog(Base):
    """One recorded decision.

    Rows are immutable: a database trigger rejects `UPDATE` and `DELETE`, because
    "el historial no debe modificarse silenciosamente" (spec §7.11) cannot rely on
    every future contributor remembering not to write one.
    """

    __tablename__ = "audit_logs"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )

    # Deliberately RESTRICT, not CASCADE: deleting a company must not be able to
    # silently erase the evidence of what happened in it.
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # Nullable for actions performed by the system rather than by a person.
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    action: Mapped[str] = mapped_column(String(ACTION_MAX_LENGTH), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(ENTITY_TYPE_MAX_LENGTH), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)

    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        METADATA_COLUMN_NAME,
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        # The two queries this table exists for: "history of a company, newest
        # first" and "what happened to this specific record".
        Index(
            "ix_audit_logs_organization_id_created_at",
            "organization_id",
            desc("created_at"),
        ),
        Index("ix_audit_logs_entity_type_entity_id", "entity_type", "entity_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"AuditLog(id={self.id!r}, action={self.action!r})"
