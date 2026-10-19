"""Imported movements, on both sides of the reconciliation.

Amounts are stored in minor units and always positive; `direction` carries the
sign. A single signed number would force every reader to remember which sign
means "money in" for a bank versus a ledger account, and that is exactly the
kind of convention that gets inverted in one report and not the other.

The fingerprint is a duplicate *signal*, not a unique key. Two legitimate
transactions can share date, amount, reference and description (§8.5); making it
unique would silently discard one of them.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    String,
    Uuid,
)
from sqlalchemy import Enum as SaEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, UuidPrimaryKeyMixin

REFERENCE_MAX_LENGTH = 100
DESCRIPTION_MAX_LENGTH = 500
EXTERNAL_ID_MAX_LENGTH = 100
FINGERPRINT_LENGTH = 64
SOURCE_SYSTEM_MAX_LENGTH = 50


class TransactionDirection(StrEnum):
    """The movement as the source states it, not an interpretation of it."""

    DEBIT = "debit"
    CREDIT = "credit"


DIRECTION_VALUES = tuple(item.value for item in TransactionDirection)
DIRECTIONS_SQL_LIST = ", ".join(f"'{value}'" for value in DIRECTION_VALUES)


def _direction_column() -> Mapped[TransactionDirection]:
    return mapped_column(
        SaEnum(
            TransactionDirection,
            name="transaction_direction",
            native_enum=False,
            create_constraint=False,
            length=10,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )


class BankTransaction(Base, UuidPrimaryKeyMixin, CreatedAtMixin):
    """One line of a bank statement."""

    __tablename__ = "bank_transactions"

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
    import_job_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("import_jobs.id", ondelete="RESTRICT"),
        nullable=False,
    )

    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    direction: Mapped[TransactionDirection] = _direction_column()

    reference: Mapped[str | None] = mapped_column(String(REFERENCE_MAX_LENGTH), nullable=True)
    description: Mapped[str | None] = mapped_column(String(DESCRIPTION_MAX_LENGTH), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(EXTERNAL_ID_MAX_LENGTH), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(FINGERPRINT_LENGTH), nullable=False)

    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="amount_is_positive"),
        CheckConstraint(f"direction IN ({DIRECTIONS_SQL_LIST})", name="direction_is_known"),
        Index(
            "ix_bank_transactions_account_date",
            "organization_id",
            "bank_account_id",
            "transaction_date",
        ),
        Index(
            "ix_bank_transactions_organization_fingerprint",
            "organization_id",
            "fingerprint",
        ),
        Index("ix_bank_transactions_import_job_id", "import_job_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"BankTransaction(id={self.id!r}, date={self.transaction_date!r}, "
            f"amount_minor={self.amount_minor!r}, direction={self.direction.value!r})"
        )


class LedgerTransaction(Base, UuidPrimaryKeyMixin, CreatedAtMixin):
    """One line of an accounting auxiliary export."""

    __tablename__ = "ledger_transactions"

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
    import_job_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("import_jobs.id", ondelete="RESTRICT"),
        nullable=False,
    )

    source_system: Mapped[str] = mapped_column(String(SOURCE_SYSTEM_MAX_LENGTH), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(EXTERNAL_ID_MAX_LENGTH), nullable=True)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    direction: Mapped[TransactionDirection] = _direction_column()

    reference: Mapped[str | None] = mapped_column(String(REFERENCE_MAX_LENGTH), nullable=True)
    description: Mapped[str | None] = mapped_column(String(DESCRIPTION_MAX_LENGTH), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(FINGERPRINT_LENGTH), nullable=False)

    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="amount_is_positive"),
        CheckConstraint(f"direction IN ({DIRECTIONS_SQL_LIST})", name="direction_is_known"),
        Index(
            "ix_ledger_transactions_account_date",
            "organization_id",
            "bank_account_id",
            "transaction_date",
        ),
        Index(
            "ix_ledger_transactions_organization_fingerprint",
            "organization_id",
            "fingerprint",
        ),
        Index("ix_ledger_transactions_import_job_id", "import_job_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"LedgerTransaction(id={self.id!r}, date={self.transaction_date!r}, "
            f"amount_minor={self.amount_minor!r}, direction={self.direction.value!r})"
        )
