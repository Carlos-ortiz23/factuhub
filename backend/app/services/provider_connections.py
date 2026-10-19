"""Storing, reading, revoking and testing one company's provider credentials.

Two rules shape this module:

* The plaintext credential exists only between `decrypt` and the adapter call.
  Nothing here returns it, logs it, or puts it in an audit row.
* A connection's status is an observation, not a default. Saving credentials
  marks the connection `untested`; only a real call can move it to `connected`,
  and a failure stores the sanitized reason instead of raising.

`test_connection` runs the adapter's coroutine with `asyncio.run`. That is safe
from the synchronous FastAPI handlers this application uses (they run in a
threadpool); calling it from inside a running event loop would refuse, which is
the correct failure for a function that owns its loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.crypto import CredentialCipher
from app.integrations.base import ConnectionCheck
from app.integrations.connectors import (
    CREDENTIAL_FIELDS,
    ConnectorFactory,
    build_connector,
)
from app.integrations.registry import get_provider
from app.models import ProviderConnectionStatus, ProviderCredential
from app.services import audit as audit_service

MODE_API = "api"
MAX_CREDENTIAL_LENGTH = 512
MAX_FIELD_NAME_LENGTH = 50

ENTITY_TYPE = "provider_connection"


class ProviderConnectionError(ValueError):
    """A refused connection operation, translated to 4xx by the endpoint."""


class UnknownProviderError(ProviderConnectionError):
    """The code is not in the catalogue."""


class ProviderNotConnectableError(ProviderConnectionError):
    """The provider exists in the catalogue but has no adapter yet."""


class CredentialInputError(ProviderConnectionError):
    """The credential set is missing a field, blank, or too long."""


class ConnectionNotFoundError(ProviderConnectionError):
    """This company has not stored credentials for that provider."""


class ConcurrentConnectionUpdateError(ProviderConnectionError):
    """Another request inserted the same connection while this one ran."""


def normalize_provider(code: str) -> str:
    return code.strip().lower()


def _validate_credentials(provider: str, credentials: Mapping[str, str]) -> dict[str, str]:
    if get_provider(provider) is None:
        raise UnknownProviderError("Unknown accounting provider.")

    expected = CREDENTIAL_FIELDS.get(provider)
    if expected is None:
        raise ProviderNotConnectableError("This provider cannot be connected yet.")

    submitted = set(credentials)
    if submitted != set(expected):
        # The field names are not secrets, so naming them is safe and useful.
        raise CredentialInputError(
            f"This provider expects exactly these credential fields: {', '.join(expected)}."
        )

    cleaned: dict[str, str] = {}
    for field in expected:
        value = credentials[field].strip()
        if not value:
            raise CredentialInputError(f"The credential field '{field}' must not be blank.")
        if len(field) > MAX_FIELD_NAME_LENGTH or len(value) > MAX_CREDENTIAL_LENGTH:
            raise CredentialInputError(f"The credential field '{field}' is too long.")
        cleaned[field] = value
    return cleaned


def get_connection(
    db: Session, *, organization_id: UUID, provider: str
) -> ProviderCredential | None:
    return db.scalar(
        select(ProviderCredential).where(
            ProviderCredential.organization_id == organization_id,
            ProviderCredential.provider == provider,
            ProviderCredential.mode == MODE_API,
        )
    )


def list_connections(db: Session, *, organization_id: UUID) -> list[ProviderCredential]:
    rows = db.scalars(
        select(ProviderCredential)
        .where(ProviderCredential.organization_id == organization_id)
        .order_by(ProviderCredential.provider, ProviderCredential.mode)
    )
    return list(rows)


def upsert_connection(
    db: Session,
    *,
    organization_id: UUID,
    actor_id: UUID,
    provider: str,
    credentials: Mapping[str, str],
    cipher: CredentialCipher,
) -> ProviderCredential:
    """Create or replace the credentials for one connection.

    Replacing resets the observed status: the previous `connected` no longer
    describes the new credentials, and carrying it over would be exactly the kind
    of reassuring lie this phase is trying to avoid.
    """
    code = normalize_provider(provider)
    cleaned = _validate_credentials(code, credentials)
    token = cipher.encrypt(cleaned, organization_id=organization_id, provider=code)

    existing = get_connection(db, organization_id=organization_id, provider=code)
    if existing is not None:
        existing.encrypted_credentials = token
        existing.status = ProviderConnectionStatus.UNTESTED
        existing.last_checked_at = None
        existing.last_error = None
        db.flush()
        audit_service.record(
            db,
            organization_id=organization_id,
            user_id=actor_id,
            action="provider_connection.updated",
            entity_type=ENTITY_TYPE,
            entity_id=existing.id,
            metadata={"provider": code, "mode": MODE_API},
        )
        return existing

    row = ProviderCredential(
        organization_id=organization_id,
        provider=code,
        mode=MODE_API,
        encrypted_credentials=token,
        status=ProviderConnectionStatus.UNTESTED,
        created_by=actor_id,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError as exc:
        raise ConcurrentConnectionUpdateError(
            "This connection was changed by another request; try again."
        ) from exc

    audit_service.record(
        db,
        organization_id=organization_id,
        user_id=actor_id,
        action="provider_connection.created",
        entity_type=ENTITY_TYPE,
        entity_id=row.id,
        metadata={"provider": code, "mode": MODE_API},
    )
    return row


def revoke_connection(db: Session, *, organization_id: UUID, actor_id: UUID, provider: str) -> None:
    code = normalize_provider(provider)
    row = get_connection(db, organization_id=organization_id, provider=code)
    if row is None:
        raise ConnectionNotFoundError("This company has no connection for that provider.")

    connection_id = row.id
    db.delete(row)
    db.flush()
    audit_service.record(
        db,
        organization_id=organization_id,
        user_id=actor_id,
        action="provider_connection.revoked",
        entity_type=ENTITY_TYPE,
        entity_id=connection_id,
        metadata={"provider": code, "mode": MODE_API},
    )


def _sanitize_error(message: str | None, credentials: Mapping[str, str]) -> str:
    """Bound the stored reason and remove any credential that slipped through.

    The adapter already redacts. This is the second lock: a future adapter
    regression must not turn the `last_error` column into a credential store.
    """
    text = " ".join((message or "").split())
    for value in credentials.values():
        if value:
            text = text.replace(value, "[redacted]")
    return text[:500] or "The provider rejected the connection."


def _probe(
    factory: ConnectorFactory,
    provider: str,
    credentials: Mapping[str, str],
) -> ConnectionCheck:
    async def run() -> ConnectionCheck:
        connector = factory(provider, credentials)
        try:
            return await connector.test_connection()
        finally:
            close = getattr(connector, "aclose", None)
            if close is not None:
                await close()

    return asyncio.run(run())


def test_connection(
    db: Session,
    *,
    organization_id: UUID,
    actor_id: UUID,
    provider: str,
    cipher: CredentialCipher,
    factory: ConnectorFactory = build_connector,
) -> ProviderCredential:
    """Call the provider and persist what was observed."""
    code = normalize_provider(provider)
    row = get_connection(db, organization_id=organization_id, provider=code)
    if row is None:
        raise ConnectionNotFoundError("This company has no connection for that provider.")

    credentials = cipher.decrypt(
        row.encrypted_credentials,
        organization_id=organization_id,
        provider=code,
    )
    check = _probe(factory, code, credentials)

    row.status = ProviderConnectionStatus.CONNECTED if check.ok else ProviderConnectionStatus.ERROR
    row.last_checked_at = datetime.now(UTC)
    row.last_error = None if check.ok else _sanitize_error(check.error, credentials)
    db.flush()

    audit_service.record(
        db,
        organization_id=organization_id,
        user_id=actor_id,
        action="provider_connection.tested",
        entity_type=ENTITY_TYPE,
        entity_id=row.id,
        metadata={"provider": code, "ok": check.ok},
    )
    return row
