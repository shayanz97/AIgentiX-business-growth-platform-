# Architecture

## Overview

```
Browser ──► Next.js (web, :3000) ──rewrite /api/v1/*──► FastAPI (api, :8000) ──► PostgreSQL
                                                                          ▲
                                       worker (python -m aigentix.worker) ┘  polls workflow_runs
```

The browser only talks to the web origin; Next.js forwards `/api/v1/*` to the API. The session cookie is
therefore first-party, and no cross-origin credentialed requests are needed. The API also enforces a CORS
allowlist and an Origin check for direct access.

## Backend layers (`apps/api/src/aigentix`)

| Layer | Responsibility | May import |
|---|---|---|
| `core/` | settings, engine/session, logging, domain errors | stdlib, libraries |
| `platform/identity` | users, password hashing, sessions | core |
| `platform/organizations` | organizations, memberships, roles, `TenantContext` | core, identity |
| `platform/workflows` | `WorkflowRun` model, lifecycle service, handler registry | core, organizations |
| `modules/<key>/` | business capability: models, schemas, service, router, descriptor | core, platform |
| `api/` | FastAPI app, middleware, dependencies (`CurrentUser`, `Tenant`, `Pagination`), platform routes | everything above |
| `worker/` | polling loop executing registered workflow handlers | core, platform |

Services are plain functions taking a `Session` and a `TenantContext`; they contain all business rules and
authorization decisions, and never import FastAPI. Routes validate input, call a service, commit, and serialize.

## Tenancy model

- `organizations` ←→ `users` via `organization_memberships(role: owner|member)`.
- Every tenant-owned table has `organization_id` (FK, indexed, `ON DELETE CASCADE`).
- The client selects the active organization with the `X-Organization-Id` header. `api.deps.get_tenant` resolves it
  through `resolve_tenant`, which requires a membership row for the authenticated user — otherwise 403.
- Services filter every query by `tenant.organization_id`. A foreign resource fetched by id returns 404.
- Database-level guard: `workflow_runs (project_id, organization_id)` has a composite FK to
  `research_projects (id, organization_id)`, so a run can never point to another tenant's project.
- Future entities (`companies`, `evidence`, `opportunities`, `lead_scores`, `approvals`, `activities`) follow the
  same pattern; child tables that reference a project should use the same composite-FK technique.

## Authentication

Server-side sessions: Argon2id password hashes (pwdlib), random 256-bit session tokens stored as SHA-256 hashes,
HttpOnly/SameSite=Lax/Secure cookie, rotation on login, deletion on logout, absolute expiry (default 7 days),
per-account login throttling and bounded concurrent hashing. `ENVIRONMENT=production` refuses
`SESSION_COOKIE_SECURE=false` and disables the interactive API docs.
Rationale and alternatives: `docs/SPRINT_1_PLAN.md` §3. An OIDC/SSO provider can later be added as another way to
*create* the same session, without changing authorization code.

## Modules

`modules/base.py::ModuleDescriptor` is the platform↔module contract (key, name, status, router, workflow handlers).
`modules/registry.py` lists modules explicitly; the API mounts their routers under `/api/v1` and the worker merges
their workflow handlers. Planned modules (Sales, Marketing, Analytics) are registered with `status=planned` and no
router, which lets the UI show them as disabled without pretending they work.

## Workflows and the worker

- `workflow_runs`: `queued → running → succeeded | failed | cancelled`, with `started_at`, `completed_at`,
  `error_type`, `error_message`, `attempts`, JSONB `metadata` (input and result).
- The worker claims the oldest queued run with `SELECT … FOR UPDATE SKIP LOCKED` (safe with several workers),
  commits the `running` state, runs the handler, then records success (result merged into metadata) or failure.
- PostgreSQL is the queue: no Redis/Celery/Temporal until throughput or scheduling needs justify it.
- Sprint 1 ships one platform workflow, `platform.noop`, used to prove the pipeline end to end. No API endpoint
  enqueues runs yet; `GET /api/v1/workflows` lists them.

### LangGraph integration plan (Sprint 2)

1. `modules/lead_intelligence/workflows/company_research.py` builds a LangGraph `StateGraph`
   (fetch site → extract evidence → opportunity audit → score). Graph state is a Pydantic model.
2. A handler `def company_research(db, run) -> dict` compiles and invokes the graph with input from
   `run.metadata`, persisting domain results (companies, evidence, opportunities, scores) via the module's service
   functions, scoped by `run.organization_id`. It is registered under `COMPANY_RESEARCH_WORKFLOW`.
3. An endpoint `POST /api/v1/projects/{id}/research` enqueues the run (tenant-checked) and the UI polls
   `GET /api/v1/workflows?project_id=…`.
4. If multi-step resumability or human approval is needed, add LangGraph's PostgreSQL checkpointer keyed by
   `workflow_runs.id` — still no extra infrastructure.
5. LLM/HTTP clients live in `aigentix/integrations/` behind small interfaces so they can be faked in tests.

### Decision: `workflow_runs.project_id` (accepted trade-off)

`workflow_runs` (platform) has a composite FK to `research_projects` (Lead Intelligence). This couples a platform
table to one module's table at the schema level, but buys a database-enforced same-tenant guarantee for the only
run subject that exists. **Revisit before a second module needs runs**: either a generic
`subject_type`/`subject_id` (integrity enforced in services + tests) or module-owned link tables
(`lead_intelligence_project_runs(run_id, project_id, organization_id)` with composite FKs to both sides).
Python code is unaffected either way: the platform never imports module models.

Worker failure handling: handler exceptions are recorded in a fresh session (so a broken transaction cannot leave a
run in `running`); only `WorkflowError` messages are shown to tenant users, other exception text stays in the worker
log; housekeeping fails runs stuck in `running` longer than `WORKER_STALE_RUN_MINUTES` and purges expired sessions.

## API conventions

- Versioned under `/api/v1`; OpenAPI at `/api/v1/openapi.json`, Swagger UI at `/api/v1/docs`.
- Lists: `?limit=1..100&offset=` → `{items, total, limit, offset}`.
- Errors: `{"error": {"code", "message", "details"}}` with codes `not_authenticated` (401), `forbidden` (403),
  `not_found` (404), `invalid_input` (400), `validation_error` (422), `conflict` (409), `origin_not_allowed` (403),
  `too_many_attempts` (429), `service_busy` (503).
- Contract: `make contracts` regenerates `packages/shared-contracts`; the web client is typed from it.

## Known limitations (Sprint 1)

- No public sign-up, invitations, password reset or e-mail verification (users are created via CLI).
- Login throttling (10 failures / 15 min per account, max 4 concurrent Argon2 hashes) is **in-process**: correct for
  one API process. With several processes/replicas, add an IP-based limit at the reverse proxy and/or move the
  counters to PostgreSQL.
- Stuck runs are failed (not retried) after `WORKER_STALE_RUN_MINUTES`; retries/backoff come with real workflows.
- `target_url` is only syntax-validated. Before Sprint 2 fetches it, resolve the host and block private,
  loopback and link-local ranges (re-check after each redirect) to prevent SSRF.
- No member management UI/API beyond listing; no project update/archive endpoints.
- `API_INTERNAL_URL` is fixed at web build time (Next.js rewrites are compiled).
- The active organization lives in `localStorage`; the server never trusts it without membership checks.
