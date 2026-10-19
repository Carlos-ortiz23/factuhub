"""Credential encryption: the properties the storage design depends on."""

from __future__ import annotations

import base64
from uuid import uuid4

import pytest

from app.core.crypto import CredentialCipher, CredentialEncryptionError

pytestmark = pytest.mark.unit

ORG = uuid4()
OTHER_ORG = uuid4()
CREDENTIALS = {"username": "contador@example.com", "access_key": "super-secret-key"}


def cipher(key_byte: bytes = b"0") -> CredentialCipher:
    return CredentialCipher.from_key(base64.urlsafe_b64encode(key_byte * 32).decode())


def test_a_round_trip_returns_exactly_what_was_stored() -> None:
    token = cipher().encrypt(CREDENTIALS, organization_id=ORG, provider="siigo")

    assert cipher().decrypt(token, organization_id=ORG, provider="siigo") == CREDENTIALS


def test_the_ciphertext_contains_no_plaintext() -> None:
    token = cipher().encrypt(CREDENTIALS, organization_id=ORG, provider="siigo")

    for value in CREDENTIALS.values():
        assert value.encode() not in token


def test_a_different_key_cannot_decrypt() -> None:
    token = cipher(b"0").encrypt(CREDENTIALS, organization_id=ORG, provider="siigo")

    with pytest.raises(CredentialEncryptionError):
        cipher(b"1").decrypt(token, organization_id=ORG, provider="siigo")


def test_a_tampered_token_is_refused() -> None:
    token = bytearray(cipher().encrypt(CREDENTIALS, organization_id=ORG, provider="siigo"))
    token[-1] ^= 0x01

    with pytest.raises(CredentialEncryptionError):
        cipher().decrypt(bytes(token), organization_id=ORG, provider="siigo")


def test_a_token_cannot_be_moved_to_another_organization() -> None:
    # The database row could be copied by a buggy migration or an operator. The
    # binding turns that into a loud refusal instead of authenticating the wrong
    # tenant.
    token = cipher().encrypt(CREDENTIALS, organization_id=ORG, provider="siigo")

    with pytest.raises(CredentialEncryptionError, match="different connection"):
        cipher().decrypt(token, organization_id=OTHER_ORG, provider="siigo")


def test_a_token_cannot_be_moved_to_another_provider() -> None:
    token = cipher().encrypt(CREDENTIALS, organization_id=ORG, provider="siigo")

    with pytest.raises(CredentialEncryptionError, match="different connection"):
        cipher().decrypt(token, organization_id=ORG, provider="alegra")


def test_an_invalid_key_is_refused_when_the_cipher_is_built() -> None:
    with pytest.raises(ValueError, match="Fernet"):
        CredentialCipher.from_key("not-a-key")


def test_a_short_key_is_refused() -> None:
    with pytest.raises(ValueError, match="Fernet"):
        CredentialCipher.from_key(base64.urlsafe_b64encode(b"short").decode())


def test_the_error_never_names_the_key_or_the_plaintext() -> None:
    token = cipher(b"0").encrypt(CREDENTIALS, organization_id=ORG, provider="siigo")

    with pytest.raises(CredentialEncryptionError) as caught:
        cipher(b"1").decrypt(token, organization_id=ORG, provider="siigo")

    message = str(caught.value)
    assert "super-secret-key" not in message
    assert base64.urlsafe_b64encode(b"1" * 32).decode() not in message
