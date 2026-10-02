# General checklist

Each item: the check — why — how to verify. An unmet item is a finding, with evidence like any other. Rules for the project's own stack live in its `CLAUDE.md` and `docs/lessons.md`, not here.

## Invariantes (also in spec mode)
- **A rule whose violation breaks reading or rendering the data is enforced in the data layer** — app validation can be bypassed (a direct API call, a script, a second client); it exists to give a good message, not the guarantee. Verify: ask "if someone calls the API directly, does it hold?"; a constraint, trigger or policy enforces it and a test writes the bad value without the app and sees it refused.
- **A check that reads one row and decides to write another is a race until proven otherwise** — two sessions both read the old state and both write. Verify: an explicit lock on what was read (taken in one global order, with namespaced keys when the lock is advisory) and a two-session test in both orders.
- **Validate the value that reaches each column or field, not only the typed one** — a derived value (sum, product, concatenation, count) can overflow a limit that every typed input respects. Verify: each derived value has its own limit and a boundary test at that limit.
- **Tests that measure the UI wait for it to stop moving** — sizes and positions read mid-animation, before fonts or images load, are wrong by a fraction and flaky. Verify: the measurement waits for running animations, fonts and images to finish first.
- **The test environment runs without dev tooling over the UI** — dev overlays and indicators cover controls at small widths. Verify: such tooling is disabled in the test environment; no test works around a covered element with synthetic events or forced clicks.
- **Every layout requirement in the spec is an automatic check in the screen's e2e** — a requirement checked by eye regresses silently. Verify: widths, touch-target sizes and overflow rules the project states are asserted in the e2e of each screen they apply to.

## Access and data
- **Every server entry point re-checks authentication, authorization and input** — an endpoint is public no matter which page calls it, and a shared layout or parent guard does not protect it. Verify: each entry point reads the user server-side, checks scope (tenant, role) and validates input before writing.
- **Privileges default to closed** — anything a new function, table or endpoint gets by default is open until someone notices. Verify: defaults are revoked, access is granted by exact identity (full signature, not a name pattern), and a test sweeps the effective privileges against that allowlist.
- **References between tenant-owned records cannot cross tenants** — a plain reference lets one tenant's row point at another's. Verify: the data layer ties the reference to the same tenant, and a test tries the cross-tenant reference.
- **Code that runs with elevated privileges trusts nothing from the caller's context** — names, paths or settings the caller controls can redirect it. Verify: every object it touches is fully qualified and the caller identity comes from the session, not from input.
- **Shared, editable data has concurrent-edit control** — two people editing the same record silently overwrite each other. Verify: a version or last-modified check refuses the stale write with a specific message, and a test makes the second write stale.
- **State transitions that touch several fields happen in one atomic write** — separate writes expose an intermediate state that checks reject or mishandle. Verify: one statement or one transaction per transition.
- **Applied migrations are never edited** — other machines already ran them. Verify: changes come as a new migration; additive first (nullable, backfill, then tighten).
- **No per-user data in a process-wide cache, and no secret in the client bundle** — one leaks across requests, the other to everyone. Verify: caches are request-scoped; client code imports no server-only module or secret value.

## Tests
- **A write test asserts what was written** — "no error" also passes when a policy silently filtered every row. Verify: the test checks the affected-row count or the resulting state.
- **Every restrictive rule has a negative test** — a rule tested only on the allowed path proves nothing. Verify: an unauthorized actor tries it and is refused.
- **Every important guard is proven by mutation** — a test that stays green when its lock, permission, limit or invariant is loosened is vacuous. Verify: the dev's report shows the guard loosened (rolled-back transaction or reverted edit), the test red, and the guard restored.
- **Empty, null and boundaries** — a `>=`/`>` swap survives tests that avoid the edge, and a null can act as "all". Verify: tests at n-1, n, n+1, both edges of time windows, and null or empty for every argument.
- **Fixes that land together are tested together** — two fixes on the same route, screen or state can undo each other. Verify: after a round with several fixes, a test or check exercises their combination.

## Auth and sessions
- **No channel reveals whether an account exists** — attackers enumerate users through signup, invite and password reset. Verify: response text, status, state visible to the actor, response time (slow work like sending mail runs off the response path) and rate-limit responses are the same for existing and unknown accounts, or the spec records the accepted risk.
- **Confirming an address is not logging in, and does not keep a password someone else set** — a pre-registered account would otherwise be taken over. Verify: confirmation creates no session; a password set before the owner confirmed is discarded.
- **Sessions follow credential changes** — a stolen session must not outlive a password change, and a recovery session may only set a new password. Verify: other sessions end after the change; sensitive actions need a normal or fresh login; checks that matter read current state rather than a still-valid token.
- **Rate limits are per account or client, not only per server address** — server-side calls share one address, so one user can exhaust the limit for all. Verify: the limiter key and the tested limit-error path, which must not become an oracle.

## Web and UI
- **Redirect targets are checked after normalization** — `/.//evil.com` and `/a/..//evil.com` normalize to `//evil.com`. Verify: the target is resolved against the app origin and the origin compared; tests cover `//x`, `/\x`, `/./`, `/.//x`, `/a/..//x`, `%2F%2F`, `javascript:`.
- **A predictable failure never becomes a generic error** — "something went wrong" for a case the user can provoke leaves them stuck. Verify: each such failure (validation, conflict, limit, permission) shows a specific message next to where it happened and keeps what the user typed (never a password).
- **All states present and accessible** — loading, empty, error, destructive confirmation; focus moves to a stable target when the focused element disappears; a live region is mounted before its message changes. Verify: each state renders and is reachable by keyboard.

## Audit and errors
- **Sensitive writes leave a trail** — a disputed change to money, roles, permissions, memberships or invites cannot be explained without one. Verify: each such write records who, when, before and after, in a queryable store (not a console log), ordered by the event's own timestamp rather than the transaction's, and append-only for every role, administrative ones included.
- **No swallowed errors on write paths** — a silent failure looks like success to the user. Verify: every `catch` on a write logs with context or returns the error to the caller.
- **Files are UTF-8** — Latin-1 text breaks tests and diffs on other machines. Verify: new and changed text files decode as UTF-8.
