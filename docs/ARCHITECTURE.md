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
- Database-level guard: every link between tenant-owned rows is a composite FK including `organization_id`
  (`research_runs → workflow_runs/companies/research_projects`, `research_sources`, `evidence`, `opportunities`,
  `opportunity_evidence`, `research_project_companies`), so the database rejects cross-tenant links even if a
  service had a bug. Companies are deduplicated per organization (`organization_id, canonical_domain`).
- Future entities (`lead_scores`, `approvals`, `activities`) follow the same pattern.

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

- `workflow_runs` (platform, module-agnostic): `pending → running → completed | partial | failed | cancelled`,
  `current_step`, `progress`, `attempts/max_attempts`, `next_attempt_at`, `heartbeat_at`, `cancel_requested_at`,
  `error_type/error_message`, token counts, `estimated_cost_usd`, JSONB `metadata` (input, persisted step state,
  result). Module tables link to runs with composite FKs (e.g. `research_runs`).
- Claiming: `SELECT … FOR UPDATE SKIP LOCKED` under a transaction-scoped advisory lock, which also enforces
  per-workflow-type concurrency limits across workers (`RESEARCH_MAX_CONCURRENT_RUNS`).
- Handlers receive a `WorkflowContext`: `checkpoint(step, progress)` commits work, records the step, heart-beats
  and raises on cancellation; `get_state/set_state` persist resumable state; `record_usage` adds model spend in
  its own transaction so it is never lost.
- Errors: `WorkflowError` → failed (message shown to users); `TransientWorkflowError` / DB `OperationalError` →
  re-queued with exponential backoff until `max_attempts`; anything else → failed with a generic message (details
  only in logs). Housekeeping re-queues runs whose heartbeat stopped (resume from the persisted step) or fails
  them after the last attempt, and purges expired sessions.
- Ownership: a worker records the attempt number it claimed; `checkpoint` and every final write verify that the
  run is still `running` with that attempt, so a worker whose run was recovered and re-claimed elsewhere stops
  without writing. A cancel requested during a failed attempt wins over the retry.
- PostgreSQL remains the queue: no Redis/Celery/Temporal/Kafka.

## Lead Intelligence research (Sprint 2)

```
VALIDATE_INPUT → FETCH_WEBSITE → DISCOVER_RELEVANT_PAGES → EXTRACT_INFORMATION → SAVE_EVIDENCE
              → AI_OPPORTUNITY_AUDIT → PERSIST_RESULTS → completed | partial
```

| Step | What happens | Failure handling |
|---|---|---|
| validate | `parse_website` (http/https, ports 80/443, no IP literals/internal TLDs/credentials) | permanent |
| fetch | robots.txt, homepage via `SafeFetcher`, readable text + signals, source stored | blocked/robots/4xx permanent; timeouts/5xx/429 transient |
| discover | ≤ `RESEARCH_MAX_PAGES`-1 same-site pages, one per category first (about, services, contact, support, booking, FAQ, products, careers, technology); excludes login/cart/legal/personal-profile/file URLs; robots + crawl-delay honoured | per-page failures recorded, run continues |
| extract | deterministic signals (forms, booking/chat widgets, FAQ, careers, documents, e-commerce, support, description) + optional LLM extraction (`claude-haiku-5-5`) whose assertions are kept only if their excerpt is found verbatim in the cited source | AI errors: transient → retry, last attempt → `partial` |
| save evidence | evidence replaced for the run; company profile fields updated only from observed or ≥medium-confidence assertions | — |
| audit | `claude-opus-5-5` proposes ≤3 opportunities citing evidence IDs; validation drops uncited ones, flags unsupported negative claims, caps confidence, strips foreign links | as extract; per-run cost cap |
| persist | opportunities + evidence links replaced for the run | — |

**SSRF protection (`SafeFetcher`)**: resolve once; every address must be global unicast (blocks loopback, RFC1918,
link-local/metadata, CGNAT, multicast, reserved, IPv4-mapped, NAT64, 6to4, Teredo); connect to the validated IP with
the original Host header and TLS SNI (no DNS-rebinding window); redirects followed manually (≤5) and re-validated;
environment proxies ignored; no keep-alive reuse (the pool is keyed by IP); uncompressed responses only, streamed
with a byte cap; connect/read timeouts plus a 30 s wall-clock deadline per request (slow-drip servers) and a
discovery time budget per run; per-domain request spacing. Look-alike or foreign links in model output are removed
by host comparison (`acme.com.evil.io`, `evil.com/?x=acme.com`, bare domains).

**Untrusted content**: hidden elements, comments, scripts, `<meta>`/`<title>` and site chrome (nav/header/footer)
are removed from text; e-mail addresses and phone numbers are redacted before storage. Prompts wrap content in
`<website_content>`/`<evidence>` blocks with `<`/`>` neutralised so page text cannot close them, and the system
prompt states that block content is data. Output is never trusted: see validation above. The UI renders all model
text as plain text.

**AI availability**: no `ANTHROPIC_API_KEY` → deterministic research only, run ends `partial` with "AI analysis
unavailable"; no opportunities are generated. `LLM_PROVIDER=fixture` (rule-based test double) and
`RESEARCH_FETCH_BACKEND=fixtures` (bundled `*.example` sites) exist for CI/E2E/demos and are refused in production.
Models used and prompt versions are stored with every run and shown in the UI.

**Cost control**: `LLM_MAX_COST_PER_RUN_USD` is a hard cap — `max_tokens` for each call is derived from the
remaining budget at the output price of the configured model, repair attempts stop when the budget is spent, and
responses that fail schema parsing are recorded at their worst-case output cost (the SDK does not report their
usage). LLM evidence wording that its excerpt does not back is downgraded to a low-confidence inference, and
negative characterisations without textual support are dropped.

**Retention**: page text is truncated (`RESEARCH_MAX_TEXT_CHARS`) and kept only as provenance for evidence; no
full-site copies, no personal profiles crawled, contact details redacted.

### AI providers and model routing

`aigentix/platform/llm/` is the shared LLM layer for every module:

| File | Role |
|---|---|
| `base.py` | `LLMProvider` protocol (what modules call), `ModelClient` (one vendor), `LLMUsage`, error taxonomy (`LLMTransientError`, `LLMPermanentError`, `LLMUnavailable`, `LLMInvalidOutput`, `LLMBudgetExceeded`) |
| `providers/anthropic.py` | Messages API `messages.parse` (+ server-side refusal fallback on supported models) |
| `providers/openai.py` | Responses API `responses.parse` with Pydantic `text_format`, `store=False`; refusal / incomplete / failed statuses mapped to the error taxonomy |
| `router.py` | `Route` (`provider:model`), `RoutedProvider` (task → vendor client + model), `PROVIDERS` registry |
| `pricing.py` | built-in prices + `LLM_PRICES_JSON` overrides; unknown models priced pessimistically so budgets fail safe |
| `config.py` | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, timeout, fallback flag, price overrides |

Modules choose models per task. Lead Intelligence uses `LLM_ROUTE_EXTRACTION` and `LLM_ROUTE_AUDIT`
(e.g. `anthropic:claude-haiku-5-5`, `openai:<model-id>`), falling back to `LLM_PROVIDER` + `LLM_*_MODEL`.
Invalid routes fail at startup; a route whose provider has no key makes that task unavailable (extraction
skipped → audit still runs on deterministic evidence; audit unavailable → run ends `partial`). Every run stores
the `provider:model` labels it used. Adding a vendor = one `ModelClient` + one entry in `PROVIDERS`.
Per-organization provider choice / bring-your-own-key is deliberately not implemented (needs encrypted
secret storage).

### Decision: no LangGraph in Sprint 2

The workflow is a fixed linear sequence; step outputs are persisted in PostgreSQL, which already gives resume,
retry, cancellation and observability. LangGraph would add a dependency and a second state store without a
concrete benefit. Revisit when a workflow needs branching/looping agent graphs or human-in-the-loop interrupts —
the handler boundary (`WorkflowContext` → `WorkflowResult`) is where a graph would be invoked.

## API conventions

- Versioned under `/api/v1`; OpenAPI at `/api/v1/openapi.json`, Swagger UI at `/api/v1/docs`.
- Lists: `?limit=1..100&offset=` → `{items, total, limit, offset}`.
- Errors: `{"error": {"code", "message", "details"}}` with codes `not_authenticated` (401), `forbidden` (403),
  `not_found` (404), `invalid_input` (400), `validation_error` (422), `conflict` (409), `origin_not_allowed` (403),
  `too_many_attempts` (429), `service_busy` (503).
- Contract: `make contracts` regenerates `packages/shared-contracts`; the web client is typed from it.

## Known limitations

- No public sign-up, invitations, password reset or e-mail verification (users are created via CLI).
- Login throttling and per-domain request spacing are in-process: correct for one API / one worker process. With
  several, add an IP limit at the reverse proxy and move counters/spacing to PostgreSQL.
- Research covers static HTML only (no JavaScript rendering), English-centric page categories and signal keywords.
- The concurrency limit counts `running` runs only; the advisory lock makes the check exact across workers.
- Re-researching a company creates a new run; the company page shows the latest finished run (older runs and
  their reviewed opportunities stay available by run id).
- Opportunity quality has been evaluated with fixture sites and a rule-based test double; no live-model
  evaluation has been run (no API key in the build environment). See `/research-eval`.
- OpenAI models have no built-in prices: set `LLM_PRICES_JSON` for accurate cost estimates and budgets.
- `API_INTERNAL_URL` is fixed at web build time (Next.js rewrites are compiled).
