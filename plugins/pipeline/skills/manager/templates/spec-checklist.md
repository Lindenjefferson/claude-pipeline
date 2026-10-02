# Spec checklist

A spec answers every section below. Write "not applicable" with the reason instead of leaving a section out. The reviewer, in spec mode, treats a missing answer as a finding.

## 1. Sensitive writes and audit trail
For every write to roles, permissions, memberships, invites, credentials or money:
- Who (actor id), when (the event's own timestamp), what changed (before and after values).
- Where it is stored, who can read it, retention; append-only for every role, administrative ones included.
- Failure paths: which errors surface to the user, which are logged, none swallowed.

## 2. Domain rules
- **Money**: unit (cents or decimal and its precision), rounding rule and where it applies, the largest value of every stored and derived amount.
- **Time**: "today" is an input to the rules, never read inside them; dates are stored in one zone and converted at the edge; the user's timezone.
- **Identity**: how names and e-mails are normalized (trim, case, accents) before comparing or storing.
Each rule has tests at both boundaries.

## 3. Invariants, concurrency and locks
- Each invariant (limits, last admin, uniqueness across rows, hierarchy rules) and where it is enforced: in the data layer when breaking it would break reading the data.
- Each check that reads one row and writes another: its lock, the global lock order, and the two-session test in both orders.
- Shared, editable records: how a stale edit is detected and what the user sees.
- Multi-field state transitions: the single atomic write that performs each one.
- Behavior of concurrent calls and of partial failure.

## 4. UI states (per screen)
- Loading, empty, error (a specific message per failure the user can provoke, shown where it happens), success.
- Destructive actions: confirmation, copy, focus after close.
- The project's layout requirements (widths, touch targets, overflow), each to be asserted in the screen's e2e; keyboard order; what live regions announce.
- What happens to typed values after a validation error (never the password).

## 5. Auth (when the spec touches accounts or sessions)
- Account-existence oracles: for signup, invite and reset, confirm text, status, visible state, timing and rate-limit responses are identical; or record the accepted residual risk.
- Pre-registration: who sets the password of an account created before its owner confirmed; confirming discards a password set by someone else.
- Confirmation ≠ login: whether confirming creates a session (it should not).
- Sessions after a password change, recovery-session scope, reauthentication for sensitive actions, how long an issued token stays valid.
- Rate limits: which are shared by the server's address and what the user sees when one trips.

## 6. Privileges and defaults
- For each server function or endpoint: who may call it (exact signature); closed to everyone else.
- For each table or collection: access per role, the access rules and their negative cases.
- Code that runs with elevated privileges: why it needs them, and that it resolves nothing from the caller's context.
- Every new flag or config defaults to closed.

## 7. Error codes and messages
A table: code | when it happens | status or return | user-facing message | logged? Codes must not act as oracles (section 5).

## 8. Test plan
- Per rule or policy: the test that proves it, including the negative case and the boundary (n-1, n, n+1; both edges of time windows; the limit of every derived value).
- Null or empty for every argument.
- Mutation targets: the guards whose loosening must turn a test red (locks, access rules, limits, invariants, audit calls, permission checks).
- What cannot be automated and how it is verified by hand.
