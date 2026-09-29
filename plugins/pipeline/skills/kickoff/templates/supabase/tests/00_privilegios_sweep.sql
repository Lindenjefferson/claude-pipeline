begin;
create extension if not exists pgtap with schema extensions;
select no_plan();

create temp table allowed_execute (grantee name not null, signature text not null) on commit drop;

-- ALLOWLIST: exact signatures of functions each role may call, e.g. 'public.create_item(text, uuid)'
insert into allowed_execute (grantee, signature)
select 'anon', unnest(array[
]::text[]);
insert into allowed_execute (grantee, signature)
select 'authenticated', unnest(array[
]::text[]);

select is_empty(
  $$ select grantee || ': ' || signature from allowed_execute where to_regprocedure(signature) is null $$,
  'every allowlisted signature resolves to an existing function'
);
select is_empty(
  $$ select a.grantee || ': ' || a.signature from allowed_execute a
     where to_regprocedure(a.signature) is not null
       and not has_function_privilege(a.grantee, to_regprocedure(a.signature)::oid, 'execute') $$,
  'every allowlisted function is executable by its role'
);

-- why: has_function_privilege sees the effective privilege, including EXECUTE inherited from PUBLIC
select is_empty(
  $$ select r.role || ': ' || p.oid::regprocedure::text
     from pg_proc p
     join pg_namespace n on n.oid = p.pronamespace
     cross join unnest(array['anon', 'authenticated']::name[]) as r(role)
     where n.nspname = 'public'
       and not exists (select 1 from pg_depend d where d.classid = 'pg_proc'::regclass and d.objid = p.oid and d.deptype = 'e')
       and has_function_privilege(r.role, p.oid, 'execute')
       and not exists (select 1 from allowed_execute a where a.grantee = r.role and to_regprocedure(a.signature) = p.oid::regprocedure) $$,
  'anon and authenticated execute only allowlisted functions (exact signature)'
);

select is_empty(
  $$ select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public' and c.relkind in ('r', 'p') and not c.relrowsecurity $$,
  'every public table has RLS enabled'
);
select is_empty(
  $$ select c.relname || ': ' || p.priv from pg_class c join pg_namespace n on n.oid = c.relnamespace
     cross join unnest(array['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN']) as p(priv)
     where n.nspname = 'public' and c.relkind in ('r', 'p', 'v', 'm', 'f') and has_table_privilege('anon', c.oid, p.priv) $$,
  'anon has no privilege on public tables and views'
);
select is_empty(
  $$ select c.relname || ': ' || p.priv from pg_class c join pg_namespace n on n.oid = c.relnamespace
     cross join unnest(array['TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN']) as p(priv)
     where n.nspname = 'public' and c.relkind in ('r', 'p') and has_table_privilege('authenticated', c.oid, p.priv) $$,
  'authenticated has no truncate, references, trigger or maintain on public tables'
);
select is_empty(
  $$ select c.relname || ': ' || p.priv from pg_class c join pg_namespace n on n.oid = c.relnamespace
     cross join unnest(array['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN']) as p(priv)
     where n.nspname = 'public' and c.relkind in ('v', 'm') and has_table_privilege('authenticated', c.oid, p.priv) $$,
  'authenticated only reads public views'
);
select is_empty(
  $$ select r.role || ': ' || c.relname || ': ' || p.priv from pg_class c join pg_namespace n on n.oid = c.relnamespace
     cross join unnest(array['USAGE', 'SELECT', 'UPDATE']) as p(priv)
     cross join unnest(array['anon', 'authenticated']::name[]) as r(role)
     where n.nspname = 'public' and c.relkind = 'S' and has_sequence_privilege(r.role, c.oid, p.priv) $$,
  'anon and authenticated have no privilege on public sequences'
);

select * from finish();
rollback;
