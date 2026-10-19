"""Provider-connection endpoints.

The routes are provider-generic (`{provider}`), as decided in the phase
document: the specification's World Office-specific paths are examples, and
hardcoding one provider's name into the URL would make the second adapter a
breaking change.

Credentials go in and never come out. The response model has no field for them,
and the service is the only code that decrypts.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import (
    OrganizationContext,
    get_connector_factory,
    get_credential_cipher,
    get_db_session,
    require_csrf,
    require_permission,
)
from app.core.crypto import CredentialCipher, CredentialEncryptionError
from app.core.permissions import Permission
from app.integrations.connectors import ConnectorFactory
from app.integrations.registry import get_provider
from app.models import ProviderCredential
from app.schemas.provider_connections import (
    ConnectionCredentialsRequest,
    ProviderConnectionListResponse,
    ProviderConnectionResponse,
)
from app.services import provider_connections as connections_service

router = APIRouter(
    prefix="/organizations/{organization_id}/connections",
    tags=["provider connections"],
)


def _as_response(row: ProviderCredential) -> ProviderConnectionResponse:
    provider = get_provider(row.provider)
    return ProviderConnectionResponse(
        provider=row.provider,
        provider_name=provider.display_name if provider is not None else row.provider,
        mode=row.mode,
        status=row.status,
        last_checked_at=row.last_checked_at,
        last_error=row.last_error,
    )


def _translate(exc: connections_service.ProviderConnectionError) -> HTTPException:
    if isinstance(
        exc,
        (
            connections_service.UnknownProviderError,
            connections_service.ConnectionNotFoundError,
        ),
    ):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(
        exc,
        (
            connections_service.ProviderNotConnectableError,
            connections_service.ConcurrentConnectionUpdateError,
        ),
    ):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(exc),
    )


@router.get(
    "",
    response_model=ProviderConnectionListResponse,
    summary="The company's provider connections",
    description=(
        "Returns the observed status of every stored connection. Credentials are "
        "never part of the response."
    ),
)
def list_connections(
    context: Annotated[OrganizationContext, Depends(require_permission(Permission.READ))],
    db: Annotated[Session, Depends(get_db_session)],
) -> ProviderConnectionListResponse:
    rows = connections_service.list_connections(db, organization_id=context.organization_id)
    return ProviderConnectionListResponse(connections=[_as_response(row) for row in rows])


@router.put(
    "/{provider}",
    response_model=ProviderConnectionResponse,
    summary="Save or replace a provider connection",
    description=(
        "Requires `manage_integrations` (admin or accountant). Replacing the "
        "credentials resets the status to `untested`: the previous result does not "
        "describe the new credentials."
    ),
    responses={
        403: {"description": "The caller's role cannot manage integrations"},
        404: {"description": "No such company, not a member, or unknown provider"},
        409: {"description": "The provider has no adapter yet"},
        422: {"description": "The credential set is missing a field or is blank"},
    },
)
def upsert_connection(
    provider: str,
    payload: ConnectionCredentialsRequest,
    context: Annotated[
        OrganizationContext, Depends(require_permission(Permission.MANAGE_INTEGRATIONS))
    ],
    db: Annotated[Session, Depends(get_db_session)],
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> ProviderConnectionResponse:
    try:
        row = connections_service.upsert_connection(
            db,
            organization_id=context.organization_id,
            actor_id=context.user_id,
            provider=provider,
            credentials=payload.credentials,
            cipher=cipher,
        )
    except connections_service.ProviderConnectionError as exc:
        raise _translate(exc) from exc

    # Build the body before committing: after `commit()` the instance is expired
    # and answering would need a second read whose failure would report an error
    # for a write that already happened.
    response = _as_response(row)
    db.commit()
    return response


@router.delete(
    "/{provider}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a provider connection",
    description=(
        "Requires `manage_integrations`. Deletes the stored credentials; the "
        "provider retains whatever it already received."
    ),
    responses={
        403: {"description": "The caller's role cannot manage integrations"},
        404: {"description": "No such company, not a member, or no such connection"},
    },
)
def revoke_connection(
    provider: str,
    context: Annotated[
        OrganizationContext, Depends(require_permission(Permission.MANAGE_INTEGRATIONS))
    ],
    db: Annotated[Session, Depends(get_db_session)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> None:
    try:
        connections_service.revoke_connection(
            db,
            organization_id=context.organization_id,
            actor_id=context.user_id,
            provider=provider,
        )
    except connections_service.ProviderConnectionError as exc:
        raise _translate(exc) from exc

    db.commit()


@router.post(
    "/{provider}/test",
    response_model=ProviderConnectionResponse,
    summary="Test a provider connection",
    description=(
        "Requires `manage_integrations`. Calls the provider's documented endpoint, "
        "stores `connected` or `error` with a sanitized reason, and returns the "
        "observed status. A provider failure is a successful test of a failing "
        "connection, not an API error."
    ),
    responses={
        403: {"description": "The caller's role cannot manage integrations"},
        404: {"description": "No such company, not a member, or no such connection"},
    },
)
def test_connection(
    provider: str,
    context: Annotated[
        OrganizationContext, Depends(require_permission(Permission.MANAGE_INTEGRATIONS))
    ],
    db: Annotated[Session, Depends(get_db_session)],
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
    factory: Annotated[ConnectorFactory, Depends(get_connector_factory)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> ProviderConnectionResponse:
    try:
        row = connections_service.test_connection(
            db,
            organization_id=context.organization_id,
            actor_id=context.user_id,
            provider=provider,
            cipher=cipher,
            factory=factory,
        )
    except connections_service.ProviderConnectionError as exc:
        raise _translate(exc) from exc
    except CredentialEncryptionError as exc:
        # The deployment key no longer opens this row. Nothing useful can be said
        # to the company, and the details belong in an operator's hands.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stored credentials cannot be read.",
        ) from exc

    response = _as_response(row)
    db.commit()
    return response
