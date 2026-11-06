---
name: security-review
description: Review authentication, access control, tenant isolation, secret exposure and input handling for this project. Use before merging changes that touch auth, tenant-owned data, API routes, configuration or infrastructure.
---

# /security-review

Scope: the current diff (`git diff main...HEAD`) if any, otherwise the whole repo. Read the "Security invariants"
section of `CLAUDE.md` first; every finding should reference the invariant it breaks.

## Procedure

1. **Tenant isolation** — for every route using `Tenant` or touching an org-owned table:
   - the service query filters on `tenant.organization_id` (grep for `select(` in `modules/*/service.py`,
     `platform/*/service.py` and check each `where`);
   - no organization id is taken from body/query/path without `resolve_tenant`;
   - by-id lookups of foreign resources return 404, foreign org headers return 403;
   - a test exists for cross-tenant list, cross-tenant get-by-id and spoofed `X-Organization-Id`
     (`apps/api/tests/test_projects.py` is the template). Run `cd apps/api && uv run pytest -q -k "tenant or spoof"`.
2. **Authentication & sessions** — `platform/identity/service.py`, `api/routes/auth.py`, `api/deps.py`:
   hashed token storage, expiry check, revocation on logout, rotation on login, cookie flags, inactive users.
3. **Authorization** — owner-only operations enforce `is_owner` in the service layer, with a member-denied test.
4. **CSRF / CORS** — no wildcard origins, `allow_credentials` only with explicit origins, origin check active.
5. **Input handling** — Pydantic models use `extra="forbid"` and length limits; URLs restricted to http(s);
   validation errors do not echo values; frontend renders user content as text (no `dangerouslySetInnerHTML`),
   external links use `rel="noopener noreferrer"`, redirects (`next=`) only allow relative paths.
6. **Secrets** — `git ls-files | xargs grep -nEi "(password|secret|token|api[_-]?key)\s*[=:]"` and review hits;
   `.env` files are git-ignored; compose/CI use placeholders or generated values only.
7. **Logging** — no cookies, passwords, tokens or request bodies logged (`api/middleware.py`, `structlog` calls).
8. **Outbound fetching (SSRF)** — any new HTTP client must go through `SafeFetcher`
   (`modules/lead_intelligence/integrations/fetcher.py`); run `uv run pytest -q tests/test_li_ssrf.py`.
   Test doubles (`RESEARCH_FETCH_BACKEND=fixtures`, `LLM_PROVIDER=fixture`) must stay refused in production.
9. **Untrusted content / LLM** — website text only enters prompts inside neutralised delimiters; model output
   is validated (citations exist and are verbatim, unsupported claims flagged, foreign links stripped) and
   rendered as plain text.
10. **Infrastructure** — containers run as non-root, ports bound to 127.0.0.1, no debug flags in production config.

## Output

Findings by severity (Critical/High/Medium/Low): `file:line · scenario · fix`. State explicitly which checks
passed. Critical/High findings block merge. Do not modify files unless asked.
