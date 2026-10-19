"""Excel export of a reconciliation period.

The workbook is a report, not a calculation: every figure comes from the same
service that answers the JSON summary, so the file and the screen cannot drift.

Text cells are forced to the `s` data type after assignment. A reference or
description that starts with `=` must never become a formula when the accountant
opens the file; that is a real injection path from an uploaded bank statement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.models import MatchStatus, MatchType, PeriodStatus
from app.reconciliation.balances import PeriodBalances
from app.reconciliation.normalizer import economic_direction
from app.reconciliation.types import EconomicDirection
from app.schemas.reconciliation import MatchResponse, PeriodResponse
from app.services.reconciliation import PeriodMovementView

HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
HEADER_FONT = Font(bold=True, color="FFFFFF")
TITLE_FONT = Font(bold=True, size=14)
SECTION_FONT = Font(bold=True, size=11)
MONEY_FORMAT = "#,##0.00"
DATE_FORMAT = "yyyy-mm-dd"

PERIOD_STATUS_LABELS = {
    PeriodStatus.OPEN: "Abierto",
    PeriodStatus.IN_REVIEW: "En revisión",
    PeriodStatus.APPROVED: "Aprobado",
    PeriodStatus.REOPENED: "Reabierto",
}
MATCH_TYPE_LABELS = {
    MatchType.EXACT: "Exacta",
    MatchType.APPROXIMATE: "Aproximada",
    MatchType.GROUPED: "Agrupada",
    MatchType.MANUAL: "Manual",
}
MATCH_STATUS_LABELS = {
    MatchStatus.SUGGESTED: "Sugerida",
    MatchStatus.CONFIRMED: "Confirmada",
    MatchStatus.REJECTED: "Rechazada",
    MatchStatus.CANCELLED: "Cancelada",
}
SIDE_LABELS = {"bank": "Banco", "ledger": "Contabilidad"}


@dataclass(frozen=True, slots=True)
class ReportHeader:
    organization_name: str
    organization_tax_id: str
    bank_name: str
    account_masked: str
    currency: str


def build_period_workbook(
    *,
    period: PeriodResponse,
    header: ReportHeader,
    balances: PeriodBalances,
    movements: list[PeriodMovementView],
    matches: list[MatchResponse],
) -> bytes:
    workbook = Workbook()
    summary = workbook.active
    summary.title = "Resumen"

    _summary_sheet(summary, period=period, header=header, balances=balances)
    _movement_sheet(
        workbook.create_sheet("Movimientos"),
        movements,
        title="Todos los movimientos del periodo",
    )
    _movement_sheet(
        workbook.create_sheet("Pendientes"),
        [movement for movement in movements if movement.match_status is None],
        title="Movimientos sin coincidencia confirmada",
    )
    _match_sheet(workbook.create_sheet("Coincidencias"), matches)

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _summary_sheet(sheet, *, period, header, balances) -> None:
    sheet.sheet_view.showGridLines = False
    _text(sheet["A1"], "Conciliación bancaria").font = TITLE_FONT
    sheet.merge_cells("A1:D1")

    rows: list[tuple[str, object]] = [
        ("Empresa", header.organization_name),
        ("NIT", header.organization_tax_id),
        ("Banco", header.bank_name),
        ("Cuenta", header.account_masked),
        ("Moneda", header.currency),
        ("Periodo", f"{period.period_start.isoformat()} a {period.period_end.isoformat()}"),
        ("Estado", PERIOD_STATUS_LABELS[period.status]),
        ("Aprobado el", period.approved_at.date().isoformat() if period.approved_at else ""),
    ]
    row = 3
    for label, value in rows:
        _text(sheet.cell(row=row, column=1), label).font = Font(bold=True)
        _value(sheet.cell(row=row, column=2), value)
        row += 1

    row += 1
    _text(sheet.cell(row=row, column=1), "Saldos (unidades monetarias)").font = SECTION_FONT
    row += 1
    balances_rows = [
        ("Saldo inicial", balances.opening_balance_minor),
        ("Entradas bancarias", balances.bank_inflow_minor),
        ("Salidas bancarias", balances.bank_outflow_minor),
        ("Saldo final calculado (banco)", balances.bank_computed_closing_minor),
        ("Saldo final del extracto", balances.statement_closing_balance_minor),
        ("Diferencia contra el extracto", balances.statement_difference_minor),
        ("Saldo final contable", balances.ledger_closing_balance_minor),
        ("Movimientos bancarios pendientes", balances.pending_bank_count),
        ("Neto bancario pendiente", balances.pending_bank_net_minor),
        ("Movimientos contables pendientes", balances.pending_ledger_count),
        ("Neto contable pendiente", balances.pending_ledger_net_minor),
        ("Saldo contable ajustado", balances.adjusted_ledger_balance_minor),
        ("Diferencia no explicada", balances.unexplained_difference_minor),
    ]
    for label, value in balances_rows:
        _text(sheet.cell(row=row, column=1), label)
        money = sheet.cell(row=row, column=2)
        money.value = _major_units(value)
        money.number_format = MONEY_FORMAT
        row += 1

    _text(sheet.cell(row=row, column=1), "Progreso")
    _text(sheet.cell(row=row, column=2), f"{balances.progress_ratio:.1%}")
    row += 1
    _text(sheet.cell(row=row, column=1), "Conciliado").font = Font(bold=True)
    _text(sheet.cell(row=row, column=2), "Sí" if balances.balanced else "No")
    row += 2

    _text(sheet.cell(row=row, column=1), "Convención aplicada").font = SECTION_FONT
    row += 1
    note = (
        "Banco → contabilidad: al saldo contable se le suman las partidas "
        "bancarias pendientes y se le restan las contables. Las cifras deben "
        "validarse con el contador antes de usarlas como dictamen."
    )
    _text(sheet.cell(row=row, column=1), note)
    sheet.merge_cells(start_row=row, start_column=1, end_row=row + 2, end_column=4)
    sheet.cell(row=row, column=1).alignment = Alignment(wrap_text=True, vertical="top")

    sheet.column_dimensions["A"].width = 42
    sheet.column_dimensions["B"].width = 46
    sheet.column_dimensions["C"].width = 18
    sheet.column_dimensions["D"].width = 18


def _movement_sheet(sheet, movements: list[PeriodMovementView], *, title: str) -> None:
    headers = [
        "Lado",
        "Fecha",
        "Valor",
        "Naturaleza",
        "Referencia",
        "Descripción",
        "ID externo",
        "Estado de coincidencia",
        "ID de coincidencia",
    ]
    _text(sheet["A1"], title).font = TITLE_FONT
    sheet.merge_cells("A1:I1")
    _header_row(sheet, row=3, headers=headers)

    row = 4
    for movement in movements:
        _text(sheet.cell(row=row, column=1), SIDE_LABELS[movement.side.value])
        day = sheet.cell(row=row, column=2)
        day.value = movement.transaction_date
        day.number_format = DATE_FORMAT
        value = sheet.cell(row=row, column=3)
        value.value = _major_units(movement.amount_minor)
        value.number_format = MONEY_FORMAT
        _text(sheet.cell(row=row, column=4), _direction_label(movement))
        _text(sheet.cell(row=row, column=5), movement.reference)
        _text(sheet.cell(row=row, column=6), movement.description)
        _text(sheet.cell(row=row, column=7), movement.external_id)
        _text(
            sheet.cell(row=row, column=8),
            MATCH_STATUS_LABELS.get(movement.match_status, "Pendiente"),
        )
        _text(
            sheet.cell(row=row, column=9),
            str(movement.match_id) if movement.match_id else "",
        )
        row += 1

    _finish_data_sheet(sheet, last_row=max(row - 1, 3), last_column=len(headers))
    widths = [12, 12, 16, 14, 20, 44, 22, 24, 38]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width


def _match_sheet(sheet, matches: list[MatchResponse]) -> None:
    headers = [
        "ID",
        "Tipo",
        "Puntaje",
        "Estado",
        "Movimientos bancarios",
        "Movimientos contables",
        "Diferencia de importe",
        "Motivos",
    ]
    _text(sheet["A1"], "Coincidencias del periodo").font = TITLE_FONT
    sheet.merge_cells("A1:H1")
    _header_row(sheet, row=3, headers=headers)

    row = 4
    for match in matches:
        _text(sheet.cell(row=row, column=1), str(match.id))
        _text(sheet.cell(row=row, column=2), MATCH_TYPE_LABELS[match.match_type])
        score = sheet.cell(row=row, column=3)
        score.value = float(match.score)
        score.number_format = "0.00"
        _text(sheet.cell(row=row, column=4), MATCH_STATUS_LABELS[match.status])
        _text(
            sheet.cell(row=row, column=5),
            ", ".join(
                str(item.bank_transaction_id) for item in match.items if item.bank_transaction_id
            ),
        )
        _text(
            sheet.cell(row=row, column=6),
            ", ".join(
                str(item.ledger_transaction_id)
                for item in match.items
                if item.ledger_transaction_id
            ),
        )
        difference = sheet.cell(row=row, column=7)
        amount_difference = match.explanation.get("amount_difference_minor")
        if isinstance(amount_difference, int):
            difference.value = _major_units(amount_difference)
            difference.number_format = MONEY_FORMAT
        _text(sheet.cell(row=row, column=8), _reasons(match))
        row += 1

    _finish_data_sheet(sheet, last_row=max(row - 1, 3), last_column=len(headers))
    widths = [38, 12, 10, 14, 42, 42, 20, 60]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width


def _header_row(sheet, *, row: int, headers: list[str]) -> None:
    for column, header in enumerate(headers, start=1):
        cell = _text(sheet.cell(row=row, column=column), header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(vertical="center")


def _finish_data_sheet(sheet, *, last_row: int, last_column: int) -> None:
    sheet.freeze_panes = "A4"
    sheet.auto_filter.ref = f"A3:{get_column_letter(last_column)}{last_row}"
    for row in sheet.iter_rows(min_row=4, max_row=last_row, max_col=last_column):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)


def _direction_label(movement: PeriodMovementView) -> str:
    direction = economic_direction(movement.side, movement.direction)
    return "Entrada" if direction is EconomicDirection.INFLOW else "Salida"


def _reasons(match: MatchResponse) -> str:
    reasons = match.explanation.get("reasons")
    if isinstance(reasons, list):
        return "; ".join(str(reason) for reason in reasons)
    return ""


def _major_units(amount_minor: int) -> float:
    return amount_minor / 100


def _text(cell, value: object):
    """Write text and force it to stay text, even when it starts with '='."""
    if value is None or value == "":
        cell.value = None
        return cell
    cell.value = str(value)
    cell.data_type = "s"
    return cell


def _value(cell, value: object) -> None:
    if isinstance(value, date):
        cell.value = value
        cell.number_format = DATE_FORMAT
    else:
        _text(cell, value)
