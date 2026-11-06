---
name: architecture-review
description: Review the codebase (or the current diff) for modular boundaries, dependency direction, duplication, overengineering and maintainability against the project's architecture rules. Use before merging structural changes or new modules.
---

# /architecture-review

Scope: the current branch diff (`git diff main...HEAD`) if there is one, otherwise the whole repo.
Read `CLAUDE.md` (Architecture principles, Module development rules) first.

## Checks

1. **Dependency direction** — run and inspect:
   - `grep -rn "from aigentix.modules" apps/api/src/aigentix/platform apps/api/src/aigentix/core`
     (allowed only: the lazy import in `platform/workflows/registry.py::build_registry`)
   - For each `modules/<a>/`, `grep -rn "aigentix.modules.<other>"` must be empty (no module→module imports).
   - `grep -rn "fastapi" apps/api/src/aigentix/platform apps/api/src/aigentix/modules/*/service.py` must be empty.
2. **Layering** — routes only parse input, call one service function, commit, and map the result. Business rules,
   queries and authorization decisions live in services.
3. **Module contract** — new modules expose a `ModuleDescriptor`, are listed in `modules/registry.py`, own their
   tables (with `organization_id`), and register long-running work as workflow handlers.
4. **Contracts** — API changes come with regenerated `packages/shared-contracts`; the frontend uses the generated
   types (`apps/web/src/lib/api.ts`) instead of hand-written duplicates.
5. **Duplication** — repeated query/serialization logic, copy-pasted components, duplicated validation rules
   beyond the intentional client-side mirror in `apps/web/src/lib/validation.ts`.
6. **Overengineering** — abstractions with a single implementation and no planned second one, generic
   frameworks, new infrastructure (brokers, caches, services) without a concrete requirement.
7. **Maintainability** — naming, file size (>400 lines is a smell), dead code, missing tests for new behavior.

## Output

Findings ordered by impact: `severity · file:line · problem · concrete fix`. Then a 3-line verdict:
boundaries respected (yes/no), complexity appropriate (yes/no), top recommendation. Do not modify files unless asked.
