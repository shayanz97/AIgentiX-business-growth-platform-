---
name: lead-scoring-eval
description: Run the Sprint 3 lead-scoring evaluation over the 16 enrichment fixture scenarios — trigger types, counts, event dates, date conflicts, freshness, buying intent, ICP fit, score bands, ranking order, prompt-injection containment and evidence integrity — and report actual results. Use after changing signal detection, date parsing, intent rules, scoring, profiles or enrichment fixtures.
---

# /lead-scoring-eval

Fixtures: `apps/api/src/aigentix/modules/lead_intelligence/fixtures/enrichment/` — 16 `.example` sites
(`sites/<domain>/site.json`, HTML, `expected.json`), `tenders.json` (offline tender source), `first_party.json`
(recorded through the API like a user would). Reference date: **2026-11-12** (`SCORING_REFERENCE_DATE`).
Suite: `apps/api/tests/test_lead_scoring_eval.py`. Needs the test PostgreSQL (`TEST_DATABASE_URL`).

1. Deterministic run (free, always):
   `cd apps/api && LEAD_SCORING_EVAL_REPORT=/tmp/lead-scoring-eval.md uv run pytest -q -s tests/test_lead_scoring_eval.py`
   Real fetch → segment → classify → dedupe → evidence → intent → score pipeline with the `fixture-rules-v1`
   test double (the AI trigger review keeps every candidate).
2. Rule-level checks: `uv run pytest -q tests/test_ls_units.py` (dates, freshness boundaries, dedupe, injection
   quarantine, intent rules, missing-data bounds, diminishing returns, AI-review guardrails).
3. Live model run — **only if the user asks**, costs money:
   `LEAD_SCORING_EVAL_LIVE=1 LEAD_SCORING_EVAL_MAX_COST_USD=0.50 ANTHROPIC_API_KEY=… uv run pytest -q -s tests/test_lead_scoring_eval.py -k live`
   (routes from `LLM_ROUTE_*`; stops starting new scenarios once the cap is spent). Live mode asserts only the
   hard safety checks (outcome, no forbidden signals, evidence integrity, no injection payload).

## Report

Paste the report table, then summarise in ≤10 lines:
- scenarios passed / 16, checks passed, total cost;
- every failed check with the scenario and the likely cause (discovery, segmentation, classification, dates,
  dedupe, intent rule, firmographics, scoring weights/thresholds);
- whether any signal or intent came from quarantined (injection) content — this must never happen;
- for live runs: which candidates the model rejected or re-typed, and whether that was right.

Rules: these are fixture results — never present them as real-world accuracy, precision or conversion. Never edit
`expected.json` to make a case pass unless the expectation is demonstrably wrong; record the reason in the
fixture's `calibration_notes` and say so in the report.
