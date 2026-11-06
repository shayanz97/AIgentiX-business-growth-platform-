# Shared API contracts

Generated files — do not edit by hand.

| File | Source |
|---|---|
| `openapi.json` | Exported from the FastAPI app (`python -m aigentix.export_openapi`) |
| `schema.d.ts` | Generated from `openapi.json` by `openapi-typescript` |

Regenerate both with `make contracts` after changing any API route or schema, and commit the result.
CI fails if these files are stale. The web app consumes the types through `openapi-fetch`
(`apps/web/src/lib/api.ts`), so a backend contract change surfaces as a TypeScript error in the frontend.
