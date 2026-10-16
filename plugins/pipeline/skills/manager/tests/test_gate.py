import atexit, os, shutil, stat, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "..", "gate.py")
LEDGER = os.path.join(HERE, "..", "ledger.py")
base_dir = tempfile.mkdtemp(prefix="gate_")
repo = os.path.join(base_dir, "repo")
PY = sys.executable.replace("\\", "/")
SECRET = "AWS_" + "KEY=AK" + "IAABCDEFGHIJKLMNOP\n"
results = []


def cleanup():
    def retry(func, path, _):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except OSError:
            pass
    shutil.rmtree(base_dir, onerror=retry)


atexit.register(cleanup)
os.environ["GIT_CONFIG_GLOBAL"] = os.path.join(base_dir, "global.gitconfig")
open(os.environ["GIT_CONFIG_GLOBAL"], "w").close()


def sh(*args):
    return subprocess.run(list(args), cwd=repo, capture_output=True, text=True, encoding="utf-8", check=True).stdout


def write(name, text):
    with open(os.path.join(repo, name), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def commit(name, text, message):
    write(name, text)
    sh("git", "add", name)
    sh("git", "commit", "-q", "--no-verify", "-m", message)


def gate(*args):
    return subprocess.run([sys.executable, GATE, *args], cwd=repo, capture_output=True, text=True, encoding="utf-8")


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("PASS" if ok else "FAIL", name, "" if ok else f"| {str(detail)[-500:]}")


def claude_md(lint_ok=True, tests=True, audit=None, test_files=None):
    lines = ["# p", "", "## Comandos", "", f"- Build: `{PY} -c \"print('built')\"`",
             f"- Lint: `{PY} -c \"import sys; sys.exit({0 if lint_ok else 1})\"`"]
    if tests:
        lines.append(f"- Testes: `{PY} -c \"print('3 passed')\"`")
    if audit is not None:
        lines.append(f"- Auditoria (dependências; opcional): `{PY} -c \"import sys; print('audit'); sys.exit({0 if audit else 1})\"`")
    if test_files:
        lines.append(f"- Arquivos de teste (globs): `{test_files}`")
    return "\n".join(lines + ["", "## Outra seção", "- Testes: `false`", ""])


os.makedirs(repo)
sh("git", "init", "-q", "-b", "main")
sh("git", "config", "user.email", "t@t.com")
sh("git", "config", "user.name", "t")
write(".gitignore", ".superpowers/\n")
sh("git", "add", ".gitignore")
commit("CLAUDE.md", claude_md(), "base")
sh("git", "switch", "-q", "-c", "feat/x")

r = gate("--base", "main")
check("no ledger: NOT READY", r.returncode == 1 and "Ledger:     FAIL" in r.stdout, r.stdout)

subprocess.run([sys.executable, LEDGER, "start", "--slug", "x", "--base", "main"], cwd=repo, check=True,
               capture_output=True)
commit("a.txt", "clean\n", "feat: a")
for args in (["--agent", "dev", "--task", "T1", "--verdict", "DONE"], ["--agent", "reviewer", "--verdict", "PASS"]):
    subprocess.run([sys.executable, LEDGER, "add", *args], cwd=repo, check=True, capture_output=True)
r = gate("--base", "main")
check("open cycle (qa missing): NOT READY", r.returncode == 1 and "qa has not run" in r.stdout, r.stdout)
subprocess.run([sys.executable, LEDGER, "add", "--agent", "qa", "--verdict", "PASS"], cwd=repo, check=True,
               capture_output=True)

r = gate("--base", "main")
check("closed cycle, clean tree, commands pass, no secrets: READY", r.returncode == 0 and "READY" in r.stdout, r.stdout)
check("commands come from the Comandos section only", "Build:      PASS" in r.stdout and "Testes:     PASS" in r.stdout
      and "Typecheck:  SKIP" in r.stdout, r.stdout)

write("dirty.txt", "x\n")
r = gate("--base", "main")
check("dirty tree: NOT READY", r.returncode == 1 and "Clean tree: FAIL" in r.stdout, r.stdout)
os.remove(os.path.join(repo, "dirty.txt"))

r = gate("--base", "main", "--cmd", f"Lint={PY} -c \"import sys; sys.exit(2)\"")
check("--cmd overrides a command and a failing one blocks", r.returncode == 1 and "Lint:       FAIL" in r.stdout,
      r.stdout)

commit("CLAUDE.md", claude_md(tests=False), "docs: no tests")
r = gate("--base", "main")
check("no test command: NOT READY", r.returncode == 1 and "Testes:     FAIL" in r.stdout, r.stdout)
commit("CLAUDE.md", claude_md(), "docs: tests back")

commit("cfg.txt", SECRET, "oops")
sh("git", "rm", "-q", "cfg.txt")
sh("git", "commit", "-q", "--no-verify", "-m", "remove it")
r = gate("--base", "main")
check("a secret added and removed in the branch history: NOT READY",
      r.returncode == 1 and "Secrets:    FAIL" in r.stdout and "cfg.txt" in r.stdout, r.stdout)
sh("git", "reset", "-q", "--hard", "HEAD~2")

commit(".env", "X=1\n", "env")
r = gate("--base", "main")
check("an .env file in the branch: NOT READY", r.returncode == 1 and ".env" in r.stdout, r.stdout)
sh("git", "reset", "-q", "--hard", "HEAD~1")

def ledger(*args):
    subprocess.run([sys.executable, LEDGER, "add", *args], cwd=repo, check=True, capture_output=True)


commit("b.txt", "minor fixed\n", "fix: minor")
ledger("--agent", "dev", "--task", "fix-1", "--verdict", "DONE")
r = gate("--base", "main")
check("a fix round after the closed cycle needs its review: NOT READY",
      r.returncode == 1 and "reviewer has not reviewed" in r.stdout, r.stdout)
ledger("--agent", "reviewer", "--verdict", "PASS", "--minor", "2", "--origin", "execution=2")
subprocess.run([sys.executable, LEDGER, "lesson", "--text", "lock before checking", "--check", "tests/race.sql"],
               cwd=repo, check=True, capture_output=True)
r = gate("--base", "main")
check("the fix reviewed and qa passed before it: READY without another qa", r.returncode == 0, r.stdout)

r = gate("--base", "main", "--report", "feature-x")
report = [name for name in os.listdir(os.path.join(repo, "docs", "quality-reports"))] if r.returncode == 0 else []
check("--report writes and stages the quality report on READY",
      r.returncode == 0 and report and "docs/quality-reports/" in sh("git", "diff", "--cached", "--name-only"),
      r.stdout)
text = open(os.path.join(repo, "docs", "quality-reports", report[0]), encoding="utf-8").read() if report else ""
check("the report carries the delivery metrics from the ledger",
      "## Metrics" in text and "- Cycle 1: 0 Critical, 0 Important, 2 Minor; 1 fix round" in text
      and "Lessons: 1 (1 automated)" in text and "- lock before checking (check: tests/race.sql)" in text, text)
check("no audit command: the audit is skipped with a note",
      "Auditoria:  SKIP" in r.stdout and "not configured" in r.stdout, r.stdout)
check("no plan in the ledger: traceability is skipped", "Criteria:   SKIP" in r.stdout, r.stdout)
sh("git", "commit", "-q", "--no-verify", "-m", "docs: quality report")


def ledger_cmd(*args):
    return subprocess.run([sys.executable, LEDGER, *args], cwd=repo, capture_output=True, text=True,
                          encoding="utf-8")


os.makedirs(os.path.join(repo, "tests"), exist_ok=True)
os.makedirs(os.path.join(repo, "src"), exist_ok=True)
commit("plan.md", "# plan\n- AC-T1-1 Given a, When b, Then c.\n- AC-T1-2 Given x.\n- AC-T1.3 Given y.\n## Errata\n",
       "docs: plan")
commit("tests/a.test.txt", "test('AC-T1-1 given a when b then c')\ntest('AC-T1.30 other')\n", "test: a")
commit("src/x.txt", "AC-T1-2\n", "feat: x")
ledger_cmd("start", "--slug", "y", "--base", "main", "--plan", "plan.md", "--archive")
ledger_cmd("add", "--agent", "dev", "--task", "T1", "--verdict", "DONE", "--seconds", "5m")
ledger_cmd("add", "--agent", "reviewer", "--verdict", "PASS", "--minor", "1", "--origin", "design=1",
           "--seconds", "1m")
ledger_cmd("add", "--agent", "qa", "--verdict", "PASS", "--seconds", "2m")
r = gate("--base", "main")
trace = r.stdout.split("Criteria:")[1].split("\n    ")[1] if "Criteria:" in r.stdout else ""
check("a criterion of the plan with no test: NOT READY, naming only that id",
      r.returncode == 1 and "Criteria:   FAIL" in r.stdout and "AC-T1.3" in trace and "AC-T1-1" not in trace,
      r.stdout)
commit("tests/b.test.txt", "test('AC-T1.3 given y')\n", "test: b")
r = gate("--base", "main")
check("every criterion id found in a tracked non-markdown file: traceability passes",
      "Criteria:   PASS" in r.stdout, r.stdout)
commit("CLAUDE.md", claude_md(test_files="tests/*"), "docs: test files")
r = gate("--base", "main")
check("declared test files limit the search: an id only in source code is missing",
      r.returncode == 1 and "AC-T1-2" in r.stdout, r.stdout)
commit("tests/c.test.txt", "test('AC-T1-2 given x')\n", "test: c")

commit("CLAUDE.md", claude_md(test_files="tests/*", audit=False), "docs: audit")
r = gate("--base", "main")
check("a failing audit command blocks", r.returncode == 1 and "Auditoria:  FAIL" in r.stdout, r.stdout)
commit("CLAUDE.md", claude_md(test_files="tests/*", audit=True), "docs: audit fixed")

ledger_cmd("defer", "--text", "wrap long names")
r = gate("--base", "main")
check("a deferred item with no decision: NOT READY",
      r.returncode == 1 and "Ledger:     FAIL" in r.stdout and "deferred D1" in r.stdout, r.stdout)
ledger_cmd("resolve", "--id", "D1", "--decision", "user: next delivery")
ledger_cmd("mode", "autonomous")
ledger_cmd("note", "--text", "page size 50", "--validar")
r = gate("--base", "main", "--report", "feature-y")
check("all criteria traced, audit passes, deferred decided: READY",
      r.returncode == 0 and "Auditoria:  PASS" in r.stdout and "Criteria:   PASS" in r.stdout, r.stdout)
name = [entry for entry in os.listdir(os.path.join(repo, "docs", "quality-reports")) if "feature-y" in entry]
text = open(os.path.join(repo, "docs", "quality-reports", name[0]), encoding="utf-8").read() if name else ""
check("the report shows time per cycle, task and agent",
      "## Time" in text and "- Cycle 1: 8m agent time, 5m elapsed (dev 5m, reviewer 1m, qa 2m)" in text
      and "- Tasks: T1 5m" in text, text)
check("the report shows findings by origin and the deferred decisions",
      "Origins: design 1, assumption 0, plan 0, execution 0, environment 0" in text
      and "- D1 wrap long names -> user: next delivery" in text, text)
check("the report shows the mode and the VALIDAR list",
      "Mode: autonomous" in text and "## VALIDAR" in text and "- page size 50" in text, text)

sh("git", "commit", "-q", "--no-verify", "-m", "docs: quality report y")
os.makedirs(os.path.join(repo, "e2e", "flows"), exist_ok=True)
commit("plan.md", "# plan\n- AC-T1-1 a\n- AC-T1-2 b\n- AC-T1.3 c\n- AC-T2-1 d\n- AC-T2-2 e\n## Errata\n", "docs: plan T2")
commit("e2e/home.spec.txt", "test('AC-T2-1 given d')\n", "test: e2e at the folder root")
commit("e2e/flows/pay.spec.txt", "test('AC-T2-2 given e')\n", "test: e2e in a subfolder")


def criteria_with(globs):
    commit("CLAUDE.md", claude_md(test_files=globs, audit=True), f"docs: test files {globs}")
    return gate("--base", "main")


r = criteria_with("tests/* e2e/**/*.spec.txt")
check("**/ matches zero or more folders: tests at the folder root and in a subfolder are found",
      "Criteria:   PASS" in r.stdout and "warning" not in r.stdout, r.stdout)
r = criteria_with("tests/* e2e/*.spec.txt")
trace = r.stdout.split("Criteria:")[1].split("\n    ")[1] if "Criteria:" in r.stdout else ""
check("* stays within one folder: a test in a subfolder is not found",
      "Criteria:   FAIL" in r.stdout and "AC-T2-2" in trace and "AC-T2-1" not in trace, r.stdout)
r = criteria_with("./tests/* e2e/**/*.{spec,test}.txt")
check("a leading ./ and {a,b} alternatives work", "Criteria:   PASS" in r.stdout, r.stdout)
r = criteria_with("tests/* e2e/**/*.spec.txt spec/**/*.txt")
check("a glob that matches no tracked file is a warning that names it, not a failure",
      "Criteria:   PASS" in r.stdout and "warning: test glob 'spec/**/*.txt' matches no tracked file" in r.stdout,
      r.stdout)
r = criteria_with("tests/* e2e/**/*.spec.txt [!]x [z-a].txt")
check("an invalid glob is a warning that names it, not a crash",
      "Criteria:   PASS" in r.stdout and "warning: invalid test glob '[!]x'" in r.stdout
      and "warning: invalid test glob '[z-a].txt'" in r.stdout, r.stdout + r.stderr[-300:])

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
