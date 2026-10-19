"""Siigo documents → the internal movement shape.

The mapping is intentionally strict. A movement whose direction cannot be read
is an error, not a skipped row: a reconciliation that silently drops one line of
an entry will disagree with the bank and nobody will know why. Negative values
are refused for the same reason — Siigo expresses direction with `movement`, so
a negative `value` means the contract is not what this adapter was built for.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.integrations.base import LedgerMovement
from app.integrations.siigo.exceptions import SiigoMappingError
from app.integrations.siigo.schemas import SiigoJournal

KNOWN_MOVEMENTS = frozenset({"debit", "credit"})


def to_ledger_movements(
    journal: SiigoJournal, *, account_code: str | None = None
) -> list[LedgerMovement]:
    """One movement per journal item, optionally filtered by account code."""
    movements: list[LedgerMovement] = []

    for index, item in enumerate(journal.items):
        if account_code is not None and item.account.code != account_code:
            continue

        direction = item.account.movement.strip().lower()
        if direction not in KNOWN_MOVEMENTS:
            raise SiigoMappingError(
                f"Journal {journal.id} item {index} has an unknown movement "
                f"{item.account.movement!r}; expected Debit or Credit."
            )

        amount = _minor_units(item.value, journal_id=journal.id, index=index)
        movements.append(
            LedgerMovement(
                external_id=f"{journal.id}:{index}",
                journal_id=journal.id,
                account_code=item.account.code,
                posted_on=journal.date,
                debit_minor=amount if direction == "debit" else 0,
                credit_minor=amount if direction == "credit" else 0,
                description=(item.description or journal.name or "").strip(),
                reference=journal.name,
            )
        )

    return movements


def _minor_units(value: Decimal, *, journal_id: str, index: int) -> int:
    if value < 0:
        raise SiigoMappingError(
            f"Journal {journal_id} item {index} has a negative value ({value}); "
            "direction must come from the movement field."
        )
    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
