# Sprint 3 — Growth Intelligence, Buying Intent & Lead Scoring

Goal: turn researched companies into a **prioritised, explainable lead list**. AIgentiX detects dated growth
triggers and verified buying intent, matches companies against configurable ICP profiles, and computes a
deterministic, evidence-linked score with honest handling of missing data. Nothing is sent to prospects.

## Scope

| Area | Delivered |
|---|---|
| Growth triggers | 12 signal types (hiring, expansion, funding, product_launch, leadership_change, technology_adoption, digital_transformation, operational_change, public_project_request, procurement_tender, inbound_inquiry, other) detected on news / press / careers / tender / project-request pages |
| Dates | `<time datetime>`, page metadata (`article:published_time`, JSON-LD `datePublished`) and DE/EN text dates; precision day/month/year; unknown stays unknown; retrieval date never used; future dates become deadlines; contradicting dates → `date_conflict`, no date chosen |
| Freshness | recent ≤30 d · moderate ≤90 d · older ≤180 d · historical · unknown (configurable per scoring profile) |
| Buying intent | EXPLICIT / STRONG / INDIRECT stored with a real source (website, configured tender source, first-party inquiry, licensed provider interface); NONE_VERIFIED / UNKNOWN computed |
| ICP profiles | several per organization, versioned; default = Germany, B2B + B2C, 1–249 employees, excluded industries, AI solution categories |
| Scoring | deterministic `scoring-v1`, default weights opportunity 35 · fit 25 · triggers 20 · intent 20 (validated to sum to 100), per-criterion states, conservative + upper bound, coverage, provisional label, evidence IDs per criterion, append-only history |
| Prioritisation | ranked list with filters and deterministic sort, review statuses, recommended next step, CSV export (formula-safe) |
| Workflow | `lead_intelligence.company_enrichment` on the existing PostgreSQL worker; re-score without crawling or AI |

Out of scope: outreach, contacting prospects, scraping protected platforms or personal profiles, identifying
individuals, buying intent data, live tender integrations (only an interface + offline fixture adapter).

## Data model (migration `0003`)

All tables carry `organization_id`; links use composite FKs `(id, organization_id)`.

| Table | Purpose |
|---|---|
| `research_runs.kind` | `research` (Sprint 2) or `enrichment` (Sprint 3); enrichment reuses sources/evidence tables |
| `evidence.evidence_type` | + `company_size`, `business_signal`, `buying_intent` |
| `business_signals` (+ `business_signal_evidence`) | deduplicated trigger per company (`dedupe_key` unique per org+company), event date + precision, `date_conflict`, date candidates, deadline, mention count, sources |
| `buying_intent_signals` (+ `buying_intent_evidence`) | strength, source type, solution category, observed / deadline dates, external reference; website and tender intents are re-derived on each enrichment, first-party records are kept |
| `icp_profiles`, `scoring_profiles` | name, version, `is_default` (one per org), validated JSON `config` |
| `lead_scores` (+ `lead_score_evidence`) | append-only snapshot: bounds, coverage, provisional, components JSON, explanation, next step, inputs hash, profile versions + config snapshot |
| `lead_reviews` | append-only review history; newest row = current status |

## Enrichment workflow

`validate_input → collect_sources → extract_signals → review_signals → verify_evidence → research_intent →
score_lead`, built on the research workflow class (same SafeFetcher, robots, rate limits, checkpoints, retries,
cancellation, cost tracking).

* **collect_sources** — homepage + up to `RESEARCH_ENRICHMENT_MAX_PAGES - 1` signal pages (round robin:
  requests, news, careers, about). Each page is split into segments (`<article>`, job postings) at fetch time.
* **extract_signals** — keyword classification (DE + EN, headline weighted), segment dates, injection-like segments
  quarantined; jobs aggregate into one `hiring` signal; repeated announcements cluster into one signal.
* **review_signals** (optional, task route `signals`) — the model may only keep/reject and re-type among
  descriptive types; it can never add a signal, change a date or create/remove a request/tender.
* **verify_evidence** — an evidence row per mention whose excerpt is verbatim in the stored page; signals without
  verifiable evidence are dropped. Firmographics (country, industry statement, employee count, conflicts) from
  enrichment + latest research pages.
* **research_intent** — website requests/tenders in a target solution category (expired/irrelevant ones are
  listed as ignored), tender source records, licensed providers (none configured).
* **score_lead** — default profiles, deterministic score snapshot.

Re-enrichment within `RESEARCH_ENRICHMENT_CACHE_HOURS` (24 h) only re-scores unless `force=true`.

## Scoring rules (`domain/scoring.py`)

Each component is built from criteria with `max_points`; a criterion is `assessed`, `unknown` (source not
collected), `insufficient_evidence` (collected but nothing / contradictory) or `not_applicable`.
`score_low` counts unassessed criteria as 0, `score_high` as full; `coverage` = assessed share of the weight;
`provisional` when coverage < `min_coverage` (0.75). Weights are never renormalised.

| Component | Criteria |
|---|---|
| Opportunity (35) | strongest supported audit opportunity (70: confidence × validation flag × target category) + breadth (30); unknown without a completed AI audit |
| Fit (25) | country (30) · industry incl. exclusions (30) · size range (20) · relevant solution category (20); excluded country/industry → `priority_band=excluded` |
| Triggers (20) | per signal: type value × freshness factor × confidence; combined with diminishing returns 1 + 0.25 + 0.10 (top three) |
| Intent (20) | strongest active intent: explicit 100 · strong 80 · indirect 40 × freshness × reliability; none → 0 with "none verified" |

Priority band from `score_low` (high ≥ 60, medium ≥ 35). Next step: reject (outside ICP) · review active request
· complete research · qualify for review · monitor · deprioritise.

## API (all tenant-scoped; profile changes owner-only)

| Method | Path | |
|---|---|---|
| GET/POST, PATCH | `/api/v1/scoring-profiles`, `/{id}` | list (creates default), create, update (version bump) |
| GET/POST, PATCH | `/api/v1/icp-profiles`, `/{id}` | same |
| POST | `/api/v1/companies/{id}/enrich` | start enrichment (`force`), or re-score when recent |
| POST | `/api/v1/enrichment-runs` | bulk: `company_ids` or `project_id` |
| GET | `/api/v1/companies/{id}/signals` | signals, intents, intent status, sources checked, ignored records |
| POST | `/api/v1/companies/{id}/intent-signals` | record a first-party inquiry |
| GET | `/api/v1/companies/{id}/scores` | score history |
| POST | `/api/v1/companies/{id}/score`, `/api/v1/projects/{id}/score` | re-score from stored data |
| GET | `/api/v1/leads/ranked`, `/api/v1/projects/{id}/leads` | filters: project, review_status, priority_band, intent_status, signal_type, min_score, provisional, include_excluded, triggered_since, q; sort: score, score_high, coverage, latest_trigger, intent, name, scored_at |
| GET | `/api/v1/leads/export` | CSV of the filtered list |
| GET | `/api/v1/leads/{company_id}` | latest score + review history |
| PATCH | `/api/v1/leads/{company_id}/review` | append review status + note |

## Frontend

Lead Intelligence tabs: **Ranked leads** (`/leads`), lead detail (`/leads/[id]`: breakdown, coverage, explanation,
trigger timeline, intent evidence, score history, review), **Scoring** (`/scoring`: scoring + ICP profiles,
owner-editable), research control on company / project pages (enrich, re-score), overview cards.

## Configuration

`RESEARCH_ENRICHMENT_MAX_PAGES` (10), `RESEARCH_ENRICHMENT_CACHE_HOURS` (24), `RESEARCH_TENDER_SOURCE`
(`none` | `fixtures`, fixtures refused in production), `SCORING_REFERENCE_DATE` (tests/demos only, refused in
production), `LLM_ROUTE_SIGNALS` (defaults to the extraction route), `RESEARCH_SIGNAL_AI_REVIEW` (true).

## Quality gates

* Unit (`test_ls_units.py`): dates, freshness boundaries, detection, dedupe, injection quarantine, intent rules,
  missing-data bounds, diminishing returns, exclusions, weight validation, AI-review guardrails, CSV escaping.
* API/security (`test_ls_api.py`): auth required, cross-tenant 404, spoofed header 403, owner-only profiles,
  versioning, re-score without crawl, idempotent re-enrichment, cache reuse, first-party intent, review history,
  filters, deterministic ranking, formula-safe export.
* Evaluation (`test_lead_scoring_eval.py`, `/lead-scoring-eval`): 16 fixture scenarios, 278 checks + ranking sanity.
* E2E (`e2e/sprint3.spec.ts`): enrich → ranked list → detail → review → profile change → re-score → export.

## Ownership

| Part | Owner |
|---|---|
| Migration, domain, workflow, services, routes, tests | lead engineer (main session) |
| Enrichment fixtures (`fixtures/enrichment/`) | fixtures agent (reviewed and calibrated by lead) |
| Frontend views + unit tests | frontend agent (after the contract was generated) |
| Independent review | reviewer agent |

## Pilot

No live dataset is available in this environment, so the pilot is the deterministic fixture pilot ([SPRINT_3_PILOT.md](SPRINT_3_PILOT.md))
(`/lead-scoring-eval`). Live validation with real companies, real tender feeds and real reviewer feedback is
**not done**; no accuracy or conversion figures are claimed.
