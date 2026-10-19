"""Exact and approximate matching: hard rules first, score second."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.models import TransactionDirection
from app.reconciliation.matcher import (
    equivalent_top_candidates,
    exact_candidates,
    score_candidate,
    suggest_candidates,
)
from app.reconciliation.types import (
    MatchBand,
    MatchConfig,
    Movement,
    MovementSide,
)


def bank(
    *,
    day: int = 1,
    amount: int = 100_000,
    direction: TransactionDirection = TransactionDirection.CREDIT,
    reference: str | None = "REF-1",
    description: str | None = "Pago proveedor",
) -> Movement:
    return Movement(
        id=uuid4(),
        side=MovementSide.BANK,
        transaction_date=date(2026, 2, day),
        amount_minor=amount,
        direction=direction,
        reference=reference,
        description=description,
    )


def ledger(
    *,
    day: int = 1,
    amount: int = 100_000,
    direction: TransactionDirection = TransactionDirection.DEBIT,
    reference: str | None = "REF-1",
    description: str | None = "Pago proveedor",
) -> Movement:
    return Movement(
        id=uuid4(),
        side=MovementSide.LEDGER,
        transaction_date=date(2026, 2, day),
        amount_minor=amount,
        direction=direction,
        reference=reference,
        description=description,
    )


def test_identical_movement_scores_one() -> None:
    candidate = score_candidate(bank(), ledger())

    assert candidate is not None
    assert candidate.score == pytest.approx(1.0)
    assert candidate.band is MatchBand.HIGH
    assert equivalent_top_candidates([candidate]) is False


def test_an_incompatible_direction_is_not_a_candidate() -> None:
    # Bank credit is an inflow; a ledger credit on the asset account is an outflow.
    assert score_candidate(bank(), ledger(direction=TransactionDirection.CREDIT)) is None


def test_a_date_inside_the_window_is_a_suggestion() -> None:
    candidate = score_candidate(bank(day=1), ledger(day=2))

    assert candidate is not None
    assert candidate.date_distance_days == 1
    assert candidate.band is MatchBand.SUGGESTION
    assert candidate.score == pytest.approx(0.9375)


def test_a_date_outside_the_window_is_not_a_candidate() -> None:
    assert score_candidate(bank(day=1), ledger(day=5)) is None


def test_a_different_amount_inside_the_tolerance_is_a_suggestion() -> None:
    candidate = score_candidate(bank(amount=1_000_000), ledger(amount=1_250_000))

    assert candidate is not None
    assert candidate.amount_difference_minor == 250_000
    assert candidate.band is MatchBand.SUGGESTION
    assert candidate.score == pytest.approx(0.9)


def test_an_amount_difference_beyond_the_tolerance_is_not_a_candidate() -> None:
    config = MatchConfig(amount_tolerance_minor=1_000)
    assert score_candidate(bank(amount=100_000), ledger(amount=102_000), config) is None


def test_a_reference_mismatch_cannot_reach_the_suggestion_band() -> None:
    candidate = score_candidate(bank(reference="REF-1"), ledger(reference="REF-2"))

    assert candidate is not None
    assert candidate.band is MatchBand.LOW
    assert candidate.score == pytest.approx(0.75)
    assert "references differ" in candidate.reasons


def test_an_absent_reference_redistributes_its_weight() -> None:
    candidate = score_candidate(bank(reference=None), ledger(reference=None))

    assert candidate is not None
    assert candidate.score == pytest.approx(1.0)
    assert any("redistributed" in reason for reason in candidate.reasons)


def test_description_similarity_changes_the_score_without_breaking_compatibility() -> None:
    candidate = score_candidate(
        bank(description="Pago factura 001"), ledger(description="Pago factura 002")
    )

    assert candidate is not None
    assert 0.90 < candidate.score < 1.0


def test_two_equivalent_candidates_tie_and_must_be_shown() -> None:
    first = ledger()
    second = ledger()

    candidates = exact_candidates(bank(), [first, second])

    assert len(candidates) == 2
    assert equivalent_top_candidates(candidates) is True


def test_exact_candidates_require_the_same_amount() -> None:
    assert exact_candidates(bank(amount=100_000), [ledger(amount=99_000)]) == []


def test_exact_candidates_allow_an_absent_reference_but_not_a_different_one() -> None:
    assert exact_candidates(bank(reference=None), [ledger(reference=None)])
    assert exact_candidates(bank(reference="A"), [ledger(reference="B")]) == []


def test_low_candidates_are_hidden_unless_requested() -> None:
    low = ledger(reference="REF-2")

    assert suggest_candidates(bank(), [low]) == []
    assert suggest_candidates(bank(), [low], include_low=True)


def test_a_pair_outside_the_tolerance_is_not_returned_even_with_low_requested() -> None:
    config = MatchConfig(amount_tolerance_minor=1_000)
    far = ledger(amount=500_000)

    assert suggest_candidates(bank(), [far], config, include_low=True) == []


def test_weights_must_sum_to_one() -> None:
    with pytest.raises(ValueError):
        MatchConfig(amount_weight=0.5)


def test_thresholds_must_be_ordered() -> None:
    with pytest.raises(ValueError):
        MatchConfig(suggestion_threshold=0.96, high_confidence_threshold=0.95)


def test_weights_are_configurable() -> None:
    config = MatchConfig(
        amount_weight=0.7,
        date_weight=0.1,
        reference_weight=0.1,
        description_weight=0.1,
    )

    candidate = score_candidate(bank(day=1), ledger(day=2), config)

    assert candidate is not None
    assert candidate.score == pytest.approx(0.7 + 0.1 * 0.75 + 0.1 + 0.1)


def test_the_engine_requires_bank_first_and_ledger_second() -> None:
    with pytest.raises(ValueError):
        score_candidate(ledger(), bank())
