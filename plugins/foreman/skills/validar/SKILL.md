---
name: validar
description: Use before the gate in supervised mode, when the user is back from autonomous mode, at approval 2, or when they ask to validate or review the decisions taken on their behalf. Walks the delivery's VALIDAR list one item at a time and records each answer in the ledger. Triggers on "validar", "validar decisões", "o que você decidiu", "revisar VALIDAR".
---

# Validar

Each VALIDAR item is a decision the manager took on the user's behalf (`note --validar`, mostly in autonomous mode). This skill asks the user about each one and records the answer, so approval 2 does not rest on a list read from memory.

1. Run `sh "${CLAUDE_PLUGIN_ROOT}/hooks/python.sh" "${CLAUDE_PLUGIN_ROOT}/skills/manager/ledger.py" status --json` and take the `validar` items whose `decision` is null, then those of each delivery in preparation (`next`, each with its `ledger`). None: say so and stop. For a delivery in preparation or an earlier stacked one, every `ledger.py` call of this skill names its ledger before the command: `ledger.py --ledger <its ledger> <command>`.
2. Ask about them in order with `AskUserQuestion`, one question per item and up to four per call. Each question says, in plain words, what was decided, why, where the user sees it (a screen, a file, a test) and the item's `recommend`. Options: **Confirm**, **Change**, **Later**, the one the recommendation points to first and marked as recommended; after a Change, ask what to change.
3. Record each answer with `ledger.py validate --id <id> --decision '<text>'`:
   - Confirm: `confirmed by the user`.
   - Change: `changed by the user: <their words, quoted>`. The change goes back to the delivery through the `manager`: a `fix-N` task of the current cycle, which goes through the reviewer and the gate again, or a product decision for a later delivery. Never edit code here.
   - Later: record nothing; the item stays on the list.
4. End with one line per item: confirmed, changed (with the task it became) or left for later.

Never record a decision the user did not give.
