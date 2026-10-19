"""A bank account whose statements and ledger movements are reconciled.

`connection_id` is nullable on purpose: importing a file is a first-class way of
working, and most companies start there before they connect an accounting
provider. Requiring a provider connection would lock them out of the product.

The number is stored masked. The full account number is not needed to reconcile
and is one more piece of financial data that does not have to exist in the
database (§7.4).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, UuidPrimaryKeyMixin

NAME_MAX_LENGTH = 120
MASKED_NUMBER_MAX_LENGTH = 32
CURRENCY_LENGTH = 3
LEDGER_CODE_MAX_LENGTH = 32
EXTERNAL_ID_MAX_LENGTH = 100


class BankAccount(Base, UuidPrimaryKeyMixin, CreatedAtMixin):
    """One company's bank account."""

    __tablename__ = "bank_accounts"

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: The provider connection this account came from, when it exists.
    connection_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("provider_credentials.id", ondelete="SET NULL"),
        nullable=True,
    )

    account_name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH), nullable=False)
    account_number_masked: Mapped[str | None] = mapped_column(
        String(MASKED_NUMBER_MAX_LENGTH), nullable=True
    )
    currency: Mapped[str] = mapped_column(
        String(CURRENCY_LENGTH), nullable=False, server_default="COP"
    )

    #: The accounting account that mirrors this bank account (for example 1110).
    #: The engine uses it to know which ledger movements belong here.
    ledger_account_code: Mapped[str | None] = mapped_column(
        String(LEDGER_CODE_MAX_LENGTH), nullable=True
    )
    external_account_id: Mapped[str | None] = mapped_column(
        String(EXTERNAL_ID_MAX_LENGTH), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    __table_args__ = (CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_is_iso_shape"),)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"BankAccount(organization_id={self.organization_id!r}, name={self.account_name!r})"
