---
name: manager
description: Use when asked to develop, implement, or deliver a module, feature, or bug fix in a personal project where the `pipeline` plugin is enabled (`claude plugin install pipeline@linde-local --scope local`). Orchestrates the agents, keeps the delivery ledger that syncs them, and ends at the `gate` agent. Triggers on "manager", "desenvolver módulo", "implementar módulo", "nova feature", "corrigir bug", "deliver".
---

# Manager

Runs one delivery (module, feature, or bug fix) through the `pipeline` plugin's agents. **The main session is the manager:** only the main session can dispatch agents, so orchestration lives here and not in an agent. It plans, dispatches agents by name (`subagent_type`, always with the plugin prefix: `pipeline:dev`, `pipeline:db`, `pipeline:gate`, and so on), routes findings, keeps the ledger, and never writes product code itself. Agents do not run on their own; name them. The final release check is the `gate` agent, which reads the ledger and never dispatches anyone.

## Ledger (how agents stay in sync)
One file per delivery, `.superpowers/ledger.jsonl` in the worktree root (git-ignored), written only through `python "${CLAUDE_PLUGIN_ROOT}/skills/manager/ledger.py" --ledger .superpowers/ledger.jsonl <command>`:
- `start --slug <slug> --base <sha>` once, before the first dispatch.
- `append --task <id> --from <sha> --head <sha> --report <path> --line '<agent LEDGER line>'` after every agent returns. `--from` is the parent of the task's first commit (the branch base for a small change) and `--head` is the current HEAD, so the entry records the exact commit range the agent covered. Round numbers are computed per task and agent.
- `note --kind ruling|deferred|parked|condition --task <id> --text '<text>'` for every decision you take on the user's behalf (a finding you rule on, a Minor you defer or park, a condition attached to an approval). Notes are how decisions survive a compacted context.
- `status [--json] [--head HEAD]` shows the latest verdict per task and agent, the findings raised so far, and the notes; with `--head`, each entry whose range ends before that commit is marked `STALE` with the number of commits after it.

This ledger is the only progress record of the delivery: do not also keep a `progress.md` or any second log, and read progress back from `status` after a context compaction.

Package files for agents come from `python "${CLAUDE_PLUGIN_ROOT}/skills/manager/package.py"`, so nothing is pasted into a prompt: `brief --plan <plan> --task <n> --out <file>` extracts one task's text, and `review --base <sha> --head <sha> --name <task>-r<round>` writes `.superpowers/reviews/review-<name>.diff` (commits, stats, diff) and a commit-by-commit `.history.patch` (needed to catch a secret that was added and later removed).

Every agent ends its report with one line `LEDGER {...}`; append it verbatim. `append` validates before writing: a known agent and a verdict valid for it (`PASS`/`FAIL` for reviewers, `DONE`/`DONE_WITH_CONCERNS`/`NEEDS_CONTEXT`/`BLOCKED`/`NO_DOC_CHANGE_NEEDED` otherwise), integer `new`/`open` counts for all three severities on a reviewer line, a verdict consistent with them (FAIL exactly when a critical or important finding is open), `--from`/`--head` that are commits in ancestor order, and an existing `--report` file. On a rejection nothing is written: re-read the saved report, fix the transcription or ask the agent for a corrected line, and append again. Save each agent's full report to `.superpowers/reports/<task>-<agent>-r<round>.md` first (reviewers are read-only and cannot save it), and pass that path as `--report`; the `gate` cross-checks ledger lines against these files.

Give every agent the ledger path in its brief. Agents read it (never write it) to see what already ran and which findings are open, so parallel reviewers do not repeat each other and a fixer sees what is still pending.

## Where this applies
Only in repos where the `pipeline` plugin is enabled: enabling it is what loads this skill, the agents and the secret-scan hook, so it is the only switch. If the project lacks the structure (`CLAUDE.md`, `docs/`), run `pipeline:kickoff` first.

## Steps

1. **Scope and pre-flight, with evidence.** Identify the target and locate its spec and its living doc (`docs/NN-*.md`). Check:
   - `CLAUDE.md` and the `docs/` convention exist. If not, stop and offer `kickoff`.
   - A spec exists for the target. If not, stop and start `discovery` (raw sources) then `superpowers:brainstorming`. If it exists, skip both.
   - Git repo with at least one commit and a clean tree (worktrees and the `gate` diff need a baseline). If not, ask the user how to proceed.
   - Prerequisites the target depends on (project scaffold, migrations, auth) exist. If not, the plan starts with a foundation task.
   - The `Comandos` section of `CLAUDE.md` lists how to run, test, typecheck, and lint (`qa` needs them). If it holds placeholders, derive the commands from the project (`package.json`, `Makefile`) and fill it in before planning.
   - `docs/quality-reports/` exists. Its presence turns on the push gate (the plugin's hook blocks `git push` unless the `gate` approved the current tree). If missing, the first commit on the worktree branch adds `docs/quality-reports/.gitkeep`.
2. **Plan.** Use `superpowers:writing-plans`. Tag each task with an id, its implementer (`dev` for app code, `db` for schema, migrations, RLS) and its required reviewers. Show the plan and wait for approval.
3. **Execute** in a worktree (`superpowers:using-git-worktrees`) with the loop below. Do not invoke `superpowers:subagent-driven-development`: it keeps its own progress ledger and reviewer prompts, which would compete with this ledger and these agents. Run ledger `start` first. One implementer at a time. Per task, in order:
   1. Implementer (`dev` or `db`), who commits the task on the worktree branch. Commits stay local; never on the default branch. Give it the task's `brief` file. Note the task's `--from` (HEAD before it) and append its report to the ledger.
   2. `docs` updates the matching `docs/NN-*.md` (or reports `NO_DOC_CHANGE_NEEDED`). Append to the ledger.
   3. Reviewers for the diff, in one message so they run in parallel: `code-review` always; `db` and `security` for schema, migrations, RLS; `security` for auth, permissions, secrets; `audit` for writes to sensitive or financial data; `design` for UI; `qa` last. Capture HEAD before dispatching, build one `review` package for the range and use that HEAD as `--head` for all of them. Append each report to the ledger.
   4. Findings go to the agent that owns the file. After the fix commit, re-run the same reviewer over the task's full range (`--from` unchanged, new `--head`) so its latest entry covers the fix. Maximum 5 rounds per task and reviewer (the ledger's `round`); at round 5 still FAIL, stop and ask the user.
   For a bug fix, run `superpowers:systematic-debugging` first and require a regression test.
   Never leave a commit uncovered: any commit made after a reviewer's `--head` in that reviewer's domain means that reviewer runs again.
4. **Gate.** Run ledger `status --head HEAD` and fix every entry it marks `STALE` (commits after that reviewer's range) or missing before calling the gate; a wasted gate run is a full-branch review. Then dispatch `gate` with the branch base, the ledger path and the reports directory; it reviews the whole branch (`<base>...HEAD`) and its commit history. On APPROVED it writes and stages the quality report and records the approval. On BLOCKED, each item names its owner: route it to step 3 (implementer, or the missing/stale reviewer), append the new reports to the ledger and call the gate again.
5. **Leave the machine.** After APPROVED, commit the staged report as is, with nothing else added. Merge into the default branch and push only when the user asks, each time; nothing merges or pushes without their request. Finish with `superpowers:finishing-a-development-branch`.
6. **Close.** End with two lists taken from `ledger.py status`: "Rulings I made" (every `ruling` note, in order, with what it costs if wrong) and the `deferred`/`parked`/`condition` notes still standing. Then list every deviation from this procedure: agent not dispatched, improvisation, anything that blocked.

## Small-change lane
Decide from the actual diff, never from how small the request sounds. The lane applies only if the change touches at most 3 files and 100 lines and none of: migrations, schema, RLS, auth, permissions, sessions, env/secrets config, write paths for sensitive or financial data. Then skip the written plan and run: `dev` (commits on a worktree branch), `code-review`, `docs` only if an interface or setup step changed, `qa` if tests exist, then `gate` as in steps 4 and 5. The ledger applies unchanged (a single task, `--from` = base). If the diff exceeds any limit, switch to the full procedure.

## Rules
- Keep `.superpowers/` out of commits.
- Pass agents file paths (briefs, diffs, reports, ledger), not pasted content.
- Never fix findings yourself in the manager session; route them.
- Never edit the ledger by hand; only through `ledger.py`.
- Keep one progress record: the ledger. No `progress.md`, no second log.
