---
name: validar
description: Use when the user is back from autonomous mode, at approval 2, or when they ask to validate or review the decisions taken on their behalf. Walks the delivery's VALIDAR list one item at a time and records each answer in the ledger. Triggers on "validar", "validar decisões", "o que você decidiu", "revisar VALIDAR".
---

# Validar

Each VALIDAR item is a decision the manager took on the user's behalf (`note --validar`, mostly in autonomous mode). This skill asks the user about each one and records the answer, so approval 2 does not rest on a list read from memory.

1. Run `python "${CLAUDE_PLUGIN_ROOT}/skills/manager/ledger.py" status --json` (with `--ledger .superpowers/ledger-<slug>.jsonl` for an earlier stacked delivery) and take the `validar` items whose `decision` is null. None: say so and stop.
2. Ask about them in order, up to four items per question round, one question per item. Each question says, in plain words, what was decided, why, and where the user sees it (a screen, a file, a test). Options: **Confirm**, **Change** (the user says what), **Later**.
3. Record each answer with `ledger.py validate --id <id> --decision '<text>'`, quoting the user:
   - Confirm: `confirmed by the user`.
   - Change: `changed by the user: <their words>`. The change goes back to the delivery through the `manager`: a `fix-N` task of the current cycle, or a product decision for the next one. Never edit code here.
   - Later: record nothing; the item stays on the list.
4. End with one line per item: confirmed, changed (with the task it became) or left for later.

Never record a decision the user did not give.
