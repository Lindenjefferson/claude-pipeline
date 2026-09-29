begin;
create extension if not exists pgtap with schema extensions;
select no_plan();

create temp table exposed_schemas (nspname name primary key) on commit drop;
create temp table allowed_execute (grantee name not null, signature text not null) on commit drop;

-- ALLOWLIST: every schema the API exposes (Data API "Exposed schemas"), then the exact signatures
-- of functions each role may call, e.g. 'public.create_item(text, uuid)'
insert into exposed_schemas (nspname) values ('public');
insert into allowed_execute (grantee, signature)
select 'anon', unnest(array[
]::text[]);
insert into allowed_execute (grantee, signature)
select 'authenticated', unnest(array[
]::text[]);

select is_empty(
  $$ select e.nspname from exposed_schemas e where to_regnamespace(e.nspname) is null $$,
  'every listed schema exists'
);
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
     where n.nspname in (select nspname from exposed_schemas)
       and not exists (select 1 from pg_depend d where d.classid = 'pg_proc'::regclass and d.objid = p.oid and d.deptype = 'e')
       and has_function_privilege(r.role, p.oid, 'execute')
       and not exists (select 1 from allowed_execute a where a.grantee = r.role and to_regprocedure(a.signature) = p.oid::regprocedure) $$,
  'anon and authenticated execute only allowlisted functions (exact signature)'
);

select is_empty(
  $$ select n.nspname || '.' || c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
     where n.nspname in (select nspname from exposed_schemas) and c.relkind in ('r', 'p') and not c.relrowsecurity $$,
  'every exposed table has RLS enabled'
);
select is_empty(
  $$ select n.nspname || '.' || c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
     where n.nspname in (select nspname from exposed_schemas) and c.relkind = 'v'
       and not exists (select 1 from pg_depend d where d.classid = 'pg_class'::regclass and d.objid = c.oid and d.deptype = 'e')
       and not exists (select 1 from unnest(coalesce(c.reloptions, '{}'::text[])) as o(opt)
                       where lower(o.opt) in ('security_invoker=true', 'security_invoker=on', 'security_invoker=1', 'security_invoker=yes')) $$,
  'every exposed view runs as the caller (security_invoker=true)'
);
select is_empty(
  $$ select n.nspname || '.' || c.relname || ': ' || p.priv from pg_class c join pg_namespace n on n.oid = c.relnamespace
     cross join unnest(array['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN']) as p(priv)
     where n.nspname in (select nspname from exposed_schemas) and c.relkind in ('r', 'p', 'v', 'm', 'f') and has_table_privilege('anon', c.oid, p.priv) $$,
  'anon has no privilege on exposed tables, views, materialized views and foreign tables'
);
select is_empty(
  $$ select n.nspname || '.' || c.relname || ': ' || p.priv from pg_class c join pg_namespace n on n.oid = c.relnamespace
     cross join unnest(array['TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN']) as p(priv)
     where n.nspname in (select nspname from exposed_schemas) and c.relkind in ('r', 'p', 'f') and has_table_privilege('authenticated', c.oid, p.priv) $$,
  'authenticated has no truncate, references, trigger or maintain on exposed tables'
);
select is_empty(
  $$ select n.nspname || '.' || c.relname || ': ' || p.priv from pg_class c join pg_namespace n on n.oid = c.relnamespace
     cross join unnest(array['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN']) as p(priv)
     where n.nspname in (select nspname from exposed_schemas) and c.relkind = 'v' and has_table_privilege('authenticated', c.oid, p.priv) $$,
  'authenticated only reads exposed views'
);
-- why: RLS does not apply to materialized views or foreign tables, so any grant exposes every row
select is_empty(
  $$ select n.nspname || '.' || c.relname || ': ' || p.priv from pg_class c join pg_namespace n on n.oid = c.relnamespace
     cross join unnest(array['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN']) as p(priv)
     where n.nspname in (select nspname from exposed_schemas) and c.relkind in ('m', 'f') and has_table_privilege('authenticated', c.oid, p.priv) $$,
  'authenticated has no privilege on exposed materialized views or foreign tables'
);
select is_empty(
  $$ select r.role || ': ' || n.nspname || '.' || c.relname || ': ' || p.priv from pg_class c join pg_namespace n on n.oid = c.relnamespace
     cross join unnest(array['USAGE', 'SELECT', 'UPDATE']) as p(priv)
     cross join unnest(array['anon', 'authenticated']::name[]) as r(role)
     where n.nspname in (select nspname from exposed_schemas) and c.relkind = 'S' and has_sequence_privilege(r.role, c.oid, p.priv) $$,
  'anon and authenticated have no privilege on exposed sequences'
);

select * from finish();
rollback;
