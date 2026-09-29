---
stack: auth
paths: ["**/*auth*", "**/*auth*/**", "**/*login*", "**/*login*/**", "**/*signup*", "**/*signup*/**", "**/*password*", "**/*password*/**", "**/*session*", "**/*invite*", "**/*invite*/**", "proxy.ts", "middleware.ts", "supabase/config.toml"]
agents: [security, code-review, audit]
---

# Auth checklist

Each item: the check — why — how to verify. An unmet item is a finding, with evidence like any other. Decide the trade-offs here in the spec, not in review rounds.

## Account-existence oracles
- **No channel reveals whether an email has an account** — attackers enumerate users through signup, invite and password reset. Verify every channel: response text, HTTP status, state the inviter can see, response time, and rate-limit codes (a per-email 429 only for existing accounts).
- **Supabase-specific channels** — admin APIs return 422 `user_already_exists`; public `signUp` returns a fake user with `identities: []` for an existing email; per-email rate limits and timing differ. Verify: the code never branches visibly on these, or the spec records the accepted residual risk.
- **Timing** — sending mail only for existing accounts makes the response slower. Verify: sends run in `after()` or both paths take the same work.

## Pre-registration and confirmation
- **Pre-registration takeover** — an attacker signs up with the victim's email and a password; when the victim confirms, the attacker's password must not survive. Verify: confirming an account created by an unverified party discards that password and the owner sets their own.
- **Confirmation ≠ login** — a confirmation link proves the address, not the identity of whoever set the password. Verify: confirming does not create a session; the user logs in afterwards.

## Sessions and passwords
- **Sign out other sessions after a password change** — a stolen session must not outlive the change. Verify: `signOut({ scope: 'others' })` (or equivalent) runs after the change.
- **GoTrue `admin.updateUserById` with a password revokes all sessions**, the current one included. Verify: the flow handles the forced re-login instead of showing an error.
- **Recovery session scope** — a session from a recovery link may only set a new password. Verify: other sensitive actions require a normal login or reauthentication.
- **`secure_password_change`** — without it a hijacked session changes the password without the old one or a recent login. Verify: enabled in `supabase/config.toml` (and the hosted project), and the `reauthentication_needed` path is handled in the UI.
- **`jwt_expiry` window** — an access token stays valid until it expires after sign-out or a role change. Verify: checks that matter read current DB state; the expiry is short enough for the risk.

## Rate limits
- **Server-side calls share the server's IP limit** — every user's auth request comes from the same server IP, so one user can exhaust the limit for all. Verify: a per-account or per-client limiter exists and the limit error path is tested and does not itself become an oracle.
