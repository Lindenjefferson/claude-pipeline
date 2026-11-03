# General checklist: auth and sessions

Slice of `general.md` (its first paragraph says how an item is read and when it applies): the product has accounts or sessions.

## Auth and sessions
- **No channel reveals whether an account exists** — attackers enumerate users through signup, invite and password reset. Verify: response text, status, state visible to the actor, response time (slow work like sending mail runs off the response path) and rate-limit responses are the same for existing and unknown accounts, or the spec records the accepted risk.
- **Confirming an address is not logging in, and does not keep a password someone else set** — a pre-registered account would otherwise be taken over. Verify: confirmation creates no session; a password set before the owner confirmed is discarded.
- **Sessions follow credential changes** — a stolen session must not outlive a password change, and a recovery session may only set a new password. Verify: other sessions end after the change; sensitive actions need a normal or fresh login; checks that matter read current state rather than a still-valid token.
- **Rate limits are per account or client, not only per server address** — server-side calls share one address, so one user can exhaust the limit for all. Verify: the limiter key and the tested limit-error path, which must not become an oracle.
