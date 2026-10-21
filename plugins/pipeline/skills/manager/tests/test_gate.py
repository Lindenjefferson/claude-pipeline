import atexit, os, re, shutil, stat, subprocess, sys, tempfile, time

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
ledger("--agent", "reviewer", "--task", "plan", "--verdict", "PASS", "--minor", "1", "--origin", "plan=1")
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
      and "- Plan review: 1 round, 0 Critical, 0 Important, 1 Minor" in text
      and "Lessons: 1 (1 automated)" in text and "- lock before checking (check: tests/race.sql)" in text, text)
check("the report shows the lines changed per dev task, with the share of fix and cleanup",
      re.search(r"- Lines changed: .*fix-1 \d+ \(fix and cleanup \d+%", text) is not None, text)
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
ledger_cmd("add", "--agent", "dev", "--task", "T1", "--verdict", "DONE", "--seconds", "5m", "--tokens", "90000")
ledger_cmd("add", "--agent", "reviewer", "--verdict", "PASS", "--minor", "1", "--origin", "design=1",
           "--seconds", "1m", "--tokens", "30000")
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
ledger_cmd("add", "--agent", "dev", "--task", "fix-1", "--verdict", "DONE")
ledger_cmd("add", "--agent", "reviewer", "--verdict", "PASS")
ledger_cmd("mode", "autonomous")
ledger_cmd("note", "--text", "page size 50", "--validar")
ledger_cmd("note", "--text", "sort by date", "--validar")
ledger_cmd("validate", "--id", "V2", "--decision", "user: confirmed")
r = gate("--base", "main", "--report", "feature-y")
check("all criteria traced, audit passes, deferred decided: READY",
      r.returncode == 0 and "Auditoria:  PASS" in r.stdout and "Criteria:   PASS" in r.stdout, r.stdout)
name = [entry for entry in os.listdir(os.path.join(repo, "docs", "quality-reports")) if "feature-y" in entry]
text = open(os.path.join(repo, "docs", "quality-reports", name[0]), encoding="utf-8").read() if name else ""
check("the report shows time per cycle, task and agent",
      "## Time" in text and "- Cycle 1: 8m agent time, " in text
      and "elapsed (dev 5m, reviewer 1m, qa 2m)" in text and "- Tasks: T1 5m" in text, text)
check("the report shows findings by origin and the deferred decisions",
      "Origins: design 1, assumption 0, plan 0, execution 0, environment 0" in text
      and "- D1 wrap long names -> user: next delivery" in text, text)
check("the report shows the mode and the VALIDAR list, each item with the user's decision or pending",
      "Mode: autonomous" in text and "## VALIDAR" in text and "- V1 page size 50 -> pending" in text
      and "- V2 sort by date -> user: confirmed" in text, text)
check("the report shows the tokens per agent and task, and how many runs have none",
      re.search(r"- Tokens: dev 90000, reviewer 30000 \(\d+ runs? unmeasured\)", text) is not None
      and "- Task tokens: T1 90000" in text, text)

sh("git", "commit", "-q", "--no-verify", "-m", "docs: quality report y")

import importlib.util
spec = importlib.util.spec_from_file_location("gate_module", GATE)
gate_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate_module)
base_metrics = {"cycles": [], "lessons": [], "origins": {}}
lines_text = chr(10).join(gate_module.metrics_lines({**base_metrics, "lines": {
    "tasks": {"T1": 120, "T2": 40, "fix-1": 30, "cleanup": 12}, "total": 202, "follow_up": 42, "share": 0.21,
    "unmeasured": 1}}))
check("the lines line names each task, the follow-up share and the unmeasured runs",
      "- Lines changed: T1 120, T2 40, fix-1 30, cleanup 12 (fix and cleanup 21%; 1 dev run unmeasured)" in lines_text,
      lines_text)
lines_text = chr(10).join(gate_module.metrics_lines({**base_metrics, "lines": {
    "tasks": {}, "total": 0, "follow_up": 0, "share": None, "unmeasured": 2}}))
check("no line when no dev run was measured", "Lines changed" not in lines_text, lines_text)
lines_text = chr(10).join(gate_module.metrics_lines(base_metrics))
check("no line for a metrics dict without lines", "Lines changed" not in lines_text, lines_text)
lines_text = chr(10).join(gate_module.metrics_lines({**base_metrics, "lines": {
    "tasks": {"T1": 8}, "total": 8, "follow_up": 0, "share": 0.0, "unmeasured": 0}}))
check("a share of 0 prints as 0% and no unmeasured text",
      "- Lines changed: T1 8 (fix and cleanup 0%)" in lines_text, lines_text)

lines_text = chr(10).join(gate_module.metrics_lines({**base_metrics, "verdicts": {
    "needs_context": 2, "simpler": 1, "blocked": 0}}))
check("the dev questions line counts needs-context, simpler proposals and blocked",
      "- Dev questions: 2 needs-context, 1 simpler proposals, 0 blocked" in lines_text, lines_text)
for verdicts in ({"needs_context": 0, "simpler": 0, "blocked": 0}, None):
    lines_text = chr(10).join(gate_module.metrics_lines({**base_metrics, **({"verdicts": verdicts} if verdicts else {})}))
    check(f"no dev questions line with {verdicts or 'no verdicts'}", "Dev questions" not in lines_text, lines_text)

os.makedirs(os.path.join(repo, "e2e", "flows"), exist_ok=True)
commit("plan.md", "# plan\n- AC-T1-1 a\n- AC-T1-2 b\n- AC-T1.3 c\n- AC-T2-1 d\n- AC-T2-2 e\n## Errata\n", "docs: plan T2")
commit("e2e/home.spec.txt", "test('AC-T2-1 given d')\n", "test: e2e at the folder root")
commit("e2e/flows/pay.spec.txt", "test('AC-T2-2 given e')\n", "test: e2e in a subfolder")


def criteria_with(globs):
    commit("CLAUDE.md", claude_md(test_files=globs, audit=True), f"docs: test files {globs}")
    return gate("--base", "main")


r = criteria_with("tests/* e2e/**/*.spec.txt")
check("**/ matches zero or more folders: tests at the folder root and in a subfolder are found",
      "Criteria:   PASS" in r.stdout and "test glob" not in r.stdout, r.stdout)
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

commit("plan.md", "# plan\n- AC-T1-1 a\n- AC-T1-2 b\n- AC-T1.3 c\n- AC-T2-1 d\n- AC-T2-2 e\n- AC-T3-1 f\n- AC-T3-2 g\n"
       "- AC-T3.3 h\n- AC-T3-4 i\n- AC-T3-5 j\n## Errata\n", "docs: plan T3")
commit("tests/ids.test.txt", "fn ac_t3_1_given_f() {}\ndef test_AC_T3_2_given_g():\nfunc Test_AC_T3_3(t *testing.T)\n"
       "test('AC-T3-40 other')\ntest('AC-T3-4.1 other')\nfn ac_t3_5_1_given_j() {}\n", "test: identifier names")
r = criteria_with("tests/* e2e/**/*.spec.txt")
trace = r.stdout.split("Criteria:")[1].split("\n    ")[1] if "Criteria:" in r.stdout else ""
check("a test named by an identifier carries the id with _ for - and . in any case; a longer id is another id",
      "Criteria:   FAIL" in r.stdout and "AC-T3-4" in trace and "AC-T3-1" not in trace and "AC-T3-2" not in trace
      and "AC-T3.3" not in trace and "AC-T3-5" in trace, r.stdout)
commit("tests/ids.test.txt", "fn ac_t3_1_given_f() {}\ndef test_AC_T3_2_given_g():\nfunc Test_AC_T3_3(t *testing.T)\n"
       "#[test] fn ac_t3_4() {}\nfn ac_t3_5_given_j() {}\n", "test: the last ids")
r = gate("--base", "main")
check("every id found in identifier-named tests: traceability passes", "Criteria:   PASS" in r.stdout, r.stdout)

r = gate("--base", "main", "--cmd", f"Lint=CI=1 {PY} -c \"import os, sys; sys.exit(os.environ.get('CI') != '1')\"")
check("the commands run in the shell of the Bash tool: a variable before the command is set",
      re.search(r"Lint:\s+PASS", r.stdout), r.stdout)
commit("CLAUDE.md", claude_md(test_files="tests/* e2e/**/*.spec.txt", audit=True).replace(
       "\n\n## Outra seção", "\n- Tempo máximo de cada comando do gate, em minutos (padrão 15): `0.05`\n\n## Outra seção"),
       "docs: gate timeout")
marker = os.path.join(base_dir, "late.txt").replace("\\", "/")
started = time.monotonic()
r = gate("--base", "main", "--cmd", f"Lint=sleep 30; echo late > '{marker}'")
check("the Comandos line sets the time limit of each command",
      re.search(r"Lint:\s+FAIL", r.stdout) and "timed out after 3s" in r.stdout, r.stdout)
check("a command that runs past the limit is stopped there, not waited for", time.monotonic() - started < 25,
      f"{time.monotonic() - started:.0f}s")
check("the time limit line is not run as a command", "running Tempo" not in r.stdout, r.stdout)
if os.name != "nt":
    time.sleep(30 - (time.monotonic() - started) + 2)
    check("a command stopped at the limit leaves no child process running", not os.path.exists(marker))
for value in ("`inf`", "30", "`1e9`"):
    commit("CLAUDE.md", claude_md(test_files="tests/* e2e/**/*.spec.txt", audit=True).replace(
           "\n\n## Outra seção", f"\n- Tempo máximo de cada comando do gate, em minutos (padrão 15): {value}\n\n"
           "## Outra seção"), f"docs: gate time limit {value}")
    r = gate("--base", "main")
    check(f"a time limit that is no number of minutes up to a day is a warning and the default: {value}",
          "warning: invalid Tempo máximo" in r.stdout and re.search(r"Lint:\s+PASS", r.stdout),
          r.stdout + r.stderr[-300:])
commit("CLAUDE.md", claude_md(test_files="tests/* e2e/**/*.spec.txt", audit=True).replace(
       "\n\n## Outra seção", "\n- Tempo máximo de cada comando do gate, em minutos (padrão 15): _(número entre crases)_"
       "\n\n## Outra seção"), "docs: gate time limit placeholder")
r = gate("--base", "main")
check("the template's placeholder is no time limit and no warning", "warning: invalid Tempo" not in r.stdout, r.stdout)

repo = os.path.join(base_dir, "repo2")
os.makedirs(repo)
sh("git", "init", "-q", "-b", "main")
sh("git", "config", "user.email", "t@t.com")
sh("git", "config", "user.name", "t")
write(".gitignore", ".superpowers/\n")
write("check_reports.py", "import subprocess, sys\n"
      "names = subprocess.run(['git', 'ls-files', 'docs/quality-reports'], capture_output=True, text=True).stdout.split()\n"
      "sys.exit(1 if any('PRIVATE-MARK' in open(n, encoding='utf-8').read() for n in names) else 0)\n")
sh("git", "add", ".gitignore", "check_reports.py")
COMANDOS = f"# p\n\n## Comandos\n\n- Testes: `{PY} check_reports.py`\n"
commit("CLAUDE.md", COMANDOS, "base")
sh("git", "switch", "-q", "-c", "feat/z")
ledger_cmd("start", "--slug", "z", "--base", "main")
commit("src.txt", "a\n", "feat: a")


def close_cycle(task="T1"):
    ledger_cmd("add", "--agent", "dev", "--task", task, "--verdict", "DONE")
    ledger_cmd("add", "--agent", "reviewer", "--verdict", "PASS")
    ledger_cmd("add", "--agent", "qa", "--verdict", "PASS")


close_cycle()
ledger_cmd("note", "--text", "kept the PRIVATE-MARK folder out")
r = gate("--base", "main", "--report", "z")
folder = os.path.join(repo, "docs", "quality-reports")
check("the project's tests run with the quality report in place: a note they refuse makes the gate NOT READY",
      r.returncode == 1 and "Testes:     FAIL" in r.stdout, r.stdout)
check("NOT READY with --report leaves no report and a clean tree",
      not (os.path.isdir(folder) and os.listdir(folder)) and sh("git", "status", "--porcelain") == "", r.stdout)

ledger_cmd("start", "--slug", "z2", "--archive")
close_cycle()
head = sh("git", "rev-parse", "HEAD").strip()
r = gate("--report", "z2")
check("without --base the gate uses the base the ledger recorded at start",
      r.returncode == 0 and f"GATE {head[:7]}..{head[:7]}" in r.stdout, r.stdout)
check("READY with --report stages the report the tests already saw",
      "docs/quality-reports/" in sh("git", "diff", "--cached", "--name-only"), r.stdout)
sh("git", "commit", "-q", "--no-verify", "-m", "docs: quality report")
r = gate("--base", "nope")
check("an invalid --base is an error, not a silent fallback",
      r.returncode != 0 and "READY" not in r.stdout and "nope" in r.stderr, r.stdout + r.stderr)

commit("docs/lessons.md", "- lock before checking\n", "docs: lesson")
r = gate()
check("commits after the last review that touch only lessons or quality reports keep the gate READY",
      r.returncode == 0, r.stdout)
sh("git", "switch", "-q", "-c", "side", "main")
commit("side.txt", "s\n", "feat: side front")
sh("git", "switch", "-q", "feat/z")
sh("git", "merge", "-q", "--no-ff", "--no-edit", "side")
r = gate()
check("a merged front (merge commit) is not counted as an unreviewed commit", r.returncode == 0, r.stdout)
commit("late.txt", "late\n", "feat: late, no ledger entry")
r = gate()
check("a commit after the last review with no ledger entry: NOT READY, naming the file",
      r.returncode == 1 and "Reviewed:" in r.stdout and "late.txt" in r.stdout, r.stdout)
close_cycle("fix-1")
r = gate()
check("the reviewer on that commit makes the gate READY again", r.returncode == 0, r.stdout)

commit(".pipeline-secrets-allow", "# user entries\n", "chore: the user allowlists a false positive")
r = gate()
check("a commit of the secret-scan allowlist (the user's file) after the last review keeps the gate READY",
      r.returncode == 0, r.stdout)
commit("z.test.txt", "test('AC-Z1-1 given z')\n", "test: z")
commit("docs/plan.md", "# plan\n- AC-Z1-1 Given z.\n## Errata\n", "docs: plan z")
close_cycle("fix-0")
ledger_cmd("plan", "--path", os.path.join(repo, "docs", "plan.md"))
commit("docs/plan.md", "# plan\n- AC-Z1-1 Given z.\n## Errata\n- renumbered\n", "docs: errata")
r = gate()
check("an Errata commit on a plan recorded with an absolute path keeps the gate READY", r.returncode == 0, r.stdout)
os.makedirs(folder, exist_ok=True)
write(f"docs/quality-reports/{__import__('datetime').date.today().isoformat()}-left.md", "# half a report\n")
sh("git", "add", "docs/quality-reports")
r = gate("--report", "left")
check("a draft report left staged by a killed gate run is cleared by the next run of the same report",
      r.returncode == 0 and "Clean tree: PASS" in r.stdout, r.stdout)
sh("git", "commit", "-q", "--no-verify", "-m", "docs: quality report left")
r = gate("--cmd", "Testes=")
check("an empty test command is not configured: NOT READY",
      r.returncode == 1 and "Testes:     FAIL" in r.stdout and "not configured" in r.stdout, r.stdout)
r = gate("--cmd", f"Lint={PY} -c \"open('src.txt', 'a').write('x')\"")
check("a command that rewrites a tracked file: NOT READY, naming it",
      r.returncode == 1 and "Unchanged:  FAIL" in r.stdout and "src.txt" in r.stdout, r.stdout)
sh("git", "checkout", "--", "src.txt")

commit("CLAUDE.md", COMANDOS + "- Testes (e2e): `" + PY + " -c \"print('e2e ok')\"`\n"
       + "- Lint: ` `\n", "docs: e2e line")
close_cycle("fix-2")
r = gate("--report", "z3")
check("two lines with the same label both run, each under its own name",
      r.returncode == 0 and "running Testes: " in r.stdout and "running Testes (e2e): " in r.stdout
      and re.search(r"Testes \(e2e\):\s+PASS", r.stdout), r.stdout)
check("a blank command line counts as not configured", "Lint:" in r.stdout and "running Lint" not in r.stdout,
      r.stdout)
check("a Comandos section changed in the branch is a warning with the diff",
      "warning: the Comandos section of CLAUDE.md changed" in r.stdout and "+- Testes (e2e)" in r.stdout, r.stdout)
name = [entry for entry in os.listdir(folder) if "z3" in entry]
text = open(os.path.join(folder, name[0]), encoding="utf-8").read() if name else ""
check("the report shows the changed Comandos section for approval 2",
      "## Comandos changed" in text and "+- Testes (e2e)" in text, text)
sh("git", "reset", "-q", "--hard")
commit("CLAUDE.md", COMANDOS.replace("check_reports.py", "-c \"import sys; sys.exit(1)\""), "docs: failing tests")
close_cycle("fix-3")
r = gate()
check("the branch's own command still runs (the change is shown, not ignored)",
      r.returncode == 1 and "Testes:     FAIL" in r.stdout, r.stdout)

sh("git", "reset", "-q", "--hard", "HEAD~1")
commit(".env.produção", "X=1\n", "env with an accented name")
r = gate()
check("an .env file with an accented name in the branch: NOT READY",
      r.returncode == 1 and re.search(r"Secrets:\s+FAIL", r.stdout) and ".env.produ" in r.stdout, r.stdout)
sh("git", "reset", "-q", "--hard", "HEAD~1")
sh("git", "switch", "-q", "main")
commit(".env", "X=1\n", "an old mistake on main")
sh("git", "switch", "-q", "-c", "feat/drop-env")
ledger_cmd("start", "--slug", "drop", "--archive")
sh("git", "rm", "-q", ".env")
sh("git", "commit", "-q", "--no-verify", "-m", "remove the tracked env")
close_cycle()
r = gate()
check("a branch that only removes a tracked .env file passes the secret check",
      re.search(r"Secrets:\s+PASS", r.stdout), r.stdout)

sh("git", "config", "log.diffMerges", "cc")
sh("git", "switch", "-q", "-c", "side-secret")
commit("side.txt", "s\n", "feat: side")
sh("git", "switch", "-q", "feat/drop-env")
sh("git", "merge", "-q", "--no-ff", "--no-commit", "side-secret")
write("merged.txt", SECRET)
sh("git", "add", "merged.txt")
sh("git", "commit", "-q", "--no-verify", "-m", "merge with a secret added in the merge itself")
r = gate()
check("a secret added in a merge commit is found even with log.diffMerges=cc in the git config",
      re.search(r"Secrets:\s+FAIL", r.stdout) and "merged.txt" in r.stdout, r.stdout)

repo = os.path.join(base_dir, "repo3")
os.makedirs(repo)
sh("git", "init", "-q", "-b", "main")
sh("git", "config", "user.email", "t@t.com")
sh("git", "config", "user.name", "t")
write(".gitignore", ".superpowers/\n")
sh("git", "add", ".gitignore")
OK = f"`{PY} -c \"print('ok')\"`"
FULL = f"# p\n\n## Comandos\n\n- Testes: {OK}\n- Testes do banco: {OK}\n- Testes afetados: {OK}\n"
commit("CLAUDE.md", FULL, "base")
sh("git", "switch", "-q", "-c", "feat/full")
ledger_cmd("start", "--slug", "full", "--base", "main")
commit("src.txt", "a\n", "feat: a")
close_cycle()
r = gate("--base", "main")
check("a test line the gate does not run prints a warning that names it",
      'warning: the Comandos line "Testes do banco" is not run by the gate: name it "Testes (<name>)" to run it'
      in r.stdout and "running Testes do banco" not in r.stdout, r.stdout)
check("Testes afetados is no gate command and prints no warning", "Testes afetados" not in r.stdout, r.stdout)
check("Full suite is SKIP without a Verificação de interface line",
      re.search(r"Full suite:\s+SKIP", r.stdout) and "no Verificação de interface line" in r.stdout, r.stdout)
r = gate("--base", "main", "--report", "full")
reports = os.path.join(repo, "docs", "quality-reports")
text = open(os.path.join(reports, os.listdir(reports)[0]), encoding="utf-8").read() if os.path.isdir(reports) else ""
check("the warning appears in the staged report",
      r.returncode == 0 and "## Test lines not run" in text and "Testes do banco" in text, r.stdout + text)
sh("git", "commit", "-q", "--no-verify", "-m", "docs: quality report")

UI = f"- Verificação de interface: {OK}\n"
commit("CLAUDE.md", FULL + "- Testes (e2e): " + OK + "\n" + UI, "docs: e2e line")
close_cycle("fix-1")
r = gate("--base", "main")
check("Full suite is SKIP when the gate runs a Testes (e2e) line",
      re.search(r"Full suite:\s+SKIP", r.stdout) and "the gate runs the interface suite (Testes (e2e))" in r.stdout,
      r.stdout)

commit("CLAUDE.md", FULL + UI, "docs: interface line only")
close_cycle("fix-2")
r = gate("--base", "main")
check("Full suite FAILs and the gate is NOT READY when no qa ran the full suite",
      r.returncode == 1 and re.search(r"Full suite:\s+FAIL", r.stdout)
      and "no qa ran the full suite at the final head" in r.stdout
      and "dispatch qa on the full suite (every test line of Comandos and the entire interface suite)" in r.stdout,
      r.stdout)
ledger_cmd("add", "--agent", "qa", "--verdict", "PASS", "--full")
r = gate("--base", "main")
check("Full suite PASSes after a qa --full at the head", re.search(r"Full suite:\s+PASS", r.stdout)
      and r.returncode == 0, r.stdout)
commit("docs/lessons.md", "- a lesson\n", "docs: lesson")
r = gate("--base", "main")
check("Full suite still PASSes when only docs/lessons.md changed after it",
      re.search(r"Full suite:\s+PASS", r.stdout), r.stdout)
commit("late.txt", "late\n", "feat: late")
ledger_cmd("add", "--agent", "dev", "--task", "fix-3", "--verdict", "DONE")
ledger_cmd("add", "--agent", "reviewer", "--verdict", "PASS")
ledger_cmd("add", "--agent", "qa", "--verdict", "PASS")
r = gate("--base", "main")
check("Full suite FAILs when a code file changed after the full qa, naming it",
      r.returncode == 1 and re.search(r"Full suite:\s+FAIL", r.stdout) and "changed after the full qa at" in r.stdout
      and "late.txt" in r.stdout, r.stdout)

ledger_cmd("add", "--agent", "qa", "--verdict", "PASS", "--full")
full_head = sh("git", "rev-parse", "HEAD").strip()
sh("git", "switch", "-q", "-c", "front")
commit("front.txt", "f\n", "feat: front")
sh("git", "switch", "-q", "feat/full")
sh("git", "merge", "-q", "--no-ff", "-m", "merge front", "front")
r = gate("--base", "main")
check("Full suite FAILs after a --no-ff merged front changed a code file since the full qa, naming it",
      r.returncode == 1 and re.search(r"Full suite:\s+FAIL", r.stdout) and "changed after the full qa at" in r.stdout
      and "front.txt" in r.stdout, r.stdout)
check("Reviewed still ignores the merged front (first-parent log)", re.search(r"Reviewed:\s+PASS", r.stdout), r.stdout)
r = gate("--base", "main", "--cmd", f"Testes (x)={PY} -c \"print('ok')\"")
check("Full suite is SKIP when --cmd adds a Testes (x) line",
      re.search(r"Full suite:\s+SKIP", r.stdout) and "the gate runs the interface suite (Testes (x))" in r.stdout,
      r.stdout)
sh("git", "switch", "-q", "-c", "alt", full_head + "~1")
commit("alt.txt", "x\n", "feat: sibling of the full qa head")
r = gate("--base", "main")
check("Full suite FAILs when the full qa head is not in this history",
      r.returncode == 1 and re.search(r"Full suite:\s+FAIL", r.stdout)
      and f"the full qa head {full_head[:7]} is not in this history" in r.stdout, r.stdout)

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
