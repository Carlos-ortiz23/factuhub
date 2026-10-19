# Imports and reconciliation — FactuHub (phase in progress)

Objective: ingest bank statements and accounting exports with column mapping and
row-level validation, then reconcile them with exact, approximate and grouped
matching under an auditable period workflow.
Branch: `main` · Delivery strategy: `ask-on-risk` · Test runner:
`backend/.venv/bin/pytest`.

This phase is split into work units because the specification covers two
different risks: file ingestion (untrusted input, money parsing) and the engine
(financial rules). Tasks R1–R2 are implemented first; R3–R6 follow.

## Specs

### S1 — Accepted files and mapping

§2.1.D: accept CSV and XLSX initially; import bank statements, accounting
auxiliaries, movement exports and opening/closing balances when available; let
the importer map columns when files use different structures.

### S2 — Row validation

Verbatim from §2.1.D:

```text
Debe validar fechas, importes, débitos, créditos, referencias y campos obligatorios.
```

### S3 — Idempotency and row errors

Verbatim from §7.5:

```text
Las importaciones deben ser idempotentes y permitir identificar errores por fila.
```

### S4 — File safety

§11.4: validate size and type, validate real content (not only the extension),
never run macros, bound the resources consumed, keep the original in private
storage, and define a retention policy. §3.5 requires S3-compatible private
storage for originals.

### S5 — Bank accounts

§7.4 lists the columns; §7.4 also says:

```text
No almacenar números completos de cuentas bancarias cuando no sean necesarios.
```

`connection_id` is nullable: a company that only imports files has no provider
connection and must still be able to reconcile.

### S6 — Exact matching

§8.2: identical amount, compatible economic direction, same date or inside a
configurable window, matching reference when available, and an unmatched
movement. If several candidates are equivalent, do not pick arbitrarily: show
them.

### S7 — Approximate score

Verbatim from §8.3:

```text
score = 0.40 * amount_score + 0.25 * date_score + 0.25 * reference_score + 0.10 * description_score
```

Thresholds: `0.95–1.00` high confidence, `0.80–0.9499` review suggestion, below
`0.80` stays pending. The score never overrides financial compatibility.

### S8 — Grouping

§8.4: one bank movement against several ledger records and several bank
movements against one ledger record; validate exact sum, compatible directions,
reasonable dates, related references when present, no already-matched movements
and no contradictory associations; bound the group size. Bank fees and justified
differences are explainable items, never forced matches.

### S9 — Duplicates

§8.5: do not use only date, amount and description. Distinguish a repeated
import, a re-import of the same movement, two legitimate similar transactions
and possible duplicates needing investigation. Never delete originals
automatically.

### S10 — Balances

§8.6: compute opening bank balance, bank debits and credits, statement closing
balance, ledger closing balance, matched movements, pending items, unexplained
differences and the reconciled balance under the configured accounting
convention. A zero net difference does not prove the reconciliation is correct.

### S11 — Periods and matches

§7.6 statuses: `open`, `in_review`, `approved`, `reopened`. §7.10 match types:
`exact`, `approximate`, `grouped`, `manual`; statuses: `suggested`, `confirmed`,
`rejected`, `cancelled`. Confirmation must run in one SQL transaction with the
relevant rows locked. §7.6: a period with unjustified differences cannot be
approved.

### S12 — Mandatory tests

§12.1–§12.4: valid/empty file, missing columns, invalid dates and amounts,
debit/credit, duplicate file, legitimate repeated rows, large file, partial
error; exact/date-window/reference matches, missing reference, two equivalent
candidates, different amount, incompatible direction, already matched, groups,
bank fees, unexplained differences; two users confirming the same movement,
cross-company access, repeated import, double approval, unauthorized reopen,
contradictory association; balance cases prepared with an accountant.

## Tasks

| ID | Specs | Task | Route | Status | Evidence |
| --- | --- | --- | --- | --- | --- |
| R1 | S5 | `bank_accounts` model, migration and routes: create, list, read. Masked account number, nullable provider connection, ledger account code. | inline | done | 297 tests, migration `9b2d5f7a1c40` |
| R2 | S1, S2, S3, S4 | Import pipeline: `import_jobs`, `import_row_errors`, `bank_transactions`, `ledger_transactions`; CSV/XLSX reader; explicit column mapping; exact money/date parsing; duplicate-file refusal; partial import with per-row errors; private file storage; retry of failed jobs; routes. | inline | done | 297 tests, ruff clean |
| R3 | S11 | `reconciliation_periods` and `reconciliation_period_transactions`, creation, summary, transaction listing, submit/approve/reopen with role checks and locks. | inline | done | 19 API tests; migration `a01c4fdc5f36` |
| R4 | S6, S7, S9 | Pure engine: normalizer, exact matcher, approximate scorer, duplicate candidates. No database access, so every rule is testable without a transaction. | inline | done | 47 engine tests; 344 total |
| R5 | S8, S11 | Grouping (bounded), match persistence, suggestions, confirm/reject/cancel with row locks and duplicate/contradiction protection. | inline | done | 24 API tests; confirm locks movements, cancels alternatives, and a confirmed match can be released |
| R6 | S10 | Balances and period summary. Must be validated with an accountant before production use. | inline | done (assumption) | 7 balance tests; convention documented and warned |

## Log

### L1 — Scope and assumptions (2026-10-19)

The user, verbatim:

> sigamos con importaciones y motor de conciliación

Decisions for R1–R2, recorded before writing:

- **Money** is an integer number of minor units (`amount_minor`) and `direction`
  carries the sign; the amount itself is always positive. Negative zero-value
  rows are rejected instead of guessed.
- **Date and decimal formats are explicit.** `date_format` defaults to
  `%d/%m/%Y` and `decimal_separator` to `,` (Colombian convention). Guessing
  between `01/02/2026` and `02/01/2026`, or between `1,234` and `1.234`, is a
  silent way to import wrong money. The client can override both per import.
- **Signed amounts need a convention.** When the file has one `amount` column
  and no `direction` column, `positive_is` (default `credit`) says what a
  positive value means. Without it, half the banks would import inverted.
- **Debit/credit columns**: exactly one of the two may be non-zero per row; both
  zero or both non-zero is a row error.
- **Idempotency key** is `(organization_id, bank_account_id, source_type,
  file_sha256, request_sha256)`, where `request_sha256` covers the mapping and
  options. Re-uploading the same bytes with the same interpretation is refused;
  the same file with a corrected mapping is a new, legitimate import.
- **Partial imports are allowed.** Valid rows are inserted, invalid rows are
  recorded in `import_row_errors`, and the job is `completed` when at least one
  row was imported, `failed` when none was. A status `completed_with_errors` is
  not invented: the counters and the error endpoint carry that truth.
- **Retry only applies to a `failed` job** (zero imported rows). Retrying a
  completed job would duplicate movements; re-importing corrected data is a new
  upload.
- **Legitimate repeated rows are preserved.** No unique constraint on the
  transaction fingerprint; duplicates are candidates for the engine, never
  automatic deletions (§8.5).
- **Original files are stored privately** under `IMPORT_STORAGE_DIR` with
  `0600`, not served by any route. A local adapter is used in development; the
  S3-compatible adapter belongs to the deployment phase and the seam is a small
  storage protocol.
- **XLSX macros are refused** (`.xlsm` rejected) and the file is opened
  read-only with `data_only=True`, so a formula cannot execute and a cached
  value is not recomputed.
- **Bank accounts do not require a provider connection.** File-only companies
  are the common case.
- **Permissions**: `import` for uploads and retries, `read` for lists and
  details; bank account creation uses `manage_integrations` because it is
  configuration, not day-to-day reconciliation.
- **Out of scope for R2**: the reconciliation engine, reports and the UI. The
  engine is R4–R6, in this same phase.

### L2 — R1/R2 implemented and verified (2026-10-19)

Delivered:

- `bank_accounts` (masked number, nullable `connection_id`, ledger code),
  `import_jobs` (SHA-256 plus interpretation hash, counters, stored mapping and
  options, per-row errors), `bank_transactions` and `ledger_transactions`
  (positive minor units plus direction, non-unique fingerprint).
- CSV/`.txt`/XLSX reader: UTF-8, UTF-8 BOM, UTF-16 and Windows-1252; comma,
  semicolon, tab and pipe delimiters, header-first; `.xlsm` refused; ZIP
  signature checked; 50,000-row and 10 MiB default bounds.
- Explicit `ColumnMapping` and `ImportOptions` (`date_format`,
  `decimal_separator`, `positive_is`, `source_system`), validated against the
  header before a job exists.
- `POST/GET /organizations/{org_id}/imports`, `GET /imports/{id}`,
  `GET /imports/{id}/errors`, `POST /imports/{id}/retry`; bank-account create,
  list and read. Added `GET /organizations/{org_id}/imports` because the UI needs
  to list an account's uploads and the specification only defines the detail
  route.
- 84 new tests (60 unit parsing/reading/storage, 27 API) for 297 total. Ruff
  check and format clean. Migration applied to development and test databases.

Recorded decisions made while implementing:

- **Numeric spreadsheet cells vs text.** A float cell with binary noise (for
  example `=A1-B1` producing `0.30000000000000004`) is rounded to the two
  decimals the cell displays. A text cell with three decimals is still rejected,
  and a `Decimal` stays exact. Without this distinction every formula-based
  export would fail; with it, a real three-decimal text value is never
  silently rounded.
- **Delimiter detection reads the header first.** A semicolon file whose amounts
  are `1.234,56` contains more commas than semicolons in the body; sniffing the
  body would split every amount. The header decides unless it has no delimiter.
- **`completed` with rejected rows is not a fifth status.** Counters, summary and
  the error endpoint carry the partial result, as recorded in L1.
- **A failed job is `201` on upload**, because the job resource was created and
  its status is `failed`; the client reads the errors endpoint. Retry is `200`
  (the existing resource is reprocessed).
- **Storage is a protocol.** The local private adapter is active; the
  S3-compatible adapter and the retention policy remain deployment work.

Verification evidence: full suite `297 passed`; `ruff check` and
`ruff format --check` clean; migration `9b2d5f7a1c40` applied; `db_session`
tests query the rows written through the API, not the service return value.

Next task: R3 (periods) and R4 (pure engine). No review was requested for this
candidate.

### L3 — pure reconciliation engine (2026-10-19)

Delivered in `backend/app/reconciliation/`:

- `types.py`: `Movement` (side, date, positive minor units, direction, reference,
  description, external id, fingerprint, import job) and `MatchConfig`.
- `normalizer.py`: accent/case/punctuation normalisation, meaningful-word
  Jaccard similarity, economic direction (bank credit = inflow; ledger debit =
  inflow for an asset account), date distance/span, related-reference check.
- `matcher.py`: hard rules (economic direction, date window, amount tolerance)
  before scoring; configurable weights; exact candidates; suggestions; tie
  detection.
- `grouping.py`: one-to-many and many-to-one exact-sum groups, bounded to three
  movements per side and 25 candidates per anchor.
- `duplicates.py`: classifies same-import, re-import, distinct documents and
  possible duplicates using fingerprint and external id, never date/amount alone.

Assumptions recorded for calibration with real data:

- Default amount tolerance **5,000 COP** (500,000 minor units); default date
  window **3 days**.
- `amount_score = 1 - difference / (2 * tolerance)`; at the tolerance edge it
  contributes half its weight.
- `date_score = 1 - days / (window + 1)`.
- An unavailable component (missing reference or description on one side)
  redistributes its weight instead of scoring zero. A **present but different**
  reference scores zero and is included in the denominator.
- Grouped references are related when equal or sharing an alphanumeric prefix
  of at least three characters; a group with unrelated references is rejected.
- Groups are exact sums only. A fee or difference is never absorbed.
- Duplicates are reported, never deleted; confirmation stays a human decision.

Verification: `344 passed`; ruff check/format clean. Persistence (R3/R5) and
balances (R6) are next; the engine itself has no database dependency.

### L4 — periods, matches and balances (2026-10-19)

Persistence and routes delivered on top of the pure engine:

- `a01c4fdc5f36` adds `reconciliation_periods`,
  `reconciliation_period_transactions`, `reconciliation_matches` and
  `reconciliation_match_items`. The item table enforces exactly one movement per
  row with a check constraint; the service enforces the cross-table rules.
- `POST /bank-accounts/{id}/periods` refuses overlapping windows for the same
  account, links existing movements to the period, and audits the creation.
- `POST /periods/{id}/match-suggestions` replaces the pending suggestions. A
  confirmed match is never regenerated; a rejected or cancelled combination is
  remembered and not offered again. The run is capped at 500 suggestions and the
  response reports `truncated`.
- `POST /matches/{id}/confirm` locks the match, the period and the movements in
  deterministic order, refuses if any movement is already confirmed elsewhere,
  and cancels the suggested alternatives that shared a movement. Two concurrent
  confirmations of the same movement cannot both succeed.
- `reject` and `cancel` are terminal human decisions on a suggested match.
- Period lifecycle: `open` → `in_review` (submit) → `approved` (approve) →
  `reopened`. Approval requires `approve`; creating and deciding requires
  `reconcile`; reads require `read`. Non-members get 404, never 403.

Balances (`app/reconciliation/balances.py`) keep three figures separate:

- `statement_difference_minor`: declared bank closing minus the imported bank
  rows. A missing row is visible here even when the net difference is zero.
- `adjusted_ledger_balance_minor`: ledger closing plus pending bank movements,
  minus pending ledger movements. This is the explicit `bank_to_ledger`
  convention, not a universal accounting truth.
- `unexplained_difference_minor`: declared bank closing minus the adjusted
  ledger.

`balanced` requires zero pending movements, zero statement difference and zero
unexplained difference. Approval uses that strict definition because this phase
has no justification model; the specification's "unjustified differences" is
narrower, and the conservative reading never approves what it cannot explain.

Verification: **380 passed**; `ruff check` and `ruff format --check` clean;
29 API tests and 7 balance tests. `alembic check` reports no drift. Advisory: `GET /matches/{id}` was added beyond
§9.5 so the UI can refresh one match after a decision; recorded here like the
imports listing.

### §12 coverage audit (2026-10-19)

- §12.1 Importación: valid, empty, missing columns, invalid dates/amounts,
  debit/credit, duplicate file, legitimate repeated rows, size limits, partial
  error — all covered by the import tests.
- §12.2 Conciliación: exact, date tolerance, reference match, absent reference,
  equivalent candidates, amount difference, incompatible direction, already
  reconciled, group, bank fee not absorbed, unexplained difference — covered by
  engine and API tests.
- §12.3 Integridad: cross-company access, repeated import, double approval,
  reopening without permission, contradictory association, double confirmation —
  covered at HTTP level. The true concurrent race is guarded by `FOR UPDATE` on
  the match, period and movements but is **not** exercised by a concurrent HTTP
  test, because the test harness runs each test in one rolled-back transaction.
  The same limitation was recorded for A12.
- §12.4 Saldos: initial plus movements, debits/credits, closing, in-transit
  items, unexplained differences and reopened periods are tested. Justified
  differences are **not modeled**: the accountant convention is still pending, so
  approval is stricter (all pending items must be zero). This is a documented
  gap, not a silent assumption.

### L5 — reversible confirmations and Excel export (2026-10-19)

Risk correction: a confirmed match is no longer irreversible.
`POST /matches/{id}/cancel` accepts a confirmed match, marks it `released` and
returns its movements to the available pool. Rejected suggestions remain
rejected; alternatives that were auto-cancelled by a confirmation are marked
with `auto_cancelled_by_match_id` and become eligible again once the confirmation
is released. Migration `5bc654f7727d` adds the `released` column.

Phase 6 export: `GET /periods/{id}/export` returns an `.xlsx` with four sheets
(Resumen, Movimientos, Pendientes, Coincidencias). The workbook is built from the
same balances and movement views as the JSON summary. Text cells are written
with `data_type = "s"` even when they start with `=`, closing the formula
injection path from an uploaded statement. The download is audited. Endpoint
added beyond §9.5 because §13 phase 6 asks for an Excel export; recorded here.

Remaining, deliberately not invented:

- **Justified differences.** Approval is stricter than the specification until
  the accountant defines which differences are acceptable. A free-text
  justification model would be a product decision, not a technical one.
- **True concurrent confirmation.** The service guard is tested by injecting a
  confirmation that bypassed auto-cancellation, and the locks serialize the
  race; the HTTP test harness still cannot run two committed transactions
  concurrently.
- **Duplicate suggestions surface.** The engine classifies duplicates, but §9
  defines no endpoint for them; the reconciliation tray belongs to the UI phase.
