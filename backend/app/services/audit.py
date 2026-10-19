"""The append-only trail of who did what inside a company.

The table's trigger already makes history immutable; this module exists so that
writing an entry is one call with one shape, instead of every handler inventing
its own metadata object. Credentials must never reach it: the guard below refuses
the obvious shapes rather than trusting each caller to remember the rule.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import AuditLog

#: Keys that would carry a credential. Checked recursively; a nested
#: `{"provider": {"access_key": ...}}` is as unacceptable as a top-level one.
FORBIDDEN_METADATA_KEYS = frozenset(
    {
        "access_key",
        "authorization",
        "credential",
        "credentials",
        "password",
        "secret",
        "token",
    }
)


class UnsafeAuditMetadataError(ValueError):
    """The metadata would store something that must never be stored."""


def _reject_secret_keys(value: Any, path: str = "metadata") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower() in FORBIDDEN_METADATA_KEYS:
                raise UnsafeAuditMetadataError(
                    f"{path}.{key} looks like a credential; audit metadata records "
                    "identifiers and outcomes only."
                )
            _reject_secret_keys(nested, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _reject_secret_keys(nested, f"{path}[{index}]")


def record(
    db: Session,
    *,
    organization_id: UUID,
    user_id: UUID | None,
    action: str,
    entity_type: str,
    entity_id: UUID,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Append one entry and flush it (the caller owns the transaction)."""
    payload = metadata or {}
    _reject_secret_keys(payload)

    entry = AuditLog(
        organization_id=organization_id,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        metadata_json=payload,
    )
    db.add(entry)
    db.flush()
    return entry
