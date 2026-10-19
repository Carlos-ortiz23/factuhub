"""Normalisation keeps the original intact and makes the comparison honest."""

from __future__ import annotations

from datetime import date

from app.models import TransactionDirection
from app.reconciliation.normalizer import (
    date_span_days,
    description_similarity,
    economic_direction,
    normalize_description,
    normalize_reference,
    references_are_related,
)
from app.reconciliation.types import EconomicDirection, MovementSide


def test_references_lose_accents_case_and_punctuation() -> None:
    assert normalize_reference(" abc-001 ") == "ABC001"
    assert normalize_reference("Ábc 001") == "ABC001"
    assert normalize_reference(None) == ""


def test_descriptions_are_upper_case_without_accents_or_punctuation() -> None:
    assert normalize_description("Pago  a proveedor, S.A.S.") == "PAGO A PROVEEDOR S A S"


def test_description_similarity_ignores_filler_words() -> None:
    assert description_similarity("Pago de proveedor", "PAGO PROVEEDOR") == 1.0


def test_description_similarity_is_partial_when_words_differ() -> None:
    assert 0.0 < description_similarity("Pago factura 001", "Pago factura 002") < 1.0


def test_description_similarity_is_zero_when_one_side_is_empty() -> None:
    assert description_similarity(None, "Pago") == 0.0


def test_a_bank_credit_is_an_inflow() -> None:
    assert (
        economic_direction(MovementSide.BANK, TransactionDirection.CREDIT)
        is EconomicDirection.INFLOW
    )


def test_a_ledger_debit_is_an_inflow_for_an_asset_account() -> None:
    assert (
        economic_direction(MovementSide.LEDGER, TransactionDirection.DEBIT)
        is EconomicDirection.INFLOW
    )


def test_a_ledger_credit_is_an_outflow_for_an_asset_account() -> None:
    assert (
        economic_direction(MovementSide.LEDGER, TransactionDirection.CREDIT)
        is EconomicDirection.OUTFLOW
    )


def test_references_related_by_equality() -> None:
    assert references_are_related(["FV-001", "fv001"])


def test_references_related_by_family_prefix() -> None:
    assert references_are_related(["FV001", "FV002", "FV003"])


def test_unrelated_references_are_not_forced_together() -> None:
    assert not references_are_related(["FV001", "RECIBO-9"])


def test_one_reference_does_not_constrain_a_group() -> None:
    assert references_are_related(["FV001", None])


def test_date_span() -> None:
    assert date_span_days([date(2026, 2, 1), date(2026, 2, 3)]) == 2
    assert date_span_days([]) == 0
