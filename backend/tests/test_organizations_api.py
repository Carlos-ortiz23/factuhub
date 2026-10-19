"""Organization endpoints: tenancy, roles and the no-existence-oracle rule.

The important assertions here are not the happy paths. They are:

* a company's data is invisible to somebody who is not a member, and the answer
  is 404 rather than 403, so the API never confirms that a company exists;
* creating a company makes the creator its admin, in one transaction;
* a state-changing request without the CSRF token is refused.

RBAC denial (403) is not reachable yet: every role holds READ, so the only
permission any route enforces today is one nobody lacks. The first genuine 403
arrives with the membership endpoints, which require MANAGE_MEMBERS, and the
denial tests are written there.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

ORGANIZATIONS = "/api/v1/organizations"
CSRF_COOKIE = "factuhub_session_csrf"
CSRF_HEADER = "X-CSRF-Token"

SECOND_EMAIL = "revisor@example.com"
SECOND_PASSWORD = "conciliacion-segura-2026"


def csrf_headers(client: TestClient) -> dict[str, str]:
    """The readable cookie, echoed in the header, as the frontend will do it."""
    return {CSRF_HEADER: client.cookies[CSRF_COOKIE]}


def second_user_client(client: TestClient) -> TestClient:
    """A separate cookie jar on the same app, for a different person.

    A different jar, not a different database: both users write to the same
    session, which is exactly what makes the isolation assertion meaningful.
    """
    app = client.app
    other = TestClient(app)
    other.post(
        "/api/v1/auth/register",
        json={"email": SECOND_EMAIL, "full_name": "Revisor", "password": SECOND_PASSWORD},
    )
    other.post("/api/v1/auth/login", json={"email": SECOND_EMAIL, "password": SECOND_PASSWORD})
    return other


def create_organization(client: TestClient, *, tax_id: str = "900123456-7") -> dict:
    response = client.post(
        ORGANIZATIONS,
        json={"name": "Ferretería La Tuerca S.A.S.", "tax_id": tax_id},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_an_authenticated_user_can_create_a_company(auth_client: TestClient) -> None:
    company = create_organization(auth_client)

    assert company["name"] == "Ferretería La Tuerca S.A.S."
    assert company["tax_id"] == "900123456-7"
    # The creator is the admin, without a second request to make it so.
    assert company["role"] == "admin"


def test_creating_a_company_requires_the_csrf_token(auth_client: TestClient) -> None:
    response = auth_client.post(ORGANIZATIONS, json={"name": "Sin token", "tax_id": "900000001-1"})

    assert response.status_code == 403


def test_creating_a_company_requires_a_session() -> None:
    from app.main import create_app

    with TestClient(create_app()) as anonymous:
        assert anonymous.get(ORGANIZATIONS).status_code == 401
        assert anonymous.post(ORGANIZATIONS, json={}).status_code == 401


def test_two_companies_cannot_share_a_tax_id(auth_client: TestClient) -> None:
    create_organization(auth_client, tax_id="900555555-5")

    response = auth_client.post(
        ORGANIZATIONS,
        json={"name": "Otra razón social, mismo NIT", "tax_id": "900555555-5"},
        headers=csrf_headers(auth_client),
    )

    assert response.status_code == 409
    # The database is the guarantee; this proves the endpoint translated it
    # instead of returning a 500.
    assert "tax" in response.json()["detail"].lower()


def test_the_list_contains_only_my_companies(auth_client: TestClient) -> None:
    mine = create_organization(auth_client, tax_id="901000001-1")

    with second_user_client(auth_client) as other:
        theirs = create_organization(other, tax_id="901000002-2")
        their_list = other.get(ORGANIZATIONS).json()["organizations"]
        assert [org["id"] for org in their_list] == [theirs["id"]]

    my_list = auth_client.get(ORGANIZATIONS).json()["organizations"]
    assert [org["id"] for org in my_list] == [mine["id"]]


def test_another_company_is_not_found_rather_than_forbidden(auth_client: TestClient) -> None:
    with second_user_client(auth_client) as other:
        theirs = create_organization(other, tax_id="901000003-3")

        response = auth_client.get(f"{ORGANIZATIONS}/{theirs['id']}")

    # 403 would confirm the identifier belongs to a real company. 404 keeps the
    # API from being an enumeration oracle.
    assert response.status_code == 404


def test_a_member_can_read_their_own_company(auth_client: TestClient) -> None:
    created = create_organization(auth_client)

    response = auth_client.get(f"{ORGANIZATIONS}/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]
    assert response.json()["role"] == "admin"


def test_a_malformed_company_id_is_refused_not_a_crash(auth_client: TestClient) -> None:
    response = auth_client.get(f"{ORGANIZATIONS}/not-a-uuid")

    assert response.status_code == 422


def test_a_blank_company_name_is_refused(auth_client: TestClient) -> None:
    response = auth_client.post(
        ORGANIZATIONS,
        json={"name": "   ", "tax_id": "901000009-9"},
        headers=csrf_headers(auth_client),
    )

    assert response.status_code == 422
