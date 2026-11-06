# Lead intelligence fixtures

Deterministic fake company websites for testing the research engine. All domains use the reserved `.example` TLD; all people, emails and phone numbers are fictional.

## Layout

- `sites/<domain>/site.json` describes the fake site:
  - `pages`: URL path -> HTML file in the same folder (no trailing slash except `/`)
  - `robots`: robots.txt body; omit for a 404
  - `redirects` (optional): path -> absolute URL or path (served as 302)
  - `status` (optional): path -> HTTP status, served with an empty body
  - any path not listed returns 404
- `sites/<domain>/expected.json` holds the expected outcome: `scenario`, `expected_company_name`, `expected_relevant_paths`, `excluded_paths`, `expected_signals` (vocabulary: company_description, service_offering, contact_form, quote_request_form, online_booking, live_chat, customer_support, faq, careers_hiring, document_download, ecommerce, technology_signal), `expect_opportunities` (strong|weak|none), `expected_outcome` (completed|failed), `notes`.
- `companies_sample.csv` is a bulk-import sample (`name,website`) with a duplicate, an invalid URL and a row with no website.

Page text is untrusted data by design; `injection-test.example` contains deliberate prompt-injection attempts.
