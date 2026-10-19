# FactuHub

Web platform for bank reconciliation: it compares bank statement movements
against a company's accounting ledger, proposes explainable matches, and lets an
accountant confirm or reject each one.

This repository is the MVP described in the project specification
(`docs/PROJECT_SPEC.md`). The product works **with or without** an accounting
API connection: file imports (CSV/XLSX) are a first-class path, not a fallback
hack.

## Status

Phase 2 — foundations. What exists today:

- Monorepo layout (`frontend/`, `backend/`, `docs/`).
- FastAPI application with a versioned health contract.
- PostgreSQL 17 development and test instances (Docker Compose), isolated from
  each other.
- Alembic wired to the application metadata.
- pytest configured with an isolated test database.

Authentication, organizations, imports, the reconciliation engine and the UI are
not implemented yet. See `odd/tasks/` for the live task document.

## Requirements

- Python 3.12+ (verified on 3.14)
- Node.js 20+ (verified on 24)
- Docker with Compose

## Quickstart

```bash
# 1. Environment file (never committed)
cp env.example .env      # then replace every value marked change-me
# CREDENTIALS_ENCRYPTION_KEY is a Fernet key; generate one with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 2. Databases: development on :5432, tests on :5433
docker compose up -d

# 3. Backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:create_app --factory --reload
```

The API is then at `http://localhost:8000`, with OpenAPI at `/docs`.

### Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000
```

The scaffold is Next.js 16 + React 19 + TypeScript + Tailwind 4 with ESLint. No
visual design work has been done yet: the brand identity, logotype, palette and
typeface are chosen in a dedicated later phase.

> Next.js 16 differs from earlier majors in ways that matter. Its documentation is
> vendored inside the installed package at `frontend/node_modules/next/dist/docs/`
> — read the relevant guide there before writing app code, rather than relying on
> memory of older versions.

### Running the tests

```bash
cd backend
.venv/bin/pytest              # fast unit tests
.venv/bin/pytest -m integration   # requires the test database to be up
```

Tests never touch the development database: they use `TEST_DATABASE_URL`, which
points at the `postgres_test` service on port 5433 with its own volume.

### Docker permission note

If `docker compose up -d` fails with `permission denied while trying to connect
to the Docker daemon socket`, your user is not in the `docker` group yet:

```bash
sudo usermod -aG docker $USER
# log out and back in, or run the command through: sg docker -c '<command>'
```

## Repository layout

```
backend/    FastAPI application, migrations and tests
frontend/   Next.js application (UI work starts in a later phase)
docs/       Specification, architecture and integration notes
odd/tasks/  Living task document for the current feature
```

Inside `backend/app/`, responsibilities are separated by layer:

| Path | Responsibility |
| --- | --- |
| `api/` | HTTP surface, versioned under `/api/v1` |
| `core/` | Configuration, security primitives, cross-cutting concerns |
| `db/` | Engine, session factory, declarative base |
| `models/` | SQLAlchemy models (persistence shape) |
| `schemas/` | Pydantic contracts (transport shape) |
| `services/` | Use cases that orchestrate domain work |
| `imports/` | File ingestion and column mapping |
| `integrations/` | External accounting systems (one package per provider) |
| `reconciliation/` | Matching, grouping and balance rules |
| `reports/` | Report generation |
| `audit/` | Append-only audit trail |

## Non-negotiable rules

These come from the specification and apply to every change:

1. Original financial data is never silently modified.
2. No match is invented to force a reconciliation; doubtful movements are never
   auto-approved.
3. Accounting entries are never written without explicit authorization. The MVP
   is read-only towards any accounting system.
4. Monetary amounts are stored exactly (integer minor units), never as floats.
5. Every organization's data is isolated, enforced in the backend and backed by
   PostgreSQL row-level security.
6. Important decisions are traceable through the audit log.

## Known open items

- **World Office capabilities**: the public API exposes generic paginated
  accounting endpoints, but the filter attribute names that would let us select
  bank movements by date and account are not published. See
  `docs/world-office-integration.md`.
