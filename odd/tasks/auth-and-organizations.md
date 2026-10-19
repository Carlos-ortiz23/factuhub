# Authentication, organizations, users, permissions, audit

Objective: an authorized user can register, log in, belong to one or more
organizations with a role, and every important action leaves a trace that cannot
be silently rewritten.
Branch: `main` · Delivery strategy: `ask-on-risk` · Test runner:
`backend/.venv/bin/pytest`.

## Specs

### S1 — Scope of the phase

Verbatim from the specification (§2.1.A):

> ### A. Autenticación y usuarios
>
> - Registro e inicio de sesión.
> - Recuperación de acceso.
> - Gestión de usuarios de una empresa.
> - Roles y permisos.
> - Separación de información por empresa.
> - Registro de acciones importantes.

### S2 — Organizations

Verbatim from the specification (§7.1):

> Campos:
>
> - `id`
> - `name`
> - `tax_id`
> - `created_at`
>
> Cada empresa constituye un espacio de datos aislado.

### S3 — Users, memberships and roles

Verbatim from the specification (§7.2):

> `users`:
>
> - `id`
> - `email`
> - `full_name`
> - `created_at`
>
> `organization_members`:
>
> - `organization_id`
> - `user_id`
> - `role`
>
> Roles iniciales:
>
> - `admin`
> - `accountant`
> - `reviewer`
> - `viewer`
>
> La autorización debe verificarse en el backend para cada operación.

**Assumption, flagged as such:** `users` gains `password_hash` and
`is_active`. The specification's field list omits them, but "Registro e inicio de
sesión" (S1) and §11.1 cannot exist without a stored credential, and an account
must be disableable without deleting its history. Both are additions, not
substitutions: no listed field is dropped.

### S4 — Audit trail

Verbatim from the specification (§7.11):

> `audit_logs`:
>
> - `id`
> - `organization_id`
> - `user_id`
> - `action`
> - `entity_type`
> - `entity_id`
> - `metadata`
> - `created_at`
>
> Registrar:
>
> - Importaciones.
> - Sincronizaciones.
> - Confirmaciones.
> - Rechazos.
> - Reaperturas.
> - Aprobaciones.
> - Cambios en conexiones.
> - Cambios de permisos.
>
> El historial no debe modificarse silenciosamente.

"The history must not be silently modified" is enforced at the database level:
an append-only trigger rejects `UPDATE` and `DELETE` on `audit_logs`.

### S5 — Session security

Verbatim from the specification (§11.1):

> - Sesiones seguras.
> - Cookies `HttpOnly`, `Secure` y política `SameSite` adecuada si se utilizan cookies.
> - Protección contra CSRF cuando corresponda.
> - Recuperación de acceso segura.
> - MFA recomendado para administradores y aprobadores.
> - Limitación de intentos de autenticación.

### S6 — Authorization and row-level security

Verbatim from the specification (§11.2):

> Comprobar en el backend:
>
> - Empresa a la que pertenece el usuario.
> - Rol.
> - Permisos de lectura.
> - Permisos de importación.
> - Permisos de conciliación.
> - Permisos de aprobación.
> - Permisos de configuración de integraciones.
>
> Aplicar Row-Level Security como capa adicional, no como sustituto de la autorización de la aplicación.

### S7 — Integrity requirements that apply here

Verbatim from the specification (§3.3, §11.5):

> - UUID como identificadores.
> - Restricciones de integridad.
> - Índices para consultas frecuentes.
> - Transacciones SQL para confirmar conciliaciones.
> - Migraciones con Alembic.
> - Row-Level Security como protección adicional para datos de diferentes empresas.

> - Utilizar transacciones SQL.
> - Prevenir dobles confirmaciones.
> - Registrar todas las aprobaciones.
> - Conservar el origen de los movimientos.
> - Evitar borrados destructivos.

### S8 — Isolation and authorization tests are acceptance criteria

Verbatim from the specification (§12.3):

> - Dos usuarios intentan confirmar el mismo movimiento.
> - Un usuario intenta acceder a otra empresa.
> - Una importación se repite.
> - Un periodo se aprueba dos veces.
> - Se intenta reabrir un periodo sin permisos.
> - Se intenta confirmar una asociación contradictoria.

Verbatim from §14 (acceptance criteria 13, 15, 16):

> 13. Los usuarios no pueden acceder a datos de otras empresas.
> 15. La integración contable no expone credenciales ni permite escrituras no autorizadas.
> 16. Se han probado las rutas críticas y los casos de error.

### S9 — Test discipline

Verbatim from the specification (§17):

> 14. Escribe pruebas para todas las reglas financieras.
> 15. Ejecuta las pruebas después de cada fase.
> 16. Corrige los errores antes de avanzar.
> 18. No marques una tarea como completada si no ha sido probada.

## Tasks

| ID | Spec | Task | Route | Status | Evidence |
| --- | --- | --- | --- | --- | --- |
| A1 | S2, S3, S4, S7 | Domain models: `organizations`, `users`, `organization_members`, `audit_logs` | inline | done | `app/models/*.py`; 4 tables created by revision `6292f9b04939` |
| A2 | S4, S7 | Migration with integrity constraints, indexes and the append-only audit trigger | inline | done | `migrations/versions/20261019_1626_6292f9b04939_*.py`; upgrade/downgrade round trip proven on the dev database; trigger present in `pg_trigger` |
| A3 | S5 | Password hashing (argon2) and the session token primitive | inline | in progress | — |
| A3 | S5 | Password hashing and session issuance (argon2, HttpOnly cookie) | inline | pending | — |
| A4 | S5 | Auth endpoints: register, login, logout, me, with rate limiting | inline | pending | — |
| A5 | S6 | RBAC dependency: role checks enforced per operation in the backend | inline | pending | — |
| A6 | S6, S7 | Row-level security policies plus the non-superuser application role they need to be real | inline | pending | — |
| A7 | S4 | Audit service wired into the actions the specification lists | inline | pending | — |
| A8 | S8 | Isolation tests: another organization's data is unreachable; audit rows cannot be rewritten | inline | pending | — |

## Log

### L1 — Original request

Verbatim from the user (phase 3 of the requested order):

> ### Tercer paso
>
> Implementa autenticación, empresas, usuarios, permisos y auditoría.

The full specification is preserved verbatim in `docs/PROJECT_SPEC.md`.

### L2 — Scope decision

The phase is split into reviewable work units instead of one large change: models
and audit integrity first (A1, A2), then credentials and sessions (A3, A4), then
authorization and its database-level second layer (A5, A6), then wiring and
isolation tests (A7, A8). Each unit runs its tests before the next one starts.

### L3 — A1 and A2 complete (2026-10-19)

Models and migration done together, because a model without its migration is not
observable and a migration without its model drifts.

RED → GREEN evidence:

- RED: `pytest` reported 7 failures, all `relation "organizations" does not
  exist`, before the revision existed. The 7 pre-existing tests stayed green.
- GREEN: `pytest` reports 14 passed (7 unit + 7 database).
- Non-vacuity check: the append-only trigger was dropped directly in the test
  database, the two audit tests failed, the trigger was restored, and both
  passed again. A test that cannot fail is not evidence.

Decisions worth recording:

- `users` gained `password_hash` and `is_active`; both are flagged as
  assumptions in S3 rather than passed off as the specification's fields.
- The `role` column stores the enum VALUE (`admin`), not the member name
  (`ADMIN`). SQLAlchemy persists the name by default, so a test asserts the
  stored string; without the `values_callable` argument it would silently
  disagree with every API payload.
- The role CHECK constraint is declared explicitly instead of letting the Enum
  emit one, because both together produced two identical constraints in the
  generated revision.
- `audit_logs.organization_id` is `ON DELETE RESTRICT` on purpose: deleting a
  company must not be able to erase its own evidence.
- The audit append-only guard is a `BEFORE UPDATE OR DELETE OR TRUNCATE ... FOR
  EACH STATEMENT` trigger, so it also covers `TRUNCATE`, which a row-level
  trigger would miss.

Test infrastructure: `tests/conftest.py` migrates the isolated test database once
per session and runs every test inside a transaction that is always rolled back,
using `join_transaction_mode="create_savepoint"` so a test that deliberately
provokes a database error can still finish cleanly.

