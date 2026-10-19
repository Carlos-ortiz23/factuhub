"""HTTP contract of the authentication endpoints.

The service tests already prove the rules; these prove the transport: status
codes, cookies, and the CSRF check that stands between a cookie and a
state-changing request.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.main import create_app

pytestmark = pytest.mark.integration

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"

PASSWORD = "conciliacion-segura-2026"
EMAIL = "contador@example.com"
SESSION_COOKIE = "factuhub_session"
CSRF_COOKIE = "factuhub_session_csrf"
CSRF_HEADER = "X-CSRF-Token"


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    """A client whose requests use the test transaction, never the dev database."""
    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def register(
    client: TestClient,
    *,
    email: str = EMAIL,
    password: str = PASSWORD,
    full_name: str = "Contadora de prueba",
):
    return client.post(
        REGISTER,
        json={"email": email, "full_name": full_name, "password": password},
    )


def login(client: TestClient, *, email: str = EMAIL, password: str = PASSWORD):
    return client.post(LOGIN, json={"email": email, "password": password})


def csrf_value(client: TestClient) -> str:
    value = client.cookies.get(CSRF_COOKIE)
    assert value, "the CSRF cookie was not set"
    return value


def test_registration_returns_the_account_and_never_a_credential(client: TestClient) -> None:
    response = register(client)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == EMAIL
    assert body["id"]
    assert "password" not in body
    assert "password_hash" not in body


def test_registration_rejects_an_address_that_already_has_an_account(client: TestClient) -> None:
    assert register(client).status_code == 201

    duplicate = register(client, full_name="Otro nombre")

    assert duplicate.status_code == 409


def test_registration_rejects_a_password_that_breaks_the_policy(client: TestClient) -> None:
    response = register(client, password="corta")

    assert response.status_code == 422
    assert "at least" in response.json()["detail"]


def test_login_sets_an_http_only_session_cookie_and_a_readable_csrf_cookie(
    client: TestClient,
) -> None:
    register(client)

    response = login(client)

    assert response.status_code == 200
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(c for c in cookies if c.startswith(f"{SESSION_COOKIE}="))
    csrf_cookie = next(c for c in cookies if c.startswith(f"{CSRF_COOKIE}="))

    assert "HttpOnly" in session_cookie
    # Readable by the frontend, so it must NOT be HttpOnly; it is only useful
    # when the client can copy it into the header.
    assert "HttpOnly" not in csrf_cookie
    assert "samesite=lax" in session_cookie.lower()


def test_login_with_a_wrong_password_answers_with_one_generic_message(
    client: TestClient,
) -> None:
    register(client)

    response = login(client, password="otra-contrasena-larga")

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."
    assert response.cookies.get(SESSION_COOKIE) is None


def test_login_with_an_unknown_address_answers_exactly_the_same_way(
    client: TestClient,
) -> None:
    response = login(client, email="desconocido@example.com")

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


def test_the_current_user_is_available_after_signing_in(client: TestClient) -> None:
    register(client)
    login(client)

    response = client.get(ME)

    assert response.status_code == 200
    assert response.json()["email"] == EMAIL


def test_the_current_user_endpoint_refuses_an_unauthenticated_request(client: TestClient) -> None:
    assert client.get(ME).status_code == 401


def test_the_current_user_endpoint_refuses_an_invented_token(client: TestClient) -> None:
    client.cookies.set(SESSION_COOKIE, "x" * 43)

    assert client.get(ME).status_code == 401


def test_logout_revokes_the_session_and_removes_the_cookies(client: TestClient) -> None:
    register(client)
    login(client)

    response = client.post(LOGOUT, headers={CSRF_HEADER: csrf_value(client)})

    assert response.status_code == 204
    assert client.get(ME).status_code == 401
    assert client.cookies.get(SESSION_COOKIE) is None


def test_logout_without_the_csrf_header_is_refused(client: TestClient) -> None:
    register(client)
    login(client)

    assert client.post(LOGOUT).status_code == 403


def test_logout_with_a_forged_csrf_header_is_refused(client: TestClient) -> None:
    register(client)
    login(client)

    response = client.post(LOGOUT, headers={CSRF_HEADER: "not-the-token"})

    assert response.status_code == 403
    # The refusal must not have ended the session.
    assert client.get(ME).status_code == 200


def test_repeated_failures_are_throttled(client: TestClient) -> None:
    register(client)

    for _ in range(5):
        assert login(client, password="otra-contrasena-larga").status_code == 401

    blocked = login(client, password="otra-contrasena-larga")

    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0


def test_the_throttle_is_tracked_per_address(client: TestClient) -> None:
    register(client)
    register(client, email="otro@example.com", full_name="Otro")

    for _ in range(5):
        login(client, password="otra-contrasena-larga")

    # Locking one address must not lock the whole platform.
    assert login(client, email="otro@example.com").status_code == 200


def test_a_successful_sign_in_clears_the_failure_count(client: TestClient) -> None:
    register(client)
    for _ in range(4):
        login(client, password="otra-contrasena-larga")

    assert login(client).status_code == 200

    # The counter is gone, so the address gets a full budget again instead of
    # being locked out by the one attempt that follows.
    for _ in range(4):
        assert login(client, password="otra-contrasena-larga").status_code == 401


def test_a_deactivated_account_cannot_sign_in(client: TestClient, db_session: Session) -> None:
    register(client)
    db_session.execute(
        text("UPDATE users SET is_active = false WHERE email = :email"),
        {"email": EMAIL},
    )
    db_session.flush()

    assert login(client).status_code == 401
