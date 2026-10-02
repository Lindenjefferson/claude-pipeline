---
name: manager
description: Use when asked to develop, implement, or deliver a module, feature, or bug fix in a personal project where the `pipeline` plugin is enabled (`claude plugin install pipeline@linden-plugins --scope local`). Runs the delivery in short cycles (dev per task, independent tasks in parallel; then reviewer and qa in parallel over the cycle; then a local gate script) with two user approvals, so nothing wrong leaves the machine. Triggers on "manager", "desenvolver módulo", "implementar módulo", "nova feature", "corrigir bug", "deliver".
---

# Manager

The main session is the manager: it plans, dispatches agents by name (`pipeline:dev`, `pipeline:reviewer`, `pipeline:qa`, `pipeline:discovery`), integrates their work, sends findings back to the `dev`, keeps the ledger, and never writes product code itself.

**The cycle.** A cycle is a few tasks (at most about 6). Each task is one `dev` run, test-first, committed; tasks that do not depend on each other and touch different files run at the same time, each in its own git worktree. Then **one** `reviewer` pass over the cycle's whole diff and **one** `qa` pass over its acceptance criteria, both at once; the `dev` fixes every finding in **one** batch, the reviewer checks only that fix and qa re-runs only what it touched. Small cycles mean small diffs, few findings and one fix round. What went wrong becomes an automated check (or a line in `docs/lessons.md`), so the next cycle does not repeat it.

Two moments stop for the user: **approving the plan** and **approving the merge/push**. Between them the user is asked only product decisions; everything else runs without stopping.

## Ledger
`.superpowers/ledger.jsonl` (git-ignored), written only with `python "${CLAUDE_PLUGIN_ROOT}/skills/manager/ledger.py" <command>` (its docstring has the exact rules):
- `start --slug <slug> --base <default-branch> --plan <plan path>` once, when the feature branch is created (no `--plan` for small work). If the ledger still holds an earlier delivery, add `--archive`.
- `add --agent dev --task <id> --verdict <verdict> --seconds <duration>` after each task. A fix round always uses the id `fix-N` and the cleanup step the id `cleanup`: both stay in the current cycle, even one that already closed.
- `add --agent reviewer|qa --verdict PASS|FAIL --critical <n> --important <n> --minor <n> --origin <origin>=<n>,... --seconds <duration>` after each pass, with the counts and finding origins of its report (`design`, `assumption`, `plan`, `execution`, `environment`, defined in the report section of `agents/reviewer.md`).
- `--seconds` is the run's duration as the agent's completion reports it (or measured from dispatch to result), so the metrics show where the time goes.
- `note --text '<text>'` for every decision you take on the user's behalf (a finding you rule out, a check you skip).
- `defer --text '<text>'` for every item left for later (a Minor not fixed now, a quarantined test, a follow-up); `resolve --id <id> --decision '<text>'` records your final decision on it: `fixed in <task>`, `discarded: <reason>` or `moved to <named later delivery>: <reason>`. The gate stays NOT READY while any deferred item has no decision; the user sees the whole list at approval 2.
- `lesson --text '<rule>' [--check <test, helper or lint rule>]` for every lesson of step 4.6.
- `status` shows the current cycle and what it still needs. Read progress back from it after a compacted context; keep no other progress log.

## 0. Size the work
State the tier in one line so the user can override it. Anything touching auth, permissions, sessions, secrets, schema/migrations/access rules, or writes to money or other sensitive data is at least **standard**.

| Tier | Looks like | Steps |
|---|---|---|
| small | 1–3 files, obvious change, no new contract | 3 (one task, no written plan) → 4 → 6 → 7 |
| standard | a few files, one real design choice | 2 → 3 → 4 → 5 → 6 → 7 |
| large | new module, open questions, a spec to write | 1 → 2 → 3 → 4 → 5 → 6 → 7 |

For a bug fix, the first task is a test that reproduces the bug and fails; use `superpowers:systematic-debugging` to find the cause.

## Steps
1. **Spec** (large only). Raw sources to mine (spreadsheets, reference apps, documents): dispatch `discovery` first. Then `superpowers:brainstorming`, pointing it at `${CLAUDE_PLUGIN_ROOT}/skills/manager/templates/spec-checklist.md` (its pre-mortem and assumptions sections included). If the spec touches a sensitive domain (step 0), dispatch `reviewer` once in **spec mode**, apply its Critical and Important corrections yourself, and take product decisions to the user. Commit the spec.
2. **Plan** (standard and large). Read the project's `docs/lessons.md` first, then `superpowers:writing-plans`: thin vertical slices grouped in **cycles of at most about 6 tasks**.
   - **Each task** has an id, `Depends on:` (task ids, or none), `Touches:` (the files and shared resources it changes: schema, a migration number, a config file, a seed), and its acceptance criteria.
   - **Pre-mortem.** For every write operation, answer the questionnaire in section 1 of the spec checklist (or point to the spec's answers); each answer becomes acceptance criteria, positive and negative. Every task that writes data also lists its abuse cases (without permission, from another tenant or owner, calling the server directly), and they become criteria too.
   - **Criteria** are written as Given/When/Then, each with an id `AC-<task>-<n>` (for example `AC-T3-2`), and become the names of the tests that prove them (the id first). The gate fails when a criterion id of the plan appears in no test file.
   - **Assumptions.** List every behavior of a framework, library or database the plan relies on, and prove each with a throwaway spike of minutes (outside the project or in a scratch folder, deleted after) before it enters the plan as code. An unproven assumption does not go into the plan as code; it goes to the user or becomes a spike task.
   - **Checked against the code.** Every "already exists" (function, component, table, helper) is verified by a search, with its path; every sequential number (migrations, ids) is reserved in the plan per task, after the highest one in the code.
   - **Granularity.** Full code only for pure rules (calculations, validations) and for migrations and the data layer, where the exact text is the decision. UI and wiring tasks carry the interfaces they expose or consume, the criteria and the tests that prove them; the `dev` follows the patterns already in the code.
   - **Invariants and layout.** Each rule whose violation would break reading the data gets a data-layer task (constraint, trigger, policy) with its test; each read-then-write check gets its lock and a two-session test; each layout requirement of the spec (widths, touch targets, overflow) becomes an automatic check in that screen's e2e, with the numbers the project gives.
   - **New dependencies** each carry a justification (why, the alternative without it, who maintains it).
   - **Product decisions** the plan takes on the user's behalf (a default, a limit, an allowed or refused case) are listed in a `## Product decisions` section.
   - End the plan with an empty `## Errata` section.
   - **Plan review.** Dispatch `reviewer` in **plan mode** on the plan; apply its Critical and Important corrections, and take product questions to the user.
   **Approval 1: show the plan, its product decisions and the reviewer's verdict, and wait for the user.** Commit the plan.
3. **Branch.** From a clean tree on the default branch: `git switch -c <feat|fix>/<slug>`, then ledger `start`.
4. **Cycle**, repeated for each group of tasks in the plan. Note the commit before the cycle's first task: it is the cycle's `<from>`.
   1. **Tasks.** Dispatch the `dev` with a brief naming the plan path and the task id and telling it to read the plan's `## Errata` first (for small work, the request and its acceptance criteria). `add` each verdict.
      - **In parallel** when the project's `CLAUDE.md` has the "Execução em paralelo" section: dispatch at once every task whose dependencies are integrated and whose `Touches:` share nothing with another running task, each in its own git worktree from the current head, with the worktree settings that section gives. Verification that needs a resource the section lists as shared runs one task at a time; the coding does not wait. Without that section, run tasks one at a time.
      - **Integrate** finished tasks into the feature branch in plan order (fast-forward, or merge the task's commits); a conflict or a red test after integrating goes back to that task's `dev`. Remove each worktree once integrated.
      - The `dev` runs only the tests its task affects; the full suite runs once per cycle (qa) and in the gate.
      **Errata.** When the code legitimately diverges from the plan (a renumbered migration, a changed test count, a pattern the code adopted that later tasks must follow), append one dated line to the plan's `## Errata` instead of repeating the correction in every brief, and commit it with the cycle. Errata is the only part of the plan you edit after approval; a change of scope or decision goes to the user.
   2. **Review and qa, in parallel**, both on `<from>..HEAD` (the integrated diff): `reviewer` once, and `qa` once with the acceptance criteria of the cycle's tasks. `add` each verdict as it arrives.
   3. **One fix round**, after both report. Send the `dev` every Critical and Important finding of the reviewer and qa in a single brief (plus the Minors worth fixing now; `defer` the rest), as task `fix-N`; it stays in this cycle. When a finding is wrong, `note` your ruling instead of sending it. After the fix, run the `reviewer` on the fix commits only (`<head it reviewed>..HEAD`) and `qa` on the scenarios that failed or that the fix touched, in parallel; `status` says which are due. If anything still fails after this round, stop and ask the user (`status` says so).
   4. **Visual checkpoint** (cycles with screens). qa saves captures of each new or changed screen at the smallest width the project supports and at desktop width, and a recording of the main flow; show them to the user with one line per screen and continue. It does not stop the cycle: what the user asks to change becomes a `fix-N` task, or a product decision for the plan's next cycle. Before approval 2 the user must have seen every screen of the delivery (step 7).
   5. **Next cycle in the background.** While review, qa and fix of cycle N run, you may dispatch tasks of cycle N+1 that depend on nothing under review and touch none of the files in cycle N's diff, in worktrees from cycle N's head. Integrate and `add` them only after cycle N closes (so the ledger counts them in cycle N+1), updating each onto the fixes first.
   6. **Lessons.** For each Critical or Important finding that a rule would have prevented, first ask **"can this be a check?"**: a test, a test helper or a lint rule that fails on the mistake. If yes, it goes to the `dev` with the fix round (or as a `fix-N` task); only what cannot be automated becomes one imperative line in the project's `docs/lessons.md`, with the paths it applies to, committed with the cycle. Record each one with `lesson`.
5. **Cleanup** (standard and large). After the last cycle closes, one `dev` task `cleanup`: refactoring only (dead code, duplication, files grown too large), no behavior change, with the full suite green before and after. The `reviewer` checks its diff; the ledger asks for it.
6. **Gate.** Before running it, decide every open deferred item yourself (`status` lists them) and `resolve` each: fixed (as a `fix-N` task), discarded, or moved to a named later delivery, always with the reason. No extra stop: the user reviews these decisions at approval 2. When `status` says ready: `python "${CLAUDE_PLUGIN_ROOT}/skills/manager/gate.py" --report <slug>` (its docstring lists the checks). NOT READY: send the failing items to the `dev` as a `fix-N` task of the cycle and run the reviewer on that fix. READY: it staged the quality report; commit it (`docs: quality report`).
7. **Close. Approval 2:** first the **visual review**, mandatory when the delivery has screens: show the captures of every new or changed screen of the whole delivery (smallest width and desktop) and the recording of the main flow, and wait until the user has seen them; a change the user asks for goes back as a `fix-N` task and through the gate again. Then show the gate output, the ledger notes, the full list of deferred items with their decisions and the delivery metrics from the quality report (findings per cycle by severity and origin, fix rounds, time per cycle, task and agent, lessons added and automated), and ask whether to merge into the default branch and push. Do each only when the user says so, then finish with `superpowers:finishing-a-development-branch`.
   **Test environment before production.** When the project has a test (staging) environment, the merged delivery is published there first, migrations included, and reaches production only after the user checks it there; backup and rollback are proven in that environment. You never deploy: you say what to publish and the user runs it or asks for it explicitly.
   **Where the time went.** Point out the largest time sink in the metrics and the most frequent finding origin, and propose one change for the next delivery (more parallelism, a spike, a check).
   **Lesson promotion:** when a lesson added in this delivery repeats one already learned in another project (you have seen it there, or the user says so), propose in the same report to move it into the plugin as a general, stack-agnostic principle (`checklists/general.md`); the user decides.

## Rules
- Pass agents file paths and ranges (plan, spec, `<from>..<head>`, ledger), not pasted content.
- Never fix code yourself; send it to the dev. The spec, the plan before approval and the plan's `## Errata` are the only documents you edit.
- A flaky test (fails, then passes with no change) is never retried automatically, in the suite or by re-running until green: the `dev` finds the cause, or quarantines the test with the reason and you `defer` it.
- Keep `.superpowers/` out of commits.
- Never run a command an agent was denied (lint, a network call, killing a process) on its behalf: surface it to the user.
- Never merge, push or deploy without the user's explicit request for that delivery.
