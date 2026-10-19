"""Membership endpoints: the first routes that can actually refuse a request.

Every role holds READ, so until now no route could return 403. These routes
require MANAGE_MEMBERS, which only an admin has, and the denial tests below are
written role by role rather than once: an authorization check that refuses the
wrong role for the wrong reason is not a check.

The other invariant under test is that a company never runs out of admins. That
one is not merely a validation: two admins demoting themselves at the same time
would each see the other and both succeed, so the operation takes a lock on the
company first.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

ORGANIZATIONS = "/api/v1/organizations"
CSRF_COOKIE = "factuhub_session_csrf"
CSRF_HEADER = "X-CSRF-Token"

PASSWORD = "conciliacion-segura-2026"


def csrf_headers(client: TestClient) -> dict[str, str]:
    return {CSRF_HEADER: client.cookies[CSRF_COOKIE]}


def register_account(client: TestClient, email: str, full_name: str = "Persona de prueba") -> None:
    """Create the account, so it can be added to a company.

    Idempotent by intent: several tests add a person and then also sign that
    person in, and registration answering 409 the second time is not a failure.
    """
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "full_name": full_name, "password": PASSWORD},
    )


def person(client: TestClient, email: str, full_name: str = "Persona de prueba") -> TestClient:
    """A second signed-in person on the same app.

    A separate cookie jar over the same database session, so "not a member" and
    "a member with the wrong role" are tested against real rows.
    """
    register_account(client, email, full_name)
    other = TestClient(client.app)
    other.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    return other


def company(client: TestClient, tax_id: str = "900123456-7") -> dict:
    response = client.post(
        ORGANIZATIONS,
        json={"name": "Distribuidora El Roble S.A.S.", "tax_id": tax_id},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def add_member(client: TestClient, organization_id: str, email: str, role: str) -> dict:
    # The account must exist first: the platform has no invitations yet, and the
    # endpoint refuses an address with no account rather than pretending.
    register_account(client, email)
    response = client.post(
        f"{ORGANIZATIONS}/{organization_id}/members",
        json={"email": email, "role": role},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_an_admin_adds_a_member_by_email(auth_client: TestClient) -> None:
    php = company(auth_client)

    member = add_member(auth_client, php["id"], "auxiliar@example.com", "accountant")

    assert member["email"] == "auxiliar@example.com"
    assert member["role"] == "accountant"
    assert "user_id" in member


def test_an_admin_can_change_a_role(auth_client: TestClient) -> None:
    php = company(auth_client)
    member = add_member(auth_client, php["id"], "cambiante@example.com", "viewer")

    with person(auth_client, "cambiante@example.com") as subject:
        assert subject.get(f"{ORGANIZATIONS}/{php['id']}").json()["role"] == "viewer"

        response = auth_client.patch(
            f"{ORGANIZATIONS}/{php['id']}/members/{member['user_id']}",
            json={"role": "reviewer"},
            headers=csrf_headers(auth_client),
        )
        assert response.status_code == 200
        assert response.json()["role"] == "reviewer"

        # The change is visible to the affected person on their next request: the
        # role is read from the database, not carried in their session.
        assert subject.get(f"{ORGANIZATIONS}/{php['id']}").json()["role"] == "reviewer"


def test_a_viewer_cannot_add_a_member(auth_client: TestClient) -> None:
    php = company(auth_client)
    add_member(auth_client, php["id"], "mirona@example.com", "viewer")

    with person(auth_client, "mirona@example.com") as viewer:
        response = viewer.post(
            f"{ORGANIZATIONS}/{php['id']}/members",
            json={"email": "colado@example.com", "role": "admin"},
            headers=csrf_headers(viewer),
        )

    assert response.status_code == 403


def test_an_accountant_cannot_change_a_role(auth_client: TestClient) -> None:
    # The accountant can import and reconcile but not decide who else may. The
    # refusal is per permission, not per "is this an admin route".
    php = company(auth_client)
    add_member(auth_client, php["id"], "contadora@example.com", "accountant")
    victim = add_member(auth_client, php["id"], "objetivo@example.com", "viewer")

    with person(auth_client, "contadora@example.com") as accountant:
        response = accountant.patch(
            f"{ORGANIZATIONS}/{php['id']}/members/{victim['user_id']}",
            json={"role": "admin"},
            headers=csrf_headers(accountant),
        )

    assert response.status_code == 403


def test_a_reviewer_cannot_remove_a_member(auth_client: TestClient) -> None:
    php = company(auth_client)
    add_member(auth_client, php["id"], "revisora@example.com", "reviewer")
    victim = add_member(auth_client, php["id"], "afectada@example.com", "viewer")

    with person(auth_client, "revisora@example.com") as reviewer:
        response = reviewer.delete(
            f"{ORGANIZATIONS}/{php['id']}/members/{victim['user_id']}",
            headers=csrf_headers(reviewer),
        )

    assert response.status_code == 403


def test_a_stranger_gets_404_and_not_403(auth_client: TestClient) -> None:
    php = company(auth_client)

    with person(auth_client, "ajena@example.com") as stranger:
        response = stranger.post(
            f"{ORGANIZATIONS}/{php['id']}/members",
            json={"email": "colado@example.com", "role": "viewer"},
            headers=csrf_headers(stranger),
        )

    # Not a member at all: the company must not be confirmed to exist, so the
    # answer is the same as for a company id that was never real.
    assert response.status_code == 404


def test_adding_an_address_with_no_account_is_a_404(auth_client: TestClient) -> None:
    php = company(auth_client)

    response = auth_client.post(
        f"{ORGANIZATIONS}/{php['id']}/members",
        json={"email": "nadie@example.com", "role": "viewer"},
        headers=csrf_headers(auth_client),
    )

    # The platform does not send invitations yet, so the only honest answer is
    # that there is no account to add. This does reveal account existence to an
    # admin of a company; recorded as a known trade-off in the feature document.
    assert response.status_code == 404
    assert "account" in response.json()["detail"].lower()


def test_the_same_person_cannot_be_added_twice(auth_client: TestClient) -> None:
    php = company(auth_client)
    add_member(auth_client, php["id"], "repetida@example.com", "viewer")

    response = auth_client.post(
        f"{ORGANIZATIONS}/{php['id']}/members",
        json={"email": "repetida@example.com", "role": "reviewer"},
        headers=csrf_headers(auth_client),
    )

    assert response.status_code == 409


def test_the_last_admin_cannot_be_demoted(auth_client: TestClient) -> None:
    php = company(auth_client)
    me = auth_client.get(f"{ORGANIZATIONS}/{php['id']}").json()
    assert me["role"] == "admin"
    my_id = auth_client.get("/api/v1/auth/me").json()["id"]

    response = auth_client.patch(
        f"{ORGANIZATIONS}/{php['id']}/members/{my_id}",
        json={"role": "viewer"},
        headers=csrf_headers(auth_client),
    )

    # A company with no admin could not be recovered from inside the product.
    assert response.status_code == 409
    assert auth_client.get(f"{ORGANIZATIONS}/{php['id']}").json()["role"] == "admin"


def test_the_last_admin_cannot_be_removed(auth_client: TestClient) -> None:
    php = company(auth_client)
    my_id = auth_client.get("/api/v1/auth/me").json()["id"]

    response = auth_client.delete(
        f"{ORGANIZATIONS}/{php['id']}/members/{my_id}",
        headers=csrf_headers(auth_client),
    )

    assert response.status_code == 409


def test_an_admin_can_be_demoted_once_another_admin_exists(auth_client: TestClient) -> None:
    # The guard must not be "the first admin is permanent": with a second admin,
    # the original can step down.
    php = company(auth_client)
    second = add_member(auth_client, php["id"], "segundo@example.com", "admin")
    my_id = auth_client.get("/api/v1/auth/me").json()["id"]

    response = auth_client.patch(
        f"{ORGANIZATIONS}/{php['id']}/members/{my_id}",
        json={"role": "accountant"},
        headers=csrf_headers(auth_client),
    )

    assert response.status_code == 200
    assert response.json()["role"] == "accountant"
    assert second["role"] == "admin"


def test_removing_a_member_revokes_their_access(auth_client: TestClient) -> None:
    php = company(auth_client)
    member = add_member(auth_client, php["id"], "saliente@example.com", "viewer")

    with person(auth_client, "saliente@example.com") as leaving:
        assert leaving.get(f"{ORGANIZATIONS}/{php['id']}").status_code == 200

        response = auth_client.delete(
            f"{ORGANIZATIONS}/{php['id']}/members/{member['user_id']}",
            headers=csrf_headers(auth_client),
        )
        assert response.status_code == 204

        # Their session is intact and their account still works; what they lost
        # is the membership.
        assert leaving.get("/api/v1/auth/me").status_code == 200
        assert leaving.get(f"{ORGANIZATIONS}/{php['id']}").status_code == 404


def test_removing_somebody_who_is_not_a_member_is_a_404(auth_client: TestClient) -> None:
    php = company(auth_client)
    with person(auth_client, "externa@example.com") as outsider:
        outsider_id = outsider.get("/api/v1/auth/me").json()["id"]

    response = auth_client.delete(
        f"{ORGANIZATIONS}/{php['id']}/members/{outsider_id}",
        headers=csrf_headers(auth_client),
    )

    assert response.status_code == 404


def test_managing_members_requires_the_csrf_token(auth_client: TestClient) -> None:
    php = company(auth_client)

    response = auth_client.post(
        f"{ORGANIZATIONS}/{php['id']}/members",
        json={"email": "sintoken@example.com", "role": "viewer"},
    )

    assert response.status_code == 403


def test_an_unknown_role_is_refused(auth_client: TestClient) -> None:
    php = company(auth_client)

    response = auth_client.post(
        f"{ORGANIZATIONS}/{php['id']}/members",
        json={"email": "raro@example.com", "role": "superadmin"},
        headers=csrf_headers(auth_client),
    )

    assert response.status_code == 422
