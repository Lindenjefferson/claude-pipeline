import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "pgmutate.py")
sys.path.insert(0, os.path.join(HERE, ".."))
import pgmutate as pg  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS" if ok else "FAIL"), name, "" if ok else f"| {str(detail)[:400]}")


def expect_error(fn, cls=pg.ToolError):
    try:
        fn()
    except cls as e:
        return str(e)
    return None


MIGRATION = """-- header; with a semicolon
create table public.t (id int);

create function public.guard(p_id uuid, p_n int) returns void
language plpgsql security definer set search_path = '' as $$
declare
  v_uid uuid := (select auth.uid());
  v_casa uuid;
  v_txt text := 'a >= b; raise exception';
begin
  -- if x >= 1 then raise
  if v_uid is null then
    raise exception using message = 'nao_autenticado';
  end if;
  if p_id is not null and p_n between 1 and 10 then
    raise notice 'fine';
  end if;
  select m.household_id into v_casa from public.members m
  where m.household_id = p_id and m.user_id = v_uid and m.papel = 'admin';
  if p_n >= 5 or p_n < 0 then
    raise exception 'limite';
  end if;
  if (v_casa->>'x') <> 'y' then
    null;
  end if;
  perform 1 from public.logs l where l.created_at > now() - interval '7 days' limit 3;
  insert into public.audit_log (acao) values (coalesce(v_txt, 'none'));
  perform public.registrar_auditoria(v_casa, 'x');
  insert into public.households (nome) values ('n');
  exit when p_n <= 2 and v_uid is null;
end;
$$;

create function public.helper(p_x int) returns int language sql as $$ select p_x + 1 where p_x > 0 $$;
create function public.helper(p_x text) returns text language sql as $$ select p_x $$;
"""

MIGRATION_2 = """create or replace function public.helper(p_x int) returns int language sql as $body$ select p_x + 2 $body$;
drop function if exists public.helper(text);
"""

toks = pg.lex("select 'a;b' , $q$ x; $q$ ; -- c;\n/* a /* nested */ ; */ x")
kinds = [t.kind for t in pg.significant(toks)]
check("lex keeps strings, dollar quotes and nested comments atomic",
      kinds == ["ident", "str", "punct", "dollar", "punct", "ident"], kinds)
check("lex splits operators without swallowing comments",
      [t.text for t in pg.significant(pg.lex("a>=--x\nb <> c->>'k'"))] == ["a", ">=", "b", "<>", "c", "->>", "'k'"])
check("lex: E-strings with backslash escapes",
      [t.kind for t in pg.significant(pg.lex(r"select E'it\'s; x' ;"))] == ["ident", "str", "punct"])

defs, drops = pg.find_function_defs(MIGRATION, "m1.sql")
names = [(d.schema, d.name, d.args) for d in defs]
check("finds functions with schema, args and language",
      names == [("public", "guard", "p_id uuid, p_n int"), ("public", "helper", "p_x int"), ("public", "helper", "p_x text")]
      and defs[0].language == "plpgsql" and defs[1].language == "sql", names)
check("function body span is the dollar-quoted body",
      MIGRATION[defs[0].body_start:defs[0].body_end].lstrip().startswith("declare")
      and MIGRATION[defs[0].start:defs[0].end].rstrip().endswith("$$;"))

latest = pg.latest_definitions([("m1.sql", MIGRATION), ("m2.sql", MIGRATION_2)])
helper = [d for k, d in latest.items() if k[1] == "helper"]
check("latest definition wins and a later drop removes an overload",
      len(helper) == 1 and helper[0].file == "m2.sql" and "p_x + 2" in helper[0].text[helper[0].body_start:helper[0].body_end],
      [(d.file, d.args) for d in helper])
check("select_functions resolves unqualified names to public",
      [d.name for d in pg.select_functions(latest, [pg.parse_function_arg("guard")])] == ["guard"])
check("select_functions errors for unknown functions",
      expect_error(lambda: pg.select_functions(latest, [("public", "nope")])) is not None)

guard = [d for d in defs if d.name == "guard"][0]
mutants = pg.generate_mutants(guard)
by_op = {}
for m in mutants:
    by_op.setdefault(m.operator, []).append(m)


def snippets(op):
    return [MIGRATION[m.start:m.end] for m in by_op.get(op, [])]


def replacements(op):
    return [(MIGRATION[m.start:m.end], m.replacement) for m in by_op.get(op, [])]


check("null-guard-removed replaces the operand and test with false",
      ("v_uid is null", "false") in replacements("null-guard-removed"), replacements("null-guard-removed"))
check("null-guard-negated covers is null and is not null",
      ("is null", "is not null") in replacements("null-guard-negated")
      and ("is not null", "is null") in replacements("null-guard-negated"), replacements("null-guard-negated"))
check("boundary swaps >=, <, >, <= but not <> or ->> or text in strings/comments",
      sorted(snippets("boundary")) == sorted([">=", "<", ">", "<="]), snippets("boundary"))
check("time-constant widens interval literals",
      ("'7 days'", "'14 days'") in replacements("time-constant"), replacements("time-constant"))
check("limit-constant bumps comparison and limit integers by one",
      {("5", "6"), ("5", "4"), ("3", "4"), ("3", "2"), ("2", "3"), ("2", "1")} <= set(replacements("limit-constant"))
      and ("0", "-1") not in replacements("limit-constant"), replacements("limit-constant"))
check("scope-filter-removed drops tenant/user conditions in where",
      set(snippets("scope-filter-removed")) == {"m.household_id = p_id", "m.user_id = v_uid"}, snippets("scope-filter-removed"))
check("scope filter ignores select-list columns",
      all(m.replacement == "true" for m in by_op["scope-filter-removed"]))
check("role-filter-removed drops the role condition",
      snippets("role-filter-removed") == ["m.papel = 'admin'"], snippets("role-filter-removed"))
audit = snippets("audit-removed")
check("audit-removed covers audit inserts and audit performs, not other inserts",
      len(audit) == 2 and any("audit_log" in a for a in audit) and any("registrar_auditoria" in a for a in audit)
      and not any("households" in a for a in audit), audit)
raises = snippets("raise-removed")
check("raise-removed removes raise exception but not raise notice",
      len(raises) == 2 and all("notice" not in r for r in raises) and all(r.endswith(";") for r in raises), raises)
check("statement removals become a plpgsql no-op",
      all(m.replacement == "null;" for m in by_op["raise-removed"] + by_op["audit-removed"]))
swaps = replacements("and-or-swap")
check("and-or-swap in if/exit-when guards, skipping between ... and",
      sorted(swaps) == sorted([("and", "or"), ("or", "and"), ("and", "or")]), swaps)
check("and-or-swap ignores where clauses",
      all(m.start < MIGRATION.index("select m.household_id") or m.start > MIGRATION.index("'admin';") for m in by_op["and-or-swap"]))
check("coalesce-default-removed keeps the first argument",
      replacements("coalesce-default-removed") == [("coalesce(v_txt, 'none')", "(v_txt)")], replacements("coalesce-default-removed"))
lit_start = MIGRATION.index("'a >= b")
lit_end = MIGRATION.index("\n", lit_start)
com_start = MIGRATION.index("-- if x >= 1")
com_end = MIGRATION.index("\n", com_start)
check("no mutant touches the string literal or comment containing >= and raise",
      not any(lit_start <= m.start < lit_end or com_start <= m.start < com_end for m in mutants))

sql_helper = [d for d in defs if d.name == "helper"][0]
sql_mutants = pg.generate_mutants(sql_helper)
check("language sql bodies get expression mutants but no statement removals",
      [m.operator for m in sql_mutants] == ["boundary", "limit-constant"], [m.operator for m in sql_mutants])

only = pg.generate_mutants(guard, operators=("raise-removed",))
check("operator filter", {m.operator for m in only} == {"raise-removed"})
custom = pg.generate_mutants(guard, operators=("scope-filter-removed",), scope_columns=("papel",))
check("custom scope columns replace the default list",
      [MIGRATION[m.start:m.end] for m in custom] == ["m.papel = 'admin'"])

ddl = pg.mutated_ddl(guard, by_op["raise-removed"][0])
check("mutated ddl is create or replace with the mutation applied",
      ddl.startswith("create or replace function public.guard(") and "'nao_autenticado'" not in ddl
      and ddl.count("null;") >= 2 and ddl.rstrip().endswith("$$;"), ddl[:200])
check("original ddl keeps the body and becomes create or replace",
      pg.original_ddl(guard).startswith("create or replace function") and "'nao_autenticado'" in pg.original_ddl(guard))
check("create or replace header stays a single create or replace",
      pg.as_replace("CREATE OR REPLACE FUNCTION a() returns int as $$ select 1 $$;").startswith("create or replace function a()"))
check("line numbers point at the migration line",
      pg.line_of(MIGRATION, by_op["raise-removed"][0].start) == MIGRATION[:MIGRATION.index("raise exception using")].count("\n") + 1)

TEST_OK = """-- comment first
begin;
create extension if not exists pgtap with schema extensions;
select plan(1);
create function pg_temp.f() returns void language plpgsql as $$ begin commit; end $$;
savepoint a;
rollback to savepoint a;
\\set x 1
select ok(true);
select * from finish();
rollback;
"""
body = pg.prepare_test(TEST_OK, "t.sql")
check("prepare_test strips the leading begin and trailing rollback only",
      "begin;" not in body.split("$$")[0] and "rollback;" not in body.replace("rollback to savepoint a;", "")
      and "rollback to savepoint a;" in body and "\\set x 1" in body and "select ok(true);" in body, body)
check("prepare_test keeps the body without begin/rollback as is",
      "select 1;" in pg.prepare_test("select 1;\n", "t.sql"))
check("prepare_test refuses a commit in the middle",
      "commit" in (expect_error(lambda: pg.prepare_test("begin;\nselect 1;\ncommit;\nselect 2;\nrollback;\n", "t.sql")) or ""))
check("prepare_test refuses a second begin",
      expect_error(lambda: pg.prepare_test("begin;\nselect 1;\nbegin;\nselect 2;\n", "t.sql")) is not None)
check("prepare_test refuses file includes and shell escapes",
      expect_error(lambda: pg.prepare_test("\\ir other.sql\nselect 1;\n", "t.sql")) is not None
      and expect_error(lambda: pg.prepare_test("\\! rm -rf x\n", "t.sql")) is not None
      and expect_error(lambda: pg.prepare_test("select 1;\n\\c other\n", "t.sql")) is not None)
check("prepare_test turns a trailing commit into the wrapper's rollback",
      "commit" not in pg.prepare_test("begin;\nselect 1;\ncommit;\n", "t.sql"))

script = pg.build_script("create or replace function x() returns int as $$ select 1 $$;", "select 1;", 30)
check("wrapper opens a transaction, sets a timeout, marks the ddl and rolls back",
      script.startswith("begin;\nset local statement_timeout = '30s';") and pg.DDL_MARKER in script
      and script.rstrip().endswith("rollback;"))

check("classify: failing pgTAP line after the marker", pg.classify(f"{pg.DDL_MARKER}\nok 1\nnot ok 2 - x\n") == ("failed", "not ok 2 - x"))
check("classify: pgTAP plan summary counts as failure",
      pg.classify(f"{pg.DDL_MARKER}\n1..3\n# Looks like you planned 3 tests but ran 2\n")[0] == "failed")
check("classify: ERROR after the marker is a kill",
      pg.classify(f"{pg.DDL_MARKER}\npsql:<stdin>:9: ERROR:  sem_permissao\n")[0] == "failed")
check("classify: ddl error means invalid mutant",
      pg.classify("psql:<stdin>:3: ERROR:  syntax error at or near x\n")[0] == "invalid")
check("classify: clean run passes", pg.classify(f"{pg.DDL_MARKER}\n1..2\nok 1\nok 2\n") == ("passed", ""))

for url in ("postgresql://postgres:pw@127.0.0.1:54322/postgres", "postgres://u@localhost/db", "postgres://u@[::1]:5432/db",
            "postgres://u@host.docker.internal:54322/db", "postgres://u@db:5432/postgres", "host=localhost dbname=x",
            "postgresql:///postgres?host=/var/run/postgresql", "postgres://u@127.0.0.2/db"):
    check(f"local url accepted: {url}", expect_error(lambda: pg.check_local_url(url)) is None)
for url in ("postgres://u@db.example.com/db", "postgres://u@10.0.0.5/db", "postgres://u@localhost,remote.example.com/db",
            "postgresql://u@localhost/db?host=remote.example.com", "host=10.1.2.3 dbname=x", "service=prod",
            "postgresql://u@localhost/db?hostaddr=192.168.0.10", "mysql://u@localhost/db"):
    check(f"remote url refused: {url}", expect_error(lambda: pg.check_local_url(url)) is not None)


class FakeDB:
    def __init__(self, kill=lambda s: False, change_fp=False, timeout=lambda s: False):
        self.kill = kill
        self.timeout = timeout
        self.change_fp = change_fp
        self.fp_calls = 0
        self.scripts = []

    def __call__(self, script):
        self.scripts.append(script)
        if script.startswith("select 'PGMUTATE_FP"):
            self.fp_calls += 1
            return f"PGMUTATE_FP {'b' if self.change_fp and self.fp_calls > 1 else 'a'}\n"
        if self.timeout(script):
            return None
        if "invalid-sql" in script:
            return "ERROR:  syntax error\n"
        out = f"{pg.DDL_MARKER}\n1..1\n"
        if self.kill(script):
            return out + "not ok 1 - caught\n"
        return out + "ok 1 - fine\n"


tests = [("t1.sql", "select 1;"), ("t2.sql", "select 2;")]
rows = pg.collect_mutants([guard], ("raise-removed", "null-guard-negated"), pg.DEFAULT_SCOPE_COLUMNS,
                          pg.DEFAULT_ROLE_COLUMNS, pg.DEFAULT_AUDIT_PATTERN, "/")
fake = FakeDB(kill=lambda s: "v_uid is not null then" in s)
pg.run_all(rows, [guard], tests, fake, 30)
statuses = [(r["line"], r["change"], r["status"]) for r in rows]
check("run_all marks killed and survived mutants from the runner output",
      [s for _, _, s in statuses].count("killed") == 1 and [s for _, _, s in statuses].count("survived") == 4
      and statuses[0][2] == "killed", statuses)
check("killed rows name the killing test file",
      all(r["killed_by"] == "t1.sql" for r in rows if r["status"] == "killed"))
check("baseline plus fingerprints ran around the mutants",
      fake.fp_calls == 2 and "create or replace function public.guard" in fake.scripts[1])
stop_first = [s for s in fake.scripts if "v_uid is not null then" in s]
check("stops at the first killing test file by default", len(stop_first) == 1, len(stop_first))

rows = pg.collect_mutants([guard], ("raise-removed",), (), (), "x", "/")
check("fingerprint change raises IntegrityError",
      expect_error(lambda: pg.run_all(rows, [guard], tests, FakeDB(change_fp=True), 30), pg.IntegrityError) is not None)
check("baseline failure is a tool error",
      expect_error(lambda: pg.run_all(rows, [guard], tests, FakeDB(kill=lambda s: "nao_autenticado" in s), 30)) is not None)
rows = pg.collect_mutants([guard], ("raise-removed",), (), (), "x", "/")
pg.run_all(rows, [guard], tests, FakeDB(timeout=lambda s: "public.guard" in s and "'limite'" not in s), 30)
check("a runner timeout on a mutant (not the baseline) is reported as timeout",
      [r["status"] for r in rows] == ["survived", "timeout"], [r["status"] for r in rows])
rows = pg.collect_mutants([guard], ("boundary",), (), (), "x", "/")[:1]
pg.run_all(rows, [guard], tests, FakeDB(kill=lambda s: "p_n > 5" in s), 30, all_tests=True)
check("--all-tests collects every killing test file", rows[0]["killed_by"] == "t1.sql, t2.sql", rows[0])
summary = pg.summarize([{"status": "killed"}, {"status": "survived"}, {"status": "invalid"}, {"status": "timeout"}])
check("score ignores invalid mutants and counts timeouts as killed", summary["score"] == 66.7, summary)

root = os.path.join(tempfile.gettempdir(), f"pgmutate_test_{int(time.time() * 1000)}")
os.makedirs(os.path.join(root, "supabase", "migrations"))
os.makedirs(os.path.join(root, "supabase", "tests"))


def sh(*args):
    return subprocess.run(args, cwd=root, capture_output=True, text=True, check=True).stdout.strip()


def tool(*args):
    return subprocess.run([sys.executable, TOOL, "--root", root, *args], capture_output=True, text=True, encoding="utf-8")


open(os.path.join(root, "supabase", "migrations", "0001_a.sql"), "w", encoding="utf-8").write(MIGRATION)
open(os.path.join(root, "supabase", "tests", "01_t.sql"), "w", encoding="utf-8").write(TEST_OK)
sh("git", "init", "-q")
sh("git", "config", "user.email", "t@example.com")
sh("git", "config", "user.name", "t")
sh("git", "add", ".")
sh("git", "commit", "-q", "-m", "one")
first = sh("git", "rev-parse", "HEAD")
open(os.path.join(root, "supabase", "migrations", "0002_b.sql"), "w", encoding="utf-8").write(MIGRATION_2)
sh("git", "add", ".")
sh("git", "commit", "-q", "-m", "two")
check("changed_functions discovers functions created/replaced in the diff range",
      pg.changed_functions(root, first, "HEAD", "supabase/migrations") == [("public", "helper")],
      pg.changed_functions(root, first, "HEAD", "supabase/migrations"))

r = tool("--from", first, "--list", "--json")
check("CLI --from --list lists the changed function's mutants", r.returncode == 0 and '"public.helper(p_x int)"' in r.stdout,
      r.stdout + r.stderr)
r = tool("--function", "guard", "--list")
check("CLI --function --list prints a table", r.returncode == 0 and "raise-removed" in r.stdout and "mutants in 1" in r.stdout,
      r.stdout + r.stderr)
r = tool("--function", "guard", "--db-url", "postgresql://postgres@db.example.com:5432/postgres")
check("CLI refuses a remote --db-url with exit 2", r.returncode == 2 and "non-local" in r.stderr, r.stdout + r.stderr)
r = tool("--function", "missing_fn", "--list")
check("CLI reports an unknown function as a tool error", r.returncode == 2 and "missing_fn" in r.stderr, r.stderr)
r = tool("--function", "guard", "--operators", "bogus", "--list")
check("CLI rejects unknown operators", r.returncode == 2 and "bogus" in r.stderr, r.stderr)
r = subprocess.run([sys.executable, TOOL, "--help"], capture_output=True, text=True, encoding="utf-8")
check("--help documents the transaction wrapper and local-only rule",
      r.returncode == 0 and "rollback" in r.stdout and "localhost" in r.stdout and "--fail-on-survivors" in r.stdout)

print(f"\n{'ALL PASS' if all(results) else 'FAILURES'} ({sum(results)}/{len(results)})")
sys.exit(0 if all(results) else 1)
