"""Duplicate suspicion distinguishes a re-import from two legitimate movements."""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from app.models import TransactionDirection
from app.reconciliation.duplicates import DuplicateKind, find_duplicate_candidates
from app.reconciliation.types import Movement, MovementSide


def movement(
    *,
    day: int = 1,
    amount: int = 100_000,
    reference: str | None = "A-1",
    description: str | None = "Comisión",
    external_id: str | None = None,
    fingerprint: str | None = "same-fingerprint",
    import_job: UUID | None = None,
) -> Movement:
    return Movement(
        id=uuid4(),
        side=MovementSide.BANK,
        transaction_date=date(2026, 2, day),
        amount_minor=amount,
        direction=TransactionDirection.DEBIT,
        reference=reference,
        description=description,
        external_id=external_id,
        fingerprint=fingerprint,
        import_job_id=import_job or uuid4(),
    )


def test_the_same_movement_in_two_imports_is_a_reimport() -> None:
    candidates = find_duplicate_candidates([movement(), movement()])

    assert len(candidates) == 1
    assert candidates[0].kind is DuplicateKind.REIMPORTED


def test_the_same_fingerprint_inside_one_job_is_the_same_import() -> None:
    job = uuid4()
    candidates = find_duplicate_candidates([movement(import_job=job), movement(import_job=job)])

    assert candidates[0].kind is DuplicateKind.SAME_IMPORT


def test_two_different_documents_are_legitimate_transactions() -> None:
    candidates = find_duplicate_candidates(
        [
            movement(external_id="DOC-1", fingerprint="one"),
            movement(external_id="DOC-2", fingerprint="two"),
        ]
    )

    assert len(candidates) == 1
    assert candidates[0].kind is DuplicateKind.DISTINCT_DOCUMENTS


def test_similar_values_without_documents_need_investigation() -> None:
    candidates = find_duplicate_candidates(
        [
            movement(reference="A-1", fingerprint="one"),
            movement(reference="A-2", fingerprint="two"),
        ]
    )

    assert candidates[0].kind is DuplicateKind.POSSIBLE_DUPLICATE
    assert "investigate" in " ".join(candidates[0].reasons)


def test_a_different_day_is_not_a_duplicate_candidate() -> None:
    assert find_duplicate_candidates([movement(day=1), movement(day=2)]) == []


def test_a_different_amount_is_not_a_duplicate_candidate() -> None:
    assert find_duplicate_candidates([movement(amount=1), movement(amount=2)]) == []


def test_movements_on_different_sides_are_not_compared() -> None:
    other = Movement(
        id=uuid4(),
        side=MovementSide.LEDGER,
        transaction_date=date(2026, 2, 1),
        amount_minor=100_000,
        direction=TransactionDirection.DEBIT,
        fingerprint="same-fingerprint",
    )

    assert find_duplicate_candidates([movement(), other]) == []
