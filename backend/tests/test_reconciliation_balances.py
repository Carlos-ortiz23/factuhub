"""Balances: the difference a zero does not explain."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.models import TransactionDirection
from app.reconciliation.balances import compute_period_balances
from app.reconciliation.types import Movement, MovementSide


def bank(amount: int, direction: TransactionDirection = TransactionDirection.CREDIT) -> Movement:
    return Movement(
        id=uuid4(),
        side=MovementSide.BANK,
        transaction_date=date(2026, 2, 1),
        amount_minor=amount,
        direction=direction,
    )


def ledger(amount: int, direction: TransactionDirection = TransactionDirection.DEBIT) -> Movement:
    return Movement(
        id=uuid4(),
        side=MovementSide.LEDGER,
        transaction_date=date(2026, 2, 1),
        amount_minor=amount,
        direction=direction,
    )


def test_a_fully_matched_period_is_balanced() -> None:
    bank_row = bank(100_000)
    ledger_row = ledger(100_000)

    balances = compute_period_balances(
        [bank_row],
        [ledger_row],
        opening_balance_minor=1_000_000,
        statement_closing_balance_minor=1_100_000,
        ledger_closing_balance_minor=1_100_000,
        confirmed_bank_ids={bank_row.id},
        confirmed_ledger_ids={ledger_row.id},
    )

    assert balances.bank_computed_closing_minor == 1_100_000
    assert balances.statement_difference_minor == 0
    assert balances.unexplained_difference_minor == 0
    assert balances.progress_ratio == 1.0
    assert balances.balanced is True


def test_a_pending_bank_movement_explains_the_ledger_gap() -> None:
    balances = compute_period_balances(
        [bank(100_000)],
        [],
        opening_balance_minor=1_000_000,
        statement_closing_balance_minor=1_100_000,
        ledger_closing_balance_minor=1_000_000,
        confirmed_bank_ids=set(),
        confirmed_ledger_ids=set(),
    )

    assert balances.adjusted_ledger_balance_minor == 1_100_000
    assert balances.unexplained_difference_minor == 0
    assert balances.pending_bank_count == 1
    assert balances.balanced is False


def test_a_pending_ledger_movement_is_removed_from_the_adjustment() -> None:
    balances = compute_period_balances(
        [],
        [ledger(100_000)],
        opening_balance_minor=1_000_000,
        statement_closing_balance_minor=1_000_000,
        ledger_closing_balance_minor=1_100_000,
        confirmed_bank_ids=set(),
        confirmed_ledger_ids=set(),
    )

    assert balances.adjusted_ledger_balance_minor == 1_000_000
    assert balances.unexplained_difference_minor == 0
    assert balances.pending_ledger_count == 1
    assert balances.balanced is False


def test_a_missing_bank_row_is_reported_even_when_the_net_difference_is_zero() -> None:
    imported = bank(50_000)

    balances = compute_period_balances(
        [imported],
        [],
        opening_balance_minor=1_000_000,
        statement_closing_balance_minor=1_100_000,
        ledger_closing_balance_minor=1_100_000,
        confirmed_bank_ids={imported.id},
        confirmed_ledger_ids=set(),
    )

    assert balances.statement_difference_minor == 50_000
    assert balances.unexplained_difference_minor == 0
    assert balances.balanced is False


def test_a_bank_outflow_reduces_the_computed_closing_balance() -> None:
    bank_row = bank(100_000, TransactionDirection.DEBIT)
    ledger_row = ledger(100_000, TransactionDirection.CREDIT)

    balances = compute_period_balances(
        [bank_row],
        [ledger_row],
        opening_balance_minor=1_000_000,
        statement_closing_balance_minor=900_000,
        ledger_closing_balance_minor=900_000,
        confirmed_bank_ids={bank_row.id},
        confirmed_ledger_ids={ledger_row.id},
    )

    assert balances.bank_outflow_minor == 100_000
    assert balances.bank_inflow_minor == 0
    assert balances.statement_difference_minor == 0
    assert balances.balanced is True


def test_progress_counts_matched_bank_movements() -> None:
    first = bank(100_000)
    second = bank(50_000)

    balances = compute_period_balances(
        [first, second],
        [],
        opening_balance_minor=0,
        statement_closing_balance_minor=150_000,
        ledger_closing_balance_minor=0,
        confirmed_bank_ids={first.id},
        confirmed_ledger_ids=set(),
    )

    assert balances.progress_ratio == 0.5
    assert balances.matched_bank_count == 1
    assert balances.matched_bank_minor == 100_000


def test_an_unknown_convention_is_refused() -> None:
    with pytest.raises(ValueError):
        compute_period_balances(
            [],
            [],
            opening_balance_minor=0,
            statement_closing_balance_minor=0,
            ledger_closing_balance_minor=0,
            confirmed_bank_ids=set(),
            confirmed_ledger_ids=set(),
            convention="whatever",
        )
