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


def add(agent, verdict, task=None, open_count=0, ledger=None, seconds=None):
    args = ["add", "--agent", agent, "--verdict", verdict]
    if open_count:
        args += ["--important", str(open_count), "--origin", f"execution={open_count}"]
    if seconds is not None:
        args += ["--seconds", str(seconds)]
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
      status()["pending"][0] == "reviewer has not reviewed the latest changes")
add("dev", "NEEDS_CONTEXT", "T3")
check("an unfinished dev task blocks the cycle", status()["pending"] == ["dev T3: NEEDS_CONTEXT"])
add("dev", "DONE", "T3")
check("reviewer and qa run in parallel: both pending after the tasks",
      status()["pending"] == ["reviewer has not reviewed the latest changes", "qa has not run on the cycle's tasks"],
      status()["pending"])
add("reviewer", "FAIL", open_count=3)
add("qa", "PASS")
check("reviewer FAIL sends one batch back to dev while qa already passed",
      len(status()["pending"]) == 1 and "one batch" in status()["pending"][0], status()["pending"])
add("dev", "DONE", "fix-1")
check("the fix of a blocking finding needs the reviewer and qa on the scenarios it touched",
      status()["pending"] == ["reviewer has not reviewed the latest changes",
                              "qa has not re-run the scenarios the fix touched"], status()["pending"])
add("reviewer", "PASS")
check("after the fix review, qa still re-runs the touched scenarios",
      status()["pending"] == ["qa has not re-run the scenarios the fix touched"], status()["pending"])
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
      pending == ["qa has not re-run the scenarios the fix touched"], pending)
add("qa", "PASS", ledger=QA)
check("qa PASS after the fix closes the cycle", status(QA)["ready_for_gate"] is True)

FIRST = ".superpowers/first.jsonl"
run("start", "--slug", "first", ledger=FIRST)
for agent, verdict, task, count in (("dev", "DONE", "T1", 0), ("reviewer", "FAIL", None, 1),
                                    ("dev", "DONE", "fix-1", 0), ("reviewer", "PASS", None, 0)):
    add(agent, verdict, task, count, ledger=FIRST)
check("no qa yet in the cycle: qa still runs on the cycle's tasks",
      status(FIRST)["pending"] == ["qa has not run on the cycle's tasks"], status(FIRST)["pending"])

ORDER = ".superpowers/order.jsonl"
run("start", "--slug", "order", ledger=ORDER)
for agent, verdict, task in (("dev", "DONE", "T1"), ("qa", "PASS", None), ("reviewer", "PASS", None)):
    add(agent, verdict, task, ledger=ORDER)
check("qa may finish before the reviewer", status(ORDER)["ready_for_gate"] is True, status(ORDER)["pending"])
for agent, verdict, task, count in (("dev", "DONE", "T2", 0), ("reviewer", "FAIL", None, 1), ("qa", "PASS", None, 0),
                                    ("dev", "DONE", "fix-1", 0), ("reviewer", "PASS", None, 0),
                                    ("qa", "PASS", None, 0), ("dev", "DONE", "fix-2", 0)):
    add(agent, verdict, task, count, ledger=ORDER)
check("a later fix of Minors only needs the reviewer, not qa",
      status(ORDER)["pending"] == ["reviewer has not reviewed the latest changes"], status(ORDER)["pending"])
add("dev", "DONE", "cleanup", ledger=ORDER)
add("reviewer", "PASS", ledger=ORDER)
state = status(ORDER)
check("the cleanup task stays in the cycle and needs only the reviewer",
      state["cycle"] == 2 and "cleanup" in state["tasks"] and state["ready_for_gate"] is True, state)
check("cleanup is not a fix round", state["metrics"]["cycles"][1]["fix_rounds"] == 2, state["metrics"])

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
r = run("add", "--agent", "reviewer", "--verdict", "FAIL", "--critical", "1", "--important", "2", "--minor", "3",
        ledger=METRICS)
check("findings without an origin are refused", r.returncode != 0 and "--origin" in r.stderr, r.stderr)
r = run("add", "--agent", "reviewer", "--verdict", "FAIL", "--critical", "1", "--important", "2", "--minor", "3",
        "--origin", "design=2,plan=1", ledger=METRICS)
check("origins that do not add up to the findings are refused", r.returncode != 0, r.stderr)
r = run("add", "--agent", "reviewer", "--verdict", "FAIL", "--critical", "1", "--important", "2", "--minor", "3",
        "--origin", "design=5,luck=1", ledger=METRICS)
check("an unknown origin is refused", r.returncode != 0 and "luck" in r.stderr, r.stderr)
r = run("add", "--agent", "reviewer", "--verdict", "FAIL", "--critical", "1", "--important", "2", "--minor", "3",
        "--origin", "design=3,assumption=1,plan=1,execution=1", "--seconds", "4m", ledger=METRICS)
check("findings split by severity and origin are recorded", r.returncode == 0, r.stderr)
add("dev", "DONE", "fix-1", ledger=METRICS, seconds="10m30s")
run("add", "--agent", "reviewer", "--verdict", "PASS", "--minor", "1", "--origin", "environment=1", "--seconds", "60",
    ledger=METRICS)
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
cycle_counts = [{key: cycle[key] for key in ("cycle", "critical", "important", "minor", "open", "fix_rounds")}
                for cycle in metrics["cycles"]]
check("metrics count findings and fix rounds per cycle",
      cycle_counts == [{"cycle": 1, "critical": 1, "important": 3, "minor": 4, "open": 4, "fix_rounds": 2},
                       {"cycle": 2, "critical": 0, "important": 0, "minor": 0, "open": 0, "fix_rounds": 0}],
      metrics)
check("metrics classify findings by origin",
      metrics["origins"] == {"design": 3, "assumption": 1, "plan": 1, "execution": 2, "environment": 1,
                             "unclassified": 0}, metrics["origins"])
time = metrics["time"]
check("metrics add up measured time per agent, task and cycle",
      time["agents"] == {"reviewer": 300, "dev": 630} and time["tasks"] == {"fix-1": 630}
      and metrics["cycles"][0]["seconds"] == 930 and time["unmeasured"] == 8, time)
r = add("dev", "DONE", "T9", ledger=METRICS, seconds="soon")
check("an unreadable duration is refused", r.returncode != 0, r.stderr)
check("metrics list lessons, automated or written",
      metrics["lessons"] == [{"text": "lock the parent row before checking it", "check": "tests/race.sql"},
                             {"text": "name buttons with a verb", "check": ""}], metrics)

DEFER = ".superpowers/defer.jsonl"
run("start", "--slug", "defer", "--plan", "docs/plans/defer.md", ledger=DEFER)
check("start records the plan path", status(DEFER)["plan"] == "docs/plans/defer.md", status(DEFER))
for agent, verdict, task in (("dev", "DONE", "T1"), ("reviewer", "PASS", None), ("qa", "PASS", None)):
    add(agent, verdict, task, ledger=DEFER)
r = run("defer", "--text", "long names wrap badly at the smallest width", ledger=DEFER)
check("defer gives the item an id", r.returncode == 0 and "D1" in r.stdout, r.stdout + r.stderr)
state = status(DEFER)
check("an undecided deferred item blocks the gate",
      state["ready_for_gate"] is False and any("D1" in item for item in state["pending"])
      and run("status", "--check", ledger=DEFER).returncode == 1, state)
check("resolve refuses an unknown id",
      run("resolve", "--id", "D7", "--decision", "x", ledger=DEFER).returncode != 0)
run("resolve", "--id", "D1", "--decision", "user: backlog item 12", ledger=DEFER)
state = status(DEFER)
check("a decided deferred item no longer blocks and keeps its decision",
      state["ready_for_gate"] is True and state["deferred"] == [
          {"id": "D1", "text": "long names wrap badly at the smallest width", "decision": "user: backlog item 12"}],
      state)

LEGACY = os.path.join(repo, ".superpowers", "legacy.jsonl")
with open(LEGACY, "w", encoding="utf-8", newline="\n") as handle:
    for entry in ({"type": "start", "slug": "old", "base": "abc"},
                  {"type": "run", "agent": "dev", "task": "T1", "verdict": "DONE", "open": 0},
                  {"type": "run", "agent": "reviewer", "task": "", "verdict": "FAIL", "open": 2, "critical": 1,
                   "important": 1, "minor": 1},
                  {"type": "run", "agent": "dev", "task": "fix-1", "verdict": "DONE", "open": 0},
                  {"type": "run", "agent": "reviewer", "task": "", "verdict": "PASS", "open": 0},
                  {"type": "run", "agent": "qa", "task": "", "verdict": "PASS", "open": 0}):
        handle.write(json.dumps({**entry, "head": "", "summary": "", "at": "2026-10-01T10:00:00+00:00"}) + "\n")
state = status(".superpowers/legacy.jsonl")
check("a 2.2 ledger is still read: closed cycle, findings unclassified, time unmeasured",
      state["ready_for_gate"] is True and state["metrics"]["origins"]["unclassified"] == 3
      and state["metrics"]["time"]["unmeasured"] == 5 and state["plan"] is None and state["deferred"] == [], state)

CLAIMS = ".superpowers/claims.jsonl"
run("start", "--slug", "claims", ledger=CLAIMS)
check("claim before start is refused", run("claim", "--task", "T1", ledger=".superpowers/none.jsonl").returncode != 0)
r = run("claim", "--task", "T1", ledger=CLAIMS)
check("claim records the dispatch", r.returncode == 0 and "T1" in r.stdout, r.stderr)
r = run("claim", "--task", "T1", ledger=CLAIMS)
check("a second claim on the same task fails and says how to release", r.returncode != 0
      and "already claimed" in r.stderr and "release --task T1" in r.stderr, r.stderr)
check("another task can be claimed in parallel", run("claim", "--task", "T2", ledger=CLAIMS).returncode == 0)
state = status(CLAIMS)
check("status lists what is in flight and the gate waits", sorted(state["in_flight"]) == ["T1", "T2"]
      and state["ready_for_gate"] is False and any("T1" in item and "no report" in item for item in state["pending"]), state)
check("status --check fails while something is in flight", run("status", "--check", ledger=CLAIMS).returncode == 1)
add("dev", "DONE", "T1", ledger=CLAIMS)
state = status(CLAIMS)
check("add on the task releases its claim", state["in_flight"] == ["T2"], state)
r = run("claim", "--task", "T1", ledger=CLAIMS)
check("a task already done in the cycle cannot be claimed again", r.returncode != 0 and "already done" in r.stderr,
      r.stderr)
r = run("release", "--task", "T2", ledger=CLAIMS)
check("release frees a lost run", r.returncode == 0 and status(CLAIMS)["in_flight"] == [], r.stderr)
check("release without a claim is refused", run("release", "--task", "T2", ledger=CLAIMS).returncode != 0)
run("claim", "--task", "T3", ledger=CLAIMS)
add("dev", "NEEDS_CONTEXT", "T3", ledger=CLAIMS)
check("a task that came back NEEDS_CONTEXT can be claimed again", run("claim", "--task", "T3", ledger=CLAIMS).returncode == 0)
check("an old ledger without claims has an empty in-flight list", status(".superpowers/legacy.jsonl")["in_flight"] == [])

run("note", "--text", "decisão não óbvia")
raw = subprocess.run([sys.executable, LEDGER, "status"], cwd=repo, capture_output=True,
                     env={**os.environ, "PYTHONIOENCODING": "latin-1", "PYTHONUTF8": "0"})
try:
    utf8 = "decisão não óbvia" in raw.stdout.decode("utf-8")
except UnicodeDecodeError:
    utf8 = False
check("status prints UTF-8 whatever the console encoding", utf8, raw.stdout[-200:])

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
