"""Reconciliation periods, the matches investigated inside them, and their items.

A period freezes a date range for one bank account. Matches are suggestions
until a human confirms them; the database enforces the shape, and the service
enforces the harder rule that a movement cannot be confirmed twice.

`reconciliation_period_transactions` is the explicit link the specification asks
for (§7.9). The polymorphic `transaction_id` cannot carry a foreign key because
it points at one of two tables; the service validates the pair instead.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy import Enum as SaEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, UuidPrimaryKeyMixin

PERIOD_NAME_MAX_LENGTH = 120
EXPLANATION_MAX_LENGTH = 4000


class PeriodStatus(StrEnum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REOPENED = "reopened"


class MatchType(StrEnum):
    EXACT = "exact"
    APPROXIMATE = "approximate"
    GROUPED = "grouped"
    MANUAL = "manual"


class MatchStatus(StrEnum):
    SUGGESTED = "suggested"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class PeriodTransactionType(StrEnum):
    BANK = "bank"
    LEDGER = "ledger"


PERIOD_STATUS_VALUES = tuple(item.value for item in PeriodStatus)
MATCH_TYPE_VALUES = tuple(item.value for item in MatchType)
MATCH_STATUS_VALUES = tuple(item.value for item in MatchStatus)
PERIOD_TRANSACTION_TYPE_VALUES = tuple(item.value for item in PeriodTransactionType)

PERIOD_STATUS_SQL = ", ".join(f"'{value}'" for value in PERIOD_STATUS_VALUES)
MATCH_TYPE_SQL = ", ".join(f"'{value}'" for value in MATCH_TYPE_VALUES)
MATCH_STATUS_SQL = ", ".join(f"'{value}'" for value in MATCH_STATUS_VALUES)
PERIOD_TRANSACTION_TYPE_SQL = ", ".join(f"'{value}'" for value in PERIOD_TRANSACTION_TYPE_VALUES)


def _enum_column(enum_cls: type[StrEnum], name: str, length: int):
    return SaEnum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=False,
        length=length,
        validate_strings=True,
        values_callable=lambda cls: [member.value for member in cls],
    )


class ReconciliationPeriod(Base, UuidPrimaryKeyMixin, CreatedAtMixin):
    """One bank account's reconciliation window."""

    __tablename__ = "reconciliation_periods"

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
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    opening_balance_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bank_closing_balance_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ledger_closing_balance_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[PeriodStatus] = mapped_column(
        _enum_column(PeriodStatus, "reconciliation_period_status", 20),
        nullable=False,
        server_default=PeriodStatus.OPEN.value,
    )
    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    approved_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "bank_account_id",
            "period_start",
            "period_end",
            name="uq_reconciliation_periods_window",
        ),
        CheckConstraint("period_start <= period_end", name="period_window_is_ordered"),
        CheckConstraint(f"status IN ({PERIOD_STATUS_SQL})", name="status_is_known"),
        Index(
            "ix_reconciliation_periods_organization_id",
            "organization_id",
            "bank_account_id",
            "period_start",
        ),
    )


class ReconciliationPeriodTransaction(Base, UuidPrimaryKeyMixin, CreatedAtMixin):
    """The explicit period-movement association required by §7.9."""

    __tablename__ = "reconciliation_period_transactions"

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    period_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("reconciliation_periods.id", ondelete="CASCADE"),
        nullable=False,
    )
    transaction_type: Mapped[PeriodTransactionType] = mapped_column(
        _enum_column(PeriodTransactionType, "period_transaction_type", 12),
        nullable=False,
    )
    transaction_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "period_id",
            "transaction_type",
            "transaction_id",
            name="uq_period_transactions_member",
        ),
        CheckConstraint(
            f"transaction_type IN ({PERIOD_TRANSACTION_TYPE_SQL})",
            name="transaction_type_is_known",
        ),
        Index(
            "ix_period_transactions_movement",
            "transaction_type",
            "transaction_id",
        ),
    )


class ReconciliationMatch(Base, UuidPrimaryKeyMixin, CreatedAtMixin):
    """One suggested, confirmed, rejected or cancelled reconciliation."""

    __tablename__ = "reconciliation_matches"

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    period_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("reconciliation_periods.id", ondelete="CASCADE"),
        nullable=False,
    )
    match_type: Mapped[MatchType] = mapped_column(
        _enum_column(MatchType, "reconciliation_match_type", 20), nullable=False
    )
    score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    status: Mapped[MatchStatus] = mapped_column(
        _enum_column(MatchStatus, "reconciliation_match_status", 20),
        nullable=False,
        server_default=MatchStatus.SUGGESTED.value,
    )
    reviewed_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # True when a confirmation was undone. The movements become available again
    # and the combination may be suggested afresh; a rejected suggestion stays
    # rejected. The flag keeps those two cancellations distinguishable.
    released: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    explanation_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        CheckConstraint(f"match_type IN ({MATCH_TYPE_SQL})", name="match_type_is_known"),
        CheckConstraint(f"status IN ({MATCH_STATUS_SQL})", name="status_is_known"),
        CheckConstraint("score >= 0 AND score <= 1", name="score_is_a_fraction"),
        Index("ix_reconciliation_matches_period_status", "period_id", "status"),
    )


class ReconciliationMatchItem(Base, UuidPrimaryKeyMixin, CreatedAtMixin):
    """One side of a match. Exactly one of the two movement columns is set."""

    __tablename__ = "reconciliation_match_items"

    match_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("reconciliation_matches.id", ondelete="CASCADE"),
        nullable=False,
    )
    bank_transaction_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("bank_transactions.id", ondelete="CASCADE"),
        nullable=True,
    )
    ledger_transaction_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ledger_transactions.id", ondelete="CASCADE"),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "(bank_transaction_id IS NOT NULL) <> (ledger_transaction_id IS NOT NULL)",
            name="item_has_exactly_one_movement",
        ),
        UniqueConstraint("match_id", "bank_transaction_id", name="uq_match_items_bank_movement"),
        UniqueConstraint(
            "match_id", "ledger_transaction_id", name="uq_match_items_ledger_movement"
        ),
        Index("ix_match_items_bank_transaction", "bank_transaction_id"),
        Index("ix_match_items_ledger_transaction", "ledger_transaction_id"),
    )
