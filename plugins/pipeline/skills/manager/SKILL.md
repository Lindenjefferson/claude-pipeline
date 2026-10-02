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
- `start --slug <slug> --base <default-branch>` once, when the feature branch is created. If the ledger still holds an earlier delivery, `start --archive` moves it to `ledger-<old-slug>.jsonl` next to it and starts fresh.
- `add --agent dev --task <id> --verdict <verdict>` after each task. A fix round always uses the id `fix-N` (`fix-1`, `fix-2`...): it stays in the current cycle, even one that already closed, so cycle numbers keep matching the plan. After a fix, `status` asks for a reviewer pass on it, and for qa again only when the cycle's last qa was a FAIL.
- `add --agent reviewer|qa --verdict PASS|FAIL --critical <n> --important <n> --minor <n>` after each pass, with the counts of its report (Critical and Important are the open, blocking ones). They feed the delivery metrics.
- `note --text '<text>'` for every decision you take on the user's behalf (a finding you rule out, a Minor you defer, a check you skip).
- `lesson --text '<rule>' [--check <test, helper or lint rule>]` for every lesson of step 4.5; `--check` when it became an automated check.
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
2. **Plan** (standard and large). `superpowers:writing-plans`: thin vertical slices grouped in **cycles of at most about 6 tasks**, each task with an id, the files it touches and its acceptance criteria. Check the current version and flags in the stack's package manager or docs before writing scaffold or install commands.
   - **Granularity.** Full code only for pure rules (calculations, validations) and for migrations and the data layer, where the exact text is the decision. UI and wiring tasks carry the interfaces they expose or consume, the acceptance criteria and the tests that prove them; the `dev` follows the patterns already in the code. A plan that writes every screen in full goes stale after the first task.
   - **Invariants and layout.** Each rule whose violation would break reading the data gets a data-layer task (constraint, trigger, policy) with its test; each read-then-write check gets its lock and a two-session test; each layout requirement of the spec (widths, touch targets, overflow) becomes an automatic check in that screen's e2e, with the numbers the project gives.
   - End the plan with an empty `## Errata` section.
   **Approval 1: show the plan and wait for the user.**
3. **Branch.** From a clean tree on the default branch: `git switch -c <feat|fix>/<slug>`, then ledger `start`.
4. **Cycle**, repeated for each group of tasks in the plan:
   1. For each task, in order: `dev` with a brief naming the plan path and the task id and telling it to read the plan's `## Errata` first (for small work, the request and its acceptance criteria). `add` its verdict. Note the commit before the cycle's first task: it is the cycle's `<from>`.
      **Errata.** When the code legitimately diverges from the plan (a renumbered migration, a changed test count, a pattern the code adopted that later tasks must follow), append one dated line to the plan's `## Errata` instead of repeating the correction in every brief, and commit it with the cycle. Errata is the only part of the plan you edit; a change of scope or decision goes to the user.
   2. `reviewer` once, on `<from>..HEAD` (the cycle's diff). `add` its verdict.
   3. `qa` once, with the same range and the acceptance criteria of the cycle's tasks. `add` its verdict. (If the reviewer failed, run qa after the fix instead, so it checks the fixed code.)
   4. **One fix round.** Send the `dev` every Critical and Important finding of the reviewer and qa in a single brief (plus the Minors worth fixing now; `note` the rest as deferred), as task `fix-N`; it stays in this cycle. When a finding is wrong, `note` your ruling instead of sending it. After the fix, run the `reviewer` on the fix commits only (`<head it reviewed>..HEAD`) and `qa` on the scenarios that failed (only when qa failed; the ledger asks for it then). If anything still fails after this round, stop and ask the user (`status` says so).
   5. For each Critical or Important finding that a rule would have prevented, first ask **"can this be a check?"**: a test, a test helper or a lint rule that fails on the mistake. If yes, it goes to the `dev` with the fix round (or as a `fix-N` task); only what cannot be automated becomes one imperative line in the project's `docs/lessons.md`, with the paths it applies to, committed with the cycle. Record each one with `lesson`.
5. **Gate.** When `status` says ready: `python "${CLAUDE_PLUGIN_ROOT}/skills/manager/gate.py" --report <slug>`. It checks the ledger, a clean tree, the Build, Typecheck, Lint and Testes commands of `CLAUDE.md` and the secret scan over the branch history, in seconds to minutes and with no agent. NOT READY: send the failing items to the `dev` as a `fix-N` task of the cycle and run the reviewer on that fix. READY: it staged the quality report; commit it (`docs: quality report`).
6. **Close. Approval 2:** show the user the gate output, the ledger notes, deferred Minors, and the delivery metrics from the quality report (findings per cycle by severity, fix rounds, lessons added and automated, so lessons can be seen to reduce findings over deliveries), and ask whether to merge into the default branch and push. **Lesson promotion:** when a lesson added in this delivery repeats one already learned in another project (you have seen it there, or the user says so), propose in this report to move it into the plugin as a general, stack-agnostic principle (the reviewer's Invariantes or `checklists/general.md`); the user decides. Do each only when the user says so, then finish with `superpowers:finishing-a-development-branch`.

## Rules
- Pass agents file paths and ranges (plan, spec, `<from>..<head>`, ledger), not pasted content.
- Never fix code yourself; send it to the dev. The spec in step 1 and the plan's `## Errata` are the only documents you edit.
- Keep `.superpowers/` out of commits.
- Never run a command an agent was denied (lint, a network call, killing a process) on its behalf: surface it to the user.
- Never merge, push or deploy without the user's explicit request for that delivery.
