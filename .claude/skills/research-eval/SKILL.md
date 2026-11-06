---
name: research-eval
description: Run the Lead Intelligence research evaluation over the fixture companies — schema validity, evidence citations, unsupported claims, prompt-injection containment and signal recall — and report actual results. Use after changing extraction, prompts, the auditor, validation rules or fixtures.
---

# /research-eval

Fixtures: `apps/api/src/aigentix/modules/lead_intelligence/fixtures/sites/<domain>/` (`site.json`, HTML pages,
`expected.json` with scenario, expected pages/signals, excluded pages, expected outcome and opportunity volume).
Suite: `apps/api/tests/test_li_eval.py`. Needs the test PostgreSQL (`TEST_DATABASE_URL`).

1. Deterministic run (free, always):
   `cd apps/api && RESEARCH_EVAL_REPORT=/tmp/research-eval.md uv run pytest -q -s tests/test_li_eval.py`
   Uses the real fetch/extract/validate pipeline with the `fixture-rules-v1` LLM test double.
2. Validation-layer checks: `uv run pytest -q tests/test_li_units.py -k "audit or extraction or excerpt"` and
   `uv run pytest -q tests/test_li_research.py -k "injection or compromised or invalid"`.
3. Live model run — **only if the user asks**, costs money:
   `RESEARCH_EVAL_LIVE=1 RESEARCH_EVAL_MAX_COST_USD=0.50 ANTHROPIC_API_KEY=… uv run pytest -q -s tests/test_li_eval.py -k live`
   To compare providers, run once per configuration, e.g. with `LLM_ROUTE_EXTRACTION=openai:<model>
   LLM_ROUTE_AUDIT=openai:<model> OPENAI_API_KEY=… LLM_PRICES_JSON=…`, and report both tables side by side.
   Stops starting new companies once the cap is spent. Report the exact cost from the report table.

## Report

Paste the report table, then summarise in ≤10 lines:
- cases passed / total, mean signal recall, total cost;
- every failed check with the fixture and the likely cause (fetching, discovery, extraction, audit, validation);
- unsupported or flagged claims (`quality_flags`), dropped assertions, any foreign link or injection payload;
- qualitative notes on live opportunities (are they plausible, hypothesis-phrased, evidence-backed?).
Never edit `expected.json` to make a case pass unless the fixture expectation is demonstrably wrong; say so.
