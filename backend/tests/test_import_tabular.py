"""The file reader: delimiters, encodings, headers and workbook safety.

The reader is the first place untrusted input meets the application. Each case
below is a way a real export goes wrong: Excel on Spanish Windows writes
Windows-1252 and semicolons, a "CSV" can actually be UTF-16, and an `.xlsx` may
be a renamed ZIP that is not a workbook at all.
"""

from __future__ import annotations

import io
from datetime import date, datetime

import pytest
from openpyxl import Workbook

from app.imports.tabular import ImportFileError, read_table


def table(data: bytes, *, name: str = "statement.csv", max_rows: int = 100):
    return read_table(
        data, file_name=name, content_type="application/octet-stream", max_rows=max_rows
    )


def test_a_semicolon_csv_is_detected() -> None:
    result = table(b"Fecha;Valor;Descripcion\n01/02/2026;1.234,56;Pago\n")

    assert result.headers == ("Fecha", "Valor", "Descripcion")
    assert result.rows[0].number == 2
    assert result.rows[0].cells["Descripcion"] == "Pago"


def test_a_comma_csv_is_detected() -> None:
    result = table(b"Fecha,Valor\n01/02/2026,1234.56\n")

    assert result.headers == ("Fecha", "Valor")
    assert result.rows[0].cells["Valor"] == "1234.56"


def test_amount_commas_do_not_steal_a_semicolon_header() -> None:
    result = table(
        (
            "Fecha;Valor;Descripción\n"
            "01/02/2026;1.234,56;A\n"
            "02/02/2026;2.345,67;B\n"
            "03/02/2026;3.456,78;C\n"
        ).encode()
    )

    assert result.headers == ("Fecha", "Valor", "Descripción")


def test_a_quoted_description_may_contain_the_delimiter() -> None:
    result = table(b'Fecha;Descripci\xc3\xb3n;Valor\n01/02/2026;"Pago; parcial";1.000,00\n')

    assert result.rows[0].cells["Descripción"] == "Pago; parcial"


def test_a_tab_separated_file_is_detected() -> None:
    result = table(b"Fecha\tValor\n01/02/2026\t1234.56\n", name="export.txt")

    assert result.headers == ("Fecha", "Valor")


def test_a_utf8_bom_does_not_become_part_of_the_first_header() -> None:
    result = table("\ufeffFecha;Valor\n01/02/2026;1\n".encode())

    assert result.headers[0] == "Fecha"


def test_windows_1252_is_accepted() -> None:
    result = table("Fecha;Descripción\n01/02/2026;Pago\n".encode("cp1252"))

    assert result.headers == ("Fecha", "Descripción")
    assert result.rows[0].cells["Descripción"] == "Pago"


def test_utf16_with_a_bom_is_accepted() -> None:
    result = table("Fecha;Valor\n01/02/2026;1\n".encode("utf-16"))

    assert result.headers == ("Fecha", "Valor")


def test_a_repeated_header_is_refused() -> None:
    with pytest.raises(ImportFileError, match="repeats"):
        table(b"Fecha;Valor;Valor\n01/02/2026;1;2\n")


def test_an_empty_header_in_the_middle_is_refused() -> None:
    with pytest.raises(ImportFileError, match="empty column name"):
        table(b"Fecha;;Valor\n01/02/2026;x;1\n")


def test_an_empty_file_is_refused() -> None:
    with pytest.raises(ImportFileError, match="empty"):
        table(b"")


def test_a_file_without_headers_is_refused() -> None:
    with pytest.raises(ImportFileError, match="no header"):
        table(b"\n\n\n")


def test_an_unsupported_extension_is_refused() -> None:
    with pytest.raises(ImportFileError, match="Only"):
        table(b"Fecha;Valor\n", name="statement.pdf")


def test_macro_enabled_workbooks_are_refused_before_reading() -> None:
    with pytest.raises(ImportFileError, match="Macro-enabled"):
        table(b"PK\x03\x04whatever", name="statement.xlsm")


def test_a_renamed_zip_is_not_an_xlsx() -> None:
    with pytest.raises(ImportFileError):
        table(b"not a zip", name="statement.xlsx")


def test_rows_with_more_columns_than_the_header_are_refused() -> None:
    with pytest.raises(ImportFileError, match="columns"):
        table(b"Fecha;Valor\n01/02/2026;1;extra\n")


def test_blank_lines_are_skipped_but_line_numbers_are_kept() -> None:
    result = table(b"Fecha;Valor\n01/02/2026;1\n\n02/02/2026;2\n")

    assert [row.number for row in result.rows] == [2, 4]


def test_the_row_limit_is_enforced() -> None:
    with pytest.raises(ImportFileError, match="more than 2"):
        table(b"Fecha;Valor\n01/02/2026;1\n02/02/2026;2\n03/02/2026;3\n", max_rows=2)


def test_xlsx_keeps_native_dates_and_numbers() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Fecha", "Valor", "Descripción"])
    sheet.append([date(2026, 2, 1), 1234.56, "Abono"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    result = table(buffer.getvalue(), name="statement.xlsx")

    assert result.file_format == "xlsx"
    assert result.rows[0].cells["Fecha"] == datetime(2026, 2, 1)
    assert result.rows[0].cells["Valor"] == 1234.56
    assert result.rows[0].cells["Descripción"] == "Abono"


def test_xlsx_with_a_blank_leading_line_still_finds_the_header() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append([None, None])
    sheet.append(["Fecha", "Valor"])
    sheet.append([date(2026, 2, 1), 10])
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    result = table(buffer.getvalue(), name="statement.xlsx")

    assert result.headers == ("Fecha", "Valor")
    assert result.rows[0].number == 3
