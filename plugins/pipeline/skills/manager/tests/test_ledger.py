import atexit, json, os, shutil, stat, subprocess, sys, tempfile

LEDGER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ledger.py")
repo = tempfile.mkdtemp(prefix="ledger_")


def cleanup():
    def retry(func, path, _):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except OSError:
            pass
    shutil.rmtree(repo, onerror=retry)


atexit.register(cleanup)
results = []


def run(*args, ledger=None):
    prefix = ["--ledger", ledger] if ledger else []
    return subprocess.run([sys.executable, LEDGER, *prefix, *args], cwd=repo, capture_output=True, text=True,
                          encoding="utf-8")


def add(agent, verdict, task=None, open_count=0, ledger=None):
    args = ["add", "--agent", agent, "--verdict", verdict, "--open", str(open_count)]
    return run(*(args + (["--task", task] if task else [])), ledger=ledger)


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("PASS" if ok else "FAIL", name, "" if ok else f"| {str(detail)[-300:]}")


def status(ledger=None):
    return json.loads(run("status", "--json", ledger=ledger).stdout)


for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@t.com"), ("config", "user.name", "t"),
             ("commit", "-q", "--allow-empty", "-m", "base")):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

check("add before start is refused", add("dev", "DONE", "T1").returncode != 0)
r = run("start", "--slug", "feature")
check("start records the base", r.returncode == 0 and "started feature" in r.stdout, r.stderr)
r = run("start", "--slug", "again")
check("start twice is refused and points to --archive", r.returncode != 0 and "--archive" in r.stderr, r.stderr)
check("unknown verdict is refused", add("dev", "PASS", "T1").returncode != 0)
check("dev needs a task", add("dev", "DONE").returncode != 0)
check("reviewer FAIL without open findings is refused", add("reviewer", "FAIL").returncode != 0)
check("reviewer PASS with open findings is refused", add("reviewer", "PASS", open_count=1).returncode != 0)

add("dev", "DONE", "T1")
add("dev", "DONE", "T2")
check("dev tasks do not need a review each: one review for the cycle",
      status()["pending"] == ["reviewer has not reviewed the latest changes"])
add("dev", "NEEDS_CONTEXT", "T3")
check("an unfinished dev task blocks the cycle", status()["pending"] == ["dev T3: NEEDS_CONTEXT"])
add("dev", "DONE", "T3")
add("reviewer", "FAIL", open_count=3)
check("reviewer FAIL sends one batch back to dev", "one batch" in status()["pending"][0])
add("dev", "DONE", "fix-1")
check("the fix needs the reviewer again", status()["pending"] == ["reviewer has not reviewed the latest changes"])
add("reviewer", "PASS")
check("after the review, qa is pending", status()["pending"] == ["qa has not run after the latest review"])
check("status --check exits 1 while the cycle is open", run("status", "--check").returncode == 1)
add("qa", "PASS")
check("qa PASS closes the cycle: ready for gate", status()["ready_for_gate"] is True)
check("status --check exits 0 when ready", run("status", "--check").returncode == 0)

add("dev", "DONE", "T4")
state = status()
check("the next dev run opens cycle 2", state["cycle"] == 2 and list(state["tasks"]) == ["T4"])
add("reviewer", "FAIL", open_count=1)
add("dev", "DONE", "fix-1")
add("reviewer", "FAIL", open_count=1)
check("a second failed review asks the user", any("ask the user" in item for item in status()["pending"]))

run("note", "--text", "minor deferred")
check("notes are listed", status()["notes"] == ["minor deferred"])
check("text status names pending items", "pending:" in run("status").stdout)

MINORS = ".superpowers/minors.jsonl"
run("start", "--slug", "minors", ledger=MINORS)
for agent, verdict, task in (("dev", "DONE", "T1"), ("reviewer", "PASS", None), ("qa", "PASS", None)):
    add(agent, verdict, task, ledger=MINORS)
add("dev", "DONE", "fix-1", ledger=MINORS)
state = status(MINORS)
check("a fix round after a closed cycle stays in that cycle", state["cycle"] == 1 and "fix-1" in state["tasks"], state)
check("the fix needs a reviewer pass on it",
      state["pending"] == ["reviewer has not reviewed the latest changes"], state["pending"])
add("reviewer", "PASS", ledger=MINORS)
state = status(MINORS)
check("qa passed before the fix: the reviewer pass on the fix closes the cycle",
      state["ready_for_gate"] is True and state["cycle"] == 1, state)
add("dev", "DONE", "T2", ledger=MINORS)
check("a regular task after the closed cycle opens the next cycle", status(MINORS)["cycle"] == 2)

QA = ".superpowers/qa.jsonl"
run("start", "--slug", "qa", ledger=QA)
for agent, verdict, task, count in (("dev", "DONE", "T1", 0), ("reviewer", "PASS", None, 0), ("qa", "FAIL", None, 2),
                                    ("dev", "DONE", "fix-1", 0)):
    add(agent, verdict, task, count, ledger=QA)
check("the fix round stays in the cycle after a qa FAIL", status(QA)["cycle"] == 1)
add("reviewer", "PASS", ledger=QA)
pending = status(QA)["pending"]
check("qa failed in the cycle: after the fix review, qa re-runs the failed scenarios",
      pending == ["qa has not re-run the scenarios that failed"], pending)
add("qa", "PASS", ledger=QA)
check("qa PASS after the fix closes the cycle", status(QA)["ready_for_gate"] is True)

FIRST = ".superpowers/first.jsonl"
run("start", "--slug", "first", ledger=FIRST)
for agent, verdict, task, count in (("dev", "DONE", "T1", 0), ("reviewer", "FAIL", None, 1),
                                    ("dev", "DONE", "fix-1", 0), ("reviewer", "PASS", None, 0)):
    add(agent, verdict, task, count, ledger=FIRST)
check("no qa yet in the cycle: qa still runs after the fix review",
      status(FIRST)["pending"] == ["qa has not run after the latest review"], status(FIRST)["pending"])

ARCHIVE = ".superpowers/archive/ledger.jsonl"
run("start", "--slug", "old/one", ledger=ARCHIVE)
add("dev", "DONE", "T1", ledger=ARCHIVE)
r = run("start", "--slug", "next", "--archive", ledger=ARCHIVE)
archived = os.path.join(repo, ".superpowers", "archive", "ledger-old-one.jsonl")
check("start --archive moves the old delivery next to the ledger and starts fresh",
      r.returncode == 0 and os.path.exists(archived) and status(ARCHIVE)["slug"] == "next"
      and status(ARCHIVE)["tasks"] == {}, r.stderr)
run("start", "--slug", "old/one", "--archive", ledger=ARCHIVE)
run("start", "--slug", "third", "--archive", ledger=ARCHIVE)
r = run("start", "--slug", "fourth", "--archive", ledger=ARCHIVE)
folder = sorted(os.listdir(os.path.join(repo, ".superpowers", "archive")))
check("archiving never overwrites an earlier archive",
      r.returncode == 0 and folder == ["ledger-next.jsonl", "ledger-old-one-2.jsonl", "ledger-old-one.jsonl",
                                       "ledger-third.jsonl", "ledger.jsonl"], folder)

METRICS = ".superpowers/metrics.jsonl"
run("start", "--slug", "metrics", ledger=METRICS)
add("dev", "DONE", "T1", ledger=METRICS)
r = run("add", "--agent", "reviewer", "--verdict", "FAIL", "--open", "2", "--critical", "1", "--important", "2",
        ledger=METRICS)
check("--open that disagrees with --critical + --important is refused", r.returncode != 0, r.stdout)
r = run("add", "--agent", "reviewer", "--verdict", "FAIL", "--critical", "1", "--important", "2", "--minor", "3",
        ledger=METRICS)
check("--critical and --important stand in for --open", r.returncode == 0, r.stderr)
add("dev", "DONE", "fix-1", ledger=METRICS)
run("add", "--agent", "reviewer", "--verdict", "PASS", "--minor", "1", ledger=METRICS)
add("qa", "FAIL", open_count=1, ledger=METRICS)
add("dev", "DONE", "fix-2", ledger=METRICS)
add("reviewer", "PASS", ledger=METRICS)
add("qa", "PASS", ledger=METRICS)
add("dev", "DONE", "T2", ledger=METRICS)
add("reviewer", "PASS", ledger=METRICS)
add("qa", "PASS", ledger=METRICS)
run("lesson", "--text", "lock the parent row before checking it", "--check", "tests/race.sql", ledger=METRICS)
run("lesson", "--text", "name buttons with a verb", ledger=METRICS)
metrics = status(METRICS)["metrics"]
check("metrics count findings and fix rounds per cycle",
      metrics["cycles"] == [{"cycle": 1, "critical": 1, "important": 2, "minor": 4, "open": 4, "fix_rounds": 2},
                            {"cycle": 2, "critical": 0, "important": 0, "minor": 0, "open": 0, "fix_rounds": 0}],
      metrics)
check("metrics list lessons, automated or written",
      metrics["lessons"] == [{"text": "lock the parent row before checking it", "check": "tests/race.sql"},
                             {"text": "name buttons with a verb", "check": ""}], metrics)

run("note", "--text", "decisão não óbvia")
raw = subprocess.run([sys.executable, LEDGER, "status"], cwd=repo, capture_output=True,
                     env={**os.environ, "PYTHONIOENCODING": "latin-1", "PYTHONUTF8": "0"})
try:
    utf8 = "decisão não óbvia" in raw.stdout.decode("utf-8")
except UnicodeDecodeError:
    utf8 = False
check("status prints UTF-8 whatever the console encoding", utf8, raw.stdout[-200:])

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
