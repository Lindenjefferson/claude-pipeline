import json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER_PY = os.path.join(HERE, "..", "ledger.py")
PACKAGE_PY = os.path.join(HERE, "..", "package.py")
repo = tempfile.mkdtemp(prefix="packagefix_")
os.makedirs(os.path.join(repo, "src"))
os.makedirs(os.path.join(repo, "docs"))
LEDGER = os.path.join(repo, ".superpowers", "ledger.jsonl")
SPEC = "docs/spec.md"
results = []


def sh(*args):
    return subprocess.run(args, cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def run(script, *args, stdin=None):
    return subprocess.run([sys.executable, script, *args], cwd=repo, capture_output=True, input=stdin,
                          encoding="utf-8")


def ledger(*args, stdin=None):
    return run(LEDGER_PY, "--ledger", LEDGER, *args, stdin=stdin)


def package(*args):
    return run(PACKAGE_PY, "review", *args)


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS" if ok else "FAIL"), name, "" if ok else f"| {detail[:400]}")


def reviewer(agent, verdict="FAIL"):
    counts = {"critical": 0, "important": 1 if verdict == "FAIL" else 0, "minor": 0}
    return "LEDGER " + json.dumps({"agent": agent, "verdict": verdict, "new": counts, "open": counts})


def review(agent, text, task="1", frm=None, verdict="FAIL", spec=None):
    ref = ledger("save-report", "--task", task, "--agent", agent, "--from", frm or base, "--stdin", stdin=text)
    extra = ["--spec", spec] if spec else []
    r = ledger("append", "--task", task, "--from", frm or base, "--head", "HEAD", "--report", ref.stdout.strip(),
               "--line", reviewer(agent, verdict), *extra)
    assert r.returncode == 0, r.stderr
    return ref.stdout.strip()


def commit(files, message):
    for name in files:
        os.makedirs(os.path.dirname(os.path.join(repo, name)), exist_ok=True)
        with open(os.path.join(repo, name), "a") as handle:
            handle.write(f"{message}\n")
    sh("git", "add", ".")
    sh("git", "commit", "-q", "-m", message)
    return sh("git", "rev-parse", "HEAD")


def header(name):
    path = os.path.join(repo, ".superpowers", "reviews", f"review-{name}.diff")
    return open(path, encoding="utf-8").read() if os.path.exists(path) else ""


sh("git", "init", "-q")
sh("git", "config", "user.email", "t@t.com")
sh("git", "config", "user.name", "t")
sh("git", "config", "core.autocrlf", "false")
open(os.path.join(repo, ".gitignore"), "w").write(".superpowers/\n")
sh("git", "add", ".gitignore")
sh("git", "commit", "-q", "-m", "base")
base = sh("git", "rev-parse", "HEAD")
ledger("start", "--slug", "x", "--base", base)

spec1 = commit([SPEC], "spec")
review("design", "Findings\n- **Important** section Screens: no empty state\n", task="spec", spec=SPEC)
review("security", "## Findings\n### Important\n- the invite crosses tenants\n", task="spec", spec=SPEC)
c1 = commit(["src/a.ts", "src/b.ts", "src/c.ts"], "task 1")
CR = ("# Code review\n\n**Verdict**: FAIL\n\n## Findings\n### Important\n1. `src/a.ts:3` misses the null check.\n"
      "2. src/b.ts:7-9 duplicates the guard.\n\n## Notes\nI also read `src/c.ts`.\n")
first = review("code-review", CR, frm=spec1)
review("design", "**Findings**\n- none that block\n\n**Verdict**: PASS\n", frm=spec1, verdict="PASS")
review("audit", "Looked at everything; FAIL for the missing trail.\n", frm=spec1)
review("security", "## Findings\n- `src/a.ts:3` trusts the caller\n", frm=spec1)

c2 = commit(["src/a.ts", "src/b.ts"], "fix a and b")
r = package("--fix-of", "1", "--agent", "code-review")
text = header("1-code-review-fix-r2")
check("a fix inside the files of the findings is fix-only",
      r.returncode == 0 and "scope: fix-only" in r.stdout and "Scope: fix-only" in text, r.stdout + r.stderr)
check("the fix-only package covers only the fix range", text.startswith(f"# Review package: {c1}..{c2}"), text[:200])
check("the package names the previous report and how to record it",
      f"Previous report: {first}" in text and f"--from {c1}" in text and "--scope fix" in text, text[:600])
check("the fix-only diff leaves the untouched file out", "src/c.ts" not in text.split("## Diff")[1],
      text)

r = package("--fix-of", "1", "--agent", "security")
text = header("1-security-fix-r2")
check("security always gets the full task range",
      "Scope: full (security always" in text and text.startswith(f"# Review package: {spec1}..{c2}"), text[:300])
r = package("--fix-of", "1", "--agent", "audit")
check("an own report citing no file is still fix-only when another reviewer's open findings cite the fixed files",
      "Scope: fix-only" in header("1-audit-fix-r2"), header("1-audit-fix-r2")[:300])
r = package("--fix-of", "1", "--agent", "design")
check("a PASS reviewer re-run on a fix of the combined brief is fix-only",
      "Scope: fix-only" in header("1-design-fix-r2"), header("1-design-fix-r2")[:300])

sh("git", "reset", "-q", "--hard", c1)
n0 = sh("git", "rev-parse", "HEAD")
commit(["src/n.ts"], "task N")
review("audit", "Looked at everything; FAIL for the missing trail.\n", task="N", frm=n0)
review("design", "**Findings**\n- the flow is wrong\n", task="N", frm=n0)
commit(["src/n.ts", "docs/modulo.md"], "fix n")
r = package("--fix-of", "N", "--agent", "audit")
check("when no reviewer's open findings cite a file the fix gets the full range",
      "Scope: full (the open findings of the task's reviewers cite no file)" in header("N-audit-fix-r2"),
      header("N-audit-fix-r2")[:300])
sh("git", "reset", "-q", "--hard", "HEAD~1")
commit(["docs/modulo.md"], "docs only")
r = package("--fix-of", "N", "--agent", "design")
check("a fix touching only docs/** is fix-only even with no cited file",
      "Scope: fix-only" in header("N-design-fix-r2"), header("N-design-fix-r2")[:300])

sh("git", "reset", "-q", "--hard", c1)
commit(["src/a.ts", "src/c.ts"], "fix a, touch c")
r = package("--fix-of", "1", "--agent", "code-review")
text = header("1-code-review-fix-r2")
check("a fix touching a file cited only outside the findings gives the full range, naming it",
      "Scope: full (the fix touches files outside the open findings: src/c.ts)" in text
      and text.startswith(f"# Review package: {spec1}..") and "--scope full" in text, text[:400])

r = package("--fix-of", "1", "--agent", "qa")
check("no previous review of that agent is an error", r.returncode != 0 and "no qa review" in r.stderr, r.stderr)
sh("git", "reset", "-q", "--hard", c1)
r = package("--fix-of", "1", "--agent", "code-review")
check("nothing changed since the last review is an error", r.returncode != 0 and "nothing changed" in r.stderr,
      r.stderr)
check("--fix-of needs --agent", package("--fix-of", "1").returncode != 0)
check("a plain package still needs --base", package().returncode != 0)

sh("git", "reset", "-q", "--hard", spec1)
spec2 = commit([SPEC, "src/a.ts"], "spec fix")
r = package("--fix-of", "spec", "--agent", "design")
text = header("spec-design-fix-r2")
check("a spec re-review is scoped to the spec diff",
      "Scope: fix-only" in text and f"Spec: {SPEC}" in text and "src/a.ts" not in text, text[:600])
r = package("--fix-of", "spec", "--agent", "security")
check("security re-reviews the whole spec", "Scope: full (security always" in header("spec-security-fix-r2"))

T1_1 = """# T1.1-code-review-r1

**Verdict: FAIL.** 2 Important (test-quality gaps on admin-only write rules); migration correct.

## Important
1. 04_privilegios.sql / 02_permissoes.sql: admin-only write policies (households_update 0002:226; household_members_insert/update 0002:232-236) have no negative test.
2. 04_privilegios.sql:131-134: lives_ok on UPDATE passes when RLS filters every row.

## Minor
4. 02:64: explicit nivel='nenhum' row not exercised.

LEDGER {"agent":"code-review","verdict":"FAIL","new":{"critical":0,"important":2,"minor":1},"open":{"critical":0,"important":2,"minor":1}}
"""
sh("git", "reset", "-q", "--hard", c1)
t0 = sh("git", "rev-parse", "HEAD")
commit(["supabase/migrations/0002_pessoas.sql", "supabase/tests/02_permissoes.sql", "supabase/tests/04_privilegios.sql",
        "supabase/tests/01_rls.sql"], "task T1.1")
review("code-review", T1_1, task="T1.1", frm=t0)
review("design", T1_1.replace("code-review", "design"), task="T1.1", frm=t0)
fix = commit(["supabase/tests/04_privilegios.sql", "supabase/tests/02_permissoes.sql",
              "supabase/migrations/0002_pessoas.sql"], "T1.1 fix")
r = package("--fix-of", "T1.1", "--agent", "code-review")
check("a real report citing bare names and shorthand (04_privilegios.sql, 0002:226, 02:64) gives fix-only",
      r.returncode == 0 and "scope: fix-only" in r.stdout, r.stdout + r.stderr)
flags = r.stdout.split("record with: ")[-1].split()
ref = ledger("save-report", "--task", "T1.1", "--agent", "code-review", "--from", flags[1], "--stdin",
             stdin="## Findings\nnone\n\n" + reviewer("code-review", "PASS")).stdout.strip()
r = ledger("append", "--task", "T1.1", "--report", ref, "--line", reviewer("code-review", "PASS"), *flags)
check("append accepts the fix scope the package printed", r.returncode == 0, r.stdout + r.stderr)
commit(["supabase/tests/01_rls.sql"], "T1.1 touches 01")
r = package("--fix-of", "T1.1", "--agent", "design")
check("a fix touching a file the real report does not cite gives the full range",
      "Scope: full (the fix touches files outside the open findings: supabase/tests/01_rls.sql)"
      in header("T1.1-design-fix-r2"), header("T1.1-design-fix-r2")[:300])

sys.path.insert(0, os.path.join(HERE, ".."))
from findings import finding_paths

for name, report, expected in (
        ("heading with severity sub-headings", "## Findings\n### Critical\n- `x/a.sql:4`\n### Minor\n- y/b.ts:2\n"
                                               "## Tests\n- `z/c.ts`\n", {"x/a.sql", "y/b.ts"}),
        ("bold label with bold severities", "**Findings**\n**Important**\n- `a/b.ts:1` wrong\n**Verdict**\n`q/r.ts`\n",
         {"a/b.ts"}),
        ("a Findings label with a trailing count", "Findings (2):\n- lib/x.ts:10 and `lib/y.ts`\n\nLEDGER {}\n"
                                                   "`lib/z.ts`", {"lib/x.ts", "lib/y.ts"}),
        ("no findings section", "All good.\n`src/a.ts`\n", None)):
    found = finding_paths(report)
    check(f"finding_paths: {name}", found == expected, str(found))

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
