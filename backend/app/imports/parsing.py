"""Cell parsing for imported files.

Money is the dangerous part. A bank statement can express `1.234,56`,
`1,234.56`, `1234.56` or `(1234,56)`, and the same characters mean different
amounts depending on the bank. Guessing is how an import silently reconciles the
wrong values, so the separator and the date format are explicit options and a
value that does not fit them is a row error, never a best-effort guess.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.models import TransactionDirection

#: One hundred billion pesos in minor units. Beyond this the file is not a
#: statement; refusing keeps a corrupted column from poisoning the database.
MAX_ABS_AMOUNT_MINOR = 10**15

_INTEGER_WITH_DOTS = re.compile(r"\d{1,3}(?:\.\d{3})+")
_INTEGER_WITH_COMMAS = re.compile(r"\d{1,3}(?:,\d{3})+")
_TWO_DECIMALS = Decimal("0.01")


class CellFormatError(ValueError):
    """One cell cannot be read under the declared options."""


def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def parse_date_cell(value: object, date_format: str) -> date:
    """Read a date cell, either a real spreadsheet date or an exact format."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    if not isinstance(value, str):
        raise CellFormatError("the date cell is numeric; format the column as a date or as text")
    text = value.strip()
    if not text:
        raise CellFormatError("the date is empty")

    try:
        return datetime.strptime(text, date_format).date()
    except ValueError:
        raise CellFormatError(
            f"the date {text!r} does not match the expected format {date_format!r}"
        ) from None


def parse_amount_cell(value: object, decimal_separator: str) -> Decimal:
    """Read a signed amount, preserving exact decimal precision.

    Returns the value with its sign as written. The caller decides whether a sign
    is meaningful (a debit/credit pair) or must be read through `positive_is`
    (a single signed amount column).
    """
    if _is_blank(value):
        raise CellFormatError("the amount is empty")

    if isinstance(value, bool):
        # bool is an int subclass; `True` is not one peso.
        raise CellFormatError("the amount is not a number")

    if isinstance(value, (int, float, Decimal)):
        parsed = Decimal(str(value))
        if not parsed.is_finite():
            raise CellFormatError("the amount is not a finite number")
        exponent = parsed.as_tuple().exponent
        if isinstance(value, float) and isinstance(exponent, int) and exponent < -2:
            # Binary floating point leaks into spreadsheets: `=A1-B1` can store
            # 0.30000000000000004 for what the cell displays as 0.30. A float
            # cell is rounded to the two decimals the accountant sees; a Decimal
            # is already exact and keeps the strict rule.
            parsed = parsed.quantize(_TWO_DECIMALS, rounding=ROUND_HALF_UP)
        else:
            _reject_excess_precision(parsed)
        return parsed

    text = str(value).strip().replace("\u00a0", " ").replace(" ", "")
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    for symbol in ("$", "COP", "USD", "EUR", "€"):
        text = text.replace(symbol, "")
    if text.startswith("-"):
        negative = True
        text = text[1:]
    elif text.startswith("+"):
        text = text[1:]
    if not text:
        raise CellFormatError("the amount is empty")

    if decimal_separator == ",":
        integer, _, fraction = text.partition(",")
        if "," in fraction:
            raise CellFormatError("the amount has more than one decimal separator")
        if "." in integer:
            if not _INTEGER_WITH_DOTS.fullmatch(integer):
                raise CellFormatError("the thousands separators are malformed")
            integer = integer.replace(".", "")
    else:
        integer, _, fraction = text.partition(".")
        if "." in fraction:
            raise CellFormatError("the amount has more than one decimal separator")
        if "," in integer:
            if not _INTEGER_WITH_COMMAS.fullmatch(integer):
                raise CellFormatError("the thousands separators are malformed")
            integer = integer.replace(",", "")

    if not integer.isdigit():
        raise CellFormatError("the amount has no valid integer part")
    if fraction and not fraction.isdigit():
        raise CellFormatError("the amount has no valid decimal part")
    if len(fraction) > 2:
        raise CellFormatError("the amount has more than two decimals; check the decimal separator")

    normalized = integer + (f".{fraction}" if fraction else "")
    try:
        parsed = Decimal(normalized)
    except InvalidOperation:
        raise CellFormatError("the amount is not a valid number") from None
    if negative:
        parsed = -parsed
    return parsed


def _reject_excess_precision(value: Decimal) -> None:
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -2:
        raise CellFormatError("the amount has more than two decimals")


def to_minor_units(value: Decimal) -> int:
    """Convert an exact decimal amount to integer cents."""
    if not value.is_finite():
        raise CellFormatError("the amount is not a finite number")
    _reject_excess_precision(value)
    minor = int(value * 100)
    if abs(minor) > MAX_ABS_AMOUNT_MINOR:
        raise CellFormatError("the amount is too large")
    return minor


def parse_direction_cell(value: object) -> TransactionDirection:
    """Read a direction column written the many ways a bank writes it."""
    if _is_blank(value):
        raise CellFormatError("the direction is empty")

    text = unicodedata.normalize("NFKD", str(value).strip().lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    compact = re.sub(r"[\s_-]+", "", text)

    if compact in {"debito", "debit", "d", "dr", "cargo", "cargos", "salida"}:
        return TransactionDirection.DEBIT
    if compact in {"credito", "credit", "c", "cr", "abono", "abonos", "entrada"}:
        return TransactionDirection.CREDIT
    raise CellFormatError(f"the direction {value!r} is not one of debit/credit (or débito/crédito)")
