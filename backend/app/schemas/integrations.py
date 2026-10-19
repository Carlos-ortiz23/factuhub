"""Provider catalogue contracts.

The catalogue carries no user-facing sentences on purpose: `evidence` is
provenance for a reviewer, and the interface owns its own copy. That keeps the
API language-neutral and leaves the Spanish wording where it belongs, in the UI
phase, instead of frozen into a response body.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.integrations.registry import ConnectionMode, Readiness


class ProviderConnectionResponse(BaseModel):
    """One connection of one provider."""

    mode: ConnectionMode
    readiness: Readiness
    evidence: str | None = None


class AccountingProviderResponse(BaseModel):
    """One provider as the interface receives it."""

    code: str
    display_name: str
    connectable: bool
    connections: list[ProviderConnectionResponse]


class AccountingProviderCatalogueResponse(BaseModel):
    """The full catalogue."""

    providers: list[AccountingProviderResponse]
