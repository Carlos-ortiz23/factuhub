"""The provider-agnostic contract every accounting connector implements.

Specification §5.3 proposes this protocol and then says the methods "deben
implementarse de acuerdo con las capacidades reales" of each provider. That
sentence is the design: the protocol is the shape, and every adapter declares
what it can actually do instead of pretending all providers are identical.

Money crosses this boundary as integer minor units (cents). External APIs send
decimals, and comparing floats is how two reconciliation runs over the same data
start disagreeing with each other.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable


class CapabilityNotSupported(Exception):
    """The provider's public API does not expose this operation.

    Raised instead of returning an empty list, because "there are no bank
    accounts" and "we cannot ask for bank accounts" are different facts and only
    one of them is true.
    """


@dataclass(frozen=True, slots=True)
class LedgerMovement:
    """One line of an accounting entry, normalized.

    `external_id` is stable across synchronizations: a journal's id plus the
    item's position. Retrying a sync must update a movement, not duplicate it.
    """

    external_id: str
    journal_id: str
    account_code: str
    posted_on: date
    debit_minor: int
    credit_minor: int
    description: str
    reference: str | None = None


@dataclass(frozen=True, slots=True)
class ConnectorCapabilities:
    """What an adapter can really do, stated in one place."""

    ledger_transactions: bool
    bank_accounts: bool
    notes: str = ""


@dataclass(frozen=True, slots=True)
class ConnectionCheck:
    """The observed result of a connection test.

    A plain `bool` would force the interface to say "it failed" without saying
    why. `error` is already sanitized by the adapter and is safe to store and to
    show to the company.
    """

    ok: bool
    error: str | None = None


@runtime_checkable
class AccountingConnector(Protocol):
    """The operations the reconciliation engine needs from any provider."""

    capabilities: ConnectorCapabilities

    async def test_connection(self) -> ConnectionCheck:
        """Whether the stored credentials can reach the provider right now."""
        ...

    async def list_bank_accounts(self) -> list[dict]:
        """The provider's bank accounts, if it exposes them at all."""
        ...

    async def fetch_ledger_transactions(
        self,
        account_id: str,
        start_date: date,
        end_date: date,
    ) -> list[LedgerMovement]:
        """Ledger lines for one account code in an inclusive date range."""
        ...
