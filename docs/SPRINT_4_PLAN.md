# Sprint 4 — Sales Intelligence, CRM & Proposal Automation

Goal: turn qualified leads into managed commercial opportunities — an internal CRM pipeline, evidence-backed
sales briefs, editable proposal drafts and follow-up tasks — with every external action human-controlled.
AIgentiX sends nothing: no e-mail, LinkedIn, SMS or calls.

## Module boundary

`modules/sales/` is a new module. It never imports `modules/lead_intelligence`. Lead data is read through a
**platform contract**:

```
platform/leads.py      LeadDataProvider (Protocol) + frozen DTOs (LeadSnapshot, EvidenceItem, …)
                       get_lead_data_provider() → looked up from ModuleDescriptor.provides["lead_data"]
lead_intelligence/services/lead_data.py   the implementation (read-only, tenant-scoped)
```

| Lead Intelligence owns | Sales owns |
|---|---|
| companies, research evidence, opportunities (hypotheses), signals, intent, lead scores, lead reviews | deals, stage history, activities, contacts + compliance, tasks, briefs, proposals, CRM mappings, service catalogue |

Sales tables reference `companies`, `lead_scores` and `opportunities` by composite FK `(id, organization_id)`
(DB-level tenant safety); Sales never writes Lead Intelligence tables and never copies research history — it
stores ids and reads current data through the provider.

## Data model (migration `0004`)

| Table | Notes |
|---|---|
| `sales_opportunities` | company, source research opportunity, source lead score, title, owner, stage, status (open/won/lost), priority, estimated value + currency (nullable, never estimated by AI), expected close, confirmed requirements, lost reason, won value, `version` (optimistic lock), `conversion_key` (unique per org → idempotent conversion), closed_at |
| `sales_stage_history` | append-only (previous/new stage, changed_by, reason, changed_at) |
| `sales_activities` | manual records (note, call, meeting, email sent/received manually, proposal sent, other) + system audit events (`system`), occurred_at ≤ now |
| `sales_contacts` | minimal business contact data; source, lawful basis + reference, restriction status |
| `sales_contact_reviews` | append-only per-channel eligibility decisions (who, when, basis, note) |
| `sales_suppressions` | opt-outs by channel, stored as SHA-256 of the normalised address/number |
| `sales_tasks` | follow-ups: assignee (org member), due_at, status open/completed/cancelled, `suggested_by` |
| `sales_briefs` | AI content (JSON) + **separate** human `edited_content`, evidence ids, model / prompt version, status generating/draft/approved/failed/superseded, workflow run |
| `sales_proposals` + `sales_proposal_revisions` | proposal header (status draft/ready/sent/accepted/declined, current revision) and immutable revisions (`origin` ai/human, sections JSON, assumptions, flags) |
| `sales_service_offerings` | the organization's AIgentiX services; prices only when explicitly approved |
| `sales_crm_mappings` | provider, local entity type/id ↔ external id, sync status; unique on both directions |

## Pipeline rules (`domain/pipeline.py`, deterministic)

Stages: `qualified → researching → contact_planned → in_conversation → proposal_sent → won | lost`.

| From | Allowed to |
|---|---|
| qualified | researching, contact_planned |
| researching | qualified, contact_planned |
| contact_planned | researching, in_conversation |
| in_conversation | contact_planned, proposal_sent |
| proposal_sent | in_conversation |
| any open | won / lost only via the explicit **close** action |
| won / lost | reopen only via the explicit **reopen** action (reason required) |

Evidence gates — stages reflect recorded real-world events:
* `in_conversation` needs a recorded contact activity (call, meeting, e-mail received/sent manually);
* `proposal_sent` needs a proposal the user marked as sent (marking it records a `proposal_sent` activity);
* AI output never changes a stage; generating a draft is not sending it; a task is not contact.

## Lead conversion (`POST /api/v1/leads/{company_id}/convert`)

1. tenant + membership (any member); 2. company belongs to the org; 3. eligible: latest lead review is
`qualified_for_review` or `reviewed` (never `rejected`) and a lead score exists; optional source research
opportunity must belong to the company and not be rejected; 4. `idempotency_key` (client UUID) — a retry returns
the same deal (`200`); 5. an open deal for the same company + source opportunity → `409` with its id unless
`allow_additional=true`; 6. create deal (stage `qualified`), link score snapshot + research opportunity, stage
history row and a `system` activity. Historical scores are never modified.

## AI sales intelligence (worker workflows, `LLMProvider` routes)

* `sales.brief_generation`: lead snapshot → evidence blocks `E1…En` (neutralised, untrusted) → structured brief
  (10 sections) → validation: every factual item cites existing evidence labels; numbers / money / staff counts
  not present in the cited evidence are removed and flagged; foreign links stripped; lead score never shown as a
  probability. Prompt `sales-brief-v1`, model recorded, cost cap per run. Regeneration creates a new brief;
  human edits live in `edited_content` and are never overwritten.
* `sales.proposal_generation`: brief + evidence + confirmed requirements + approved service offerings →
  13-section draft. Validation: prices only from approved offerings (else a placeholder), guaranteed ROI /
  certification promises removed and flagged, inferred pains marked as hypotheses, unknown requirements marked.
  Always `draft`; never sent. Markdown export.
* No provider configured → the run ends `partial`/unavailable with a message; nothing is fabricated.

## Follow-ups, contacts & compliance

* Tasks: CRUD, reschedule, complete, views `overdue`, `today`, `upcoming` (7 days), `completed`, `mine`.
  Deterministic per-stage suggestions (never auto-created). In-app only.
* Contacts are entered manually (no scraping of individuals). Channel eligibility is a recorded human review
  with a legal basis; `domain/compliance.py::contact_permission()` is the single gate (suppression always wins;
  German B2B defaults: e-mail advertising needs prior consent or the §7(3) UWG existing-customer exception, phone
  needs at least presumed consent, a public business address alone permits nothing). Recording an outbound
  activity to a suppressed contact is refused.

## CRM integration

`integrations/crm.py`: `CRMProvider` protocol (health, upsert company / contact / deal, idempotent by external id)
+ `ExternalCRMMapping`. **No provider is configured** (HubSpot / Pipedrive adapters are future work; the contract
is documented). Export to a provider requires an owner and `confirm=true`; without a configured provider the API
says so — no fake sync. CSV export of deals works without any account.

## Metrics (`GET /api/v1/sales/metrics`, deterministic)

| Metric | Definition |
|---|---|
| qualified_leads | companies whose latest lead review is qualified_for_review / reviewed, or that were converted |
| converted_leads | distinct companies with ≥ 1 sales opportunity |
| lead_to_opportunity_rate | converted_leads / qualified_leads (null when 0) |
| opportunities_by_stage | count per stage |
| pipeline_value | sum of `estimated_value` of open deals **with a value**, per currency; count without value reported |
| won_count / lost_count, won_value | closed deals; won value = recorded `won_value` (or estimated value if the user confirmed it at close) per currency |
| opportunity_to_won_rate | won / all opportunities; win_rate = won / (won + lost) |
| overdue_tasks | open tasks with due_at < now |

## API (all under `/api/v1`, tenant-scoped)

`POST /leads/{company_id}/convert` · `GET/POST /sales/opportunities` · `GET/PATCH /sales/opportunities/{id}` ·
`POST /sales/opportunities/{id}/stage|close|reopen` · `GET /sales/opportunities/{id}/history` ·
`GET/POST /sales/opportunities/{id}/activities` · `GET/POST /sales/opportunities/{id}/briefs` ·
`PATCH /sales/briefs/{id}` · `GET/POST /sales/opportunities/{id}/proposals` · `GET/PATCH /sales/proposals/{id}` ·
`GET /sales/proposals/{id}/revisions` · `GET /sales/proposals/{id}/export` (Markdown) ·
`GET/POST /sales/tasks` · `PATCH /sales/tasks/{id}` · `GET /sales/opportunities/{id}/task-suggestions` ·
`GET/POST /sales/contacts`, `PATCH /sales/contacts/{id}`, `POST /sales/contacts/{id}/reviews`,
`POST /sales/suppressions` · `GET/POST/PATCH /sales/services` · `GET /sales/metrics` · `GET /sales/export` (CSV) ·
`GET /sales/crm/providers`, `POST /sales/crm/{provider}/export`.

## Ownership (multi-agent)

| Part | Owner |
|---|---|
| platform contract, models, migration 0004, pipeline, conversion, contacts/compliance, metrics, opportunity routes | lead architect |
| `agents/`, brief/proposal services + workflows + routes, fixtures, `/sales-eval`, `/proposal-review` | AI agent (B) |
| tasks + suggestions, CSV/Markdown export, CRM interface + mappings, `/crm-integrity` | integration agent (D) |
| `apps/web` sales pages | frontend agent (C), after `make contracts` |
| independent review | reviewer (E) |

Migrations are written only by the lead (one migration, before agents start).
