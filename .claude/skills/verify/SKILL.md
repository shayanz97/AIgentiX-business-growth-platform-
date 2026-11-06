---
name: verify
description: Run all backend and frontend checks (lint, format, type checks, tests, production build, contract freshness) and summarize the actual results. Use before committing or when asked whether the project is green.
---

# /verify

Run each step from the repository root, even if an earlier one fails. Record the real exit status and the key
output lines. Never report a step as passing unless you saw it pass.

1. Backend (needs PostgreSQL reachable at `TEST_DATABASE_URL`; if unreachable, report "blocked" with the error):
   - `cd apps/api && uv run ruff check src tests migrations`
   - `cd apps/api && uv run ruff format --check src tests migrations`
   - `cd apps/api && uv run mypy`
   - `cd apps/api && uv run pytest -q` (includes the fixture research evaluation, see `/research-eval`)
2. Contracts: `make contracts && git diff --stat -- packages/shared-contracts` — any diff means the committed
   contract was stale (report it; keep the regenerated files only if the API change was intended).
3. Frontend:
   - `cd apps/web && npm run lint -- --max-warnings 0`
   - `cd apps/web && npm run typecheck`
   - `cd apps/web && npm test`
   - `cd apps/web && npm run build`
4. E2E (only if the stack runs with `-f docker-compose.e2e.yml`, services are healthy and `E2E_PASSWORD` is set):
   `cd apps/web && npx playwright test`. Otherwise mark as "not run" with the reason.

## Report format

| Check | Result | Notes |
|---|---|---|
| ruff / format / mypy / pytest (N passed) / contracts / eslint / tsc / vitest / build / e2e | pass · FAIL · blocked · not run | first error line |

End with one line: overall status and the most important failure to fix first.
