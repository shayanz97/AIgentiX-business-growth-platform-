# AIgentiX Growth Platform

Multi-tenant SaaS where AI agents automate SME growth work (lead intelligence, sales, marketing, analytics).
Sprint 1 = platform foundation. Sprint 2 = Lead Intelligence: companies, CSV import, safe website research,
evidence, AI Opportunity Audit, review. Lead scoring and outreach are later sprints.

## Architecture principles
- **Modular monolith.** One backend package (`apps/api/src/aigentix`), one web app. No microservices, brokers or K8s.
- Layers: `api/` (HTTP only) → `platform/*/service.py`, `modules/*/service.py` (business logic, no FastAPI) → SQLAlchemy models.
- `core/` = config, DB, logging, errors. `platform/` = identity, organizations, workflows. `modules/` = business modules.
- Simplest secure solution; no speculative abstractions; prefer explicit dependencies over globals.

## Technology decisions
FastAPI + Pydantic v2 + SQLAlchemy 2 (sync, psycopg 3) + Alembic + PostgreSQL 16 · uv · pytest/ruff/mypy strict ·
Next.js 16 App Router + React 19 + Tailwind 4 + TypeScript 5.9 + Zod · openapi-typescript/openapi-fetch ·
Docker Compose · GitHub Actions. Auth: pwdlib (Argon2id) + server-side DB sessions. Worker: PostgreSQL-backed queue
(`SELECT … FOR UPDATE SKIP LOCKED`) with step checkpoints, retries, cancellation. Research: httpx2 `SafeFetcher`
(SSRF-safe) + BeautifulSoup; LLM via `anthropic` SDK behind `LLMProvider` (Haiku extraction, Opus audit).
LangGraph deliberately not used yet (linear workflow; see docs/ARCHITECTURE.md).

## Repository structure
```
apps/api/        backend package `aigentix` (API, platform, modules, worker, CLI), migrations/, tests/
apps/web/        Next.js app: src/app (routes), src/components, src/lib (api client, session), e2e/, tests/unit
packages/shared-contracts/  GENERATED openapi.json + schema.d.ts (never hand-edit; `make contracts`)
infra/docker/    Dockerfiles · docker-compose.yml at root · docs/ design docs · .claude/ skills & agents
```

## Commands
`make help` lists everything. Common: `make up` (full stack), `make verify` (lint+types+tests+build),
`make contracts` (after any API change), `make e2e` (stack started with `-f docker-compose.e2e.yml` + `E2E_PASSWORD`),
`/research-eval` (fixture research evaluation).
Backend tests need PostgreSQL at `TEST_DATABASE_URL` (default `postgresql://aigentix:aigentix-local-dev@localhost:5432/aigentix_test`).
New migration: `cd apps/api && uv run alembic revision --autogenerate -m "..."` then **review the file by hand**.

## Testing requirements
- Every new tenant-owned endpoint needs: auth-required test, cross-tenant read test, spoofed-`X-Organization-Id` test.
- Backend tests use real PostgreSQL + Alembic migrations (no SQLite, no mocking the DB).
- Research changes: keep `tests/test_li_ssrf.py`, `test_li_research.py` and `test_li_eval.py` green; new fixture
  sites go in `modules/lead_intelligence/fixtures/sites/` with an `expected.json`.
- `test_models_match_migrations` must stay green: models and migrations never drift.
- Never claim checks passed without running them (`/verify`).

## Security invariants (do not break)
1. Every tenant-scoped query filters by `TenantContext.organization_id` obtained from `api.deps.Tenant`.
   Never read an organization id from a body/query/header without `resolve_tenant` membership verification.
2. Foreign tenant resources return 404 (by id) or 403 (org header) — never data.
3. Owner-only actions check `tenant.is_owner` in the service layer.
4. Session tokens: only SHA-256 hashes stored; cookie HttpOnly + SameSite=Lax (+ Secure outside local HTTP).
5. No custom crypto. Passwords via `platform/identity/passwords.py` only.
6. No secrets in git; config only via env (`.env.example` holds placeholders). Logs never include cookies, passwords, bodies.
7. Validation errors never echo input values.
8. All outbound HTTP to user-supplied URLs goes through `SafeFetcher` (DNS-pinned, every redirect re-validated,
   public addresses only, size/time limits, robots.txt). Never call httpx/requests directly on such URLs.
9. Website text is untrusted: it enters prompts only inside neutralised `<website_content>`/`<evidence>` blocks;
   model output is validated (citations must exist and be verbatim, unsupported claims flagged, foreign links
   stripped) and rendered as plain text. No AI result is fabricated: without a provider runs end `partial`.
10. Test doubles (`RESEARCH_FETCH_BACKEND=fixtures`, `LLM_PROVIDER=fixture`) are refused in production.

## Module development rules
- A module lives in `apps/api/src/aigentix/modules/<key>/` and exports a `ModuleDescriptor` (see `modules/base.py`).
- Register it explicitly in `modules/registry.py`. No dynamic plugin loading.
- A module may import `aigentix.core` and `aigentix.platform`; **never another module**.
- Module tables carry `organization_id` (FK, indexed) and every query is tenant-scoped.
- Long-running work = a workflow type in the descriptor's `workflows` (`WorkflowSpec`), executed by the worker —
  never inside a request. Handlers call `ctx.checkpoint(step, progress)` between steps, keep step outputs
  idempotent (resume after crash/retry), raise `WorkflowError` (permanent, user-safe message) or
  `TransientWorkflowError` (retried), and report model spend with `ctx.record_usage`.
- External providers (LLM, search, fetching) stay behind small interfaces with test doubles; prompts are versioned.
- Do not show unimplemented features as functional in the UI; planned modules stay disabled.
- Changing an API contract → `make contracts` and commit both generated files in the same change.
