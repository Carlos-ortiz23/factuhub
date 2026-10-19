"""The Siigo connector: the provider-specific half of the common protocol."""

from __future__ import annotations

from datetime import date

from app.integrations.base import (
    CapabilityNotSupported,
    ConnectorCapabilities,
    LedgerMovement,
)
from app.integrations.siigo.capabilities import SIIGO_CAPABILITIES
from app.integrations.siigo.client import SiigoClient
from app.integrations.siigo.exceptions import SiigoError
from app.integrations.siigo.mapper import to_ledger_movements


class SiigoConnector:
    """Implements `AccountingConnector` over a company's Siigo credentials."""

    capabilities: ConnectorCapabilities

    def __init__(self, client: SiigoClient) -> None:
        self._client = client
        self.capabilities = SIIGO_CAPABILITIES

    async def test_connection(self) -> bool:
        """A cheap authenticated read, not just a token request.

        A token can be issued for a user who cannot read anything; asking for the
        invoice document types proves the credentials reach real company data.
        """
        try:
            await self._client.get_json("/v1/document-types", params={"type": "FV"})
        except SiigoError:
            return False
        return True

    async def list_bank_accounts(self) -> list[dict]:
        raise CapabilityNotSupported(SIIGO_CAPABILITIES.notes)

    async def fetch_ledger_transactions(
        self,
        account_id: str,
        start_date: date,
        end_date: date,
    ) -> list[LedgerMovement]:
        journals = await self._client.list_journals(start_date, end_date)
        return [
            movement
            for journal in journals
            for movement in to_ledger_movements(journal, account_code=account_id)
        ]

    async def aclose(self) -> None:
        await self._client.aclose()
