"""What Siigo API can and cannot do, stated once.

The important line is `bank_accounts = False`. Siigo's public API exposes
accounting documents (journals, invoices, purchases, receipts, credit notes) but
no bank-accounts resource: bank accounts appear only as accounting codes inside a
journal item, and the portal's "saldos cuentas bancarias" report is a screen, not
a documented API resource. Returning an empty list would claim "this company has
no bank accounts", which is false; the adapter raises instead.

The reconciliation side that matters is the ledger, and that one is real:
`GET /v1/journals` is documented with date filters and pagination.
"""

from __future__ import annotations

from app.integrations.base import ConnectorCapabilities

SIIGO_CAPABILITIES = ConnectorCapabilities(
    ledger_transactions=True,
    bank_accounts=False,
    notes=(
        "Siigo API exposes journal entries (/v1/journals) with date filters and "
        "pagination, but no bank-accounts resource. Bank accounts are accounting "
        "codes inside journal items (for example 11050501), so the bank side of a "
        "reconciliation comes from the statement import, not from this API."
    ),
)
