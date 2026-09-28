---
name: kickoff
description: Use when starting a new personal project, or when the user asks to add the multiagent structure (CLAUDE.md, docs/ convention, knowledge graph, graph gitignore) to an existing personal project. Exists only where the `pipeline` plugin is enabled (`claude plugin install pipeline@linden-plugins --scope local`, run once in the project folder). Triggers on "kickoff", "novo projeto", "iniciar projeto", "preparar o projeto".
---

# Project Kickoff

Prepares a project so the `pipeline` plugin's agents work from day one. **Idempotent:** inspect first, add only what is missing, never overwrite an existing file, never commit or push.

## Steps (run from the project root)

1. **Pre-flight.** Confirm the plugin pieces exist: agents `pipeline:discovery`, `pipeline:dev`, `pipeline:db`, `pipeline:security`, `pipeline:audit`, `pipeline:design`, `pipeline:code-review`, `pipeline:qa`, `pipeline:gate` and `pipeline:docs` among the agent types, the skill `pipeline:manager` (with `ledger.py` and `package.py` under `${CLAUDE_PLUGIN_ROOT}/skills/manager/`), and `${CLAUDE_PLUGIN_ROOT}/hooks/pre-commit-secret-scan.py` (the plugin's `hooks/hooks.json` wires it while the plugin is enabled), and the `superpowers` plugin enabled (`superpowers:brainstorming`, `writing-plans`, `using-git-worktrees`, `finishing-a-development-branch` appear among the available skills; the pipeline depends on them). If any is missing, stop and tell the user; they belong to the plugin, do not recreate them here.
2. **Git.** `git init` if the folder is not a repo. Then ask the user before installing the push-time secret scan (a persistent git hook; if the permission system denies it, stop and report): `python "${CLAUDE_PLUGIN_ROOT}/hooks/pre-commit-secret-scan.py" --install-pre-push`. It never overwrites an existing pre-push hook. The hook stores no path: it finds the scanner through `CLAUDE_PIPELINE_HOME` or `git config pipeline.home` and blocks the push if neither resolves. If `git config --get pipeline.home` is empty, tell the user the command the installer prints (`git config --global pipeline.home ...`) and let them run it. Unlike the Claude Code hook, it blocks a push of secret-containing commits however git is invoked.
3. **`.gitignore`.** Create from `templates/gitignore`, or append the template's missing blocks (with their comment headers). It must ignore `graphify-out/` (the graph is rebuilt locally, never committed) and `.env`. Add stack-specific ignores later, once the stack is decided.
4. **Docs convention.** Create `docs/README.md` from `templates/docs-README.md` (skip if present), and `docs/discovery/` and `docs/quality-reports/` with a `.gitkeep` (its presence turns on the plugin's push gate for this project). Per-module docs (`NN-*.md`) are not created now: once a spec exists, dispatch the `docs` agent to create them.
5. **`CLAUDE.md`.** Create from `templates/CLAUDE.md`, filling the project name and one-line description (ask the user if not obvious). If a `CLAUDE.md` exists, append only the sections it lacks.
6. **Knowledge graph.** Only when raw sources or code already exist; otherwise skip and tell the user to run this step after `discovery` gathers them. A corpus of only a few small files gains little from a graph: say so and skip until the sources grow. Already partly set up? Skip 6.1 if `graphify-out/graph.json` exists, skip 6.3 if `CLAUDE.md` already has the graphify section and `.claude/settings.json` has its hooks, skip 6.4 if `.git/hooks/post-commit` exists, and always run 6.5 and step 7.
   1. Build: `/graphify .` (first build uses the LLM on docs/papers; confirm with the user when the corpus is large).
   2. **Ask the user before 6.3 and 6.4.** They install persistent hooks (project `.claude/settings.json` hooks, a `CLAUDE.md` section, git post-commit/post-checkout hooks), which the permission system may deny. If it denies, stop and report; never write those hooks by hand to get around it.
   3. `python -m graphify claude install` (graphify section in `CLAUDE.md` and PreToolUse hooks in the project `.claude/settings.json`).
   4. `python -m graphify hook install` (git hooks keep the graph fresh after commits, AST-only).
   5. Fix-ups, after 6.3 and 6.4. If `which graphify` finds nothing, make the commands use `python -m graphify`; because the graph is git-ignored, drop the merge driver:
      ```bash
      sed -i -E 's/(^|[^m] )graphify (query|path|explain|update)/\1python -m graphify \2/g; s/`graphify (query|path|explain|update)/`python -m graphify \1/g' CLAUDE.md
      sed -i -E 's/"command": "graphify /"command": "python -m graphify /' .claude/settings.json
      sed -i '/graphify-out\/graph.json merge=graphify/d' .gitattributes; [ -s .gitattributes ] || rm .gitattributes
      git config --local --unset-all merge.graphify.name; git config --local --unset-all merge.graphify.driver
      ```
7. **Verify with evidence**, then report each result: the plugin is enabled for this repo (`claude plugin list` shows `pipeline@linden-plugins` enabled); `git check-ignore graphify-out/graph.json` prints the path; `git status` shows only intended new files; if step 2 installed it, `.git/hooks/pre-push` contains `secretscan-managed`. If 6.3 and 6.4 ran, also: `.claude/settings.json` parses as JSON and its hook commands start with `python -m graphify`; `python -m graphify --help` exits 0; `git config --local --get-regexp merge` prints nothing. If they did not run, say so.
8. **Hand off.** State the pipeline and ask whether to start `discovery` now: discovery → brainstorming → writing-plans → dev/db → docs + reviewers → gate (quality report). The `manager` skill runs everything from the plan onward and keeps the ledger that syncs the agents.

## Notes
- The plugin is enabled per repo (`--scope local`), never globally, so repos that do not enable it never load the agents, skills or hook. Enabling the plugin is the only per-project switch.
- Everything a template contains is project-agnostic. Stack rules (ORM choice, test policy, deploy target) belong in the project's own `CLAUDE.md` after brainstorming decides them.
