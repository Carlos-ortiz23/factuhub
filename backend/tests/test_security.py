"""Credential handling: how a secret is stored and how a token is minted.

These tests are pure unit tests. They do not need a database, a request or a
clock, because the rules they protect are the kind that are easy to get subtly
wrong and impossible to notice from the outside: a password stored in the clear,
a session token that repeats, a verification that raises instead of returning
false.
"""

from __future__ import annotations

import pytest

from app.core.security import (
    PASSWORD_MAX_LENGTH,
    SESSION_TOKEN_BYTES,
    SESSION_TOKEN_LENGTH,
    PasswordPolicyError,
    generate_session_token,
    hash_password,
    hash_session_token,
    verify_password,
)

VALID_PASSWORD = "conciliacion-segura-2026"


def test_hash_is_not_the_password_and_verifies_against_it() -> None:
    password_hash = hash_password(VALID_PASSWORD)

    assert VALID_PASSWORD not in password_hash
    assert verify_password(VALID_PASSWORD, password_hash) is True


def test_the_same_password_hashes_differently_every_time() -> None:
    first = hash_password(VALID_PASSWORD)
    second = hash_password(VALID_PASSWORD)

    # A salt per hash. Without it, two users with the same password would share
    # a digest, and one leaked table would reveal who shares passwords.
    assert first != second
    assert verify_password(VALID_PASSWORD, second) is True


def test_a_wrong_password_is_rejected() -> None:
    password_hash = hash_password(VALID_PASSWORD)

    assert verify_password("conciliacion-segura-2027", password_hash) is False


@pytest.mark.parametrize(
    "malformed_hash",
    [
        "",
        "not-a-hash",
        "$argon2id$v=19$m=65536,t=3,p=4$truncated",
        "$2b$12$abcdefghijklmnopqrstuv",
    ],
)
def test_a_malformed_stored_hash_is_rejected_instead_of_crashing(malformed_hash: str) -> None:
    # A stored hash can be corrupted by a bad migration or a hand-edited row.
    # The login endpoint must answer "no" rather than return a 500 or, worse,
    # leak a stack trace that reveals the algorithm.
    assert verify_password(VALID_PASSWORD, malformed_hash) is False


@pytest.mark.parametrize("password", ["", "corta", "contrasena1", "a" * 11])
def test_passwords_below_the_minimum_length_are_refused(password: str) -> None:
    with pytest.raises(PasswordPolicyError):
        hash_password(password)


def test_a_password_of_exactly_the_minimum_length_is_accepted() -> None:
    assert verify_password("a" * 12, hash_password("a" * 12)) is True


def test_absurdly_long_passwords_are_refused() -> None:
    # Hashing is deliberately expensive; a megabyte "password" is a way to make
    # the server spend that cost on someone else's behalf.
    with pytest.raises(PasswordPolicyError):
        hash_password("a" * (PASSWORD_MAX_LENGTH + 1))


def test_session_tokens_are_url_safe_random_strings() -> None:
    token = generate_session_token()

    assert len(token) == SESSION_TOKEN_LENGTH
    assert set(token) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    # 32 random bytes is 256 bits; a collision would be a textbook catastrophe.
    assert generate_session_token() != generate_session_token()


def test_token_digest_is_stable_and_does_not_reveal_the_token() -> None:
    token = generate_session_token()
    digest = hash_session_token(token)

    assert digest == hash_session_token(token)
    assert len(digest) == 64
    assert token not in digest
    assert SESSION_TOKEN_BYTES == 32
