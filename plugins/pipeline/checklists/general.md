---
stack: general
paths: ["**"]
---

# General checklist

Each item: the check — why — how to verify. An unmet item is a finding, with evidence like any other.

- **Sensitive writes leave a trail** — a disputed change to money, roles, permissions, memberships or invites cannot be explained without one. Verify: each such write records who, when, before and after, in a queryable table (not a console log).
- **No swallowed errors on write paths** — a silent failure looks like success to the user. Verify: every `catch` on a write logs with context or returns the error to the caller.
- **Fixes that land together are tested together** — two fixes on the same route, screen or state can undo each other. Verify: after a round with several fixes, a test or check exercises their combination.
- **Files are UTF-8** — Latin-1 text breaks tests and diffs on other machines. Verify: new and changed text files decode as UTF-8.
