"""The one place that maps a catalogue code to a runnable connector.

The registry says what exists in the catalogue; this module says what can actually
be built today. Keeping them apart is what lets the catalogue list Alegra before
Alegra has an adapter, without pretending it can be connected.

`CREDENTIAL_FIELDS` is also the validation contract: a provider accepts exactly
the fields it documents, and nothing else. A typo in a credential name must fail
before anything is encrypted and stored.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

import httpx

from app.integrations.base import AccountingConnector
from app.integrations.siigo import SiigoClient, SiigoConnector, SiigoCredentials

#: The exact keys each provider expects. Order is the order the interface shows.
CREDENTIAL_FIELDS: dict[str, tuple[str, ...]] = {
    "siigo": ("username", "access_key"),
}

#: A callable with this shape builds a connector for one set of credentials.
#: Tests override the FastAPI dependency with a fake that records the call.
ConnectorFactory = Callable[..., AccountingConnector]


class UnsupportedProviderError(ValueError):
    """No adapter exists for this provider yet."""


def build_connector(
    provider_code: str,
    credentials: Mapping[str, str],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AccountingConnector:
    """Build the adapter for `provider_code`.

    `transport` exists for tests: production passes `None` and httpx uses its
    real network transport.
    """
    if provider_code == "siigo":
        client = SiigoClient(
            SiigoCredentials(
                username=credentials["username"],
                access_key=credentials["access_key"],
            ),
            transport=transport,
        )
        return SiigoConnector(client)

    raise UnsupportedProviderError(f"No adapter exists for provider {provider_code!r} yet.")
