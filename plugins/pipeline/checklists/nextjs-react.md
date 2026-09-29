---
stack: nextjs-react
paths: ["app/**", "src/**", "components/**", "lib/**", "**/*.tsx", "**/*.jsx", "**/actions.ts", "**/actions/**", "**/*.actions.ts", "**/*-actions.ts", "**/page.tsx", "**/layout.tsx", "**/route.ts", "**/*redirect*", "**/*redirect*/**", "**/*callback*/**", "proxy.ts", "middleware.ts", "next.config.*"]
---

# Next.js / React checklist

Each item: the check — why — how to verify. An unmet item is a finding, with evidence like any other.

## Framework versions
- **Next 16 uses `proxy.ts`** (exported `proxy`) instead of `middleware.ts` — a plan written from memory gets names and flags wrong. Verify: the file and export match the installed version (`npm ls next`); scaffold commands were checked with `npm view` or current docs.
- **`agentRules: false` in `next.config`** on Next ≥ 16 — otherwise `next dev` rewrites the versioned `CLAUDE.md`. Verify: the key is set and `git status` is clean after `next dev`.

## Server boundaries
- **Server Actions re-check auth, authorization and input** — an action is a public endpoint no matter which page renders the form. Verify: each action reads the user server-side, checks scope (tenant, role) and validates input before writing.
- **Page-level guards, not only layouts** — layouts do not re-run on every navigation and do not protect actions or route handlers. Verify: each protected page (or the proxy) enforces access.
- **`cache()` for per-request lookups** — React `cache()` dedupes `getUser`/session reads within one request; it is not a cross-request cache. Verify: no module-level memo holds user data.
- **`after()` for timing-sensitive sends** — sending mail inline makes response time reveal state (see auth checklist). Verify: the response returns before the send.
- **No secrets in the client** — `NEXT_PUBLIC_*` and server-only modules imported from client components leak. Verify: grep for `NEXT_PUBLIC_` values and `"use client"` files importing server code.

## Forms (React 19)
- **Form reset after an action** — React 19 resets uncontrolled fields after a form action, so a validation error wipes what the user typed. Verify: the action state echoes submitted values into `defaultValue` (with a `key` to remount) or the inputs are controlled; passwords are never echoed.

## Open redirects
- **Redirect sanitizer tested against normalizing forms** — `/.//evil.com` and `/a/..//evil.com` normalize to `//evil.com`. Verify: tests cover `//x`, `/\x`, `/./`, `/.//x`, `/a/..//x`, `%2F%2F`, `javascript:`; the check resolves with `new URL(next, origin)` and compares the origin.

## UI and accessibility
- **44px touch targets everywhere** — shadcn/Radix defaults are smaller, including RadioGroup items, Select items, Checkbox, DropdownMenu items and icon buttons. Verify: computed size or classes on each primitive used.
- **AlertDialog opened from a DropdownMenuItem** — the closing menu unmounts the dialog or leaves `pointer-events: none` on `body`. Verify: the item uses `onSelect={(e) => e.preventDefault()}` or the dialog is controlled outside the menu, and focus returns to the trigger.
- **Persistent `aria-live` regions** — a region inserted together with its text is not announced. Verify: the region is mounted (empty) before the message changes.
- **Focus after unmount** — when the focused element disappears (row deleted, dialog closed, step changed) focus falls to `body`. Verify: focus moves explicitly to a stable target.
- **All states present** — loading, empty, error, destructive confirmation, 360px width. Verify: each state renders and is reachable.
