# Spec checklist

A spec answers every section below. Write "not applicable" with the reason instead of leaving a section out. The reviewer, in spec mode, treats a missing answer as a finding. The plan answers sections 1 and 2 for every write operation even when there is no spec.

## 1. Pre-mortem per write operation
For every operation that creates, changes or deletes data that another actor or a later read uses (a record, a file, saved state), answer each question; a question about something the product does not have (accounts, a server, a second user) is answered "n/a" with the reason; every answer becomes acceptance criteria, positive and negative, written as Given/When/Then:
- **Who can** do it, and who cannot (role, owner, tenant)? What happens when someone without permission, from another tenant, or calling the server directly tries?
- **On which rows?** Does it touch every row it should (all the affected ones, not only those the actor can see), and does it check how many it changed?
- **What it references** (a category, a person, an account): what if that item is hidden, inactive, removed or deleted? Editing must keep the record's current value even when it is no longer selectable.
- **Two at once:** what if two people do it, or this and a conflicting operation, at the same time?
- **Derived values:** the limit of every value it computes (sum, product, count, concatenation), not only of what is typed.
- **Each failure:** what the user sees for each one (specific message, where, what stays typed).
- **Validate before writing:** what is already written if the next validation refuses? Validation and permission come before any write; what must happen together is one atomic operation.
- **The past:** what it changes in history, balances, totals or reports already shown.

## 2. Technical assumptions
Every behavior of a framework, library, database or service the design relies on (how a form resets, what a lock covers, what a function already in the code does): listed, and each proven by a throwaway spike of minutes before the plan uses it as code. A disproved assumption changes the design before the plan.

## 3. Sensitive writes and audit trail
For every write to roles, permissions, memberships, invites, credentials or money:
- Who (actor id), when (the event's own timestamp), what changed (before and after values).
- Where it is stored, who can read it, retention; append-only for every role, administrative ones included.
- Failure paths: which errors surface to the user, which are logged, none swallowed.

## 4. Domain rules
- **Money**: unit (cents or decimal and its precision), rounding rule and where it applies, the largest value of every stored and derived amount.
- **Time**: "today" is an input to the rules, never read inside them; dates are stored in one zone and converted at the edge; the user's timezone.
- **Identity**: how names and e-mails are normalized (trim, case, accents) before comparing or storing.
Each rule has tests at both boundaries.

## 5. Invariants, concurrency and locks
- Each invariant (limits, last admin, uniqueness across rows, hierarchy rules) and where it is enforced: in the data layer when breaking it would break reading the data.
- Each check that reads one row and writes another: its lock, the global lock order, and the two-session test in both orders.
- Shared, editable records: how a stale edit is detected and what the user sees.
- Multi-field state transitions: the single atomic write that performs each one.
- Behavior of concurrent calls and of partial failure.

## 6. UI states (per screen)
- Loading, empty, error (a specific message per failure the user can provoke, shown where it happens), success.
- The data states each screen shows differently (zero or negative, an old record, an optional field filled in): the plan lists them per screen, so qa captures each from the cycle's first run.
- Destructive actions: confirmation, copy, focus after close.
- The project's layout requirements (widths, touch targets, overflow), each to be asserted in the screen's automated interface test; keyboard order; what live regions announce.
- What happens to typed values after a validation error (never the password).

## 7. Auth (when the spec touches accounts or sessions)
- Account-existence oracles: for signup, invite and reset, confirm text, status, visible state, timing and rate-limit responses are identical; or record the accepted residual risk.
- Pre-registration: who sets the password of an account created before its owner confirmed; confirming discards a password set by someone else.
- Confirmation ≠ login: whether confirming creates a session (it should not).
- Sessions after a password change, recovery-session scope, reauthentication for sensitive actions, how long an issued token stays valid.
- Rate limits: which are shared by the server's address and what the user sees when one trips.

## 8. Privileges and defaults
- For each server function or endpoint: who may call it (exact signature); closed to everyone else.
- For each table or collection: access per role, the access rules and their negative cases.
- Code that runs with elevated privileges: why it needs them, and that it resolves nothing from the caller's context.
- Every new flag or config defaults to closed.

## 9. Error codes and messages
A table: code | when it happens | status or return | user-facing message | logged? Codes must not act as oracles (section 7).

## 10. Test plan
- Acceptance criteria as Given/When/Then, the negative ones included, each with an id (`AC-<task>-<n>` once the plan exists) that the test proving it carries in its name.
- Permissions as a matrix (role × resource × action × relationship to the record), every cell tested, not a sample.
- Per rule or policy: the test that proves it, including the negative case and the boundary (n-1, n, n+1; both edges of time windows; the limit of every derived value).
- Null or empty for every argument.
- Mutation targets: the guards whose loosening must turn a test red (locks, access rules, limits, invariants, audit calls, permission checks).
- What cannot be automated and how it is verified by hand.

## 10. Stack (a new project)
- The constraints the choice depends on (platform and devices, data, offline use, where it runs, cost, users, what the user knows) and the candidates considered, each with its pros and cons against them (the `discovery` lays them out).
- The stack the user chose and why, with its versions as checked in the official sources (never from memory); the plan repeats it under `## Product decisions`, for approval 1.
- The verification it needs (tests, type check, lint, interface tests when there are screens), which the first task turns into the "Comandos" lines of the project's `CLAUDE.md`.
