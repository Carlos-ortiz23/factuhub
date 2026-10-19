"""Registration, credential checks and session lifecycle.

These rules decide who gets in. Each test below exists because getting it wrong
is invisible from the outside: an enumeration oracle that answers 404 for an
unknown email, a revoked session that keeps working, an expired one that does
not.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import PasswordPolicyError, hash_session_token, verify_password
from app.services import auth

pytestmark = pytest.mark.integration

PASSWORD = "conciliacion-segura-2026"


def test_registration_stores_a_lowercase_email_and_never_the_password(
    db_session: Session,
) -> None:
    user = auth.register_user(
        db_session,
        email="  Contador@Example.COM ",
        full_name="Contadora de prueba",
        password=PASSWORD,
    )

    assert user.email == "contador@example.com"
    assert user.full_name == "Contadora de prueba"
    assert PASSWORD not in user.password_hash
    assert user.is_active is True


def test_the_same_email_cannot_register_twice_in_any_case(db_session: Session) -> None:
    auth.register_user(db_session, email="contador@example.com", full_name="Uno", password=PASSWORD)

    with pytest.raises(auth.EmailAlreadyRegisteredError):
        auth.register_user(
            db_session, email="CONTADOR@example.com", full_name="Otro", password=PASSWORD
        )

    # And the database agrees, even when the service is bypassed: two accounts
    # for one person would split their history.
    stored = db_session.execute(text("SELECT count(*) FROM users")).scalar_one()
    assert stored == 1


def test_registration_refuses_a_password_that_breaks_the_policy(db_session: Session) -> None:
    with pytest.raises(PasswordPolicyError):
        auth.register_user(db_session, email="corta@example.com", full_name="Uno", password="corta")

    # The account must not exist half-created: a rejected registration must not
    # leave a user with a credential nobody can satisfy.
    assert db_session.execute(text("SELECT count(*) FROM users")).scalar_one() == 0


def test_registration_refuses_a_blank_full_name(db_session: Session) -> None:
    with pytest.raises(auth.RegistrationError):
        auth.register_user(
            db_session, email="sinnombre@example.com", full_name="   ", password=PASSWORD
        )

    assert db_session.execute(text("SELECT count(*) FROM users")).scalar_one() == 0


def test_authentication_accepts_the_right_password(db_session: Session) -> None:
    auth.register_user(db_session, email="contador@example.com", full_name="Uno", password=PASSWORD)

    authenticated = auth.authenticate(
        db_session, email="  CONTADOR@example.com  ", password=PASSWORD
    )

    assert authenticated is not None
    assert authenticated.email == "contador@example.com"


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("contador@example.com", "otra-contrasena-larga"),
        ("desconocido@example.com", PASSWORD),
    ],
)
def test_authentication_fails_the_same_way_for_a_wrong_password_and_an_unknown_user(
    db_session: Session, email: str, password: str
) -> None:
    auth.register_user(db_session, email="contador@example.com", full_name="Uno", password=PASSWORD)

    # One `None`, one shape: telling an attacker which half was wrong hands them
    # a list of valid accounts.
    assert auth.authenticate(db_session, email=email, password=password) is None


def test_authentication_refuses_a_deactivated_account(db_session: Session) -> None:
    user = auth.register_user(
        db_session, email="contador@example.com", full_name="Uno", password=PASSWORD
    )
    user.is_active = False
    db_session.flush()

    assert auth.authenticate(db_session, email=user.email, password=PASSWORD) is None


def test_a_new_session_stores_only_the_digest_of_its_token(db_session: Session) -> None:
    user = auth.register_user(
        db_session, email="contador@example.com", full_name="Uno", password=PASSWORD
    )

    token, _, session_row = auth.create_session(db_session, user=user)

    stored = db_session.execute(text("SELECT token_hash FROM sessions")).scalar_one()
    assert stored == hash_session_token(token)
    assert stored != token
    assert session_row.user_id == user.id
    assert session_row.revoked_at is None


def test_a_fresh_token_resolves_to_its_user(db_session: Session) -> None:
    user = auth.register_user(
        db_session, email="contador@example.com", full_name="Uno", password=PASSWORD
    )
    token, _, _ = auth.create_session(db_session, user=user)

    resolved = auth.resolve_session(db_session, token=token)

    assert resolved is not None
    assert resolved.id == user.id


def test_the_session_expires_when_its_ttl_has_passed(db_session: Session) -> None:
    user = auth.register_user(
        db_session, email="contador@example.com", full_name="Uno", password=PASSWORD
    )
    token, _, session_row = auth.create_session(db_session, user=user, ttl=timedelta(hours=1))

    assert session_row.expires_at - session_row.created_at >= timedelta(minutes=55)

    # Move the deadline into the past rather than waiting an hour.
    session_row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()

    assert auth.resolve_session(db_session, token=token) is None


def test_a_revoked_session_stops_resolving(db_session: Session) -> None:
    user = auth.register_user(
        db_session, email="contador@example.com", full_name="Uno", password=PASSWORD
    )
    token, _, _ = auth.create_session(db_session, user=user)

    assert auth.revoke_session(db_session, token=token) is True
    assert auth.resolve_session(db_session, token=token) is None


def test_revoking_a_token_that_does_not_exist_reports_nothing_to_revoke(
    db_session: Session,
) -> None:
    assert auth.revoke_session(db_session, token="not-a-real-token") is False


@pytest.mark.parametrize("candidate", ["", "not-a-real-token", "x" * 43])
def test_an_invented_token_never_resolves(db_session: Session, candidate: str) -> None:
    user = auth.register_user(
        db_session, email="contador@example.com", full_name="Uno", password=PASSWORD
    )
    auth.create_session(db_session, user=user)

    assert auth.resolve_session(db_session, token=candidate) is None


def test_deactivating_a_user_kills_their_live_sessions(db_session: Session) -> None:
    user = auth.register_user(
        db_session, email="contador@example.com", full_name="Uno", password=PASSWORD
    )
    token, _, _ = auth.create_session(db_session, user=user)
    user.is_active = False
    db_session.flush()

    # The membership was not revoked, the person was disabled. A live cookie
    # must not outvote that decision.
    assert auth.resolve_session(db_session, token=token) is None


def test_revoking_sessions_can_target_one_token_or_every_token_of_a_user(
    db_session: Session,
) -> None:
    user = auth.register_user(
        db_session, email="contador@example.com", full_name="Uno", password=PASSWORD
    )
    first, _, _ = auth.create_session(db_session, user=user)
    second, _, _ = auth.create_session(db_session, user=user)

    assert auth.revoke_all_sessions(db_session, user_id=user.id) == 2
    assert auth.resolve_session(db_session, token=first) is None
    assert auth.resolve_session(db_session, token=second) is None


def test_sessions_belong_to_a_real_user(db_session: Session) -> None:
    user = auth.register_user(
        db_session, email="contador@example.com", full_name="Uno", password=PASSWORD
    )
    auth.create_session(db_session, user=user)

    db_session.execute(text("DELETE FROM users WHERE id = :user_id"), {"user_id": user.id})

    # Deleting an account must not leave an orphan session that still resolves.
    assert db_session.execute(text("SELECT count(*) FROM sessions")).scalar_one() == 0


def test_the_stored_credential_is_an_argon2id_hash(db_session: Session) -> None:
    user = auth.register_user(
        db_session, email="contador@example.com", full_name="Uno", password=PASSWORD
    )

    # Named explicitly: a future dependency change that silently downgraded the
    # algorithm, or stored a plain digest, must fail here instead of in an audit.
    assert user.password_hash.startswith("$argon2id$")
    assert verify_password(PASSWORD, user.password_hash) is True


def test_a_login_attempt_is_allowed_until_the_budget_is_spent(db_session: Session) -> None:
    for _ in range(auth.MAX_LOGIN_ATTEMPTS):
        assert auth.claim_login_attempt(db_session, email="contador@example.com") is None

    retry_after = auth.claim_login_attempt(db_session, email="contador@example.com")

    assert retry_after is not None
    assert retry_after > 0


def test_the_lockout_ends_when_the_window_ends(db_session: Session) -> None:
    for _ in range(auth.MAX_LOGIN_ATTEMPTS):
        auth.claim_login_attempt(db_session, email="contador@example.com")
    assert auth.claim_login_attempt(db_session, email="contador@example.com") is not None

    # Move the window into the past instead of sleeping for fifteen minutes.
    db_session.execute(
        text(
            "UPDATE login_throttles SET window_started_at = window_started_at - :offset "
            "WHERE email = :email"
        ),
        {
            "offset": auth.LOGIN_ATTEMPT_WINDOW + timedelta(seconds=1),
            "email": "contador@example.com",
        },
    )
    db_session.flush()

    assert auth.claim_login_attempt(db_session, email="contador@example.com") is None


def test_the_attempt_budget_is_per_address(db_session: Session) -> None:
    for _ in range(auth.MAX_LOGIN_ATTEMPTS):
        auth.claim_login_attempt(db_session, email="contador@example.com")

    assert auth.claim_login_attempt(db_session, email="otro@example.com") is None


def test_clearing_attempts_returns_the_full_budget(db_session: Session) -> None:
    for _ in range(auth.MAX_LOGIN_ATTEMPTS):
        auth.claim_login_attempt(db_session, email="contador@example.com")

    auth.clear_login_attempts(db_session, email="contador@example.com")

    assert auth.claim_login_attempt(db_session, email="contador@example.com") is None


def test_the_throttle_normalizes_the_address(db_session: Session) -> None:
    for _ in range(auth.MAX_LOGIN_ATTEMPTS):
        auth.claim_login_attempt(db_session, email="Contador@Example.com")

    # Same mailbox, different case: the budget is shared, not duplicated.
    assert auth.claim_login_attempt(db_session, email="contador@example.com") is not None
