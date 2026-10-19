"""Authenticated encryption for each company's provider credentials.

Fernet gives AES-128-CBC plus an HMAC-SHA256 tag: a modified ciphertext is
rejected, not decrypted into plausible garbage. The envelope also records the
company and provider the credentials belong to, so a row copied to another
company fails loudly instead of silently authenticating the wrong tenant.

The plaintext is a small JSON object. It exists only inside this module and in
the memory of the request that needs it; it is never persisted, logged, or
returned.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

ENVELOPE_VERSION = 1

#: Every stored credential is a short JSON object; a megabyte of ciphertext is a
#: sign of corruption or abuse, not a real credential set.
MAX_CIPHERTEXT_BYTES = 16 * 1024


class CredentialEncryptionError(Exception):
    """Stored credentials cannot be read with the configured key.

    The message is deliberately generic: which part failed (key, tag, envelope,
    tenant binding) is useful to an attacker and useless to the company.
    """


@dataclass(frozen=True, slots=True)
class CredentialCipher:
    """Encrypts and decrypts one deployment's credential payloads."""

    _fernet: Fernet

    @classmethod
    def from_key(cls, key: SecretStr | str) -> CredentialCipher:
        raw = key.get_secret_value() if isinstance(key, SecretStr) else key
        try:
            return cls(_fernet=Fernet(raw))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "CREDENTIALS_ENCRYPTION_KEY must be a Fernet key: 32 url-safe "
                "base64-encoded bytes, e.g. the output of Fernet.generate_key()"
            ) from exc

    def encrypt(
        self,
        credentials: dict[str, str],
        *,
        organization_id: UUID,
        provider: str,
    ) -> bytes:
        envelope = {
            "v": ENVELOPE_VERSION,
            "organization_id": str(organization_id),
            "provider": provider,
            "credentials": credentials,
        }
        payload = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False)
        token = self._fernet.encrypt(payload.encode("utf-8"))
        if len(token) > MAX_CIPHERTEXT_BYTES:
            raise ValueError("Credential payload is too large to store.")
        return token

    def decrypt(
        self,
        token: bytes,
        *,
        organization_id: UUID,
        provider: str,
    ) -> dict[str, str]:
        if len(token) > MAX_CIPHERTEXT_BYTES:
            raise CredentialEncryptionError("Stored credentials cannot be read.")

        try:
            raw = self._fernet.decrypt(token)
        except InvalidToken:
            # `from None`: the Fernet exception carries no useful public detail
            # and chaining it only invites a caller to log internals.
            raise CredentialEncryptionError("Stored credentials cannot be read.") from None

        try:
            envelope = json.loads(raw)
        except (UnicodeDecodeError, ValueError):
            raise CredentialEncryptionError("Stored credentials cannot be read.") from None

        if not isinstance(envelope, dict) or envelope.get("v") != ENVELOPE_VERSION:
            raise CredentialEncryptionError("Stored credentials cannot be read.")
        if (
            envelope.get("organization_id") != str(organization_id)
            or envelope.get("provider") != provider
        ):
            raise CredentialEncryptionError("Stored credentials belong to a different connection.")

        credentials = envelope.get("credentials")
        if not isinstance(credentials, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in credentials.items()
        ):
            raise CredentialEncryptionError("Stored credentials cannot be read.")
        return credentials
