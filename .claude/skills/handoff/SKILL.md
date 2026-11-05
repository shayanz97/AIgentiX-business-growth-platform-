---
name: handoff
description: Summarize completed work, current state, unresolved problems and next implementation steps so another engineer or session can continue. Use at the end of a work session or sprint.
---

# /handoff

Gather facts, do not guess:

1. `git status --short`, `git log --oneline -15`, current branch and whether it is pushed (`git status -sb`).
2. Latest verification results: run `/verify` if nothing has been verified in this session; otherwise reuse the
   real results you observed. Label anything not run as "not run".
3. Open items: `grep -rn "TODO\|FIXME" apps --include=*.py --include=*.ts --include=*.tsx`, the "Known
   limitations" and "Next steps" sections of `docs/ARCHITECTURE.md`, and unresolved review findings.

Write the handoff (in chat, or to `docs/HANDOFF.md` if asked) with these sections, max ~1 page:

- **Completed** — what changed, with key files.
- **Current state** — branch, pushed?, check results table (actual).
- **Unresolved problems** — bugs, failing checks, blocked items with the exact error and how to unblock.
- **Decisions made** — non-obvious choices and why (link docs).
- **Next steps** — ordered, concrete, each small enough for one session.
