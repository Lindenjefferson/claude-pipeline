---
name: atualizar
description: Use when the user asks to update the pipeline plugin in a project ("atualizar o plugin", "atualiza o plugin aqui", "update pipeline"). Updates only at a stop point of the delivery, then, in a new session on the new version, brings the project's files up to it: the templates' missing sections and lines, the allowlist and each skipped version's upgrade notes. Triggers on "atualizar", "atualizar o plugin", "update the plugin".
---

# Atualizar

A new plugin version loads only in a new session, so this skill runs in two halves, and `.superpowers/atualizar.json` (git-ignored) carries the versions from one to the other.

## In the running session
1. **Stop point.** Run `sh "${CLAUDE_PLUGIN_ROOT}/hooks/python.sh" "${CLAUDE_PLUGIN_ROOT}/skills/manager/ledger.py" status --json`. When a claim is in flight and the delivery is not paused, stop: tell the user to let the running agents report or to pause the delivery (`pause` in the manager), then ask again. No ledger, or nothing in flight, is a stop point.
2. **Versions.** The running one is in `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json`; the scope of this project's install comes from `claude plugin list --json`.
3. **Update.** `claude plugin update pipeline@linden-plugins --scope <that scope> --json`. A command the marketplace declares is shown to the user to confirm; never pass `-y` or `--accept-command` on your own. Already on the latest: say so and run the second half here.
4. **Hand over.** Write `{"from": "<old>", "to": "<new>"}` to `.superpowers/atualizar.json`. Then open a session in the project folder as `${CLAUDE_PLUGIN_ROOT}/skills/manager/references/sessions.md` says and brief it to run this skill, or ask the user to restart Claude Code here and ask again. This session starts nothing more.

## In the new session (`.superpowers/atualizar.json` exists and the running version is its `to`)
5. **Notes.** Read `${CLAUDE_PLUGIN_ROOT}/UPGRADING.md`: the note of every version after `from` up to `to`, oldest first.
6. **Kickoff.** Run the `kickoff` skill. It appends the templates' missing sections and lines and runs its allowlist step again, as it does for any existing project.
7. **Manual steps.** Apply each step of those notes that the kickoff does not cover, in the project's own files. Ask the user, in one list, about the steps that need a decision.
8. **Report and clean up.** Give the versions, what was added (a placeholder line keeps the plugin's default until filled) and the decisions still waiting, then delete `.superpowers/atualizar.json`. When the delivery is paused, `resume` in the manager comes next.
