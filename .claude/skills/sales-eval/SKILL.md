---
name: sales-eval
description: Run the Sprint 4 Sales AI evaluation over 15 scenarios — evidence grounding of sales briefs, uncertainty marking (missing, conflicting, stale data, no verified intent), proposal sections and price placeholders, removal of unsupported ROI / guarantee / certification claims and injected content, contact-data exclusion, closed-deal and cross-tenant rules — and report actual results. Use after changing the sales agents, prompts, validation, fixture LLM, brief/proposal workflows or their fixtures.
---

# /sales-eval

Suite: `apps/api/tests/test_sales_eval.py` (scenarios) and `apps/api/tests/test_sales_ai.py` (validation units,
versioning, human edits, status rules, tenant isolation). Companies come from the Lead Intelligence fixtures
(`modules/lead_intelligence/fixtures/{sites,enrichment/sites}`, reference date 2026-11-12); scripted bad model
outputs live in `apps/api/src/aigentix/modules/sales/fixtures/scripted/` (see its README). Needs the test
PostgreSQL (`TEST_DATABASE_URL`).

1. Deterministic run (free, always):
   `cd apps/api && SALES_EVAL_REPORT=/tmp/sales-eval.md uv run pytest -q -s tests/test_sales_eval.py`
   Real research → enrichment → conversion → worker → validation, with the `fixture-sales-v1` test double
   (rule-based, quotes only labelled evidence) plus scripted misbehaving outputs for scenarios 9 and 10.
2. Rule-level checks: `uv run pytest -q tests/test_sales_ai.py` (safety helpers, brief/proposal validation,
   commercial terms, no provider / cost cap / invalid output → `failed`, retries, edits preserved, revisions,
   proposal status rules, 401/404/403 on every new endpoint).
3. Live model run — **only if the user asks**, costs money:
   `SALES_EVAL_LIVE=1 SALES_EVAL_MAX_COST_USD=0.50 ANTHROPIC_API_KEY=… uv run pytest -q -s tests/test_sales_eval.py -k live`
   (routes from `SALES_LLM_ROUTE_BRIEF` / `SALES_LLM_ROUTE_PROPOSAL`, else `LLM_PROVIDER:LLM_AUDIT_MODEL`; stops
   starting scenarios once the cap is spent). Live mode asserts only the hard checks: status, grounding,
   no injected payload, no contact data, no invented price, not sent, isolation.

## Report

Paste the report table, then summarise in ≤10 lines:
- scenarios passed / 15, checks passed, total cost;
- every failed check with the scenario and likely cause (input selection, prompt, validation rule, fixture LLM,
  workflow/status handling);
- whether any number, price, guarantee, certification, link or contact detail reached a brief or proposal
  without support — this must never happen;
- for live runs: which statements validation removed or downgraded (quality flags), and whether that was right.

Rules: fixture results are not real-world accuracy or conversion. A brief or proposal without a provider must be
`failed` with a message, never fabricated. Never weaken a validation rule or edit a scripted fixture to make a
case pass; explain the change in the report if an expectation was demonstrably wrong.
