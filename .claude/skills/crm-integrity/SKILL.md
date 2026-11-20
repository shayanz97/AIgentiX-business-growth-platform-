---
name: crm-integrity
description: Validate Sales pipeline data integrity - deal stage transitions, duplicate conversion, tenant boundaries, task/CRM-mapping consistency. Use after changing pipeline, conversion, tasks, export or CRM code, or when pipeline data looks wrong.
---

# /crm-integrity

Checks that the Sales data model and code still uphold the pipeline rules (docs/SPRINT_4_PLAN.md) and the security
invariants in `CLAUDE.md`. Report actual results; never claim a check passed without running it.

## 1. Code and test checks

Run from `apps/api` (PostgreSQL at `TEST_DATABASE_URL`):

- `uv run pytest -q tests/test_sales_pipeline.py tests/test_sales_tasks.py tests/test_sales_crm.py` - stage rules,
  idempotent / duplicate-safe conversion, tasks, export, CRM mappings, cross-tenant 404 / spoofed-header 403.
- `uv run pytest -q tests/test_models_match_migrations.py` - models and migration 0004 must not drift.
- `grep -rn "modules.lead_intelligence" src/aigentix/modules/sales` - must print nothing (module boundary).
- `grep -rnE "httpx|requests|smtplib|sendgrid|twilio" src/aigentix/modules/sales` - must print nothing (no sending,
  no direct outbound HTTP; a real CRM adapter would need review and `SafeFetcher` rules).
- `grep -n "crm_providers\|mock" src/aigentix/modules/sales/config.py` - `mock` still refused in production.

## 2. SQL checks on a live database (each must return 0 rows)

Run with `psql "$DATABASE_URL"`; replace nothing, they scan all tenants.

```sql
-- Stage / status / closed_at consistency (also enforced by CHECK status_stage_consistent)
SELECT id FROM sales_opportunities
WHERE (status = 'open') <> (closed_at IS NULL)
   OR (status = 'open' AND stage IN ('won','lost'))
   OR (status <> 'open' AND status <> stage);

-- Duplicate open deals for the same company + source opportunity (conversion must be idempotent/duplicate-safe;
-- rows are legitimate only when created with allow_additional=true - review each)
SELECT organization_id, company_id, source_opportunity_id, count(*)
FROM sales_opportunities WHERE status = 'open'
GROUP BY 1,2,3 HAVING count(*) > 1;

-- Same conversion key used twice in an org (unique index should make this impossible)
SELECT organization_id, conversion_key, count(*) FROM sales_opportunities
WHERE conversion_key IS NOT NULL GROUP BY 1,2 HAVING count(*) > 1;

-- Current stage must equal the latest stage-history row
SELECT o.id FROM sales_opportunities o
JOIN LATERAL (SELECT new_stage FROM sales_stage_history h WHERE h.sales_opportunity_id = o.id
              ORDER BY changed_at DESC, id DESC LIMIT 1) last ON true
WHERE last.new_stage <> o.stage;

-- Deals without any history row
SELECT o.id FROM sales_opportunities o
WHERE NOT EXISTS (SELECT 1 FROM sales_stage_history h WHERE h.sales_opportunity_id = o.id);

-- Evidence gates: in_conversation needs a recorded contact activity; proposal_sent needs a sent proposal
SELECT o.id FROM sales_opportunities o
WHERE o.stage = 'in_conversation' AND NOT EXISTS (
  SELECT 1 FROM sales_activities a WHERE a.sales_opportunity_id = o.id
    AND a.activity_type IN ('call','meeting','email_sent','email_received','letter_sent'));
SELECT o.id FROM sales_opportunities o
WHERE o.stage = 'proposal_sent' AND NOT EXISTS (
  SELECT 1 FROM sales_proposals p WHERE p.sales_opportunity_id = o.id AND p.status IN ('sent','accepted','declined'));

-- Tenant boundaries: children must share the organization of their deal (composite FKs enforce it; verify anyway)
SELECT t.id FROM sales_tasks t JOIN sales_opportunities o ON o.id = t.sales_opportunity_id
WHERE t.organization_id <> o.organization_id;
SELECT a.id FROM sales_activities a JOIN sales_opportunities o ON o.id = a.sales_opportunity_id
WHERE a.organization_id <> o.organization_id;
SELECT o.id FROM sales_opportunities o JOIN companies c ON c.id = o.company_id
WHERE c.organization_id <> o.organization_id;

-- Task assignees must be members of the task's organization
SELECT t.id FROM sales_tasks t
WHERE t.assigned_user_id IS NOT NULL AND NOT EXISTS (
  SELECT 1 FROM organization_memberships m
  WHERE m.organization_id = t.organization_id AND m.user_id = t.assigned_user_id);

-- Task status / completed_at consistency
SELECT id FROM sales_tasks WHERE (status = 'completed') <> (completed_at IS NOT NULL);

-- CRM mappings: synced rows have an external id; failed rows are never counted as synced; mapped entities exist
SELECT id FROM sales_crm_mappings WHERE sync_status = 'synced' AND external_entity_id IS NULL;
SELECT id FROM sales_crm_mappings WHERE sync_status = 'failed' AND last_error IS NULL;
SELECT m.id FROM sales_crm_mappings m WHERE m.local_entity_type = 'deal'
  AND NOT EXISTS (SELECT 1 FROM sales_opportunities o WHERE o.id = m.local_entity_id AND o.organization_id = m.organization_id);
SELECT organization_id, provider, local_entity_type, external_entity_id, count(*) FROM sales_crm_mappings
WHERE external_entity_id IS NOT NULL GROUP BY 1,2,3,4 HAVING count(*) > 1;

-- Contacts exported to a CRM must not be suppressed / restricted
SELECT m.id FROM sales_crm_mappings m JOIN sales_contacts c ON c.id = m.local_entity_id
WHERE m.local_entity_type = 'contact' AND m.sync_status = 'synced' AND c.restriction_status <> 'unverified';

-- Every CRM export left an audit trail on the deal
SELECT m.id FROM sales_crm_mappings m WHERE m.local_entity_type = 'deal' AND m.sync_status = 'synced'
  AND NOT EXISTS (SELECT 1 FROM sales_activities a WHERE a.sales_opportunity_id = m.local_entity_id
                  AND a.activity_type = 'system' AND a.description LIKE 'Exported to CRM%');

-- Money fields are never negative and currency is ISO (CHECK constraints) and no AI-invented values:
-- spot-check deals with a value but no created_by / owner
SELECT id FROM sales_opportunities WHERE estimated_value IS NOT NULL AND created_by_user_id IS NULL AND owner_user_id IS NULL;
```

## 3. Report

List each check with its real result (rows returned / pass / fail / blocked and why). For every failing row group,
name the invariant or rule it breaks and the code path to inspect (`services/pipeline.py`, `services/conversion.py`,
`services/tasks.py`, `services/crm.py`). Do not auto-fix data; propose a fix and ask first.
