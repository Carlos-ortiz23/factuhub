# Accounting integration — FactuHub (phase not started)

Objective: connect a company's accounting system with credentials that company
owns, chosen from Configuración, and synchronize without ever exposing a secret.
Branch: `main` · Delivery strategy: `ask-on-risk` · Test runner:
`backend/.venv/bin/pytest`.

This document exists ahead of the phase to record one decision made on
2026-10-19: provider credentials are per organization, never platform-wide
environment values. Nothing here is implemented yet; the provider catalogue
(`app/integrations/registry.py`) is the only piece that exists.

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
connectable only when a connection is `implemented` with evidence. Siigo and
Alegra currently declare no connection at all; World Office declares two at
`contract_reviewed`. No adapter may simulate success.

## Tasks

| ID | Specs | Task | Route | Status | Evidence |
| --- | --- | --- | --- | --- | --- |
| I1 | S1, S2, S3 | Per-organization provider credentials: table (organization, provider, mode, encrypted secret, status, timestamps), encryption at rest with a platform key, connection test in the backend, and responses that never include the secret. Replaces the five `WORLD_OFFICE_*` environment keys removed on 2026-10-19, which nothing read and which would have represented the platform's token rather than the company's. | — | pending | — |
| I2 | S2 | Provider-generic connection routes (`{provider}`) validated against the catalogue, then the World Office adapter behind them. | — | pending | — |

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
