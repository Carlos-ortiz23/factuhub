"""The catalogue of accounting systems a company can connect.

This module is data, not behaviour. The API serves it and the frontend renders
it, so adding a provider must never require touching either.

The important part is the guard on `ProviderConnection`: a connection cannot be
reported as reviewed or implemented without naming the evidence that verifies
it. The specification is unambiguous about this (§17 rule 11: "No simules una
integración real cuando no exista una conexión verificada"), and a rule that
lives only in a developer's intentions is a rule that quietly stops holding. Here
it cannot: constructing the claim raises.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ConnectionMode(StrEnum):
    """How a company's accounting system can be reached."""

    API = "api"
    FILE_IMPORT = "file_import"


class Readiness(StrEnum):
    """How far a specific connection actually is.

    `IMPLEMENTED` is the only value that means a user can connect today. The
    other two exist so the interface can tell the truth about the rest of the
    catalogue instead of hiding it behind a disabled button with no explanation.
    """

    NOT_STARTED = "not_started"
    CONTRACT_REVIEWED = "contract_reviewed"
    IMPLEMENTED = "implemented"


@dataclass(frozen=True, slots=True)
class ProviderConnection:
    """One way of reaching a provider, with the evidence behind the claim."""

    mode: ConnectionMode
    readiness: Readiness
    #: What verifies this claim, for a human reviewer: a date plus the official
    #: source that was checked, or the specification section that defines the
    #: path. Deliberately not user-facing copy.
    evidence: str | None = None

    def __post_init__(self) -> None:
        if self.readiness is Readiness.NOT_STARTED:
            return
        if not self.evidence:
            raise ValueError(
                f"{self.mode.value} cannot be reported as '{self.readiness.value}' "
                "without evidence: an unverified integration must not be presented "
                "as real (specification §17 rule 11)"
            )


@dataclass(frozen=True, slots=True)
class AccountingProvider:
    """One accounting system, as offered to a company."""

    code: str
    display_name: str
    connections: tuple[ProviderConnection, ...] = ()

    @property
    def is_connectable(self) -> bool:
        """Whether a company can connect this provider right now."""
        return any(connection.readiness is Readiness.IMPLEMENTED for connection in self.connections)


WORLD_OFFICE = AccountingProvider(
    code="world_office",
    display_name="World Office",
    connections=(
        ProviderConnection(
            mode=ConnectionMode.FILE_IMPORT,
            readiness=Readiness.CONTRACT_REVIEWED,
            evidence=(
                "specification §5.4 defines file import as the path that always works; "
                "the import phase has not been built yet"
            ),
        ),
        ProviderConnection(
            mode=ConnectionMode.API,
            readiness=Readiness.CONTRACT_REVIEWED,
            evidence=(
                "OpenAPI reviewed 2026-10-19 (docs/world-office-integration.md): the "
                "accounting endpoints and the 'Authorization: WO <token>' scheme are "
                "confirmed; the filter attribute names are not published, and the pilot "
                "company's credentials are still missing"
            ),
        ),
    ),
)

SIIGO = AccountingProvider(code="siigo", display_name="Siigo")

ALLEGRA = AccountingProvider(code="allegra", display_name="Allegra")

#: Everything the interface may offer. Order is presentation order.
CATALOGUE: tuple[AccountingProvider, ...] = (WORLD_OFFICE, SIIGO, ALLEGRA)


def get_provider(code: str) -> AccountingProvider | None:
    """Return the provider registered under `code`, or `None`."""
    return next((provider for provider in CATALOGUE if provider.code == code), None)
