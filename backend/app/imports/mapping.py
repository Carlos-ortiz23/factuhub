"""Column mapping and the rule that turns one table row into one movement.

The mapping is explicit because the same bank exports different headers in every
branch and every version. It is validated against the actual header before a job
is created: a typo must be a clear 422, not a file full of row errors.

Nothing here writes to the database. That keeps the interpretation testable on
its own and makes a retry produce exactly the same movements.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.imports.parsing import (
    CellFormatError,
    parse_amount_cell,
    parse_date_cell,
    parse_direction_cell,
    to_minor_units,
)
from app.imports.tabular import CellValue, TableRow
from app.models import ImportSourceType, TransactionDirection

REFERENCE_MAX_LENGTH = 100
DESCRIPTION_MAX_LENGTH = 500
EXTERNAL_ID_MAX_LENGTH = 100
SOURCE_SYSTEM_MAX_LENGTH = 50

MAPPING_FIELDS = (
    "date",
    "amount",
    "debit",
    "credit",
    "direction",
    "reference",
    "description",
    "external_id",
    "value_date",
)


class MappingError(ValueError):
    """The mapping does not describe this file."""


class RowProblem(ValueError):
    """One row cannot be interpreted; the job records it and moves on."""

    def __init__(self, field: str | None, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


class ColumnMapping(BaseModel):
    """Which header feeds which field. Header names, not positions."""

    date: str = Field(min_length=1, max_length=120)
    amount: str | None = Field(default=None, max_length=120)
    debit: str | None = Field(default=None, max_length=120)
    credit: str | None = Field(default=None, max_length=120)
    direction: str | None = Field(default=None, max_length=120)
    reference: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=120)
    external_id: str | None = Field(default=None, max_length=120)
    value_date: str | None = Field(default=None, max_length=120)

    def named_columns(self) -> dict[str, str]:
        """The fields that were mapped, field name to header name."""
        return {
            field: value for field in MAPPING_FIELDS if (value := getattr(self, field)) is not None
        }

    @model_validator(mode="after")
    def _one_amount_shape(self) -> ColumnMapping:
        has_amount = self.amount is not None
        has_debit_credit = self.debit is not None and self.credit is not None
        partial_pair = (self.debit is None) != (self.credit is None)

        if has_amount and has_debit_credit:
            raise ValueError("map either amount or debit+credit, not both")
        if has_amount and partial_pair:
            raise ValueError("amount cannot be combined with a single debit or credit column")
        if not has_amount and not has_debit_credit:
            raise ValueError("map amount, or both debit and credit")
        if self.direction is not None and not has_amount:
            raise ValueError("a direction column requires an amount column")
        return self


class ImportOptions(BaseModel):
    """How to read the cells once the columns are known."""

    date_format: str = Field(default="%d/%m/%Y", min_length=1, max_length=32)
    decimal_separator: Literal[",", "."] = ","
    positive_is: Literal["credit", "debit"] = "credit"
    source_system: str | None = Field(default=None, max_length=SOURCE_SYSTEM_MAX_LENGTH)

    @model_validator(mode="after")
    def _format_looks_like_a_format(self) -> ImportOptions:
        if "%" not in self.date_format:
            raise ValueError("date_format must contain at least one % directive")
        return self


@dataclass(frozen=True, slots=True)
class ParsedMovement:
    transaction_date: date
    value_date: date | None
    amount_minor: int
    direction: TransactionDirection
    reference: str | None
    description: str | None
    external_id: str | None
    fingerprint: str


def validate_mapping(
    headers: tuple[str, ...],
    mapping: ColumnMapping,
    *,
    source_type: ImportSourceType,
) -> None:
    """Refuse a mapping that cannot address this file before creating a job."""
    available = set(headers)
    named = mapping.named_columns()

    missing = sorted({header for header in named.values() if header not in available})
    if missing:
        raise MappingError(
            "The mapping names column(s) that the file does not have: "
            f"{', '.join(missing)}. Available: {', '.join(headers)}."
        )

    seen: dict[str, str] = {}
    for field, header in named.items():
        if header in seen:
            raise MappingError(f"Column {header!r} is mapped twice ({seen[header]} and {field}).")
        seen[header] = field

    if source_type is not ImportSourceType.BANK_STATEMENT and mapping.value_date is not None:
        raise MappingError("value_date only applies to bank statements.")


def build_movement(
    row: TableRow,
    mapping: ColumnMapping,
    options: ImportOptions,
    *,
    source_type: ImportSourceType,
) -> ParsedMovement:
    """Interpret one row, or raise `RowProblem` naming the offending field."""
    transaction_date = _date(row, mapping.date, "date", options.date_format)

    value_date: date | None = None
    if source_type is ImportSourceType.BANK_STATEMENT and mapping.value_date is not None:
        raw_value_date = row.cells.get(mapping.value_date)
        if not _is_blank(raw_value_date):
            value_date = _date(row, mapping.value_date, "value_date", options.date_format)

    amount_minor, direction = _amount_and_direction(row, mapping, options)

    movement = ParsedMovement(
        transaction_date=transaction_date,
        value_date=value_date,
        amount_minor=amount_minor,
        direction=direction,
        reference=_text(row, mapping.reference, "reference", REFERENCE_MAX_LENGTH),
        description=_text(row, mapping.description, "description", DESCRIPTION_MAX_LENGTH),
        external_id=_text(row, mapping.external_id, "external_id", EXTERNAL_ID_MAX_LENGTH),
        fingerprint="",
    )
    return replace(movement, fingerprint=fingerprint(movement))


def fingerprint(movement: ParsedMovement) -> str:
    """A stable digest used as a duplicate signal, never as a unique key."""
    payload = json.dumps(
        [
            movement.transaction_date.isoformat(),
            movement.amount_minor,
            movement.direction.value,
            movement.reference or "",
            movement.description or "",
            movement.external_id or "",
        ],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _date(row: TableRow, column: str, field: str, date_format: str) -> date:
    try:
        return parse_date_cell(row.cells.get(column), date_format)
    except CellFormatError as exc:
        raise RowProblem(field, str(exc)) from None


def _amount_and_direction(
    row: TableRow,
    mapping: ColumnMapping,
    options: ImportOptions,
) -> tuple[int, TransactionDirection]:
    if mapping.amount is not None:
        raw = row.cells.get(mapping.amount)
        try:
            amount = parse_amount_cell(raw, options.decimal_separator)
        except CellFormatError as exc:
            raise RowProblem("amount", str(exc)) from None

        if mapping.direction is not None:
            try:
                direction = parse_direction_cell(row.cells.get(mapping.direction))
            except CellFormatError as exc:
                raise RowProblem("direction", str(exc)) from None
            if amount <= 0:
                raise RowProblem(
                    "amount",
                    "must be positive when a direction column provides the sign",
                )
            return _minor(abs(amount), "amount"), direction

        if amount == 0:
            raise RowProblem("amount", "must not be zero")
        if amount > 0:
            direction = (
                TransactionDirection.CREDIT
                if options.positive_is == "credit"
                else TransactionDirection.DEBIT
            )
        else:
            direction = (
                TransactionDirection.DEBIT
                if options.positive_is == "credit"
                else TransactionDirection.CREDIT
            )
        return _minor(abs(amount), "amount"), direction

    assert mapping.debit is not None and mapping.credit is not None
    debit = _optional_amount(row, mapping.debit, "debit", options.decimal_separator)
    credit = _optional_amount(row, mapping.credit, "credit", options.decimal_separator)

    if debit > 0 and credit > 0:
        raise RowProblem("debit", "a row cannot have both a debit and a credit")
    if debit == 0 and credit == 0:
        raise RowProblem("amount", "a row must have a debit or a credit")
    if debit > 0:
        return _minor(debit, "debit"), TransactionDirection.DEBIT
    return _minor(credit, "credit"), TransactionDirection.CREDIT


def _optional_amount(row: TableRow, column: str, field: str, decimal_separator: str) -> Decimal:
    raw = row.cells.get(column)
    if _is_blank(raw):
        return Decimal("0")
    try:
        amount = parse_amount_cell(raw, decimal_separator)
    except CellFormatError as exc:
        raise RowProblem(field, str(exc)) from None
    if amount < 0:
        raise RowProblem(field, "must not be negative; use the other column instead")
    return amount


def _minor(amount, field: str) -> int:
    try:
        return to_minor_units(amount)
    except CellFormatError as exc:
        raise RowProblem(field, str(exc)) from None


def _text(row: TableRow, column: str | None, field: str, max_length: int) -> str | None:
    if column is None:
        return None
    raw = row.cells.get(column)
    if isinstance(raw, (date, datetime)):
        text = raw.isoformat()
    elif raw is None:
        text = ""
    else:
        text = str(raw).strip()
    if not text:
        return None
    if len(text) > max_length:
        raise RowProblem(field, f"exceeds {max_length} characters")
    return text


def _is_blank(value: CellValue) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())
