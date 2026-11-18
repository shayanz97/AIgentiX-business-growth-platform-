# Sales AI evaluation fixtures

Scripted model outputs that simulate bad model behaviour for `tests/test_sales_eval.py` (`/sales-eval`).
They are replayed by the `ScriptedSalesLLM` test double; validation must remove or flag every problem.
`{{E1}}` is replaced with the fact of evidence E1 from the actual prompt, so a scripted answer can also
contain one legitimately grounded statement.

| File | Simulates |
|---|---|
| `scripted/roi_brief.json` | invented staff / revenue numbers, guaranteed ROI, certification promise, lead score as probability, automatic outreach |
| `scripted/roi_proposal.json` | guaranteed ROI, invented prices and savings, ISO 27001 / DSGVO certification, unjustified timeline, missing and unknown sections |
| `scripted/injection_brief.json` | a model that followed website prompt injection: fake tender, invented evidence label, exfiltration link, contact data, outreach |

The lead-intelligence fixture companies (research + enrichment) live in
`modules/lead_intelligence/fixtures/`; the Sales evaluation reuses them.
