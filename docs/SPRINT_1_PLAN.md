# Sprint 1 Plan — Platform Foundation

Status: executed. This is the plan written before implementation; deviations are noted inline.

## 1. Environment findings (Phase A)

| Tool | Version | Notes |
|---|---|---|
| Python | 3.12 / 3.13 | Target 3.12 (`requires-python >=3.12`) |
| uv | 0.11 | Python dependency management |
| Node | 22 LTS | pnpm/npm available; npm chosen (no workspace tooling needed) |
| PostgreSQL | 16 | Local cluster available; Docker image `postgres:16-alpine` |
| Docker | 29 + Compose v2 | Used for the full stack |
| Playwright | 1.63 + Chromium | Used for E2E |

Key library choices (latest stable at time of writing): FastAPI 0.16x, Pydantic 2.x, SQLAlchemy 2.1 (sync, psycopg 3),
Alembic 1.x, pwdlib (Argon2), structlog; Next.js 16 (App Router), React 19, Tailwind 4, TypeScript 5.9
(TS 7 rejected: typescript-eslint supports `<6.1`; TS 6 rejected: openapi-typescript peers on `^5`), Zod 4,
openapi-typescript + openapi-fetch, Vitest, Playwright 1.63 (matches the pre-installed browser build).

## 2. Architecture decisions

* **Modular monolith.** One Python package `aigentix` (in `apps/api`) holds the API, the platform services,
  business modules and the worker entrypoint. `apps/worker` is *not* a separate Python project: the worker is
  the same image started with `python -m aigentix.worker`. This avoids multi-package Python packaging while
  keeping a clear runtime split. Business modules live in `apps/api/src/aigentix/modules/` instead of a
  top-level `modules/` directory for the same reason.
* **Layers:** `api/` (HTTP only) → `platform/*/service.py` and `modules/*/service.py` (business logic, no FastAPI
  imports) → `models` (SQLAlchemy). `core/` holds config, DB, logging, errors.
* **Module contract:** each module exports a `ModuleDescriptor` (key, name, status, optional router,
  workflow handlers). Registration is an explicit list in `aigentix/modules/registry.py` — no dynamic loader.
* **Sync SQLAlchemy.** Simpler than async and sufficient; FastAPI runs sync dependencies in a threadpool.
* **Contracts:** FastAPI's OpenAPI document is exported to `packages/shared-contracts/openapi.json`;
  `openapi-typescript` generates `packages/shared-contracts/schema.d.ts`; the web app uses `openapi-fetch`.
  CI fails if the committed contract is stale.

## 3. Authentication (security-sensitive)

Options considered:

| Option | Verdict |
|---|---|
| Clerk / Auth0 / WorkOS | Rejected for Sprint 1: external SaaS + credentials, not runnable offline |
| Auth.js / Better Auth (in Next.js) | Rejected: auth would live in the TS app, requiring the Python API to share a second ORM/session schema |
| fastapi-users | Rejected: project is in maintenance mode; heavy for our needs |
| **pwdlib (Argon2id) + server-side DB sessions** | **Chosen** |

Design: passwords hashed with `pwdlib` (Argon2id — the library recommended by the FastAPI docs). Sessions are
opaque 256-bit tokens from `secrets.token_urlsafe`, stored **only as SHA-256 hashes** in a `user_sessions` table,
delivered as an `HttpOnly`, `SameSite=Lax`, `Secure` (configurable for local HTTP) cookie. Sign-out deletes the row
(real revocation). This follows the OWASP Session Management Cheat Sheet and uses no custom cryptography.
Future: an OIDC provider can be added as another way to create the same server-side session.

CSRF: `SameSite=Lax` cookie + an Origin check on unsafe methods against the configured allowed origins.
Tenant selection: client sends `X-Organization-Id`; the backend **always** verifies an active membership for the
authenticated user before resolving tenant-scoped data. Non-members receive `404` for tenant resources (no
existence oracle) and `403` for an organization header they are not a member of.

Bootstrap: no public sign-up in Sprint 1. Users are created with `python -m aigentix.cli create-user` or
`seed-dev` (password supplied via env/argument, never committed).

## 4. Data model

`organizations`, `users`, `organization_memberships` (role: owner|member, unique per org/user),
`user_sessions`, `research_projects` (org-owned), `workflow_runs` (org-owned, optional project FK).
All PKs are UUIDs, timestamps `timestamptz` in UTC, explicit Alembic migrations. Future `companies`, `evidence`,
`opportunities`, `lead_scores`, `approvals`, `activities` will follow the same `organization_id` + FK pattern.

## 5. API contract (v1)

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | /health | – | liveness |
| GET | /ready | – | DB connectivity + migration head check |
| POST | /api/v1/auth/login | – | sets session cookie |
| POST | /api/v1/auth/logout | session | revokes session |
| GET | /api/v1/me | session | user + memberships |
| GET | /api/v1/organizations | session | caller's organizations |
| POST | /api/v1/organizations | session | create org, caller becomes owner |
| PATCH | /api/v1/organizations/{id} | owner | rename |
| GET | /api/v1/organizations/{id}/members | member | |
| GET | /api/v1/modules | session | registered modules |
| GET/POST | /api/v1/projects | member + org header | paginated list / create |
| GET | /api/v1/projects/{id} | member + org header | |
| GET | /api/v1/workflows | member + org header | paginated workflow runs |

Pagination: `?limit=&offset=` → `{items, total, limit, offset}`. Errors: `{"error": {"code", "message", "details"}}`.

## 6. Ownership & delegation

Greenfield repo with tightly coupled contracts → implementation executed serially by the lead to avoid
contract churn between parallel agents. An independent reviewer subagent performs the Phase D
architecture/security review (independence is where a separate agent adds real value).

| Area | Paths |
|---|---|
| Backend | `apps/api/**` |
| Frontend | `apps/web/**` |
| Contracts | `packages/shared-contracts/**` (generated; changed only via `make contracts`) |
| DevOps | `docker-compose.yml`, `infra/**`, `.github/**`, `Makefile` |

## 7. Acceptance tests

Backend (pytest, real PostgreSQL): app starts; DB connection; migrations from empty DB (+ downgrade); auth
required; login/logout/session revocation; membership checks; owner-only operation; project create/list/get;
cross-tenant access rejected (list, get, header spoofing); invalid input → 422; worker claims/completes/fails runs.
Frontend: tsc, eslint, `next build`, Vitest component tests (login form, create project form).
E2E (Playwright against Docker stack): login → select org → dashboard → create project → list → detail → sign out;
project persists in PostgreSQL; second-tenant user cannot see it.
