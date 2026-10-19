"""Siigo API (Colombia) adapter.

Verified contract, unknowns and the reason `bank_accounts` is not supported are
recorded in `docs/siigo-integration.md` and `capabilities.py`.
"""

from __future__ import annotations

from app.integrations.siigo.auth import SiigoCredentials, SiigoTokenCache
from app.integrations.siigo.capabilities import SIIGO_CAPABILITIES
from app.integrations.siigo.client import SiigoClient
from app.integrations.siigo.service import SiigoConnector

__all__ = [
    "SIIGO_CAPABILITIES",
    "SiigoClient",
    "SiigoConnector",
    "SiigoCredentials",
    "SiigoTokenCache",
]
