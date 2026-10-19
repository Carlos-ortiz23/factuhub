# Siigo integration — verified findings

This document records what was **verified** against Siigo's public API
documentation on 2026-10-19, and what remains **unknown**. It exists so nobody
has to guess later, and so no endpoint is ever invented.

The executable half lives in `backend/app/integrations/siigo/`.

Sources:

- `https://developers.siigo.com/docs/siigoapi/autenticacion/autenticacion`
- `https://developers.siigo.com/docs/siigoapi/partner-id/`
- `https://developers.siigo.com/docs/siigoapi/journal-entry/3-get-journals`
- `https://developers.siigo.com/docs/siigoapi/journal-entry/4-get-journal`
- `https://github.com/SiigoSAS/siigo_sdk_javascript` (official SDK, endpoint list)

## Verified

### Authentication

`POST https://api.siigo.com/auth`

Headers:

| Header | Value |
| --- | --- |
| `Partner-Id` | The integrated application's name, 3–100 alphanumeric characters, no spaces or special characters |
| `Content-Type` | `application/json` |

Body:

```json
{ "username": "<username>", "access_key": "<access_key>" }
```

`201` response:

```json
{
  "access_token": "<JWT>",
  "expires_in": 86400,
  "token_type": "Bearer",
  "scope": ""
}
```

Every subsequent request carries `Authorization: Bearer <access_token>` and the
same `Partner-Id`. The credentials are generated in Siigo Nube: *Alianzas* →
*Mi Credencial API*.

`Partner-Id` is **not** a secret and **not** the company's identifier: it names
the software doing the integration (here, `FactuHub`). It is a fixed application
value, not a per-company credential.

### Journal entries (the ledger side of a reconciliation)

`GET https://api.siigo.com/v1/journals` — documented as "Listar Comprobantes
Contables".

Query parameters:

| Name | Type | Meaning |
| --- | --- | --- |
| `name` | string | Filter by entry name |
| `created_start` / `created_end` | RFC3339 date-time | Creation window |
| `date_start` / `date_end` | RFC3339 date-time | **Posting** window |
| `updated_start` / `updated_end` | RFC3339 date-time | Update window |
| `page` | number | Page number |
| `page_size` | number | Page size |
| `document_id` | number | Filter by document id |

Response:

```json
{
  "pagination": { "page": 1, "page_size": 100, "total_results": 12 },
  "results": [
    {
      "id": "63f918c2-ca65-4edc-a7db-66bcdd5159fb",
      "document": { "id": 27441 },
      "number": 20,
      "name": "CC-10-20",
      "date": "2021-10-10",
      "currency": { "code": "USD", "exchange_rate": 3825.03 },
      "items": [
        {
          "account": { "code": "11050501", "movement": "Credit" },
          "value": 119000.5,
          "description": "Pago proveedor"
        }
      ]
    }
  ]
}
```

Each item is one ledger line: `account.code` is the PUC account, `movement` is
`Debit` or `Credit`, `value` is a decimal amount. `GET /v1/journals/{id}`
returns a single entry with the same item shape.

`GET /v1/document-types` is documented in Siigo's official SDK
(`DocumentTypeApi.getDocumentTypes`); the adapter calls it with `type=FV` as the
cheapest authenticated read that proves the credentials reach real company data.

## Not available in the public API

**Bank accounts.** Siigo's API has no bank-accounts resource: the portal's
"Informe saldos cuentas bancarias / cajas" is a screen, not a documented API
endpoint, and bank accounts appear in the API only as accounting codes inside a
journal item (the `11…` family in the Colombian PUC).

The adapter therefore declares `bank_accounts = False` and raises
`CapabilityNotSupported` instead of returning `[]`. "This company has no bank
accounts" and "this API cannot be asked for bank accounts" are different facts.

This does not block reconciliation: the bank side arrives from the statement
import, and the accounting side is exactly what `/v1/journals` provides.

## How the adapter maps it

| Siigo | Internal |
| --- | --- |
| journal `id` + item index | `external_id` (`"<id>:<index>"`), stable across syncs |
| `date` | `posted_on` |
| `account.code` | `account_code` |
| `movement: Debit` | `debit_minor` (positive) |
| `movement: Credit` | `credit_minor` (positive) |
| `value * 100` | integer minor units, `ROUND_HALF_UP` |
| `description`, else journal `name` | `description` |
| journal `name` | `reference` |

Refused on purpose:

- An unknown `movement` → `SiigoMappingError`. Skipping the line would make the
  reconciliation disagree with the bank with no visible cause.
- A negative `value` → `SiigoMappingError`. Direction is expressed by
  `movement`; a negative amount means the contract is not the one this adapter
  was built for.

Date filtering is applied twice: the request sends `date_start`/`date_end`, and
the client also drops entries outside the range locally. If Siigo ever treats
`date_end` as exclusive, the last day of a month would silently disappear from a
reconciliation; the local filter makes that impossible.

Retries: bounded (`max_retries`, default 3) on `429`, `500`, `502`, `503`, `504`
and transport errors, with a 0.5s/1s/2s backoff. A `401`/`403` invalidates the
cached token and retries **once**, because a second rejection is a credentials
problem, not a stale token.

## Unknowns

1. **No real company credentials have been exercised yet.** Every claim above is
   documentation-verified; the adapter is unit tested against a fake transport
   only. Until a real NIT's credentials are used, the connection stays
   `contract_reviewed` and **not** `implemented` (specification §17 rule 11).
2. **Rate limits** are not published. The adapter backs off on `429`; the actual
   per-minute budget is unknown.
3. **Maximum `page_size`** is not published. The adapter defaults to 100 and
   paginates against the page size the provider *reports*, so a server-side cap
   produces more pages rather than a truncated ledger.
4. **Whether `value` can ever be negative** in a real company's data is unknown.
   If it can, the mapper must be revisited deliberately, not patched to `abs()`.
5. **Siigo México** is a separate documentation tree
   (`/docs/siigoapimexico/`) and a separate base URL. This adapter targets
   Colombia only.
6. **Which document types carry bank movements** in a given company is an
   accounting decision (journal entries do; invoices and receipts feed them).
   The adapter reads journals, not every document.
7. **The timezone Siigo applies to `date_start`/`date_end`** is not stated. The
   adapter sends UTC (`Z`) and filters locally, so an exclusive `date_end` cannot
   drop the last day; a provider that interprets the bound in Colombia local time
   could still exclude up to five hours of the final day before the local filter
   sees them. This needs a real account to settle.

## Verifying with real credentials

Once a company supplies its `username` and `access_key`, the check is a single
authenticated read — no writes:

```python
from app.integrations.siigo import SiigoClient, SiigoConnector, SiigoCredentials

client = SiigoClient(SiigoCredentials(username="...", access_key="..."))
connector = SiigoConnector(client)
print(await connector.test_connection())          # True / False
print(await connector.fetch_ledger_transactions("11050501", start, end))
await client.aclose()
```

Only after that succeeds does the registry entry move to `IMPLEMENTED`, in the
same commit as the evidence.
