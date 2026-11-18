# Enrichment fixtures

Deterministic, offline fixtures for growth-trigger, buying-intent and ICP-fit detection.
Reference date for freshness: **2026-11-12** (recent <=30 days, moderate 31-90, older 91-180, historical >180, no date = unknown).

- `sites/<domain>/` - 16 fictional `.example` sites (same format as `../sites/`): `site.json`, HTML pages, and `expected.json` (scenario, expected signals, dates, freshness, intent, country, fit, score band).
- `tenders.json` - offline tender-source records (one per tender, linked by `buyer_domain`; includes an expired, an irrelevant and an unmatched-domain tender).
- `first_party.json` - a first-party inbound inquiry (vielfalt-gmbh) that the evaluation records through the API, as a user would.

Digitalwerk's intent is INDIRECT from its own digitalisation announcement (no request was published).

All content is untrusted; `injektion-news.example` deliberately contains prompt-injection text. Extra keys in `expected.json` beyond the base schema: `expected_company_size`, `expected_company_size_conflict`, `expected_deadline`, `forbidden_urls`.
