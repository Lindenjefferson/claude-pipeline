import atexit
import os
import shutil
import stat
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
check("lex: >=-1 splits into >= and -, other operators keep their trailing sign rules",
      [t.text for t in pg.significant(pg.lex("a >=-1 and b<=+2 and c @- d and e ->> f"))]
      == ["a", ">=", "-", "1", "and", "b", "<=", "+", "2", "and", "c", "@-", "d", "and", "e", "->>", "f"],
      [t.text for t in pg.significant(pg.lex("a >=-1 and b<=+2 and c @- d and e ->> f"))])
boundary_fn = pg.find_function_defs(
    "create function public.b(n int) returns bool language sql as $$ select n >=-1 $$;", "b.sql")[0][0]
check("boundary mutant generated for n >=-1",
      [(m.operator, m.replacement) for m in pg.generate_mutants(boundary_fn, operators=("boundary",))] == [("boundary", ">")],
      pg.generate_mutants(boundary_fn))
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
rollback work to b;
release savepoint a;
select ok(true), E'a\\b\\'', 'c\\d', "we\\ird"; -- \\! not a command
/* \\c nor /* nested \\o */ this */
select $f$ \\gexec $f$;
select * from finish();
rollback;
"""
body = pg.prepare_test(TEST_OK, "t.sql")
check("prepare_test strips the leading begin and trailing rollback only",
      "begin;" not in body.split("$$")[0] and "rollback;" not in body.replace("rollback to savepoint a;", "")
      and "rollback to savepoint a;" in body and "select ok(true)," in body and "$f$ \\gexec $f$" in body, body)
check("prepare_test keeps the body without begin/rollback as is",
      "select 1;" in pg.prepare_test("select 1;\n", "t.sql"))
check("prepare_test refuses a commit in the middle",
      "commit" in (expect_error(lambda: pg.prepare_test("begin;\nselect 1;\ncommit;\nselect 2;\nrollback;\n", "t.sql")) or ""))
check("prepare_test refuses a second begin",
      expect_error(lambda: pg.prepare_test("begin;\nselect 1;\nbegin;\nselect 2;\n", "t.sql")) is not None)
META_FORMS = [
    r"\ir other.sql" "\nselect 1;\n",
    r"\! rm -rf x" "\n",
    "select 1;\n" r"\c other" "\n",
    r"select 1; \! echo pwned" "\n",
    r"select ok(true); \c postgresql://evil.example.com/db" "\n",
    r"select 'commit' \gexec" "\n",
    r"select 1 \g |calc.exe" "\n",
    r"select 1 \g out.txt" "\n",
    r"select 1 \gx" "\n",
    r"select 1; \lo_export 123 /tmp/x" "\n",
    r"\s history.txt" "\n",
    r"\setenv PGHOST evil" "\n",
    r"\cd /tmp" "\n",
    r"\set x 1" "\n",
    r"select 1\;select 2;" "\n",
    r"select 'a\'' \! pwn '" "\n",
    r"select 'ok' as x -- fine" "\n" r"/* ok */ \o /tmp/x" "\n",
]
for form in META_FORMS:
    check(f"prepare_test refuses unquoted backslash: {form.strip()[:40]!r}",
          expect_error(lambda: pg.prepare_test(form, "t.sql"), pg.UnsupportedTest) is not None)
check("refusal names the line of the meta-command",
      ":2:" in (expect_error(lambda: pg.prepare_test("select 1;\nselect 2; \\! x\n", "t.sql")) or ""))
QUOTED_BACKSLASHES = [
    r"select E'\\ \' \! x';" "\n",
    r"select 'c:\dir\n';" "\n",
    r'select "a\b" from t;' "\n",
    r"-- \! x" "\nselect 1;\n",
    r"/* \! /* \c */ \o */ select 1;" "\n",
    r"select $x$ \! $$ \c $x$;" "\n",
    r"do $$ begin raise notice '\!'; end $$;" "\n",
]
for form in QUOTED_BACKSLASHES:
    check(f"prepare_test allows quoted backslashes: {form.strip()[:40]!r}",
          expect_error(lambda: pg.prepare_test(form, "t.sql")) is None, expect_error(lambda: pg.prepare_test(form, "t.sql")))
TX_FORMS = ["commit;", "end;", "end work;", "abort;", "rollback;", "rollback work;", "rollback prepared 'x';",
            "prepare transaction 'x';", "commit prepared 'x';", "start transaction;", "begin;", "begin isolation level serializable;"]
for form in TX_FORMS:
    check(f"prepare_test refuses top-level `{form}` in the middle",
          expect_error(lambda: pg.prepare_test(f"begin;\nselect 1;\n{form}\nselect 2;\nrollback;\n", "t.sql"),
                       pg.UnsupportedTest) is not None)
for form in ("rollback to savepoint a;", "rollback to a;", "rollback transaction to savepoint a;", "savepoint a;",
             "release savepoint a;", "select 'commit';", "create function pg_temp.g() returns int language plpgsql as $$ begin commit; end $$;"):
    check(f"prepare_test allows `{form}` in the middle",
          expect_error(lambda: pg.prepare_test(f"begin;\nselect 1;\n{form}\nselect 2;\nrollback;\n", "t.sql")) is None,
          expect_error(lambda: pg.prepare_test(f"begin;\nselect 1;\n{form}\nselect 2;\nrollback;\n", "t.sql")))
check("prepare_test strips a trailing end/abort as the closing statement",
      "end" not in pg.prepare_test("begin;\nselect 1;\nend;\n", "t.sql")
      and "abort" not in pg.prepare_test("start transaction;\nselect 1;\nabort;\n", "t.sql"))
check("build_script refuses a DDL that would carry a meta-command",
      expect_error(lambda: pg.build_script("select 1; \\! x", "select 1;", 30), pg.UnsupportedTest) is not None)
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
for url in ("postgres://u@134744072/db", "postgres://u@0x08080808/db", "postgres://u@010.0.0.1/db",
            "postgres://u@0x7f.1/db", "host=134744072 dbname=x", "postgresql://u@localhost/db?host=0x08080808",
            "postgres://u@0/db", "postgres://u@0X7F000001/db"):
    check(f"numeric/hex/octal host refused: {url}", expect_error(lambda: pg.check_local_url(url)) is not None)
os.environ["PGHOST"] = "remote.example.com"
check("a URL without host is local even when PGHOST points elsewhere (PGHOST is stripped)",
      expect_error(lambda: pg.check_local_url("postgresql:///postgres")) is None)
del os.environ["PGHOST"]
env = pg.psql_env({"PATH": "p", "PGHOST": "evil", "PGHOSTADDR": "1.2.3.4", "PGPORT": "1", "PGSERVICE": "prod",
                   "PGSERVICEFILE": "f", "PGPASSFILE": "f", "PGSSLMODE": "disable", "PGSSLROOTCERT": "c",
                   "PGSYSCONFDIR": "d", "PGOPTIONS": "-c x=1", "PSQLRC": "rc", "PGCLIENTENCODING": "LATIN1"})
check("psql child env drops every PG* variable and PSQLRC, keeps the rest, sets PGCLIENTENCODING",
      env == {"PATH": "p", "PGCLIENTENCODING": "UTF8"}, env)
check("psql runs with -X and ON_ERROR_STOP=1",
      "-X" in pg.psql_command_for_url("postgres://u@localhost/db", "psql")
      and "ON_ERROR_STOP=1" in pg.psql_command_for_url("postgres://u@localhost/db", "psql")
      and "-X" in pg.psql_command_for_container("c") and "ON_ERROR_STOP=1" in pg.psql_command_for_container("c"))
os.environ["PGHOST"] = "remote.example.com"
probe = pg.make_runner([sys.executable, "-c", "import os,sys; sys.stdin.read(); print(os.environ.get('PGHOST', 'unset'))"], 30)
check("runner does not pass PGHOST to the child", probe("x").strip() == "unset", probe("x"))
del os.environ["PGHOST"]
exit3 = pg.make_runner([sys.executable, "-c", "import sys; sys.stdin.read(); print('ERROR:  boom'); sys.exit(3)"], 30)
check("psql exit 3 (script error under ON_ERROR_STOP) returns the output to classify", "ERROR:  boom" in (exit3("x") or ""))
exit2 = pg.make_runner([sys.executable, "-c", "import sys; sys.stdin.read(); sys.exit(2)"], 30)
check("psql exit 2 (connection) is a tool error", expect_error(lambda: exit2("x")) is not None)

for ep, ok in (("unix:///var/run/docker.sock", True), ("npipe:////./pipe/docker_engine", True),
               ("tcp://127.0.0.1:2375", True), ("tcp://localhost:2375", True), ("ssh://me@localhost", True),
               ("tcp://10.0.0.5:2376", False), ("ssh://me@build.example.com", False), ("tcp://134744072:2375", False),
               ("tcp://:2375", False), ("fd://", False)):
    check(f"docker endpoint {ep} {'local' if ok else 'refused'}", pg.docker_endpoint_is_local(ep) == ok)


class FakeRun:
    def __init__(self, stdout, code=0):
        self.stdout, self.code, self.calls = stdout, code, []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, self.code, self.stdout, "boom")


def ctx(host):
    return '[{"Name":"x","Endpoints":{"docker":{"Host":"%s"}}}]' % host


saved = {k: os.environ.pop(k) for k in ("DOCKER_HOST", "DOCKER_CONTEXT") if k in os.environ}
check("docker context with a local endpoint passes",
      expect_error(lambda: pg.check_local_docker(FakeRun(ctx("npipe:////./pipe/docker_engine")))) is None)
os.environ["DOCKER_CONTEXT"] = "remote"
err = expect_error(lambda: pg.check_local_docker(FakeRun(ctx("tcp://10.1.2.3:2376"))))
check("docker context with a remote endpoint is refused and names DOCKER_CONTEXT", err and "DOCKER_CONTEXT=remote" in err, err)
del os.environ["DOCKER_CONTEXT"]
check("unreadable docker context fails closed", expect_error(lambda: pg.check_local_docker(FakeRun("", 1))) is not None
      and expect_error(lambda: pg.check_local_docker(FakeRun("not json"))) is not None)
os.environ["DOCKER_HOST"] = "tcp://build.example.com:2376"
fake_run = FakeRun(ctx("unix:///var/run/docker.sock"))
check("remote DOCKER_HOST is refused before the context", expect_error(lambda: pg.check_local_docker(fake_run)) is not None
      and not fake_run.calls)
os.environ["DOCKER_HOST"] = "unix:///var/run/docker.sock"
check("local DOCKER_HOST overrides the context", expect_error(lambda: pg.check_local_docker(FakeRun(ctx("tcp://10.1.2.3:1"))))
      is None)
del os.environ["DOCKER_HOST"]
os.environ.update(saved)


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


def remove_tree(path):
    def writable(func, target, _):
        os.chmod(target, stat.S_IWRITE)
        func(target)
    if os.path.isdir(path):
        shutil.rmtree(path, onerror=writable)


atexit.register(lambda: remove_tree(root))
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

second = sh("git", "rev-parse", "HEAD")
sh("git", "mv", "supabase/migrations/0002_b.sql", "supabase/migrations/0003_b.sql")
open(os.path.join(root, "supabase", "migrations", "0003_b.sql"), "a", encoding="utf-8").write(
    "create function public.renamed_extra() returns int language sql as $$ select 1 $$;\n")
sh("git", "add", ".")
sh("git", "commit", "-q", "-m", "rename and edit")
check("changed_functions follows a renamed and edited migration (--diff-filter=AMR)",
      pg.changed_functions(root, second, "HEAD", "supabase/migrations") == [("public", "helper"), ("public", "renamed_extra")],
      pg.changed_functions(root, second, "HEAD", "supabase/migrations"))

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
