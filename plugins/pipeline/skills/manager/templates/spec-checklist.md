# Spec checklist

A spec answers every section below. Write "not applicable" with the reason instead of leaving a section out. The reviewer, in spec mode, treats a missing answer as a finding.

## 1. Sensitive writes and audit trail
For every write to roles, permissions, memberships, invites, credentials or money:
- Who (actor id), when (`clock_timestamp()`), what changed (before and after values).
- Where it is stored (table), who can read it, retention.
- The audit table is append-only for every role, `service_role` included.
- Failure paths: which errors surface to the user, which are logged, none swallowed.

## 2. UI states (per screen)
- Loading, empty, error (one message per error code), success.
- Destructive actions: confirmation dialog, copy, focus after close.
- 360px width; 44px touch targets; keyboard order; what `aria-live` announces.
- What happens to typed values after a validation error (never the password).

## 3. Concurrency, locks and invariants
- Each invariant (limits, last admin, uniqueness across rows) and the lock that protects it.
- Lock key namespaces and the global lock order.
- Multi-column state transitions: the single statement that performs each one.
- Behavior of concurrent calls and of partial failure.

## 4. Auth (when the spec touches accounts or sessions)
- Account-existence oracles: for signup, invite and reset, confirm text, status, visible state, timing and rate-limit codes are identical; or record the accepted residual risk.
- Pre-registration: who sets the password of an account created before its owner confirmed; confirming discards a password set by someone else.
- Confirmation ≠ login: whether confirming creates a session (it should not).
- Sessions after password change, recovery-session scope, reauthentication (`secure_password_change`), `jwt_expiry` window.
- Rate limits: which are shared by the server IP and what the user sees when one trips.

## 5. Privileges and defaults
- For each function: who may EXECUTE (exact signature); revoked from `public`, `anon`, `authenticated` (and `service_role` for internal helpers) otherwise.
- For each table, view and sequence: grants per role; RLS policies and their negative cases.
- `security definer` functions: why definer is needed; `search_path = ''`.
- Every new flag or config defaults to closed.

## 6. Error codes and messages
A table: code | when it happens | HTTP/status or return | user-facing message | logged? Codes must not act as oracles (section 4).

## 7. Test plan
- Per rule or policy: the test that proves it, including the negative case and the boundary (n-1, n, n+1; both edges of time windows).
- NULL for every RPC argument.
- Mutation targets: the rules whose loosening must turn a test red (policies, checks, guards, scope filters, audit calls, permission checks).
- What cannot be automated and how it is verified by hand.
