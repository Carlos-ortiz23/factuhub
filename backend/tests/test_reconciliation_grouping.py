"""Grouped candidates: exact sums only, bounded, and never fee-absorbing."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from app.models import TransactionDirection
from app.reconciliation.grouping import find_groups
from app.reconciliation.types import Movement, MovementSide


def bank(
    amount: int,
    *,
    day: int = 1,
    direction: TransactionDirection = TransactionDirection.CREDIT,
    reference: str | None = "FAC000",
) -> Movement:
    return Movement(
        id=uuid4(),
        side=MovementSide.BANK,
        transaction_date=date(2026, 2, day),
        amount_minor=amount,
        direction=direction,
        reference=reference,
    )


def ledger(
    amount: int,
    *,
    day: int = 1,
    direction: TransactionDirection = TransactionDirection.DEBIT,
    reference: str | None = "FAC001",
) -> Movement:
    return Movement(
        id=uuid4(),
        side=MovementSide.LEDGER,
        transaction_date=date(2026, 2, day),
        amount_minor=amount,
        direction=direction,
        reference=reference,
    )


def test_one_bank_movement_against_two_ledger_postings() -> None:
    groups = find_groups(
        [bank(500_000)],
        [ledger(300_000, reference="FAC001"), ledger(200_000, reference="FAC002")],
    )

    assert len(groups) == 1
    group = groups[0]
    assert len(group.bank_movements) == 1
    assert len(group.ledger_movements) == 2
    assert group.total_minor == 500_000
    assert any("sum exactly" in reason for reason in group.reasons)


def test_two_bank_movements_against_one_ledger_posting() -> None:
    groups = find_groups(
        [bank(300_000, reference="FAC001"), bank(200_000, reference="FAC002")],
        [ledger(500_000)],
    )

    assert len(groups) == 1
    assert len(groups[0].bank_movements) == 2
    assert len(groups[0].ledger_movements) == 1


def test_the_sum_must_be_exact() -> None:
    assert find_groups([bank(500_000)], [ledger(300_000), ledger(199_000)]) == []


def test_a_fee_difference_is_not_absorbed() -> None:
    assert find_groups([bank(500_000)], [ledger(498_000)]) == []


def test_dates_must_fit_the_window() -> None:
    assert (
        find_groups(
            [bank(500_000)],
            [ledger(300_000, day=1), ledger(200_000, day=5)],
        )
        == []
    )


def test_unrelated_references_block_a_group() -> None:
    assert (
        find_groups(
            [bank(500_000)],
            [ledger(300_000, reference="FAC001"), ledger(200_000, reference="RECIBO9")],
        )
        == []
    )


def test_an_incompatible_direction_is_excluded() -> None:
    # The second ledger credit is an outflow; the bank credit is an inflow.
    assert (
        find_groups(
            [bank(500_000)],
            [
                ledger(300_000, direction=TransactionDirection.DEBIT),
                ledger(200_000, direction=TransactionDirection.CREDIT),
            ],
        )
        == []
    )


def test_the_group_size_is_bounded() -> None:
    ledgers = [ledger(100_000, reference=f"FAC00{index}") for index in range(1, 5)]

    assert find_groups([bank(400_000)], ledgers, max_group_size=3) == []
    assert find_groups([bank(400_000)], ledgers, max_group_size=4)


def test_empty_sides_produce_nothing() -> None:
    assert find_groups([], []) == []
    assert find_groups([bank(100_000)], []) == []
