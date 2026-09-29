---
stack: postgres-supabase
paths: ["supabase/**", "**/*.sql"]
agents: [db, security, code-review, audit]
---

# Postgres / Supabase checklist

Each item: the check — why — how to verify. An unmet item is a finding, with evidence like any other.

## RLS tests (pgTAP)
- **Every write under RLS asserts the affected-row count** — `lives_ok` passes when the policy silently filters every row. Verify: the test checks `row_count` (helper with `get diagnostics`) or the resulting state, not only "no error".
- **Every restrictive policy has a negative test** — an admin-only rule with only positive tests proves nothing. Verify: a non-authorized role tries the read/write and the test asserts zero rows or the expected error.
- **Mutation check on policies, checks and guards** — tests that stay green when the rule is loosened are vacuous. Verify: loosen each rule (policy to `true`, guard removed) in a rolled-back transaction or temporary edit, run the suite, see red; the implementer reports a mutation → failing test table, and `code-review` runs its own mutations.
- **No data-modifying `WITH` inside `is()` / `results_eq()`** — Postgres rejects it (must be top level). Verify: writes run as top-level statements or via a helper, and the assertion reads the result afterwards.

## Privileges
- **Revoke default EXECUTE** — Supabase grants EXECUTE on new functions to `PUBLIC`, `anon` and `authenticated`. Verify: every function has `revoke execute ... from public, anon, authenticated` (plus `service_role` for internal helpers) and grants back only what the API calls; `alter default privileges` covers future functions.
- **Effective-privilege sweep** — reading grants misses inherited and default privileges. Verify: a pgTAP test loops over functions with `has_function_privilege(role, oid, 'EXECUTE')` for `anon`, `authenticated` and `public`, and over relations with `has_table_privilege` / `has_sequence_privilege`, including relkind `S` (sequences), views, `TRUNCATE`, `TRIGGER`, `REFERENCES` and PG17 `MAINTAIN`.
- **Allowlist by exact signature** — a name-based allowlist also admits every overload. Verify: the sweep compares `oid::regprocedure::text` (e.g. `public.f(uuid, text)`).
- **`security definer` hardening** — a mutable `search_path` lets a caller shadow objects. Verify: `set search_path = ''`, every object schema-qualified, caller read via `(select auth.uid())` (also in policies, evaluated once per statement).

## Triggers and state
- **`update of col` triggers need `when (old.col is distinct from new.col)`** — they fire on any UPDATE that lists the column, even with an unchanged value. Verify: the trigger definition has the WHEN clause and a test updates the column to the same value.
- **Multi-column state transitions in one UPDATE** — separate UPDATEs expose an intermediate state that checks and triggers reject or mis-handle. Verify: every transition that touches several columns is a single statement.

## Concurrency
- **Every limit or invariant takes a lock** — "max N per user" or "last admin" checks race without one. Verify: `select ... for update` (ordered by id) or an advisory lock before the check.
- **Namespaced lock keys and one global lock order** — bare advisory keys collide across features; inconsistent order deadlocks. Verify: keys use a namespace (two-int form or `hashtext('ns:' || id)`) and the spec/doc states the order, which every function follows.

## Inputs
- **NULL arguments to RPCs** — `x <> y` with NULL yields NULL and skips `if` guards; NULL may act as "all" or a destructive default. Verify: explicit `is null` checks or `is distinct from`, and a test per argument passing NULL.
- **Boundaries** — a `>=` / `>` swap survives tests that avoid the edge. Verify: tests at n-1, n, n+1 and both edges of time windows.

## Multi-tenant integrity
- **Composite FKs `(household_id, x_id)`** — a single-column FK lets a row reference another tenant's row. Verify: parent has `unique (household_id, id)`, child FK is composite.
- **`on delete set null (x_id)`** (PG15+) on composite FKs — plain `set null` also nulls the tenant column. Verify: the column list is present.

## Audit tables
- **Order with `clock_timestamp()`** — `now()` is the transaction start, so events in one transaction tie. Verify: audit default/insert uses `clock_timestamp()`.
- **Append-only even for `service_role`** — service_role holds table grants by default. Verify: UPDATE, DELETE, TRUNCATE and TRIGGER revoked from every role including `service_role`, a trigger rejecting UPDATE/DELETE, and tests that each is refused.
