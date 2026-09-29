revoke all on all tables in schema public from anon;
revoke truncate, references, trigger, maintain on all tables in schema public from authenticated;
revoke all on all sequences in schema public from anon, authenticated;
revoke execute on all functions in schema public from public, anon, authenticated;

alter default privileges in schema public revoke all on tables from anon;
alter default privileges in schema public revoke truncate, references, trigger, maintain on tables from authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;
alter default privileges in schema public revoke execute on functions from anon, authenticated;

-- why: PUBLIC's EXECUTE on new functions is a global default a per-schema revoke cannot remove; every function migration revokes it explicitly
-- revoke execute on function public.<name>(<arg types>) from public, anon, authenticated;
-- grant execute on function public.<name>(<arg types>) to authenticated;

-- why: default privileges cannot tell views from tables, so each view is made read-only where it is created (and runs RLS as the caller)
-- create view public.<name> with (security_invoker = true) as ...;
-- revoke insert, update, delete, truncate, references, trigger, maintain on public.<name> from authenticated;

-- why: RLS does not apply to materialized views or foreign tables, so clients get no privilege on them at all
-- revoke all on public.<name> from anon, authenticated;
