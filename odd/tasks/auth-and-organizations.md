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

Consequently both foreign keys on `audit_logs` are `ON DELETE RESTRICT`, not
`CASCADE` and not `SET NULL`. Deleting a company or a person who has history is
refused by the database; the `SET NULL` alternative would have quietly rewritten
"who approved this" into "nobody", which is precisely the silent modification
the specification forbids. People are deactivated, never erased.

### S5 — Session security

Verbatim from the specification (§11.1):

> - Sesiones seguras.
> - Cookies `HttpOnly`, `Secure` y política `SameSite` adecuada si se utilizan cookies.
> - Protección contra CSRF cuando corresponda.
> - Recuperación de acceso segura.
> - MFA recomendado para administradores y aprobadores.
> - Limitación de intentos de autenticación.

**Assumption, flagged as such:** §7's model list has no `sessions` table, and
none is possible without one. A signed stateless token cannot be revoked, and
this platform must be able to end access immediately when someone is removed
from a company or deactivated. Sessions are therefore rows: the token is stored
as a SHA-256 digest, and the server checks the deadline, the revocation flag and
the account's `is_active` on every authenticated request. The cost is one
indexed lookup per request; the benefit is that "quitale el acceso" means now.

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
| A2 | S4, S7 | Migration with integrity constraints, indexes and the append-only audit trigger | inline | done | revision `6292f9b04939`; upgrade/downgrade round trip proven; trigger present in `pg_trigger` |
| A3 | S5 | Password hashing (Argon2id) and session-token primitives | inline | done | `app/core/security.py`; 15 unit tests; commit `97e6e9a` |
| A4 | S5 | Server-side sessions and the registration/authentication service | inline | done | `app/models/user_session.py`, `app/services/auth.py`; revision `1be4915f3856`; 21 integration tests |
| A5 | S5 | Auth endpoints: register, login, logout, me, with rate limiting and CSRF | inline | done | `api/v1/endpoints/auth.py`, `api/deps.py`, `api/cookies.py`; revision `246fdeef0361`; 21 API + throttle tests |
| A6 | S6 | RBAC: permission matrix and the `require_permission` dependency enforced per operation | inline | done | `app/core/permissions.py`, `api/deps.py::require_permission`; 7 unit tests; used by every organization route |
| A7 | S6, S7 | Row-level security policies plus the non-superuser application role they need to be real | inline | pending | — |
| A8 | S4 | Audit service wired into the actions the specification lists | inline | pending | — |
| A9 | S8 | Isolation tests: another organization's data is unreachable | inline | pending | — |
| A10 | S6 | Organization endpoints: create, list, detail | inline | done | `api/v1/endpoints/organizations.py`, `app/services/organizations.py`; RED `ModuleNotFoundError: app.core.permissions`, GREEN 104 passed with 9 new integration tests |
| A11 | S6 | Membership management: add member, change role, remove member; 403 denials and last-admin protection | inline | done | RED 13 failed / GREEN 15 passed in `test_members_api.py`; `require_permission(MANAGE_MEMBERS)` + `organizations_service.change_member_role`/`remove_member`; lock via `SELECT ... FOR UPDATE` on the company row |

Task IDs A5-A9 were renumbered when the session work split away from the
endpoints task; A1-A4 keep the meaning they had when they were committed.

A6 is the *mechanism* and A10 is its first *caller*; they are separate rows
because A7 (row-level security) depends on the mechanism, not on the endpoints.

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

### L4 — A3 complete (2026-10-19)

`app/core/security.py`, committed as `97e6e9a`, with 15 unit tests.

- Argon2id for passwords (already a declared dependency), SHA-256 for session
  tokens. The asymmetry is deliberate: a token carries 256 bits of entropy, so
  slowness buys nothing there and would make every authenticated request a
  denial-of-service lever; a human password is guessable, so slowness is the
  defence.
- `verify_password` returns `False` for a corrupted stored hash instead of
  raising. A damaged row must look like a failed login, not like a server error
  that tells the caller their input reached a different code path.
- Password policy: 12 to 128 characters. Flagged in S5 as an assumption, because
  §11.1 asks for secure authentication without stating a policy. Length is the
  part that resists guessing; composition rules mostly produce `Password1!`.
  The upper bound exists so hashing cannot be weaponised.

### L5 — A4 complete (2026-10-19)

`app/models/user_session.py`, `app/services/auth.py`, revision `1be4915f3856`,
21 integration tests. Suite total: 55 passed.

The design conflict this unit surfaced is worth recording, because it changed the
schema:

- `audit_logs.user_id` was initially `ON DELETE SET NULL`. Deleting a user made
  PostgreSQL emit `UPDATE audit_logs SET user_id = NULL`, and the append-only
  trigger rejected it — correctly. The `SET NULL` cascade was itself the silent
  modification of history that §7.11 forbids: "quién aprobó esto" would have
  become "nobody". Both audit foreign keys are now `ON DELETE RESTRICT`; a person
  with history cannot be deleted, only deactivated.
- The trigger is statement-level, so it fires even for an `UPDATE` that matches
  zero rows. That is why the failure appeared in a test that had no audit rows at
  all, and why `RESTRICT` (checked only when a referencing row exists) is the
  behaviour that fits.
- Because the revision had not been pushed and no environment had been deployed,
  it was corrected in place and both databases were rebuilt (`downgrade base`,
  `upgrade head`) instead of stacking a fixup migration on a mistake.
- Registration hashes the password before writing anything, so a rejected
  password cannot leave an account nobody can sign in to. The uniqueness
  pre-check is a courtesy; the real guarantee is the unique constraint, and an
  `IntegrityError` inside a savepoint is translated into the same domain error so
  two simultaneous registrations produce a conflict, not a 500.
- `authenticate` verifies against a cached dummy hash when the email is unknown,
  so an attacker cannot enumerate accounts by timing.
- `resolve_session` re-reads `is_active` on every request. A cookie must not
  outvote a decision made in the database.

Deliberately deferred, so it is not mistaken for forgotten: no `last_used_at`
(nothing in the specification needs it and it would add a write per request) and
no IP or user-agent stored on the session (data minimisation, given the
data-protection obligations in §12.2).

### L6 — A5 complete (2026-10-19)

`api/v1/endpoints/auth.py`, `api/deps.py`, `api/cookies.py`, revision
`246fdeef0361`. Suite: 76 passed.

- **Rate limiting lives in PostgreSQL** (the user approved this explicitly:
  "si es lo mejor hazlo así como dices"). A per-worker dictionary protects one
  worker out of N and resets when the process restarts. The check and the
  increment are a single atomic step — `INSERT ... ON CONFLICT DO NOTHING` then
  `SELECT ... FOR UPDATE` — because a plain check-then-record lets a burst of
  parallel requests all observe the same stale count. Each *reserved* attempt is
  committed before the password is verified: a failed login ends in an
  exception, and rolling the counter back with it is exactly how a rate limiter
  stops limiting.
- The lockout window is fixed from the first failure and never slides, so the
  lock always ends after 15 minutes. The accepted trade-off: someone who knows an
  address can lock it for that window. The alternative (no per-address limit)
  would let an attacker guess passwords forever, which is worse.
- **CSRF is bound to the session**, not merely double-submitted. The token is
  stored with the session; a state-changing request must send it in
  `X-CSRF-Token` and it must match both the readable cookie and the stored value,
  so a cookie injected from a sibling subdomain fails. `SameSite=Lax` is the
  baseline and implies a deployment constraint now documented in
  `docs/architecture.md`: API and web app stay same-site.
- `POST /auth/register` intentionally does not sign the user in, so registration
  never leaves a session behind. `/auth/login` does.
- The password policy is owned by the domain, not duplicated in the Pydantic
  schema: the endpoint translates `PasswordPolicyError` into a 422. One
  definition of "valid password", and the translation is covered by a test.
- The 429 response carries `Retry-After`, and login failures return one message
  for a wrong password, an unknown address and a disabled account.
- `email-validator` was added as a dependency rather than hand-rolling address
  validation.

Test note: the CSRF tests assert both directions — the same logout that answers
204 with the header answers 403 without it, so the check is proven to
discriminate rather than merely to exist.

### L7 — Authorization and the first tenant-scoped endpoints (2026-10-19)

Spec §11.2 lists the permissions to verify per operation (read, import,
reconcile, approve, integration configuration) and §7.2 names the four roles, but
the specification never joins the two. That join is an **assumption**, written
into `app/core/permissions.py` and recorded here so it can be corrected by the
user rather than discovered later:

| Role | Permissions |
| --- | --- |
| `admin` | every permission |
| `accountant` | read, import, reconcile, manage integrations |
| `reviewer` | read, approve |
| `viewer` | read only |

`MANAGE_MEMBERS` is not in §11.2's list; it is needed by the membership
endpoints and is added as a named assumption, not smuggled in. The reviewer is
deliberately denied `reconcile`: separation of duties is the point of having a
reviewer at all (§7.7 has the reviewer approve or reopen what somebody else
produced).

Design decisions worth not re-litigating:

- **404, never 403, for a company you do not belong to.** Answering 403 would
  confirm that the identifier belongs to a real company, turning the API into an
  enumeration oracle. One test pins this, and the two neighbouring tests (401
  anonymous, 200 as a member) prove the 404 comes from the membership check and
  not from something else.
- **The role is read from the database on every request.** Nothing about
  authorization is carried in the session cookie or sent by the client, so a
  role change takes effect on the next request instead of when a token expires.
- **Creating a company makes the caller its admin in one savepoint.** A company
  with no admin would be unreachable, so the state must not be observable.
- **The duplicate-tax-id answer comes from the database constraint**, not from a
  prior `SELECT` that would still race; the endpoint translates the
  `IntegrityError` into a 409 rather than a 500.
- **RBAC is a mechanism with its own tests** (`test_permissions.py`, 7 unit
  tests, no database) and the routes are just callers. The matrix is exhaustive
  over `MembershipRole` by test, so a fifth role cannot be added without
  deciding its permissions.

Was there a route that could produce a 403? Not yet at this point: every role
holds `READ`, so the only permission enforced was one nobody lacks. That gap
closed with A11, where `MANAGE_MEMBERS` is required and `viewer`, `reviewer` and
`accountant` are each refused by test.

Tests: 16 new (104 total), all green; ruff clean. Test-first held this time — the
two test files were written and run before any of the implementation existed, and
the observed failure was `ModuleNotFoundError: No module named
'app.core.permissions'`.

Test-writing note, recorded because it cost two runs: the `client` fixture is an
*unauthenticated* client; authenticated tests need `auth_client`. Eight tests
were green-by-accident until the fixture was fixed, which is a reminder that a
test that fails for the wrong reason can also pass for the wrong reason.

Open decision for the user (their domain, not mine to guess): whether
`900123456-7` and `900123456` are the same NIT. Today they are two different
companies because the platform compares the string exactly. Normalising NITs
without knowing how their clients write them would be inventing a rule.

### L8 — Membership management: the first real 403, and the only-admin invariant (2026-10-19)

Spec §7.2 leaves "how a member is added" open. Decisions taken, all of them
recorded as assumptions:

- **Adding a member requires the account to exist**: `POST .../members` takes an
  email and answers 404 when there is no account. The platform does not send
  invitations yet, and an endpoint that pretended to would be worse than one
  that refuses. The trade-off is real and named: this reveals account existence,
  but only to an admin of a company, and the alternative (silent success) would
  make the members screen lie.
- **Invitations are not implemented**, so the members screen lists members and
  adds existing ones. If the product needs invitations, that is a new task, not
  a hidden behaviour.
- **The last-admin rule returns 409**, on both role change and removal. The
  reason is that a company with no admin cannot be repaired from inside the
  product: nobody left can grant the role back.
- **The role change takes effect on the next request** of the affected person,
  because `require_permission` reads the membership from the database. A test
  asserts this from the affected person's own session, not from the admin's.
- **Removing a member removes the membership, not the account.** A test proves
  the removed person's `/auth/me` still answers 200 while their access to that
  company becomes 404. People with history are deactivated, never erased —
  consistent with the `audit_logs` foreign keys being `ON DELETE RESTRICT`.

The one genuinely risky part, and why: the last-admin rule is a read-then-write.
Two admins demoting themselves at the same instant would each read the other and
both succeed, leaving a company nobody can administer. `change_member_role` and
`remove_member` therefore take `SELECT ... FOR UPDATE` on the *company* row
before counting admins, which serialises membership changes per company. The lock
is taken on `organizations` rather than on the membership row because the row
being removed may be the one that would have to be locked.

**Honest limit of the evidence**: the two-admin race is reasoned and locked, but
it is *not* proven by a test here — the test harness deliberately runs every test
inside one rolled-back transaction, so two concurrent connections cannot be
produced inside it. That is what the independent verification pass is for.

Tests: 15 new (119 total), ruff clean. Test-first held: the file ran first and
produced 13 failures, then 15 passes.

Test-writing note, worth keeping: the first run of these tests failed because the
helper added a member by email without creating the account. Two of them passed
for the wrong reason — a missing route also answers 404. A test that passes
because the route does not exist is not evidence, which is why the two 404
assertions are now paired with the 200 and 201 assertions in the same file.

