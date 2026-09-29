---
name: manager
description: Use when asked to develop, implement, or deliver a module, feature, or bug fix in a personal project where the `pipeline` plugin is enabled (`claude plugin install pipeline@linden-plugins --scope local`). Runs the delivery in short cycles (dev per task, then one reviewer and one qa pass per cycle, then a local gate script) with two user approvals, so nothing wrong leaves the machine. Triggers on "manager", "desenvolver módulo", "implementar módulo", "nova feature", "corrigir bug", "deliver".
---

# Manager

The main session is the manager: it plans, dispatches agents by name (`pipeline:dev`, `pipeline:reviewer`, `pipeline:qa`, `pipeline:discovery`), sends findings back to the `dev`, keeps the ledger, and never writes product code itself.

**The cycle.** A cycle is a few tasks (at most about 6): the `dev` implements them one by one, test-first, committing each; then **one** `reviewer` pass over the cycle's whole diff and **one** `qa` pass over its acceptance criteria; the `dev` fixes every finding in **one** batch and the reviewer checks only that fix. Small cycles mean small diffs, few findings and one fix round, so each cycle ends fast and the next starts from a clean base. What went wrong becomes a line in `docs/lessons.md`, so the next cycle does not repeat it.

Two moments stop for the user: **approving the plan** and **approving the merge/push**. Everything between them runs without stopping.

## Ledger
`.superpowers/ledger.jsonl` (git-ignored), written only with `python "${CLAUDE_PLUGIN_ROOT}/skills/manager/ledger.py" <command>`:
- `start --slug <slug> --base <default-branch>` once, when the feature branch is created.
- `add --agent dev --task <id> --verdict <verdict>` after each task (fixes use a task id like `fix-1`).
- `add --agent reviewer|qa --verdict PASS|FAIL --open <n>` after each pass (`<n>` = open Critical + Important).
- `note --text '<text>'` for every decision you take on the user's behalf (a finding you rule out, a Minor you defer, a check you skip).
- `status` shows the current cycle and what it still needs. Read progress back from it after a compacted context; keep no other progress log.

## 0. Size the work
State the tier in one line so the user can override it. Anything touching auth, permissions, sessions, secrets, schema/migrations/RLS, or writes to money or other sensitive data is at least **standard**.

| Tier | Looks like | Steps |
|---|---|---|
| small | 1–3 files, obvious change, no new contract | 3 (one task, no written plan) → 4 → 5 → 6 |
| standard | a few files, one real design choice | 2 → 3 → 4 → 5 → 6 |
| large | new module, open questions, a spec to write | 1 → 2 → 3 → 4 → 5 → 6 |

For a bug fix, the first task is a test that reproduces the bug and fails; use `superpowers:systematic-debugging` to find the cause.

## Steps
1. **Spec** (large only). Raw sources to mine (spreadsheets, reference apps, documents): dispatch `discovery` first. Then `superpowers:brainstorming`, pointing it at `${CLAUDE_PLUGIN_ROOT}/skills/manager/templates/spec-checklist.md`. If the spec touches a sensitive domain (step 0), dispatch `reviewer` once in **spec mode**, apply its Critical and Important corrections yourself, and take product decisions to the user. Commit the spec.
2. **Plan** (standard and large). `superpowers:writing-plans`: thin vertical slices grouped in **cycles of at most about 6 tasks**, each task with an id, the files it touches and its acceptance criteria. Check current versions (`npm view`, docs) before writing scaffold commands. **Approval 1: show the plan and wait for the user.**
3. **Branch.** From a clean tree on the default branch: `git switch -c <feat|fix>/<slug>`, then ledger `start`.
4. **Cycle**, repeated for each group of tasks in the plan:
   1. For each task, in order: `dev` with a brief naming the plan path and the task id (for small work, the request and its acceptance criteria). `add` its verdict. Note the commit before the cycle's first task: it is the cycle's `<from>`.
   2. `reviewer` once, on `<from>..HEAD` (the cycle's diff). `add` its verdict.
   3. `qa` once, with the same range and the acceptance criteria of the cycle's tasks. `add` its verdict. (If the reviewer failed, run qa after the fix instead, so it checks the fixed code.)
   4. **One fix round.** Send the `dev` every Critical and Important finding of the reviewer and qa in a single brief (plus the Minors worth fixing now; `note` the rest as deferred). When a finding is wrong, `note` your ruling instead of sending it. After the fix, run the `reviewer` on the fix commits only (`<head it reviewed>..HEAD`) and `qa` on the scenarios that failed. If anything still fails after this round, stop and ask the user (`status` says so).
   5. For each Critical or Important finding that a written rule would have prevented, add that rule to the project's `docs/lessons.md` (one imperative line, with the paths it applies to) and commit it with the cycle.
5. **Gate.** When `status` says ready: `python "${CLAUDE_PLUGIN_ROOT}/skills/manager/gate.py" --report <slug>`. It checks the ledger, a clean tree, the Build, Typecheck, Lint and Testes commands of `CLAUDE.md` and the secret scan over the branch history, in seconds to minutes and with no agent. NOT READY: send the failing items to the `dev` as one more task of the cycle and run the cycle's reviewer on that fix. READY: it staged the quality report; commit it (`docs: quality report`).
6. **Close. Approval 2:** show the user the gate output, the ledger notes, deferred Minors and lessons added, and ask whether to merge into the default branch and push. Do each only when the user says so, then finish with `superpowers:finishing-a-development-branch`.

## Rules
- Pass agents file paths and ranges (plan, spec, `<from>..<head>`, ledger), not pasted content.
- Never fix code yourself; send it to the dev. The spec in step 1 is the only document you edit.
- Keep `.superpowers/` out of commits.
- Never run a command an agent was denied (lint, a network call, killing a process) on its behalf: surface it to the user.
- Never merge, push or deploy without the user's explicit request for that delivery.
