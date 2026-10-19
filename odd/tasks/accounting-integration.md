# Accounting integration — FactuHub (phase in progress)

Objective: connect a company's accounting system with credentials that company
owns, chosen from Configuración, and synchronize without ever exposing a secret.
Branch: `main` · Delivery strategy: `ask-on-risk` · Test runner:
`backend/.venv/bin/pytest`.

This document records the phase decisions. The storage (I1/I4) and the
provider-generic routes (I2/I5) are implemented and verified; the Siigo adapter
(I3) is wired behind them. The catalogue stays at `contract_reviewed` until a
real credential exchange is recorded, so nothing claims to be a working
integration it has not proved. The World Office adapter (I6) is still blocked on
its unpublished filter attribute names.

## Specs

### S1 — External credentials are encrypted and never leave the backend

Verbatim from §11.3:

```text
- Utilizar variables de entorno para configuración local.
- Utilizar un gestor de secretos en producción.
- Cifrar credenciales externas.
- No guardar tokens en código fuente.
- No registrar cabeceras de autenticación.
- No devolver secretos al frontend.
- Rotar credenciales cuando corresponda.
```

And from §8 (World Office rules, which apply to every provider):

```text
- Nunca exponer tokens en el navegador.
- Nunca guardar credenciales en el repositorio.
- Utilizar secretos cifrados.
- Evitar registrar cabeceras de autenticación.
```

The interface may show whether a connection works, and the last error, but never
a token, not even truncated.

### S2 — The company chooses its provider; the schema is not provider-shaped

The specification lists connection routes under a World Office path
(`POST /api/v1/organizations/{org_id}/connections/world-office`). That shape
contradicts the product decision recorded in `mvp-foundation.md` S10: the
catalogue offers three providers and the company picks one from Configuración.
**Assumption:** the implemented routes are provider-generic
(`.../connections/{provider}`), with the provider code validated against the
catalogue. The World Office-specific paths in the specification are read as
examples, not as the contract.

### S3 — A connection is only offered when it can actually work

Rule 11 of §17, already enforced in the registry: a provider appears as
connectable only when a connection is `implemented` with evidence. World Office
declares two connections and Siigo one, all at `contract_reviewed`; Alegra
declares none. A `contract_reviewed` adapter is not a working connection, and no
adapter may simulate success.

### S4 — The adapter reads the ledger, not invented resources

§5.2 defines the `AccountingConnector` protocol (`test_connection`,
`list_bank_accounts`, `fetch_ledger_transactions`) and §5.3 says the methods must
follow what each provider actually exposes. Siigo exposes journal entries, not
bank accounts; the adapter implements the ledger method, declares
`bank_accounts = False`, and raises `CapabilityNotSupported` instead of returning
an empty list.

### S5 — Credentials are encrypted with a key separate from the session secret

Each company's provider credentials are encrypted at rest with Fernet
(AES-128-CBC + HMAC-SHA256) using `CREDENTIALS_ENCRYPTION_KEY`, a key independent
of `APP_SECRET_KEY`. The encrypted payload is bound to its
`(organization_id, provider)` pair: moving a ciphertext to another company or
provider fails authentication instead of decrypting. The plaintext is never
written to the database, a log, an audit row, or an HTTP response.

**Assumption:** the key lives in the environment for local development and in the
deployment's secret manager in production, as §11.3 already requires. Key
rotation is a re-encryption job, not a silent breakage; that job is not built yet.

### S6 — Connecting is a real, testable operation with a truthful status

A company administrator or accountant (`manage_integrations`) can save, replace,
revoke and test its provider connection. Every response states the observed
status (`untested`, `connected`, `error`), the last check time and a sanitized
last error — never a credential. A provider with no adapter is refused; the
catalogue stays conservative until a real credential exchange is recorded.
`world_office` and `alegra` are refused until their adapters exist.

## Tasks

| ID | Specs | Task | Route | Status | Evidence |
| --- | --- | --- | --- | --- | --- |
| I1 | S1, S2, S3, S5 | Per-organization provider credentials: table (organization, provider, mode, encrypted secret, status, timestamps), encryption at rest with a platform key, connection test in the backend, and responses that never include the secret. Replaces the five `WORLD_OFFICE_*` environment keys removed on 2026-10-19, which nothing read and which would have represented the platform's token rather than the company's. | inline | done | commits `9c13f1c`, `331fb4d` (see L3) |
| I2 | S2, S6 | Provider-generic connection routes (`{provider}`) validated against the catalogue, with Siigo wired behind them. The World Office adapter is split into I6. | inline | done | commit `c18e6d6` (see L3) |
| I3 | S3, S4 | Siigo adapter: credentials + token cache, HTTP client with bounded retries and redacted errors, validated response schemas, ledger mapper, capabilities, and the connector implementing the common protocol. Registry entry moves to `contract_reviewed` with evidence; it stays non-connectable until a real credential exchange is verified. | inline | done | commit `41ac4dc`; 31 unit tests, no network (see L2) |
| I4 | S5 | Encryption module, `provider_credentials` table and migration, storage service, audit rows, and unit tests for round-trip, binding and tamper refusal. | inline | done | commit `9c13f1c`; 9 crypto tests (see L3) |
| I5 | S6 | Connection endpoints (`GET`, `PUT`, `DELETE`, `POST .../test`) with `manage_integrations`, CSRF, cross-company 404, sanitized responses, and a connector factory tests can override. | inline | done | commits `c18e6d6`, `331fb4d`, `0e6a22f` (see L3) |
| I6 | S6 | World Office adapter behind the same connector factory and routes. Blocked on the provider's filter attribute names and a real credential exchange; the catalogue must not move to `implemented` before that. | — | pending | blocked (see S2/L1) |

## Log

### L1 — Why this task exists (2026-10-19)

The user, verbatim:

> en el .env aparece world office integración porque si no solo se va utiliar esa tambien se puede conectar siigo si yo como usuario uso siigo y no word office en un caso hipotetico

Verified before answering: the five `WORLD_OFFICE_*` keys existed in
`env.example` and `app/core/config.py`, and **nothing read them** — a grep across
the backend outside `config.py` returned zero uses. They were a leftover from the
contract-verification phase, and even if used they would have been wrong: a
platform-wide token is not a company's token.

Decision: removed the five keys from `env.example` and `config.py`; credentials
move to the per-organization design recorded above, implemented in this phase.
The provider catalogue is unchanged and already serves all three providers, so a
company using Siigo will select Siigo; what does not exist yet is a connectable
adapter for it, and the UI must show it as unavailable until there is one.

Open questions carried from earlier phases, still unresolved here:

- Whether the pilot company uses World Office Cloud or the desktop product.
- The API filter attribute names, which the published documentation does not
  include; they need the pilot's real credentials.
- Whether NIT `900123456-7` and `900123456` identify the same company (today the
  exact string comparison treats them as different companies).

### L2 — Siigo adapter (2026-10-19)

The user, verbatim:

> investiga y crea el adaptador

Read as the Siigo adapter: it was the provider in the immediately preceding
exchange ("siigo si yo como usuario uso siigo y no word office en un caso
hipotetico"), and the adapter is built so Alegra and World Office can follow
behind the same protocol if that reading was wrong.

Verified in the official documentation, not assumed:

- `POST https://api.siigo.com/auth` with `Partner-Id`, `username` and
  `access_key` returns a JWT with `expires_in` (86400).
- `GET /v1/journals` accepts `date_start`, `date_end`, `page`, `page_size` and
  answers `{pagination: {page, page_size, total_results}, results: [...]}`.
- Each item carries `account.code`, `account.movement` (`Debit`/`Credit`) and a
  decimal `value`.
- Siigo publishes **no bank-accounts resource**: the portal report is a screen,
  not an API. The adapter declares that capability false and raises, so nobody
  can mistake "unsupported" for "no accounts".

What was built: `app/integrations/base.py` (common protocol, `LedgerMovement`,
capabilities), and `app/integrations/siigo/` with `auth`, `client`, `schemas`,
`mapper`, `capabilities`, `service`, `exceptions`, following the §5.3 layout.
Money crosses the boundary as integer minor units; unknown movements and
negative values are errors, not skipped rows.

Decisions:

- The registry moves Siigo to `contract_reviewed` with the document as evidence;
  it stays **not connectable**, because no real credential has been exercised.
  Marking it `implemented` would violate §17 rule 11.
- Date filtering is sent to the API *and* applied locally, so an exclusive
  `date_end` cannot silently drop the last day of a month.
- The token lives only in memory; errors are built from a bounded provider
  message with the access key and the live token replaced by `[redacted]`.

Verification: 31 new unit tests against `httpx.MockTransport` (authentication
contract, token cache/expiry, one-shot refresh on 401, bounded retries on 429,
5xx and transport failures for both `/auth` and data requests, no retry on 4xx,
pagination including a server-capped page size and a provider that ignores
`page`, date and account filtering, minor-unit conversion including half cents,
refusal of unknown movements and negative values, redaction of the access key,
username and every issued token, unsupported bank accounts), plus one registry
test. Full suite: 161 passed. Ruff clean.

An independent verifier reviewed the change and found three real defects: a
token leaking through a chained pydantic error, `/auth` bypassing retries and
typed errors, and a server-capped page size truncating the ledger. All three were
fixed and the regression tests above fail without the fixes; the recheck passed
with no new blocker.

Risk: item 2 — the adapter handles provider credentials; a redaction regression
would leak them into an error message. Mitigated by dedicated tests and by never
logging a request, a header or a body.

Not done here, on purpose: credential storage (I1), HTTP routes (I2), and any
claim that the connection works with a real company.

### L3 — Concrete connection storage and routes (2026-10-19)

The user, verbatim:

> vale concretemos la conexion

Scope: I1 + I2 as one phase — encrypted per-company credentials, the storage
service, and the provider-generic routes with a real connection test. The UI
stays out (it belongs to the design phase), and so does a key-rotation job.

Design decisions:

- **Fernet, separate key.** Credentials are encrypted with
  `CREDENTIALS_ENCRYPTION_KEY`, not derived from `APP_SECRET_KEY`: rotating
  sessions must not make stored credentials unreadable, and rotating credentials
  must not sign everybody out.
- **Binding.** The ciphertext contains the `(organization_id, provider)` it was
  created for; decryption refuses a ciphertext moved to another row. Fernet
  already authenticates; the binding makes a database-level mix-up loud.
- **One row per (company, provider, mode).** Replacing credentials overwrites the
  ciphertext and resets the status to `untested`; it does not create a second row
  that could disagree with the first.
- **No lock on write.** Unlike membership changes, saving a connection does not
  move authority, so it does not need the A12 lock-and-re-read treatment. The
  route dependency still resolves the caller's role from the database on every
  request.
- **The test is a real call.** `POST .../test` decrypts, builds the provider's
  connector, calls `test_connection`, and persists `connected`/`error` plus the
  sanitized reason. A network failure is an `error` row, not a 500: the company
  needs to see it.
- **Providers without an adapter are refused** (409). The catalogue keeps Siigo
  at `contract_reviewed` until the first real credential exchange is recorded;
  the API flow exists and its per-company status tells the truth in the meantime.
- **`test_connection` returns `ConnectionCheck(ok, error)`** instead of the
  protocol's proposed `bool`, so the reason can be stored without a second
  failure path. Recorded deviation from §5.2; the rest of the protocol is
  unchanged.

Out of scope, on purpose: a World Office adapter (its filter attribute names are
still unpublished), any UI, and key rotation.

#### Verification (2026-10-19)

- Full suite: **206 passed** (161 at the previous head), including 9 encryption
  unit tests and 30 connection API tests.
- `ruff check .` and `ruff format --check .`: clean.
- Migration `7c1f0a9d2e34` applied to the development database and to a fresh
  test database; downgrade and re-upgrade verified by the independent verifier.
- Independent verifier (`gentle-ai-verify`) over `ce1d99f..c18e6d6`: **no
  blockers**. It confirmed, by probe: rejected saves leave the ciphertext, status
  and audit count unchanged; the 422 body echoes no credential (including
  wrong-type payloads); a non-member gets 404 even without a CSRF token; a
  failed test redacts both username and access key and bounds `last_error` to
  500 characters; a corrupt ciphertext is a generic 500 and leaves the row
  `untested`; `alegra` is refused exactly like `world_office`.
- Its five probes were committed as `0e6a22f`.
- Correction from its advisories: the configuration now refuses
  `CREDENTIALS_ENCRYPTION_KEY == APP_SECRET_KEY` (`331fb4d`), because separation
  that a deployment can silently undo is not separation.
- Deliberate behavior change: the app-wide 422 body no longer repeats the
  submitted value under `input`/`ctx`/`url`. Existing status codes and the
  `type`/`loc`/`msg` fields are unchanged; no test or contract relied on the
  removed keys. Recorded in `docs/architecture.md`.
- Remaining limitation, stated rather than hidden: no real Siigo credential has
  been exercised. The flow is real and its per-company status tells the truth,
  but the provider catalogue stays at `contract_reviewed` and
  `connectable = false` until that exchange happens.

#### Native review decision (2026-10-19)

The native review of `ce1d99f..9f545fe` (lenses: risk, resilience, readability)
was offered and the user chose **"Skip this time"** (`action: declined`,
`consent: declined_this_candidate`). No review record was created; the
independent verifier's result above stands, and future reviews stay enabled.
