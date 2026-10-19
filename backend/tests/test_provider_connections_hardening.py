"""Independent regression probes for S5/S6: invariants the writer's suite omits.

Each test states the rule it protects. Credentials here are fake.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_connector_factory
from app.integrations.base import ConnectionCheck
from app.models import AuditLog, ProviderCredential

pytestmark = pytest.mark.integration

ORGANIZATIONS = "/api/v1/organizations"
CSRF_COOKIE = "factuhub_session_csrf"
CSRF_HEADER = "X-CSRF-Token"
PASSWORD = "conciliacion-segura-2026"
USERNAME = "contador-siigo@example.com"
ACCESS_KEY = "clave-de-acceso-que-no-debe-salir"


def csrf_headers(client: TestClient) -> dict[str, str]:
    return {CSRF_HEADER: client.cookies[CSRF_COOKIE]}


def person(client: TestClient, email: str) -> TestClient:
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "full_name": "Persona de prueba", "password": PASSWORD},
    )
    other = TestClient(client.app)
    other.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    return other


def company(client: TestClient, tax_id: str = "900123456-7") -> dict[str, Any]:
    response = client.post(
        ORGANIZATIONS,
        json={"name": "Distribuidora El Roble S.A.S.", "tax_id": tax_id},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def save_connection(
    client: TestClient,
    organization_id: str,
    *,
    provider: str = "siigo",
    credentials: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
):
    return client.put(
        f"{ORGANIZATIONS}/{organization_id}/connections/{provider}",
        json={"credentials": credentials or {"username": USERNAME, "access_key": ACCESS_KEY}},
        headers=csrf_headers(client) if headers is None else headers,
    )


def stored_row(db: Session, organization_id: str) -> ProviderCredential:
    row = db.scalar(
        select(ProviderCredential).where(
            ProviderCredential.organization_id == UUID(organization_id)
        )
    )
    assert row is not None
    return row


class FakeConnector:
    def __init__(self, result: ConnectionCheck) -> None:
        self._result = result

    async def test_connection(self) -> ConnectionCheck:
        return self._result


def test_a_rejected_save_changes_no_ciphertext_no_status_and_no_audit_row(
    auth_client: TestClient, db_session: Session
) -> None:
    """S5/S6: a refused PUT must not rewrite the stored token or the trail."""
    company_row = company(auth_client)
    assert save_connection(auth_client, company_row["id"]).status_code == 200
    organization_id = UUID(company_row["id"])

    def snapshot() -> tuple[bytes, str, int]:
        row = stored_row(db_session, company_row["id"])
        count = db_session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.organization_id == organization_id)
        )
        assert count is not None
        return bytes(row.encrypted_credentials), row.status.value, count

    before = snapshot()

    rejected_extra = save_connection(
        auth_client,
        company_row["id"],
        credentials={"username": USERNAME, "access_key": ACCESS_KEY, "extra": "x"},
    )
    assert rejected_extra.status_code == 422
    world_office = save_connection(auth_client, company_row["id"], provider="world_office")
    unknown = save_connection(auth_client, company_row["id"], provider="inventado")
    assert world_office.status_code == 409
    assert unknown.status_code == 404

    assert snapshot() == before


def test_a_rejected_credential_payload_never_echoes_any_credential(
    auth_client: TestClient,
) -> None:
    """S5: neither the expected nor an unexpected credential value may be echoed."""
    company_row = company(auth_client)
    unexpected = "otra-clave-que-tampoco-debe-salir"

    extra = save_connection(
        auth_client,
        company_row["id"],
        credentials={"username": USERNAME, "access_key": ACCESS_KEY, "unexpected": unexpected},
    )
    assert extra.status_code == 422
    assert ACCESS_KEY not in extra.text
    assert unexpected not in extra.text

    wrong_type = auth_client.put(
        f"{ORGANIZATIONS}/{company_row['id']}/connections/siigo",
        json={"credentials": {"username": 123, "access_key": ACCESS_KEY}},
        headers=csrf_headers(auth_client),
    )
    assert wrong_type.status_code == 422
    assert ACCESS_KEY not in wrong_type.text


def test_a_non_member_gets_404_without_a_csrf_token(
    auth_client: TestClient,
) -> None:
    """S6: membership is decided before CSRF, and a non-member never sees 403."""
    company_row = company(auth_client)
    save_connection(auth_client, company_row["id"])

    with person(auth_client, "sin-csrf-ajena@example.com") as outsider:
        base = f"{ORGANIZATIONS}/{company_row['id']}/connections/siigo"
        assert (
            outsider.put(base, json={"credentials": {"username": "u", "access_key": "k"}})
        ).status_code == 404
        assert outsider.delete(base).status_code == 404
        assert outsider.post(f"{base}/test").status_code == 404


def test_a_failed_test_redacts_the_username_too_and_stamps_the_check_time(
    auth_client: TestClient, db_session: Session
) -> None:
    """S1/S6: the stored reason is bounded, carries no credential, and is timestamped."""
    company_row = company(auth_client)
    save_connection(auth_client, company_row["id"])
    error = f"user={USERNAME} key={ACCESS_KEY} " + "x" * 900

    def factory(_provider: str, _credentials: dict[str, str]) -> FakeConnector:
        return FakeConnector(ConnectionCheck(ok=False, error=error))

    auth_client.app.dependency_overrides[get_connector_factory] = lambda: factory
    response = auth_client.post(
        f"{ORGANIZATIONS}/{company_row['id']}/connections/siigo/test",
        headers=csrf_headers(auth_client),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "error"
    assert body["last_checked_at"] is not None
    assert USERNAME not in response.text
    assert ACCESS_KEY not in response.text
    assert len(body["last_error"]) <= 500

    row = stored_row(db_session, company_row["id"])
    assert row.last_error is not None
    assert USERNAME not in row.last_error
    assert ACCESS_KEY not in row.last_error


def test_a_corrupt_ciphertext_is_a_generic_500_and_the_row_stays_as_it_was(
    auth_client: TestClient, db_session: Session
) -> None:
    """S5: an unreadable token is never decrypted into a response or a 4xx hint."""
    company_row = company(auth_client)
    save_connection(auth_client, company_row["id"])
    row = stored_row(db_session, company_row["id"])
    row.encrypted_credentials = b"not-a-fernet-token"
    db_session.flush()

    response = auth_client.post(
        f"{ORGANIZATIONS}/{company_row['id']}/connections/siigo/test",
        headers=csrf_headers(auth_client),
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Stored credentials cannot be read."}
    assert ACCESS_KEY not in response.text
    db_session.refresh(row)
    assert row.status.value == "untested"


def test_alegra_is_refused_like_world_office(auth_client: TestClient) -> None:
    """S6: every catalogued provider without an adapter is 409, not just one."""
    company_row = company(auth_client)

    response = save_connection(auth_client, company_row["id"], provider="alegra")

    assert response.status_code == 409
