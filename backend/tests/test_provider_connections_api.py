"""Provider connection endpoints: storage, permissions, and honest statuses.

The tests that matter most here are the negative ones. A connection endpoint that
returns credentials, accepts an unknown provider, or reports `connected` without
calling anybody would look perfectly fine in the happy path and be worthless in
production.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_connector_factory
from app.core.config import get_settings
from app.core.crypto import CredentialCipher
from app.integrations.base import ConnectionCheck
from app.models import AuditLog, ProviderCredential

pytestmark = pytest.mark.integration

ORGANIZATIONS = "/api/v1/organizations"
CSRF_COOKIE = "factuhub_session_csrf"
CSRF_HEADER = "X-CSRF-Token"

PASSWORD = "conciliacion-segura-2026"
USERNAME = "contador-siigo@example.com"
ACCESS_KEY = "clave-de-acceso-que-no-debe-salir"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def csrf_headers(client: TestClient) -> dict[str, str]:
    return {CSRF_HEADER: client.cookies[CSRF_COOKIE]}


def register_account(client: TestClient, email: str) -> None:
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "full_name": "Persona de prueba", "password": PASSWORD},
    )


def person(client: TestClient, email: str) -> TestClient:
    register_account(client, email)
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


def add_member(client: TestClient, organization_id: str, email: str, role: str) -> None:
    register_account(client, email)
    response = client.post(
        f"{ORGANIZATIONS}/{organization_id}/members",
        json={"email": email, "role": role},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text


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


class FakeConnector:
    """A stand-in adapter that records what the service decrypted for it."""

    def __init__(self, result: ConnectionCheck, seen: dict[str, Any]) -> None:
        self._result = result
        self._seen = seen
        self.closed = False

    async def test_connection(self) -> ConnectionCheck:
        return self._result

    async def aclose(self) -> None:
        self.closed = True


def fake_factory(result: ConnectionCheck | None = None, seen: dict[str, Any] | None = None):
    """Build a connector factory and the dict it writes its observations into."""
    observations = seen if seen is not None else {}
    outcome = result or ConnectionCheck(ok=True)

    def factory(provider: str, credentials: dict[str, str]) -> FakeConnector:
        observations["provider"] = provider
        observations["credentials"] = dict(credentials)
        connector = FakeConnector(outcome, observations)
        observations["connector"] = connector
        return connector

    return factory, observations


@pytest.fixture
def cipher() -> CredentialCipher:
    return CredentialCipher.from_key(get_settings().credentials_encryption_key)


# --------------------------------------------------------------------------
# Happy path and the no-secrets invariant
# --------------------------------------------------------------------------


def test_an_admin_saves_a_connection_and_never_sees_the_secret(
    auth_client: TestClient,
) -> None:
    company_row = company(auth_client)

    response = save_connection(auth_client, company_row["id"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "siigo"
    assert body["provider_name"] == "Siigo"
    assert body["mode"] == "api"
    assert body["status"] == "untested"
    assert body["last_checked_at"] is None
    assert body["last_error"] is None
    assert ACCESS_KEY not in response.text
    assert USERNAME not in response.text
    assert "access_key" not in response.text


def test_the_list_never_returns_credentials(auth_client: TestClient) -> None:
    company_row = company(auth_client)
    save_connection(auth_client, company_row["id"])

    response = auth_client.get(f"{ORGANIZATIONS}/{company_row['id']}/connections")

    assert response.status_code == 200
    assert len(response.json()["connections"]) == 1
    assert ACCESS_KEY not in response.text
    assert USERNAME not in response.text


def test_the_database_stores_ciphertext_bound_to_the_company(
    auth_client: TestClient, db_session: Session, cipher: CredentialCipher
) -> None:
    company_row = company(auth_client)
    save_connection(auth_client, company_row["id"])

    row = db_session.scalar(select(ProviderCredential))
    assert row is not None
    assert ACCESS_KEY.encode() not in row.encrypted_credentials
    assert USERNAME.encode() not in row.encrypted_credentials

    decrypted = cipher.decrypt(
        row.encrypted_credentials,
        organization_id=row.organization_id,
        provider=row.provider,
    )
    assert decrypted == {"username": USERNAME, "access_key": ACCESS_KEY}


def test_replacing_credentials_resets_the_observed_status(
    auth_client: TestClient,
) -> None:
    company_row = company(auth_client)
    save_connection(auth_client, company_row["id"])

    factory, _ = fake_factory()
    auth_client.app.dependency_overrides[get_connector_factory] = lambda: factory
    tested = auth_client.post(
        f"{ORGANIZATIONS}/{company_row['id']}/connections/siigo/test",
        headers=csrf_headers(auth_client),
    )
    assert tested.json()["status"] == "connected"

    replaced = save_connection(
        auth_client,
        company_row["id"],
        credentials={"username": "otra-cuenta@example.com", "access_key": "otra-clave"},
    )

    assert replaced.status_code == 200
    assert replaced.json()["status"] == "untested"
    assert replaced.json()["last_checked_at"] is None


# --------------------------------------------------------------------------
# Permissions
# --------------------------------------------------------------------------


def test_an_accountant_can_manage_connections(auth_client: TestClient) -> None:
    company_row = company(auth_client)
    add_member(auth_client, company_row["id"], "auxiliar@example.com", "accountant")

    with person(auth_client, "auxiliar@example.com") as accountant:
        response = save_connection(accountant, company_row["id"])

    assert response.status_code == 200, response.text


@pytest.mark.parametrize("role", ["reviewer", "viewer"])
def test_read_only_roles_cannot_save_or_test(auth_client: TestClient, role: str) -> None:
    company_row = company(auth_client)
    email = f"{role}-conexiones@example.com"
    add_member(auth_client, company_row["id"], email, role)

    with person(auth_client, email) as subject:
        saved = save_connection(subject, company_row["id"])
        tested = subject.post(
            f"{ORGANIZATIONS}/{company_row['id']}/connections/siigo/test",
            headers=csrf_headers(subject),
        )

    assert saved.status_code == 403
    assert tested.status_code == 403


@pytest.mark.parametrize("role", ["reviewer", "viewer"])
def test_read_only_roles_can_read_the_status(auth_client: TestClient, role: str) -> None:
    company_row = company(auth_client)
    save_connection(auth_client, company_row["id"])
    email = f"{role}-lectura@example.com"
    add_member(auth_client, company_row["id"], email, role)

    with person(auth_client, email) as subject:
        response = subject.get(f"{ORGANIZATIONS}/{company_row['id']}/connections")

    assert response.status_code == 200
    assert response.json()["connections"][0]["status"] == "untested"


def test_a_non_member_gets_404_not_403(auth_client: TestClient) -> None:
    company_row = company(auth_client)

    with person(auth_client, "ajena@example.com") as outsider:
        saved = save_connection(outsider, company_row["id"])
        listed = outsider.get(f"{ORGANIZATIONS}/{company_row['id']}/connections")

    # A 403 would confirm the company exists; the platform does not reveal that.
    assert saved.status_code == 404
    assert listed.status_code == 404


def test_another_company_cannot_reach_this_connection(auth_client: TestClient) -> None:
    first = company(auth_client)
    save_connection(auth_client, first["id"])

    with person(auth_client, "otra-empresa@example.com") as other:
        second = company(other, tax_id="901555000-1")

        listed = other.get(f"{ORGANIZATIONS}/{second['id']}/connections")
        stolen = save_connection(other, first["id"])
        tested = other.post(
            f"{ORGANIZATIONS}/{first['id']}/connections/siigo/test",
            headers=csrf_headers(other),
        )

    assert listed.json() == {"connections": []}
    assert stolen.status_code == 404
    assert tested.status_code == 404


@pytest.mark.parametrize("method", ["put", "delete", "post_test"])
def test_writes_require_a_csrf_token(auth_client: TestClient, method: str) -> None:
    company_row = company(auth_client)
    save_connection(auth_client, company_row["id"])
    base = f"{ORGANIZATIONS}/{company_row['id']}/connections/siigo"

    if method == "put":
        response = auth_client.put(base, json={"credentials": {"username": "u", "access_key": "k"}})
    elif method == "delete":
        response = auth_client.delete(base)
    else:
        response = auth_client.post(f"{base}/test")

    assert response.status_code == 403


# --------------------------------------------------------------------------
# Provider validation
# --------------------------------------------------------------------------


def test_an_unknown_provider_is_404(auth_client: TestClient) -> None:
    company_row = company(auth_client)

    response = save_connection(auth_client, company_row["id"], provider="inventado")

    assert response.status_code == 404


def test_a_catalogued_provider_without_an_adapter_is_409(
    auth_client: TestClient,
) -> None:
    company_row = company(auth_client)

    response = save_connection(auth_client, company_row["id"], provider="world_office")

    # The catalogue knows the provider; the platform cannot connect it yet, and
    # saying so is better than accepting credentials nobody will ever use.
    assert response.status_code == 409


@pytest.mark.parametrize(
    "credentials",
    [
        {"username": USERNAME},
        {"username": USERNAME, "access_key": ACCESS_KEY, "extra": "x"},
        {"username": "   ", "access_key": ACCESS_KEY},
        {"username": USERNAME, "access_key": ""},
    ],
)
def test_an_incomplete_credential_set_is_refused(
    auth_client: TestClient, credentials: dict[str, str]
) -> None:
    company_row = company(auth_client)

    response = save_connection(auth_client, company_row["id"], credentials=credentials)

    assert response.status_code == 422
    assert ACCESS_KEY not in response.text or not credentials.get("access_key")


# --------------------------------------------------------------------------
# The test endpoint tells the truth
# --------------------------------------------------------------------------


def test_a_successful_test_stores_connected_and_receives_decrypted_credentials(
    auth_client: TestClient,
) -> None:
    company_row = company(auth_client)
    save_connection(auth_client, company_row["id"])
    factory, seen = fake_factory()
    auth_client.app.dependency_overrides[get_connector_factory] = lambda: factory

    response = auth_client.post(
        f"{ORGANIZATIONS}/{company_row['id']}/connections/siigo/test",
        headers=csrf_headers(auth_client),
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "connected"
    assert response.json()["last_checked_at"] is not None
    assert response.json()["last_error"] is None
    assert seen["provider"] == "siigo"
    assert seen["credentials"] == {"username": USERNAME, "access_key": ACCESS_KEY}
    assert seen["connector"].closed is True


def test_a_failed_test_stores_a_sanitized_reason(
    auth_client: TestClient,
) -> None:
    company_row = company(auth_client)
    save_connection(auth_client, company_row["id"])
    # The adapter is supposed to redact; this checks the second lock in the
    # service, which must survive a future adapter regression.
    factory, _ = fake_factory(ConnectionCheck(ok=False, error=f"Invalid access key {ACCESS_KEY}"))
    auth_client.app.dependency_overrides[get_connector_factory] = lambda: factory

    response = auth_client.post(
        f"{ORGANIZATIONS}/{company_row['id']}/connections/siigo/test",
        headers=csrf_headers(auth_client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert "[redacted]" in body["last_error"]
    assert ACCESS_KEY not in response.text


def test_testing_without_a_stored_connection_is_404(auth_client: TestClient) -> None:
    company_row = company(auth_client)

    response = auth_client.post(
        f"{ORGANIZATIONS}/{company_row['id']}/connections/siigo/test",
        headers=csrf_headers(auth_client),
    )

    assert response.status_code == 404


# --------------------------------------------------------------------------
# Revocation and audit
# --------------------------------------------------------------------------


def test_revoking_deletes_the_credentials_and_the_list_is_empty(
    auth_client: TestClient, db_session: Session
) -> None:
    company_row = company(auth_client)
    save_connection(auth_client, company_row["id"])

    response = auth_client.delete(
        f"{ORGANIZATIONS}/{company_row['id']}/connections/siigo",
        headers=csrf_headers(auth_client),
    )

    assert response.status_code == 204
    assert db_session.scalar(select(ProviderCredential)) is None
    listed = auth_client.get(f"{ORGANIZATIONS}/{company_row['id']}/connections")
    assert listed.json() == {"connections": []}


def test_revoking_an_absent_connection_is_404(auth_client: TestClient) -> None:
    company_row = company(auth_client)

    response = auth_client.delete(
        f"{ORGANIZATIONS}/{company_row['id']}/connections/siigo",
        headers=csrf_headers(auth_client),
    )

    assert response.status_code == 404


def test_the_audit_trail_records_the_lifecycle_without_secrets(
    auth_client: TestClient, db_session: Session
) -> None:
    company_row = company(auth_client)
    save_connection(auth_client, company_row["id"])
    factory, _ = fake_factory()
    auth_client.app.dependency_overrides[get_connector_factory] = lambda: factory
    auth_client.post(
        f"{ORGANIZATIONS}/{company_row['id']}/connections/siigo/test",
        headers=csrf_headers(auth_client),
    )
    auth_client.delete(
        f"{ORGANIZATIONS}/{company_row['id']}/connections/siigo",
        headers=csrf_headers(auth_client),
    )

    entries = list(
        db_session.scalars(
            select(AuditLog)
            .where(AuditLog.organization_id == company_row["id"])
            .order_by(AuditLog.created_at)
        )
    )
    actions = [entry.action for entry in entries]
    assert "provider_connection.created" in actions
    assert "provider_connection.tested" in actions
    assert "provider_connection.revoked" in actions

    stored = " ".join(str(entry.metadata_json) for entry in entries)
    assert ACCESS_KEY not in stored
    assert USERNAME not in stored


def test_audit_metadata_refuses_a_lookalike_secret_key() -> None:
    """The guard exists so a future caller cannot quietly store a credential."""
    from app.services.audit import UnsafeAuditMetadataError, _reject_secret_keys

    with pytest.raises(UnsafeAuditMetadataError):
        _reject_secret_keys({"provider": {"access_key": "leak"}})


def test_a_rejected_payload_never_echoes_the_secret(
    auth_client: TestClient,
) -> None:
    company_row = company(auth_client)
    oversized = "x" * 600  # exceeds the documented credential length

    response = save_connection(
        auth_client,
        company_row["id"],
        credentials={"username": USERNAME, "access_key": oversized},
    )

    assert response.status_code == 422
    # FastAPI's default validation body repeats the submitted value under
    # `input`. For a credentials endpoint that is a secret written into an error
    # response, and possibly into any proxy that logs it.
    assert oversized not in response.text
