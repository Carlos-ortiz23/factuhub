"""Period balances and the difference that is actually unexplained.

The figures are deliberately separate. `statement_difference_minor` compares the
imported bank rows against the closing balance the statement declares; it catches
a file that is missing rows. `unexplained_difference_minor` compares the
statement against the ledger adjusted by the pending items. Either one being zero
does not prove the period is reconciled, so `balanced` requires both to be zero
and no pending movement to remain (§8.6).

The adjustment convention is `bank_to_ledger`: pending bank movements would be
posted to the ledger, and pending ledger movements not on the statement are
removed from it. It is an explicit convention, not a universal accounting truth,
and it must be validated with an accountant before production use.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.reconciliation.normalizer import economic_direction
from app.reconciliation.types import EconomicDirection, Movement

SUPPORTED_CONVENTIONS = frozenset({"bank_to_ledger"})


@dataclass(frozen=True, slots=True)
class PeriodBalances:
    opening_balance_minor: int
    bank_inflow_minor: int
    bank_outflow_minor: int
    bank_computed_closing_minor: int
    statement_closing_balance_minor: int
    statement_difference_minor: int
    ledger_closing_balance_minor: int
    matched_bank_count: int
    matched_ledger_count: int
    matched_bank_minor: int
    pending_bank_count: int
    pending_ledger_count: int
    pending_bank_net_minor: int
    pending_ledger_net_minor: int
    adjusted_ledger_balance_minor: int
    unexplained_difference_minor: int
    progress_ratio: float
    balanced: bool
    convention: str


def compute_period_balances(
    bank_movements: list[Movement],
    ledger_movements: list[Movement],
    *,
    opening_balance_minor: int,
    statement_closing_balance_minor: int,
    ledger_closing_balance_minor: int,
    confirmed_bank_ids: set[UUID],
    confirmed_ledger_ids: set[UUID],
    convention: str = "bank_to_ledger",
) -> PeriodBalances:
    """Compute the period's figures from the movements and confirmed matches."""
    if convention not in SUPPORTED_CONVENTIONS:
        raise ValueError(f"unsupported reconciliation convention: {convention}")

    bank_inflow = sum(
        movement.amount_minor
        for movement in bank_movements
        if economic_direction(movement.side, movement.direction) is EconomicDirection.INFLOW
    )
    bank_outflow = sum(
        movement.amount_minor
        for movement in bank_movements
        if economic_direction(movement.side, movement.direction) is EconomicDirection.OUTFLOW
    )
    bank_computed = opening_balance_minor + bank_inflow - bank_outflow
    statement_difference = statement_closing_balance_minor - bank_computed

    pending_bank = [
        movement for movement in bank_movements if movement.id not in confirmed_bank_ids
    ]
    pending_ledger = [
        movement for movement in ledger_movements if movement.id not in confirmed_ledger_ids
    ]
    pending_bank_net = _net(pending_bank)
    pending_ledger_net = _net(pending_ledger)

    adjusted_ledger = ledger_closing_balance_minor + pending_bank_net - pending_ledger_net
    unexplained = statement_closing_balance_minor - adjusted_ledger

    matched_bank = [movement for movement in bank_movements if movement.id in confirmed_bank_ids]
    matched_ledger = [
        movement for movement in ledger_movements if movement.id in confirmed_ledger_ids
    ]

    total_bank = len(bank_movements)
    progress = len(matched_bank) / total_bank if total_bank else 0.0
    balanced = (
        statement_difference == 0 and unexplained == 0 and not pending_bank and not pending_ledger
    )

    return PeriodBalances(
        opening_balance_minor=opening_balance_minor,
        bank_inflow_minor=bank_inflow,
        bank_outflow_minor=bank_outflow,
        bank_computed_closing_minor=bank_computed,
        statement_closing_balance_minor=statement_closing_balance_minor,
        statement_difference_minor=statement_difference,
        ledger_closing_balance_minor=ledger_closing_balance_minor,
        matched_bank_count=len(matched_bank),
        matched_ledger_count=len(matched_ledger),
        matched_bank_minor=sum(movement.amount_minor for movement in matched_bank),
        pending_bank_count=len(pending_bank),
        pending_ledger_count=len(pending_ledger),
        pending_bank_net_minor=pending_bank_net,
        pending_ledger_net_minor=pending_ledger_net,
        adjusted_ledger_balance_minor=adjusted_ledger,
        unexplained_difference_minor=unexplained,
        progress_ratio=progress,
        balanced=balanced,
        convention=convention,
    )


def _net(movements: list[Movement]) -> int:
    total = 0
    for movement in movements:
        direction = economic_direction(movement.side, movement.direction)
        total += (
            movement.amount_minor
            if direction is EconomicDirection.INFLOW
            else -movement.amount_minor
        )
    return total
