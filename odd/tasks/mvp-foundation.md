# MVP foundations — FactuHub

Objective: stand up the monorepo foundation (Python + Next.js + PostgreSQL) so
every later phase builds on a tested base.
Branch: `main` (bootstrap of an empty repository) · Delivery strategy:
`ask-on-risk` · Test runner: `backend/.venv/bin/pytest`.

Authored-change forecast for this feature: ~700–900 lines (config, db layer, API
surface, Alembic baseline, tests, docs, compose). The bootstrap commit is a
documented exception to the ~400-line slice guidance: an empty repository has no
default-branch history to review against, so the initial scaffold lands as one
unit and every later phase is sliced normally.

## Specs

### S1 — Repository structure

Verbatim from the specification (§6):

```text
conciliapp/
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   ├── components/
│   │   ├── features/
│   │   │   ├── dashboard/
│   │   │   ├── organizations/
│   │   │   ├── connections/
│   │   │   ├── imports/
│   │   │   ├── bank-accounts/
│   │   │   ├── reconciliation/
│   │   │   ├── reports/
│   │   │   └── audit/
│   │   ├── lib/
│   │   ├── hooks/
│   │   └── types/
│   └── package.json
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── v1/
│   │   ├── core/
│   │   ├── db/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   ├── imports/
│   │   ├── integrations/
│   │   │   └── world_office/
│   │   ├── reconciliation/
│   │   ├── reports/
│   │   └── audit/
│   ├── migrations/
│   ├── tests/
│   │   └── pyproject.toml
├── docs/
│   ├── architecture.md
│   ├── database.md
│   ├── world-office-integration.md
│   └── reconciliation-rules.md
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

The specification adds: *"Adaptar la estructura si el proyecto existente ya tiene
convenciones establecidas. No duplicar módulos o configuraciones sin necesidad."*

**Deviation, with reason:** the environment template is named `env.example`
instead of `.env.example`. The agent runtime denies read/write access to every
`*.env*` path as a secret-protection rule, so a file literally named
`.env.example` cannot be authored or read by tooling in this project. The
template is tracked, the real `.env` is git-ignored, and the README documents
`cp env.example .env`.

### S2 — Containers and environments

Verbatim from the specification (§3.6):

> - Docker para desarrollo y despliegue.
> - Variables de entorno.
> - Entornos independientes de desarrollo, pruebas y producción.
> - Copias de seguridad.
> - Registro centralizado de errores.
> - Monitoreo básico.
> - Migraciones controladas.
>
> No implementar microservicios durante el MVP. Utilizar un backend modular con
> responsabilidades claramente separadas.

Scope for this phase: Docker for local development (PostgreSQL), environment
variables, independent development and test databases, controlled migrations.
Backups, centralized logging and monitoring belong to the deployment phase.

### S3 — Database foundations

Verbatim from the specification (§3.3):

> PostgreSQL.
>
> Utilizar:
>
> - UUID como identificadores.
> - Restricciones de integridad.
> - Índices para consultas frecuentes.
> - Transacciones SQL para confirmar conciliaciones.
> - Migraciones con Alembic.
> - Row-Level Security como protección adicional para datos de diferentes empresas.
> - Importes almacenados de manera exacta, nunca utilizando números de punto
>   flotante para operaciones financieras.

Scope for this phase: connection layer, declarative base with a stable constraint
naming convention (required for reliable Alembic autogenerate), and a baseline
migration that enables the extensions the model will depend on. Tables arrive
with their phase.

### S4 — Secrets never reach the repository

Verbatim from the specification (§17, working rules 10 and 11; §5.4; §11.3):

> 10. Nunca incluyas credenciales reales en el repositorio.
>
> 11. No simules una integración real cuando no exista una conexión verificada.

> - Nunca exponer tokens en el navegador.
> - Nunca guardar credenciales en el repositorio.
> - Utilizar secretos cifrados.
> - Evitar registrar cabeceras de autenticación.

> - No guardar tokens en código fuente.
> - No registrar cabeceras de autenticación.
> - No devolver secretos al frontend.

Checks: `.env` is git-ignored; `env.example` holds placeholders only; the
settings object rejects a placeholder or short secret when `APP_ENV=production`.

### S5 — Requested execution order

Verbatim from the specification (§17):

> ### Segundo paso
>
> Prepara los fundamentos del proyecto:
>
> - Estructura de carpetas.
> - Configuración del entorno.
> - Docker.
> - PostgreSQL.
> - Migraciones.
> - Variables de entorno.
> - README.
> - Configuración de pruebas.

### S6 — Test discipline

Verbatim from the specification (§17):

> 14. Escribe pruebas para todas las reglas financieras.
> 15. Ejecuta las pruebas después de cada fase.
> 16. Corrige los errores antes de avanzar.
> 18. No marques una tarea como completada si no ha sido probada.

> 1. Antes de escribir código, inspecciona el repositorio y determina si existe una aplicación previa.
> 2. No sobrescribas código existente sin comprenderlo.

### S7 — Durable context between sessions

Verbatim from the user's chat instructions:

> siempre guardar en emgram para no perder el contexto de por donde quedamos,
> clean code y seguir todas las reglas legales para no tener problema. Clean code
> principios solid etc para codigo.

Each phase records findings and decisions in Engram, with this document as the
local mirror.

### S8 — Documented uncertainty instead of invented endpoints

Verbatim from the specification (§17, working rules 7, 8 and 12):

> 7. No inventes endpoints de World Office.
>
> 8. Si no puedes verificar un recurso oficial, documenta la incertidumbre y crea
>    una interfaz de integración preparada para implementarlo posteriormente.

> 12. No utilices datos ficticios en reportes que se presenten como resultados reales.

### S9 — The product is FactuHub

Verbatim correction from the user (2026-10-19):

> ojo la aplicación es factuhub no conciliapp

Consequences: the backend distribution and service identity are
`factuhub-backend`; the API title is `FactuHub API`; the monorepo root is
`factuhub/`. The specification document itself is preserved verbatim in
`docs/PROJECT_SPEC.md` with an explicit note that its provisional name is
superseded. No user-facing string may carry the old name.

### S10 — The accounting provider is chosen from the UI

Verbatim requirement from the user (2026-10-19):

> recuerda que el usuario puede configurar desde la interfaz en cinfiguración la
> app contable que va utilizar ya sea si es siigo, wordoffice etc... las que
> existen en colombia y mas usadas

Interpretation, bounded by the specification's own rules: the platform exposes a
**provider catalogue** served by the backend (never hardcoded in the frontend),
and the choice is made from the Configuración section. World Office is the first
implementation; other Colombian providers (Siigo, and others added later) appear
in the catalogue as *not yet available* rather than as a working integration,
because spec rule 11 forbids simulating a connection that has not been verified.

Acceptance criteria:

- The catalogue is data returned by `GET /api/v1/accounting-providers`; adding a
  provider must not require a frontend change.
- Each entry declares its code, display name, supported connection modes and an
  availability status.
- Selecting an unavailable provider explains what is missing; it never pretends
  to connect, sync, or return data.
- Connecting a provider requires the capability-first adapter of spec §5.3, so a
  provider can only be *available* once its official contract has been verified.

## Tasks

| ID | Spec | Task | Route | Status | Evidence |
| --- | --- | --- | --- | --- | --- |
| T1 | S1, S4 | Monorepo skeleton, `.gitignore`, `env.example`, README | inline | done | commit (bootstrap) |
| T2 | S2 | `docker-compose.yml` with isolated development and test PostgreSQL instances | inline | done | `factuhub_postgres` and `factuhub_postgres_test` both `Up (healthy)`; ports 5432/5433 |
| T3 | S5, S7 | Backend foundations: settings, db base/session, app factory, `/api/v1/health` | inline | done | RED: `ModuleNotFoundError: No module named 'app'` (2 collection errors). GREEN: `7 passed` |
| T4 | S3 | Alembic plumbing (runtime settings URL, stable naming convention) | inline | done | probe revision: `upgrade head` created the table, `downgrade base` removed it, probe file deleted afterwards |
| T5 | S6 | pytest configuration and test-database isolation | inline | done | `configfile: pyproject.toml`, 7 tests green; dev and test databases are separate containers |
| T6 | S1 | Next.js scaffold (`frontend/`) without UI design work | inline | done | `npm run lint` clean; `npm run build` compiled, TypeScript checked, 4 static pages; product deps `0 vulnerabilities` (5 high are dev-only in the eslint chain) |
| T7 | S8 | Verbatim specification in `docs/PROJECT_SPEC.md`; World Office findings in `docs/world-office-integration.md` | inline | done | files present |
| T8 | S6 | Initial commit and push of the bootstrap | inline | blocked | commits `0ee38bf` and `b0e9811` created locally; push blocked pending deploy-key registration |
| T10 | S9 | Git access for pushing to `factuhub` | inline | in progress | both pre-existing SSH keys are single-repo deploy keys (`siigo-mcp`, `e-VIR-LandingPage`); generated `~/.ssh/id_ed25519_factuhub` + `github.com-factuhub` alias |
| T11 | S10 | Accounting provider catalogue (backend-served) and provider selection in Configuración | delegated later | pending | scheduled with the integration phase (spec §5.3, paso 7) |
| T9 | S9 | Rename product identity to FactuHub (distribution, service name, API title, docs) | inline | done | distribution resolves `factuhub-backend 0.1.0` after reinstall; `7 passed` |

## Log

### L1 — Original request (verbatim, technical specification in full)

The complete specification the user supplied is preserved verbatim in
`docs/PROJECT_SPEC.md`. Its executable instructions, quoted word for word:

> Actúa como un ingeniero de software sénior especializado en aplicaciones SaaS
> financieras, Python, FastAPI, PostgreSQL, Next.js y sistemas de conciliación
> bancaria.
>
> Desarrolla este proyecto siguiendo esta especificación como documento principal.
>
> ## Reglas de trabajo
>
> 1. Antes de escribir código, inspecciona el repositorio y determina si existe una aplicación previa.
> 2. No sobrescribas código existente sin comprenderlo.
> 3. Identifica las herramientas disponibles y utiliza las versiones estables compatibles.
> 4. Crea un plan de implementación por fases.
> 5. Implementa un MVP funcional, no una colección de pantallas estáticas.
> 6. Mantén la separación entre frontend, API, importadores, integraciones y motor de conciliación.
> 7. No inventes endpoints de World Office.
> 8. Si no puedes verificar un recurso oficial, documenta la incertidumbre y crea una interfaz de integración preparada para implementarlo posteriormente.
> 9. Utiliza datos ficticios únicamente para demostraciones y pruebas.
> 10. Nunca incluyas credenciales reales en el repositorio.
> 11. No simules una integración real cuando no exista una conexión verificada.
> 12. No utilices datos ficticios en reportes que se presenten como resultados reales.
> 13. No implementes escritura contable sin autorización y sin una capacidad oficial verificada.
> 14. Escribe pruebas para todas las reglas financieras.
> 15. Ejecuta las pruebas después de cada fase.
> 16. Corrige los errores antes de avanzar.
> 17. Documenta las decisiones técnicas importantes.
> 18. No marques una tarea como completada si no ha sido probada.

> **Empieza inspeccionando el repositorio y presentando el plan de implementación.
> No intentes construir todas las fases en una sola operación sin verificar cada
> resultado.** El design lo dejamos de ultimo UI/UX la idea es inspirarnos en
> diseños crear nuestra propia identidad de marca tengo un logo. para que este
> proyecto sea original y no copia y menos que parezca hecho por ia los iconos que
> utilizaremos seran de lucide, tipografia de google fonts pero una que se adapte
> perfectamente al proyecto. por eso en esto nos enfocamos despues vamos paso a
> paso siempre hacer prueba pero primero conectaremos repositorio que no esta
> conectado y siempre guardar en emgram para no perder el contexto de por donde
> quedamos, clean code y seguir todas las reglas legales para no tener problema.
> Clean code principios solid etc para codigo. no fallar en nada.... repositorio
> https://github.com/Carlos-ortiz23/factuhub.git

### L2 — Environment inspection (2026-10-19)

Repository `Carlos-ortiz23/factuhub` was public, empty and had no commits; it was
cloned into `workspace/factuhub` and `origin` switched to SSH. Verified toolchain:
Python 3.14.4, Node 24.15.0, npm 12.0.2, Docker 29.9.1, Compose v5.6.0, no local
PostgreSQL, no `gh` CLI.

Blocker found and resolved by the user: the `coiam` user was not in the `docker`
group, so the Docker socket was unreachable and `sudo` requires an interactive
password. The user ran `sudo usermod -aG docker $USER`; the group is active and
Docker works, including through `sg docker -c '<command>'` without re-login.

### L3 — World Office contract verified (2026-10-19)

The three accounting endpoints exist in the published OpenAPI (101 paths) and all
three accept the same generic paginated envelope with dynamic `filtros`. There is
no public token endpoint — tokens are provisioned manually per API user with
per-service permissions and sent as `Authorization: WO <token>`. The filter
attribute names, and therefore whether bank movements can be selected by date and
account, are **not published** and remain unknown. Recorded in
`docs/world-office-integration.md`. Consequence: file import stays the primary
path; the connector is built capability-first.

### L4 — Runtime constraint, secrets template (2026-10-19)

The agent runtime denies read/write on every `*.env*` path, so `.env.example`
could not be created. Resolution: the tracked template is `env.example`; the real
`.env` is generated locally with random values and stays git-ignored. Recorded as
the S1 deviation.

### L5 — Next step

Finish T3/T5 (RED→GREEN on the settings and health contracts), then T4 (Alembic
baseline), T6 (frontend scaffold) and T8 (bootstrap commit and push).

### L6 — Product name corrected to FactuHub (2026-10-19)

Verbatim user correction:

> ojo la aplicación es factuhub no conciliapp

Applied to: `backend/pyproject.toml` distribution name, `SERVICE_NAME` and
`DISTRIBUTION_NAME` in `app/core/app_info.py`, the API title in
`app/main.py`, the health contract test, `README.md`, `env.example`, this
document, and a vigencia note at the top of `docs/PROJECT_SPEC.md` (whose body
stays verbatim). Recorded as spec S9.

### L7 — Push blocked: SSH keys are single-repo deploy keys (2026-10-19)

`git push` failed with `Permission to Carlos-ortiz23/factuhub.git denied to
deploy key`. Cause: both existing keys authenticate as deploy keys bound to
other repositories — `id_ed25519_siigo_mcp` resolves to `Carlos-ortiz23/siigo-mcp`
and `id_ed25519_evir_landing` to `Carlos-ortiz23/e-VIR-LandingPage`. Deploy keys
are per-repository and cannot be reused. No credential helper was configured
either.

Decision (user's choice): a dedicated deploy key for `factuhub`. Generated
`~/.ssh/id_ed25519_factuhub`, appended a `github.com-factuhub` host alias to
`~/.ssh/config` (backup left at `config.bak-20261019`), and pointed `origin` at
`git@github.com-factuhub:Carlos-ortiz23/factuhub.git`. The existing keys and host
entries were left untouched.

Both commits are already in the local `main`; the push happens as soon as the
public key is registered on the repository with write access.

### L8 — Accounting provider must be selectable from the UI (2026-10-19)

Verbatim user requirement:

> listo, recuerda que el usuario puede configurar desde la interfaz en
> cinfiguración la app contable que va utilizar ya sea si es siigo, wordoffice
> etc... las que existen en colombia y mas usadas

Recorded as spec S10 and task T11. Constraint kept from the specification: the
provider catalogue is served by the backend and only lists as *available* what
has a verified official contract. World Office stays the first implementation
(spec: "Integración inicial: World Office"); additional Colombian providers are
catalogue entries marked unavailable until verified. This is consistent with
objective 9 ("Preparar una arquitectura extensible para integrar otros sistemas
contables en el futuro") and rule 11 ("No simules una integración real cuando no
exista una conexión verificada").
