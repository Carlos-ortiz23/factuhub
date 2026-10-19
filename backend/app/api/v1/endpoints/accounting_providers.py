"""Accounting provider catalogue endpoint.

Read-only data for the Configuración screen. It exposes what has actually been
verified for each provider, including — especially — what has not.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import AuthContext, get_auth_context
from app.integrations import registry
from app.schemas.integrations import (
    AccountingProviderCatalogueResponse,
    AccountingProviderResponse,
    ProviderConnectionResponse,
)

router = APIRouter(tags=["integrations"])


@router.get(
    "/accounting-providers",
    response_model=AccountingProviderCatalogueResponse,
    summary="Accounting providers a company can choose from",
    description=(
        "Served from the backend registry so adding a provider never requires a "
        "frontend change. `connectable` is true only for a provider whose "
        "connection has actually been implemented; every other entry declares "
        "what it still needs, and no entry may claim a reviewed or implemented "
        "connection without naming its evidence. The response carries no "
        "user-facing copy: the interface owns its own wording."
    ),
)
def read_accounting_providers(
    _context: Annotated[AuthContext, Depends(get_auth_context)],
) -> AccountingProviderCatalogueResponse:
    return AccountingProviderCatalogueResponse(
        providers=[
            AccountingProviderResponse(
                code=provider.code,
                display_name=provider.display_name,
                connectable=provider.is_connectable,
                connections=[
                    ProviderConnectionResponse(
                        mode=connection.mode,
                        readiness=connection.readiness,
                        evidence=connection.evidence,
                    )
                    for connection in provider.connections
                ],
            )
            for provider in registry.CATALOGUE
        ]
    )
