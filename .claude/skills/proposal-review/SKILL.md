---
name: proposal-review
description: Review an AI-drafted sales proposal (or the proposal pipeline after a change) before a person sends it — section completeness, prices only from approved service offerings, no guarantees / ROI promises / certification claims, hypotheses marked as such, unknown requirements and timelines marked, no contact data, revision history and human-only status changes. Use when asked to check a proposal draft, its export, or changes to proposal generation.
---

# /proposal-review

Code: `apps/api/src/aigentix/modules/sales/agents/proposal_assistant.py` (sections, commercial terms, validation),
`agents/validation.py` (TextGuard), `services/proposals.py` (revisions, status rules, Markdown export),
`workflows/generation.py`. Prompt version `sales-proposal-v1`.

For a specific proposal: `GET /api/v1/sales/proposals/{id}` (current revision), `…/revisions`, `…/export`.
Check, and report each item as OK / problem (quote the section):

1. Exactly the 13 sections in order (executive_summary … next_steps); `needs_input` sections are visibly marked.
2. Commercial terms list only offerings with `price_approved` (amount, currency, unit as configured); everything
   else shows `[PRICE TO BE CONFIRMED — no approved price configured]`. No other section contains an amount.
3. No guaranteed results or ROI, no "garantiert", no certification or compliance promises (ISO 27001,
   GDPR/DSGVO-certified, "compliant guaranteed").
4. Customer pains are hypotheses ("may", "to be validated") and appear in assumptions; nothing from the brief's
   hypotheses is stated as fact (`hypothesis_stated_as_fact` flag).
5. Scope / success criteria without confirmed requirements say `[TO BE CONFIRMED WITH CUSTOMER]`; a timeline
   appears only when requirements or offerings justify it.
6. No contact persons, e-mail addresses, phone numbers or foreign links; the export contains no HTML.
7. Revisions: revision 1 is `ai`, later ones `human`, older revisions unchanged; status moved only by people
   (draft ↔ ready → sent with a confirmed `sent_at` → accepted/declined), and `sent` recorded a `proposal_sent`
   activity. AIgentiX never sends anything.

For a code change also run `uv run pytest -q tests/test_sales_ai.py -k proposal` and the `/sales-eval` suite and
report the actual results. Never mark a proposal ready or sent on the user's behalf.
