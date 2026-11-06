# Sprint 2 Plan — Lead Intelligence: Research & Opportunity Discovery

Status: implemented. Results and deviations: see the completion notes at the end of this file.

## 0. Baseline (inspected before changes)

Sprint 1 green: ruff, mypy --strict, 90 backend tests, eslint, tsc, 18 Vitest tests. Branch not yet pushed
(GitHub App access missing — see report). No LLM API key in this environment: AI paths are verified with
test doubles; the Anthropic provider is implemented against the documented SDK and only exercised live when a
key is configured (`RESEARCH_EVAL_LIVE=1`, spending cap enforced).

## 1. Key decisions

| Topic | Decision | Why |
|---|---|---|
| Orchestration | Explicit step pipeline on the existing PostgreSQL worker; **no LangGraph yet** | The workflow is linear; step outputs persisted in PostgreSQL already give resume/retry/cancel. LangGraph adds a dependency without concrete value until branching/human-in-the-loop graphs appear |
| Run model | Extend platform `workflow_runs` (generic: status, step, progress, usage, cost, retries, cancel, heartbeat); module table `research_runs` links run → company/project | Keeps the platform module-agnostic. Removes the Sprint 1 `workflow_runs.project_id` FK into a module table (review finding M3) |
| Statuses | `pending, running, completed, partial, failed, cancelled` (Sprint 1 `queued/succeeded` migrated) | Spec vocabulary |
| Retries | `TransientWorkflowError` → back to `pending` with exponential backoff until `max_attempts`; `WorkflowError` → `failed`, never retried | Permanent input errors must not retry |
| Interruption | Heartbeat per step; housekeeping re-queues stale `running` runs (resume at persisted step) or fails them after max attempts | Recover from worker crashes |
| Fetching | Own SSRF-safe fetcher on `httpx2` (already required by `anthropic`): DNS resolve → all IPs must be global → connect to the validated IP with Host/SNI of the name (no rebinding window) → manual redirects re-validated | Library-free SSRF guards are not available in a maintained package; the rules are small and fully tested |
| HTML | BeautifulSoup (`html.parser`) | Tolerant of malformed HTML, boring |
| LLM | `anthropic` SDK behind `LLMProvider` protocol; `messages.parse` with Pydantic schemas; extraction on `claude-haiku-5-5`, audit on `claude-opus-5-5` (configurable) | Structured outputs, typed errors, usage reporting |
| No API key | Deterministic research still runs; run ends `partial` with "AI analysis unavailable"; no opportunities fabricated | Spec §11 |
| Test double | `FixtureLLMProvider` (rule-based, model id `fixture-rules-v1`), refused in production, used by CI/E2E | Deterministic CI |
| E2E websites | `RESEARCH_FETCH_BACKEND=fixtures` serves bundled `*.example` sites (RFC 2606 reserved TLD) through the same fetch pipeline; refused in production | Docker CI has no internet |
| CSV upload | JSON body with CSV text (client reads the file) — no multipart dependency; `dry_run` preview then import | Simplicity |
| Repositories layer | Not added: services own queries (Sprint 1 convention) | Avoid a pass-through layer |

## 2. Data model (migration `0002`)

- `workflow_runs` (platform): status values migrated; add `current_step`, `progress` (0–100), `heartbeat_at`,
  `next_attempt_at`, `max_attempts`, `cancel_requested_at`, `input_tokens`, `output_tokens`,
  `estimated_cost_usd`; drop `project_id`; unique `(id, organization_id)` for module composite FKs.
- `companies`: org-scoped; `canonical_domain` unique per org (partial, non-null); name-only rows unique by
  `lower(name)` among domain-less rows; profile columns (`industry`, `location`, `short_description`).
- `research_project_companies(project_id, company_id, organization_id, added_at)` — composite FKs, same org.
- `research_runs(workflow_run_id PK, organization_id, company_id, project_id, profile JSONB, ai_status,
  audit_summary, pages_fetched)` — composite FKs to workflow_runs/companies/projects in the same org.
- `research_sources(run, company, url, page_title, page_category, retrieved_at, http_status, content_hash,
  extraction_status, extracted_text ≤ RESEARCH_MAX_TEXT_CHARS)` — unique `(research_run_id, source_url)`.
- `evidence(run, company, source, observed_fact, supporting_excerpt, evidence_type, basis observed|inferred,
  confidence, origin deterministic|llm)` — excerpts are verified substrings of the stored source text.
- `opportunities(run, company, title, observed_context, problem_hypothesis, proposed_ai_solution,
  estimated_business_impact, implementation_complexity, confidence, assumptions[], validation_questions[],
  next_step, quality_flags[], status, reviewer_note, reviewed_by, reviewed_at)`.
- `opportunity_evidence(opportunity_id, evidence_id)` — same-org composite FKs.

Retention: source text is truncated to the configured size and kept only for evidence provenance; e-mail
addresses and phone numbers are redacted from stored text and excerpts.

## 3. API contract (all under `/api/v1`, `Tenant` required)

| Method | Path | Notes |
|---|---|---|
| GET | /lead-intelligence/summary | overview counts |
| GET/POST | /companies | list (paginated, `q`, `project_id`), create from website (dedup → 200 + `created:false`) |
| GET | /companies/{id} | profile + latest run |
| POST | /companies/import | `{csv_text, dry_run, project_id?}` → preview / import result |
| GET | /companies/{id}/evidence, /sources, /opportunities | latest run by default, `?run_id=` |
| GET/POST | /projects/{id}/companies | list / link companies |
| GET/POST | /research-runs | list (`company_id`, `project_id`) / start for `company_ids` or `project_id` (skips active duplicates) |
| GET | /research-runs/{id}, /research-runs/{id}/results | progress, steps, errors, usage, cost / profile+evidence+opps |
| POST | /research-runs/{id}/cancel | pending → cancelled; running → cancelled at next step boundary |
| GET | /opportunities | review queue (`status`) |
| PATCH | /opportunities/{id} | `{status?, reviewer_note?}` with allowed transitions |

## 4. Workflow

`VALIDATE_INPUT → FETCH_WEBSITE → DISCOVER_RELEVANT_PAGES → EXTRACT_INFORMATION → SAVE_EVIDENCE →
AI_OPPORTUNITY_AUDIT → PERSIST_RESULTS → COMPLETED`. Idempotency: every step first checks for its persisted
output for this run (sources unique per run+URL; evidence/opportunities replaced per run inside one
transaction), so a retried or resumed run never duplicates records.

## 5. Tasks, ownership, dependencies

| # | Task | Owner | Depends on |
|---|---|---|---|
| T1 | Plan, contracts, migration, platform workflow changes | Lead | — |
| T2 | Fixture websites (12) + sample CSV | Agent (fixtures dir only) | — |
| T3 | Companies, dedup, CSV import, projects link | Lead | T1 |
| T4 | Safe fetcher, robots, discovery, extraction | Lead | T1 |
| T5 | LLM provider, extractor + auditor agents, validation | Lead | T1 |
| T6 | Research workflow, retries, cancel, usage/cost | Lead | T3–T5 |
| T7 | Frontend pages | Agent (apps/web only) | T1 contract generated |
| T8 | Tests: security, integration, eval, E2E | Lead (+T7 agent for UI tests) | T2–T7 |
| T9 | Independent review | Reviewer agent (read-only) | T8 |

## 6. Acceptance tests

Unit: domain normalisation, dedup, CSV validation, URL/IP policy, extraction, evidence references, structured
output validation, opportunity transitions. Security: cross-tenant company/evidence/opportunity/run access,
SSRF via URL/redirect/DNS, private & reserved IPs, oversized responses, malformed HTML, prompt injection.
Integration: create → import → start run → worker lifecycle → persistence, transient retry, permanent failure,
cancel, stale recovery, duplicate-run prevention. Eval: 12 fixture companies (strong/weak/none/missing/
conflicting/injection/malformed/blocked) run through the full pipeline with the test double; scripted bad LLM
outputs to prove unsupported claims are dropped/flagged. E2E (Playwright, Docker): create company → research →
monitor → evidence → review opportunity; CSV bulk import + campaign.

## 7. Completion notes

**Delegation actually used**: lead (backend, workflow, AI, tests, integration); one Sonnet agent wrote the 12
fixture websites; one Sonnet agent built the frontend against the frozen OpenAPI contract (`apps/web` only);
an independent read-only reviewer audited the result. The lead verified every agent's output by running the checks.

**Deviations from this plan**: none in scope. Additions found necessary: a wall-clock fetch deadline and
claim-ownership checks (review H1), host-based link filtering (M1), excerpt-backed LLM wording (M2), lost-cancel
fix (M3), hard cost cap (M4), no compression / no keep-alive in the fetcher, robots 5xx retried, LIKE escaping.
One fixture expectation was corrected (`fjord-accounting.example` listed `document_download`, but the site has no
downloadable files; it describes uploads → `document_workflow`).

**Live check**: researching https://www.python.org/ from the host worker (internet mode, no LLM key) found four
bugs the fixtures did not (meta tags removed before being read, substring keyword matching, navigation text as
excerpts, metadata description listed as unknown); all fixed with regression tests.

**Not verified**: the real Anthropic provider has never been called (no API key in this environment) — its error
mapping, refusal handling, fallback parameters and cost estimation are tested against a fake SDK client only, and
opportunity quality has only been evaluated with the rule-based test double. Run `/research-eval` live (opt-in,
capped) before relying on AI output.
