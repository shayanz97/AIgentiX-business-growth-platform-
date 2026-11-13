# Sprint 3 pilot report — deterministic fixture pilot

**Status: live validation not done.** No live company dataset, tender feed, intent provider or AI API key was
available in the build environment, so the pilot ran on the 16 bundled fixture companies (`fixtures/enrichment/`)
with the offline tender fixture and the rule-based `fixture-rules-v1` test double. These results test the pipeline
against scenarios we wrote ourselves. They are **not** accuracy, precision, recall or conversion figures for real
leads, and none are claimed.

How to reproduce: `/lead-scoring-eval` (or `cd apps/api && LEAD_SCORING_EVAL_REPORT=report.md uv run pytest -q
tests/test_lead_scoring_eval.py`). It was also run end to end in Docker through the UI (`e2e/sprint3.spec.ts`).


| Company | Scenario | Run | Signals | Intent | Score (coverage) | Checks | Notes |
|---|---|---|---|---|---|---|---|
| alte-meldung.example | old_announcement | completed | expansion x1, product_launch x1 | none_verified | 17-22 (95%) | PASS |  |
| digitalwerk-solutions.example | strong_opportunity | completed | digital_transformation x1, technology_adoption x1 | indirect | 71-71 (100%) | PASS |  |
| doppelte-meldung.example | duplicate_announcements | completed | funding x1 | none_verified | 31-36 (95%) | PASS |  |
| groesse-unbekannt.example | missing_size | completed | none | none_verified | 15-20 (95%) | PASS |  |
| injektion-news.example | prompt_injection | completed | product_launch x1 | none_verified | 25-30 (95%) | PASS |  |
| kleinbetrieb-minimal.example | weak_opportunity | completed | none | none_verified | 15-20 (95%) | PASS |  |
| kundenservice-anfrage.example | explicit_request | completed | hiring x1, public_project_request x1 | explicit | 65-65 (100%) | PASS |  |
| nordwerk-hiring.example | relevant_hiring | completed | hiring x1 | none_verified | 38-38 (100%) | PASS |  |
| ohne-datum.example | missing_dates | completed | hiring x1, other x1, product_launch x1 | none_verified | 20-26 (95%) | PASS |  |
| rhein-logistik-expansion.example | recent_expansion | completed | expansion x1, operational_change x1 | none_verified | 35-40 (95%) | PASS |  |
| stadtwerke-vergabe.example | public_tender | completed | procurement_tender x1 | strong | 53-53 (100%) | PASS |  |
| tabak-usa.example | low_icp_fit | completed | expansion x1 | none_verified | 18-23 (95%) | PASS |  |
| ungueltige-firma.example | invalid_company | pending | none | unknown | 0-100 (0%) | PASS |  |
| vielfalt-gmbh.example | multiple_opportunities | completed | hiring x1, leadership_change x1, product_launch x1 | explicit | 87-87 (100%) | PASS |  |
| wachstum-ohne-intent.example | no_verified_intent | completed | expansion x1, funding x1 | none_verified | 35-40 (95%) | PASS |  |
| widerspruch-daten.example | contradictory_sources | completed | expansion x1, hiring x1 | none_verified | 20-25 (95%) | PASS |  |

Scenarios passed: 16/16 · checks passed 278/278 · total cost $0.0000

Fixture results only: they do not measure real-world accuracy, precision or conversion.

## Observations

- **Detection:** trigger types, counts, event dates, the date conflict (widerspruch-daten), duplicate collapse
  (doppelte-meldung: 3 mentions → 1 signal) and missing dates (ohne-datum → freshness unknown) all match.
- **Prompt injection:** the injected article in injektion-news was quarantined; no intent, tender or funding
  signal came from it, and the payload URL appears nowhere in the outputs.
- **Intent:**
  - explicit from a website project request (kundenservice-anfrage) and from a first-party inquiry (vielfalt-gmbh);
  - strong from a public tender, merged across the website and the tender source (stadtwerke-vergabe);
  - indirect from a digitalisation programme (digitalwerk-solutions);
  - the expired tender (rhein-logistik) and the irrelevant road-works tender (nordwerk) were ignored, with reasons.
- **Missing data:** most fixtures publish no employee count, so the size criterion is `insufficient_evidence`.
  Coverage is 95% and the conservative score is 5 points below the upper bound. The failed site
  (ungueltige-firma, HTTP 500, retry scheduled) scores 0–100 at 0% coverage, provisional, with next step
  "complete research".
- **Opportunity component:** it is 0 for most fixtures because the Sprint 2 audit (test double) only proposes
  opportunities for sites with forms, booking or downloads. A real model will propose more; that has not been
  measured.
- **Ranking:** the leads with verified explicit intent and the strong opportunity rank top 3; the excluded tobacco
  wholesaler (USA), the minimal site and the failed site rank in the bottom half.

## Calibration notes

The fixture author's guessed fit and score bands were inconsistent with each other. Nine `expected.json` values
were set to the documented rule instead:
- fit band = conservative fit score;
- priority = default thresholds 60 / 35.

Each change is recorded in that fixture's `calibration_notes`. Weights and thresholds are defaults that have not
been validated against real outcomes.

## Before relying on scores

1. Run enrichment on a real list of 30–50 known companies, with a reviewer labelling triggers and intent.
2. Run `/lead-scoring-eval` live (`LEAD_SCORING_EVAL_LIVE=1`, capped cost) to measure the AI trigger review.
3. Compare the ranking with sales judgement before changing the weights. Track review outcomes over time; the
   review history is stored for exactly this.
