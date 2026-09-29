---
name: manager
description: Use when asked to develop, implement, or deliver a module, feature, or bug fix in a personal project where the `pipeline` plugin is enabled (`claude plugin install pipeline@linden-plugins --scope local`). Runs one delivery through a short loop (dev, reviewer, qa per task, then the gate) with two user approvals, so nothing wrong leaves the machine. Triggers on "manager", "desenvolver módulo", "implementar módulo", "nova feature", "corrigir bug", "deliver".
---

# Manager

The main session is the manager: only it can dispatch agents, so it plans, dispatches them by name (`pipeline:dev`, `pipeline:reviewer`, `pipeline:qa`, `pipeline:gate`, `pipeline:discovery`), passes findings back to the `dev`, keeps the ledger, and never writes product code itself.

The loop, per task: **dev** implements test-first and commits → **reviewer** reviews the task's diff → **qa** checks the acceptance criteria → findings go back to the dev. At the end the **gate** runs every check locally. Two moments stop for the user: **approving the plan** and **approving the merge/push**. Everything between them runs without stopping.

## Ledger
One file per delivery, `.superpowers/ledger.jsonl` (git-ignored), written only with `python "${CLAUDE_PLUGIN_ROOT}/skills/manager/ledger.py" <command>`:
- `start --slug <slug> --base <default-branch>` once, when the feature branch is created.
- `add --task <id> --agent <agent> --verdict <verdict> [--open <n>] [--summary '<one line>']` after every agent returns. `--open` is the count of open Critical + Important findings (FAIL needs it above 0, PASS needs 0).
- `note --task <id> --text '<text>'` for every decision you take on the user's behalf (a finding you rule out, a Minor you defer, a check you skip). Notes survive a compacted context.
- `status` shows, per task, the latest verdict per agent and what is pending, and whether the delivery is ready for the gate. Read progress back from it after a compaction; keep no other progress log.

## 0. Size the work
Score the request and state the tier in one line so the user can override it. Anything touching auth, permissions, sessions, secrets, schema/migrations/RLS, or writes to money or other sensitive data is at least **standard**.

| Tier | Looks like | Steps |
|---|---|---|
| small | 1–3 files, obvious change, no new contract | 3 (no plan: one task) → 4 → 5 → 6 |
| standard | a few files, one real design choice | 2 (plan) → 3 → 4 → 5 → 6 |
| large | new module, several open questions, a spec to write | 1 (spec) → 2 → 3 → 4 → 5 → 6 |

For a bug fix, the first task is a test that reproduces the bug and fails; use `superpowers:systematic-debugging` to find the cause.

## Steps
1. **Spec** (large only). If the project has raw sources to mine (spreadsheets, reference apps, documents), dispatch `discovery` first. Then run `superpowers:brainstorming`, pointing it at `${CLAUDE_PLUGIN_ROOT}/skills/manager/templates/spec-checklist.md`; the spec answers every section of it. If the spec touches a sensitive domain (the list in step 0), dispatch `reviewer` once in **spec mode** on it, apply the Critical and Important corrections yourself (the spec is this session's document), and take any product decision to the user. Commit the spec.
2. **Plan** (standard and large). Use `superpowers:writing-plans`: thin vertical slices, each task with an id, the files it touches and its acceptance criteria. Check current versions (`npm view`, docs) before writing scaffold commands. **Approval 1: show the plan and wait for the user.**
3. **Branch.** From a clean tree on the default branch: `git switch -c <feat|fix>/<slug>`, then ledger `start`. Commits stay on this branch.
4. **Loop per task**, one task at a time:
   1. `dev` with a brief naming the plan path and the task id (for small work, the request itself as the task and its acceptance criteria). `add` its verdict.
   2. `reviewer` with the task's range (`<commit before the task>..HEAD`). `add` its verdict with the open count.
   3. `qa` with the same range and the acceptance criteria, once the reviewer passes. `add` its verdict.
   4. **Findings** (reviewer or qa FAIL): send the dev a brief with the findings as reported, then run the same reviewer or qa again on the same task range. Minors do not block: fix them in a round that runs anyway, or `note` them as deferred. When a finding is wrong, `note` your ruling instead of sending it. After 3 failed rounds of the same agent on a task (`status` says so), stop and ask the user.
   When a Critical or Important finding came from a mistake a written rule would have prevented, add that rule to the project's `docs/lessons.md` (one line, imperative, with the paths it applies to); the dev and the reviewer read it on every task.
5. **Gate.** When `status` says ready, dispatch `gate` with the base and the ledger path. NOT READY: send each item to its owner (dev for code; the user for the environment or the allowlist), loop back to step 4 for the affected task, then call the gate again. READY: it staged the quality report; commit it on the branch (`docs: quality report`).
6. **Close. Approval 2:** show the user what the branch delivers (the gate report, the ledger notes, deferred Minors, lessons added) and ask whether to merge into the default branch and push. Do each only when the user says so, then finish with `superpowers:finishing-a-development-branch`.

## Rules
- Pass agents file paths (plan, spec, ranges, ledger), not pasted content.
- Never fix code yourself; send it to the dev. The spec in step 1 is the only document you edit.
- Keep `.superpowers/` out of commits.
- Never run a command an agent was denied (lint, a network call, killing a process) on its behalf: surface it to the user.
- Never merge, push or deploy without the user's explicit request for that delivery.
