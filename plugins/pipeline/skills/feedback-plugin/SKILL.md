---
name: feedback-plugin
description: Use at the end of a delivery, or when the user asks for feedback on the pipeline plugin, to write the request for the plugin's own session from what the delivery showed (metrics, frictions with the plugin, lessons that could become general rules), each item with its evidence. Writes .superpowers/pedido-plugin.md and sends it only when the user asks. Triggers on "feedback do plugin", "pedido para o plugin", "feedback-plugin".
---

# Plugin feedback

The plugin takes delivery feedback only as general rules that hold in any stack. This skill turns one delivery into that request, so it is not rebuilt by hand from scattered notes.

1. **Read**, without changing anything:
   - `sh "${CLAUDE_PLUGIN_ROOT}/hooks/python.sh" "${CLAUDE_PLUGIN_ROOT}/skills/manager/ledger.py" status --json`: metrics (findings per cycle and origin, fix rounds, spec and plan review rounds, time and tokens per agent and task, lines changed per task and the share of `fix-N` and `cleanup`), notes, waivers, deferred items with their decisions, lessons.
   - The delivery's quality report in `docs/quality-reports/`, and the lines its branch added to `docs/lessons.md` (`git diff <base>..HEAD -- docs/lessons.md`, with the base from `status`).
   - A file of frictions noted during the delivery, if the project keeps one (for example `.superpowers/plugin-feedback.md`).
   - The plugin version, from `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json`.
2. **Keep what the plugin can act on**: a step of the flow that stalled, was skipped or was done twice; a check of the gate, the ledger or a hook that missed a defect or blocked a correct change; an agent instruction that was ignored or misread; where the time or the tokens went, when a flow change would cut it. A lesson about the stack or about this project stays in the project: leave it out, with one line saying so. An item the plugin already answered (a version, on hold or refused) is left out with no line and removed from the frictions file: its destination is in the plugin's history and roadmap. A lesson that repeats one learned in another project (seen there, or the user says so) is marked as a candidate principle for `checklists/general.md`.
3. **Write `.superpowers/pedido-plugin.md`** in the user's language, with these sections:
   - **Context**: the delivery slug, the plugin version, the mode (supervised or autonomous).
   - **Metrics**: one short table from the ledger, beside the same numbers of the previous delivery, per task and per cycle (`ledger.py --ledger .superpowers/ledger-<slug>.jsonl status --json`), with the delivery's clock (`metrics.time.delivery`) and the gate's warnings from the quality report; then, for each "Número:" of the installed version's section of `${CLAUDE_PLUGIN_ROOT}/UPGRADING.md`, its value in this delivery, or why it cannot be read.
   - **Items**, numbered: the problem, its evidence and the general rule proposed.
   - **Left out**: what was left out and why, one line each.
   The file leaves the project: evidence is ledger text, paths relative to the project and measured numbers, never product content, real data or credentials.
4. Tell the user the path, and that they bring it to the plugin's session. Never send it on your own: only when the user asks, to the session they name (`SendMessage`, the file's path and a one-line summary). Never open or change the plugin's repository.
