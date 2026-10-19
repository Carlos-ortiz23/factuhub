"""Bank accounts and file imports through the HTTP API.

The happy path is the least interesting part. These tests care about the ways an
import lies: a silently dropped duplicate, a partial import reported as clean, an
account reachable by another company, a file accepted without its mapped columns,
or a retry that duplicates what already succeeded.
"""

from __future__ import annotations

import io
import json
from datetime import date
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_import_storage
from app.imports.storage import LocalImportStorage
from app.models import (
    AuditLog,
    BankAccount,
    BankTransaction,
    ImportJob,
    ImportStatus,
    LedgerTransaction,
    TransactionDirection,
)

pytestmark = pytest.mark.integration

ORGANIZATIONS = "/api/v1/organizations"
IMPORTS = "/api/v1/imports"
BANK_ACCOUNTS = "/api/v1/bank-accounts"

CSRF_COOKIE = "factuhub_session_csrf"
CSRF_HEADER = "X-CSRF-Token"
PASSWORD = "conciliacion-segura-2026"

DEFAULT_MAPPING = {
    "date": "Fecha",
    "debit": "Débito",
    "credit": "Crédito",
    "description": "Descripción",
    "reference": "Referencia",
}

BANK_CSV = (
    "Fecha;Descripción;Débito;Crédito;Referencia\n"
    "01/02/2026;Pago proveedor;1.234,56;;A-1\n"
    "02/02/2026;Abono cliente;;2.000,00;A-2\n"
).encode()


@pytest.fixture(autouse=True)
def isolated_import_storage(client: TestClient, tmp_path) -> LocalImportStorage:
    """Never write uploads into the repository during the suite."""
    storage = LocalImportStorage(tmp_path / "imports")
    client.app.dependency_overrides[get_import_storage] = lambda: storage
    return storage


def csrf_headers(client: TestClient) -> dict[str, str]:
    return {CSRF_HEADER: client.cookies[CSRF_COOKIE]}


def company(client: TestClient, tax_id: str = "900123456-7") -> dict[str, Any]:
    response = client.post(
        ORGANIZATIONS,
        json={"name": "Distribuidora El Roble S.A.S.", "tax_id": tax_id},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def bank_account(client: TestClient, organization_id: str, **overrides: Any) -> dict[str, Any]:
    payload = {
        "account_name": "Cuenta corriente",
        "bank_name": "Bancolombia",
        "account_number_masked": "****1234",
        "currency": "COP",
        "ledger_account_code": "1110",
    }
    payload.update(overrides)
    response = client.post(
        f"{ORGANIZATIONS}/{organization_id}/bank-accounts",
        json=payload,
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def upload(
    client: TestClient,
    organization_id: str,
    bank_account_id: str,
    content: bytes = BANK_CSV,
    *,
    filename: str = "extracto.csv",
    content_type: str = "text/csv",
    source_type: str = "bank_statement",
    mapping: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
):
    form: dict[str, Any] = {
        "source_type": source_type,
        "bank_account_id": bank_account_id,
        "mapping": json.dumps(mapping or DEFAULT_MAPPING),
    }
    if options is not None:
        form["options"] = json.dumps(options)
    return client.post(
        f"{ORGANIZATIONS}/{organization_id}/imports",
        data=form,
        files={"file": (filename, content, content_type)},
        headers=csrf_headers(client) if headers is None else headers,
    )


def register(client: TestClient, email: str) -> None:
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "full_name": "Persona de prueba", "password": PASSWORD},
    )


def sign_in(client: TestClient, email: str) -> TestClient:
    register(client, email)
    other = TestClient(client.app)
    other.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    return other


def add_member(client: TestClient, organization_id: str, email: str, role: str) -> None:
    register(client, email)
    response = client.post(
        f"{ORGANIZATIONS}/{organization_id}/members",
        json={"email": email, "role": role},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text


# --------------------------------------------------------------------------
# Bank accounts
# --------------------------------------------------------------------------


def test_a_bank_account_is_created_and_listed_without_a_full_number(
    auth_client: TestClient,
) -> None:
    organization = company(auth_client)

    created = auth_client.post(
        f"{ORGANIZATIONS}/{organization['id']}/bank-accounts",
        json={
            "account_name": "Cuenta corriente",
            "bank_name": "Bancolombia",
            "account_number_masked": "****1234",
            "ledger_account_code": "1110",
        },
        headers=csrf_headers(auth_client),
    )

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["account_number_masked"] == "****1234"
    assert "account_number" not in body
    assert body["active"] is True

    listing = auth_client.get(f"{ORGANIZATIONS}/{organization['id']}/bank-accounts")
    assert listing.status_code == 200
    assert [row["id"] for row in listing.json()["accounts"]] == [body["id"]]


def test_an_import_only_company_needs_no_provider_connection(auth_client: TestClient) -> None:
    organization = company(auth_client)

    account = bank_account(auth_client, organization["id"])

    assert account["connection_id"] is None


def test_a_bank_account_from_another_company_is_a_404(auth_client: TestClient) -> None:
    organization = company(auth_client)
    account = bank_account(auth_client, organization["id"])

    stranger = sign_in(auth_client, "otra@example.com")

    response = stranger.get(f"{BANK_ACCOUNTS}/{account['id']}")

    assert response.status_code == 404


# --------------------------------------------------------------------------
# Importing
# --------------------------------------------------------------------------


def test_a_bank_statement_imports_debits_and_credits(
    auth_client: TestClient, db_session: Session
) -> None:
    organization = company(auth_client)
    account = bank_account(auth_client, organization["id"])

    response = upload(auth_client, organization["id"], account["id"])

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["rows_read"] == 2
    assert body["rows_imported"] == 2
    assert body["error_summary"] is None
    assert body["mapping"]["date"] == "Fecha"

    rows = list(
        db_session.scalars(
            select(BankTransaction).where(BankTransaction.import_job_id == UUID(body["id"]))
        )
    )
    by_amount = {row.amount_minor: row for row in rows}
    assert by_amount[123456].direction is TransactionDirection.DEBIT
    assert by_amount[200000].direction is TransactionDirection.CREDIT
    assert by_amount[123456].reference == "A-1"


def test_the_import_is_recorded_in_the_audit_trail(
    auth_client: TestClient, db_session: Session
) -> None:
    organization = company(auth_client)
    account = bank_account(auth_client, organization["id"])

    body = upload(auth_client, organization["id"], account["id"]).json()

    entry = db_session.scalar(
        select(AuditLog).where(
            AuditLog.action == "import.completed", AuditLog.entity_id == UUID(body["id"])
        )
    )
    assert entry is not None
    assert entry.metadata_json["rows_imported"] == 2


def test_a_partial_import_reports_the_rejected_rows(
    auth_client: TestClient, db_session: Session
) -> None:
    organization = company(auth_client)
    account = bank_account(auth_client, organization["id"])
    content = (
        "Fecha;Descripción;Débito;Crédito;Referencia\n"
        "01/02/2026;Pago;1.000,00;;A-1\n"
        "31/02/2026;Fecha imposible;500,00;;A-2\n"
        "03/02/2026;Importe inválido;;abc;\n"
    ).encode()

    response = upload(auth_client, organization["id"], account["id"], content)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["rows_read"] == 3
    assert body["rows_imported"] == 1
    assert "2 of 3" in body["error_summary"]

    errors = auth_client.get(f"{IMPORTS}/{body['id']}/errors")
    assert errors.status_code == 200, errors.text
    payload = errors.json()
    assert payload["total"] == 2
    assert [(row["row_number"], row["field"]) for row in payload["errors"]] == [
        (3, "date"),
        (4, "credit"),
    ]


def test_an_import_where_every_row_fails_is_failed(auth_client: TestClient) -> None:
    organization = company(auth_client)
    account = bank_account(auth_client, organization["id"])
    content = "Fecha;Descripción;Débito;Crédito;Referencia\n31/02/2026;Mala;1,00;;\n".encode()

    body = upload(auth_client, organization["id"], account["id"], content).json()

    assert body["status"] == "failed"
    assert body["rows_imported"] == 0


def test_the_same_file_with_the_same_interpretation_is_refused(
    auth_client: TestClient,
) -> None:
    organization = company(auth_client)
    account = bank_account(auth_client, organization["id"])

    first = upload(auth_client, organization["id"], account["id"])
    second = upload(auth_client, organization["id"], account["id"])

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["detail"]["existing_import_id"] == first.json()["id"]


def test_the_same_file_with_a_corrected_mapping_is_a_new_import(
    auth_client: TestClient,
) -> None:
    organization = company(auth_client)
    account = bank_account(auth_client, organization["id"])

    first = upload(auth_client, organization["id"], account["id"])
    corrected = upload(
        auth_client,
        organization["id"],
        account["id"],
        options={"positive_is": "debit"},
    )

    assert first.status_code == 201
    assert corrected.status_code == 201
    assert corrected.json()["id"] != first.json()["id"]


def test_legitimate_repeated_rows_are_both_imported(auth_client: TestClient) -> None:
    organization = company(auth_client)
    account = bank_account(auth_client, organization["id"])
    content = (
        "Fecha;Descripción;Débito;Crédito;Referencia\n"
        "01/02/2026;Comisión;4.500,00;;\n"
        "01/02/2026;Comisión;4.500,00;;\n"
    ).encode()

    body = upload(auth_client, organization["id"], account["id"], content).json()

    assert body["status"] == "completed"
    assert body["rows_imported"] == 2


def test_an_empty_file_is_refused(auth_client: TestClient) -> None:
    organization = company(auth_client)
    account = bank_account(auth_client, organization["id"])

    response = upload(auth_client, organization["id"], account["id"], b"")

    assert response.status_code == 422


def test_an_upload_without_the_csrf_token_is_refused(auth_client: TestClient) -> None:
    organization = company(auth_client)
    account = bank_account(auth_client, organization["id"])

    response = upload(auth_client, organization["id"], account["id"], headers={})

    assert response.status_code == 403


def test_a_mapping_that_names_a_missing_column_creates_no_job(
    auth_client: TestClient, db_session: Session
) -> None:
    organization = company(auth_client)
    account = bank_account(auth_client, organization["id"])

    response = upload(
        auth_client,
        organization["id"],
        account["id"],
        mapping={"date": "Fecha", "amount": "Importe inexistente"},
    )

    assert response.status_code == 422
    assert "does not have" in response.json()["detail"]
    assert db_session.scalar(select(ImportJob)) is None


def test_a_mapping_without_an_amount_shape_is_refused(auth_client: TestClient) -> None:
    organization = company(auth_client)
    account = bank_account(auth_client, organization["id"])

    response = upload(
        auth_client,
        organization["id"],
        account["id"],
        mapping={"date": "Fecha", "description": "Descripción"},
    )

    assert response.status_code == 422
    assert "amount" in response.json()["detail"].lower()


def test_a_value_date_mapping_is_refused_for_a_ledger_export(
    auth_client: TestClient,
) -> None:
    organization = company(auth_client)
    account = bank_account(auth_client, organization["id"])

    response = upload(
        auth_client,
        organization["id"],
        account["id"],
        source_type="ledger_export",
        mapping={**DEFAULT_MAPPING, "value_date": "Fecha"},
    )

    assert response.status_code == 422
    assert "value_date" in response.json()["detail"]


def test_a_signed_amount_uses_the_declared_positive_convention(
    auth_client: TestClient,
) -> None:
    organization = company(auth_client)
    account = bank_account(auth_client, organization["id"])
    content = "Fecha;Valor;Descripción\n01/02/2026;-1500,00;Pago\n".encode()
    mapping = {"date": "Fecha", "amount": "Valor", "description": "Descripción"}

    body = upload(
        auth_client,
        organization["id"],
        account["id"],
        content,
        mapping=mapping,
    ).json()

    assert body["status"] == "completed"

    response = auth_client.get(f"{IMPORTS}/{body['id']}")
    assert response.status_code == 200


def test_positive_is_debit_inverts_the_signed_amount(
    auth_client: TestClient, db_session: Session
) -> None:
    organization = company(auth_client)
    account = bank_account(auth_client, organization["id"])
    content = "Fecha;Valor;Descripción\n01/02/2026;1500,00;Pago\n".encode()
    mapping = {"date": "Fecha", "amount": "Valor", "description": "Descripción"}

    body = upload(
        auth_client,
        organization["id"],
        account["id"],
        content,
        mapping=mapping,
        options={"positive_is": "debit"},
    ).json()

    row = db_session.scalar(
        select(BankTransaction).where(BankTransaction.import_job_id == UUID(body["id"]))
    )
    assert row is not None
    assert row.direction is TransactionDirection.DEBIT


def test_an_xlsx_statement_is_imported(auth_client: TestClient) -> None:
    organization = company(auth_client)
    account = bank_account(auth_client, organization["id"])

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Fecha", "Valor", "Descripción"])
    sheet.append([date(2026, 2, 1), 1234.56, "Abono"])
    sheet.append([date(2026, 2, 2), -900, "Pago"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    response = upload(
        auth_client,
        organization["id"],
        account["id"],
        buffer.getvalue(),
        filename="extracto.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        mapping={"date": "Fecha", "amount": "Valor", "description": "Descripción"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["rows_imported"] == 2


def test_a_ledger_export_lands_in_its_own_table(
    auth_client: TestClient, db_session: Session
) -> None:
    organization = company(auth_client)
    account = bank_account(auth_client, organization["id"])

    body = upload(
        auth_client,
        organization["id"],
        account["id"],
        source_type="ledger_export",
        options={"source_system": "siigo"},
    ).json()

    assert body["source_type"] == "ledger_export"
    rows = list(
        db_session.scalars(
            select(LedgerTransaction).where(LedgerTransaction.import_job_id == UUID(body["id"]))
        )
    )
    assert len(rows) == 2
    assert {row.source_system for row in rows} == {"siigo"}


def test_an_import_of_another_company_is_a_404(auth_client: TestClient) -> None:
    organization = company(auth_client)
    account = bank_account(auth_client, organization["id"])
    imported = upload(auth_client, organization["id"], account["id"]).json()

    stranger = sign_in(auth_client, "intruso@example.com")

    assert stranger.get(f"{IMPORTS}/{imported['id']}").status_code == 404
    assert stranger.get(f"{IMPORTS}/{imported['id']}/errors").status_code == 404
    assert (
        stranger.post(
            f"{IMPORTS}/{imported['id']}/retry", headers=csrf_headers(stranger)
        ).status_code
        == 404
    )


def test_a_non_member_cannot_upload_to_a_company(auth_client: TestClient) -> None:
    organization = company(auth_client)
    account = bank_account(auth_client, organization["id"])

    stranger = sign_in(auth_client, "intruso@example.com")
    response = upload(stranger, organization["id"], account["id"])

    assert response.status_code == 404


def test_a_viewer_cannot_import(auth_client: TestClient) -> None:
    organization = company(auth_client)
    account = bank_account(auth_client, organization["id"])
    add_member(auth_client, organization["id"], "revisor@example.com", "viewer")

    viewer = sign_in(auth_client, "revisor@example.com")

    assert viewer.get(f"{ORGANIZATIONS}/{organization['id']}/imports").status_code == 200
    response = upload(viewer, organization["id"], account["id"])

    assert response.status_code == 403


def test_the_row_limit_is_enforced(auth_client: TestClient) -> None:
    organization = company(auth_client)
    account = bank_account(auth_client, organization["id"])
    auth_client.app.state.settings.import_max_rows = 2
    content = (
        "Fecha;Descripción;Débito;Crédito;Referencia\n"
        "01/02/2026;Uno;1,00;;\n"
        "02/02/2026;Dos;1,00;;\n"
        "03/02/2026;Tres;1,00;;\n"
    ).encode()

    response = upload(auth_client, organization["id"], account["id"], content)

    assert response.status_code == 422
    assert "more than 2" in response.json()["detail"]


def test_the_byte_limit_is_enforced(auth_client: TestClient) -> None:
    organization = company(auth_client)
    account = bank_account(auth_client, organization["id"])
    auth_client.app.state.settings.import_max_bytes = 1024

    response = upload(
        auth_client,
        organization["id"],
        account["id"],
        b"x" * 2048,
    )

    assert response.status_code == 413


def test_a_failed_import_can_be_retried_without_duplicating_rows(
    auth_client: TestClient, db_session: Session
) -> None:
    organization = company(auth_client)
    account = bank_account(auth_client, organization["id"])
    content = "Fecha;Descripción;Débito;Crédito;Referencia\n31/02/2026;Mala;1,00;;\n".encode()
    failed = upload(auth_client, organization["id"], account["id"], content).json()

    response = auth_client.post(
        f"{IMPORTS}/{failed['id']}/retry", headers=csrf_headers(auth_client)
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "failed"
    assert response.json()["rows_imported"] == 0
    errors = auth_client.get(f"{IMPORTS}/{failed['id']}/errors").json()
    assert errors["total"] == 1


def test_a_completed_import_cannot_be_retried(auth_client: TestClient) -> None:
    organization = company(auth_client)
    account = bank_account(auth_client, organization["id"])
    completed = upload(auth_client, organization["id"], account["id"]).json()

    response = auth_client.post(
        f"{IMPORTS}/{completed['id']}/retry", headers=csrf_headers(auth_client)
    )

    assert response.status_code == 409


def test_an_inactive_bank_account_refuses_new_imports(
    auth_client: TestClient, db_session: Session
) -> None:
    organization = company(auth_client)
    account = bank_account(auth_client, organization["id"])
    row = db_session.get(BankAccount, UUID(account["id"]))
    assert row is not None
    row.active = False
    db_session.flush()

    response = upload(auth_client, organization["id"], account["id"])

    assert response.status_code == 409


def test_the_import_list_can_be_filtered_by_account(auth_client: TestClient) -> None:
    organization = company(auth_client)
    account = bank_account(auth_client, organization["id"])
    upload(auth_client, organization["id"], account["id"])

    response = auth_client.get(
        f"{ORGANIZATIONS}/{organization['id']}/imports",
        params={"bank_account_id": account["id"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["imports"][0]["status"] == ImportStatus.COMPLETED.value
