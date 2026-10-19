"""Money, dates and direction: the cells that decide whether an import is true.

These are pure functions and every case here is one that a real Colombian bank
statement produces. The dangerous acceptance is the one that looks reasonable:
`1.234` is 1234 with a Peruvian/Colombian thousands dot, and 1.234 with a decimal
point. The option is explicit, so a file that does not fit it is an error.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.imports.parsing import (
    CellFormatError,
    parse_amount_cell,
    parse_date_cell,
    parse_direction_cell,
    to_minor_units,
)
from app.models import TransactionDirection


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.234,56", Decimal("1234.56")),
        ("1234,56", Decimal("1234.56")),
        ("1234", Decimal("1234")),
        ("1,5", Decimal("1.50")),
        ("  $ 1.234,56 ", Decimal("1234.56")),
        ("(1.234,56)", Decimal("-1234.56")),
        ("-1.234,56", Decimal("-1234.56")),
        ("+1.234,56", Decimal("1234.56")),
        ("1 234,56", Decimal("1234.56")),
        ("\u00a01.234,56", Decimal("1234.56")),
    ],
)
def test_colombian_amounts_are_read_exactly(raw: str, expected: Decimal) -> None:
    assert parse_amount_cell(raw, ",") == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,234.56", Decimal("1234.56")),
        ("1234.56", Decimal("1234.56")),
        ("(1,234.56)", Decimal("-1234.56")),
    ],
)
def test_dot_decimal_amounts_are_read_exactly(raw: str, expected: Decimal) -> None:
    assert parse_amount_cell(raw, ".") == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "abc",
        "1,2,3",
        "1.2.3",
        "1,234",  # three decimals under a comma-decimal file
        "1,2345",
        "1e5",
        "--5",
    ],
)
def test_bad_amounts_are_rejected(raw: str) -> None:
    with pytest.raises(CellFormatError):
        parse_amount_cell(raw, ",")


def test_a_boolean_is_not_one_peso() -> None:
    with pytest.raises(CellFormatError):
        parse_amount_cell(True, ",")


def test_numeric_spreadsheet_cells_keep_their_value() -> None:
    assert parse_amount_cell(1234.56, ",") == Decimal("1234.56")
    assert parse_amount_cell(1234, ",") == Decimal("1234")
    assert parse_amount_cell(Decimal("0.10"), ",") == Decimal("0.10")


def test_binary_float_noise_in_a_spreadsheet_cell_rounds_to_visible_cents() -> None:
    assert parse_amount_cell(0.1 + 0.2, ",") == Decimal("0.30")
    assert parse_amount_cell(1234.5600000000002, ",") == Decimal("1234.56")


def test_more_than_two_decimals_are_refused_not_rounded() -> None:
    with pytest.raises(CellFormatError):
        parse_amount_cell(Decimal("10.005"), ",")
    with pytest.raises(CellFormatError):
        to_minor_units(Decimal("10.005"))


def test_minor_units_are_exact() -> None:
    assert to_minor_units(Decimal("1234.56")) == 123456
    assert to_minor_units(Decimal("0.01")) == 1
    assert to_minor_units(Decimal("-1234.56")) == -123456


def test_an_absurd_amount_is_refused() -> None:
    with pytest.raises(CellFormatError):
        to_minor_units(Decimal("1000000000000000"))


def test_dates_use_the_declared_format() -> None:
    assert parse_date_cell("01/02/2026", "%d/%m/%Y") == date(2026, 2, 1)
    assert parse_date_cell("2026-02-01", "%Y-%m-%d") == date(2026, 2, 1)


def test_spreadsheet_date_cells_need_no_format() -> None:
    assert parse_date_cell(date(2026, 2, 1), "%d/%m/%Y") == date(2026, 2, 1)
    assert parse_date_cell(datetime(2026, 2, 1, 23, 59), "%d/%m/%Y") == date(2026, 2, 1)


def test_an_impossible_date_is_not_guessed() -> None:
    with pytest.raises(CellFormatError):
        parse_date_cell("31/02/2026", "%d/%m/%Y")


def test_an_excel_serial_date_is_refused_with_a_clear_reason() -> None:
    with pytest.raises(CellFormatError, match="numeric"):
        parse_date_cell(46000, "%d/%m/%Y")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("D", TransactionDirection.DEBIT),
        ("débito", TransactionDirection.DEBIT),
        ("DEBITO", TransactionDirection.DEBIT),
        ("Cargo", TransactionDirection.DEBIT),
        ("C", TransactionDirection.CREDIT),
        ("crédito", TransactionDirection.CREDIT),
        ("Abono", TransactionDirection.CREDIT),
    ],
)
def test_direction_words_are_understood(raw: str, expected: TransactionDirection) -> None:
    assert parse_direction_cell(raw) == expected


def test_an_unknown_direction_is_an_error() -> None:
    with pytest.raises(CellFormatError):
        parse_direction_cell("otro")
