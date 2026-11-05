# AIgentiX Growth Platform

Modular, multi-tenant SaaS platform that helps SMEs automate business growth with AI agents.
**Status: Sprint 1 — platform foundation** (auth, organizations, research projects, workflow/worker skeleton).
AI research and analysis start in Sprint 2.

| Component | Tech | Path |
|---|---|---|
| Web app | Next.js 16, React 19, Tailwind 4, TypeScript | `apps/web` |
| API + worker | FastAPI, SQLAlchemy 2, Alembic, Python 3.12 | `apps/api` |
| Database | PostgreSQL 16 | Docker volume `pgdata` |
| API contract | OpenAPI → TypeScript types | `packages/shared-contracts` |

Docs: [Architecture](docs/ARCHITECTURE.md) · [Sprint 1 plan](docs/SPRINT_1_PLAN.md) · [Claude Code guide](CLAUDE.md)

## Quick start (Docker)

Prerequisites: Docker with Compose v2.

```bash
cp .env.example .env
# Edit .env: set POSTGRES_PASSWORD to a long random value, e.g. `openssl rand -hex 24`
docker compose up -d --build --wait       # db, migrate (one-shot), api, worker, web
docker compose run --rm api python -m aigentix.cli seed-dev   # prompts for a demo password (min 12 chars)
```

Open http://localhost:3000 and sign in as `owner@acme.example` with the password you chose.
`seed-dev` creates two tenants for trying isolation:

| User | Organization | Role |
|---|---|---|
| owner@acme.example | Acme Robotics | owner |
| member@acme.example | Acme Robotics | member |
| owner@globex.example | Globex Analytics | owner |

To create a real user instead: `docker compose run --rm api python -m aigentix.cli create-user --email you@company.com --organization "Your Co"`.
There is no public sign-up in Sprint 1 (by design; see Known limitations).

URLs: web http://localhost:3000 · API docs http://localhost:8000/api/v1/docs · OpenAPI http://localhost:8000/api/v1/openapi.json
· liveness `/health` · readiness `/ready`. All ports bind to 127.0.0.1.

Stop with `docker compose down` (add `-v` to delete the database).

## Local development (without Docker for the apps)

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 22, PostgreSQL 16 (or `docker compose up -d db`).

```bash
make install
cp apps/api/.env.example apps/api/.env      # set DATABASE_URL
cp apps/web/.env.example apps/web/.env.local
make migrate
cd apps/api && uv run python -m aigentix.cli seed-dev && cd ../..
make api-dev      # http://localhost:8000
make worker-dev   # optional, separate terminal
make web-dev      # http://localhost:3000 (proxies /api/v1 to the API)
```

## Tests and checks

```bash
# Backend tests need a disposable PostgreSQL database (the schema is dropped and re-migrated):
export TEST_DATABASE_URL=postgresql://aigentix:<password>@localhost:5432/aigentix_test
make verify        # ruff, mypy --strict, pytest, eslint, tsc, vitest, next build
make contracts     # regenerate OpenAPI + TS types after API changes (CI checks freshness)

# End-to-end (stack running and seeded):
E2E_PASSWORD=<seed password> make e2e
```

CI (`.github/workflows/ci.yml`) runs backend, contract-freshness, frontend and a Docker Compose + Playwright
integration job that also verifies the UI-created project is persisted in PostgreSQL.

## Repository layout

```
apps/api/src/aigentix/
  core/          config, database, logging, errors
  api/           FastAPI app, middleware, auth/tenant dependencies, platform routes
  platform/      identity (users, sessions), organizations (tenancy, roles), workflows (runs, registry)
  modules/       business modules (lead_intelligence) + explicit registry
  worker/        background worker (PostgreSQL-backed queue)
  cli.py         create-user, seed-dev
apps/api/migrations/   Alembic migrations
apps/web/src/          app routes, components, typed API client, session context
packages/shared-contracts/  generated API contract
infra/docker/          Dockerfiles
.claude/skills/        /verify, /architecture-review, /security-review, /handoff
```

## Configuration

All configuration is environment-based; see `.env.example`, `apps/api/.env.example`, `apps/web/.env.example`.
No secrets are committed. `SESSION_COOKIE_SECURE` must stay `true` whenever the app is served over HTTPS.
`API_INTERNAL_URL` (web) is compiled into the Next.js build (rewrites), so set it as a build arg for deployments.

## Deployment notes (VPS)

The same `docker-compose.yml` runs on a single VPS. Put a TLS-terminating reverse proxy (Caddy/nginx) in front of
`web` (port 3000) only, set `SESSION_COOKIE_SECURE=true`, `ENVIRONMENT=production`, `CORS_ORIGINS=https://your.domain`,
and use a managed or backed-up PostgreSQL volume. Do not expose the API or database ports publicly.
