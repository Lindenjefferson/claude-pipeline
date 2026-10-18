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


def run(*args, ledger=None, cwd=None):
    prefix = ["--ledger", ledger] if ledger else []
    return subprocess.run([sys.executable, LEDGER, *prefix, *args], cwd=cwd or repo, capture_output=True, text=True,
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
      and state["metrics"]["time"]["unmeasured"] == 5 and state["plan"] is None and state["deferred"] == []
      and state["autonomous"] is False and state["validar"] == [], state)

AUTO = ".superpowers/auto.jsonl"
check("mode before start is refused", run("mode", "autonomous", ledger=AUTO).returncode != 0)
run("start", "--slug", "auto", ledger=AUTO)
check("a delivery starts supervised", status(AUTO)["autonomous"] is False, status(AUTO))
check("an unknown mode is refused", run("mode", "yolo", ledger=AUTO).returncode != 0)
r = run("mode", "autonomous", ledger=AUTO)
check("mode autonomous is recorded and status says so",
      r.returncode == 0 and status(AUTO)["autonomous"] is True and "autonomous" in run("status", ledger=AUTO).stdout,
      r.stderr)
for agent, verdict, task, count in (("dev", "DONE", "T1", 0), ("reviewer", "FAIL", None, 1),
                                    ("dev", "DONE", "fix-1", 0), ("reviewer", "FAIL", None, 1)):
    add(agent, verdict, task, count, ledger=AUTO)
pending = status(AUTO)["pending"]
check("autonomous: a second failed review does not stop for the user, the fix rounds go on",
      not any("ask the user" in item for item in pending) and any("one batch" in item for item in pending), pending)
run("mode", "supervised", ledger=AUTO)
check("back to supervised: the same cycle asks the user again",
      any("ask the user" in item for item in status(AUTO)["pending"]), status(AUTO)["pending"])
run("note", "--text", "page size 50", "--validar", ledger=AUTO)
run("note", "--text", "ruled out a finding", ledger=AUTO)
state = status(AUTO)
check("note --validar goes to the VALIDAR list with an id, apart from plain notes",
      state["validar"] == [{"id": "V1", "text": "page size 50", "decision": None}]
      and state["notes"] == ["ruled out a finding"], state)
text = run("status", ledger=AUTO).stdout
check("text status shows the VALIDAR list with ids", "VALIDAR V1: page size 50" in text, text)
run("note", "--text", "sort by date", "--validar", ledger=AUTO)
r = run("validate", "--id", "V2", "--decision", "user: sort by name", ledger=AUTO)
state = status(AUTO)
check("validate records the user's decision on a VALIDAR item",
      r.returncode == 0 and state["validar"][1] == {"id": "V2", "text": "sort by date", "decision": "user: sort by name"}
      and state["validar"][0]["decision"] is None, (r.stderr, state["validar"]))
text = run("status", ledger=AUTO).stdout
check("text status lists only the pending VALIDAR items, and the decided ones apart",
      "VALIDAR V1: page size 50" in text and "VALIDAR V2" not in text
      and "validated V2: sort by date -> user: sort by name" in text, text)
check("validate with an empty decision is refused",
      run("validate", "--id", "V1", "--decision", "  ", ledger=AUTO).returncode != 0
      and status(AUTO)["validar"][0]["decision"] is None)
check("validate of an unknown id is refused",
      run("validate", "--id", "V9", "--decision", "x", ledger=AUTO).returncode != 0)
run("mode", "autonomous", ledger=AUTO)
text = run("status", ledger=AUTO).stdout
check("text status says autonomous mode never merges into nor pushes the default branch",
      "never merge into or push the default branch" in text, text)

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
check("status --json gives the dispatch time of each task in flight",
      sorted(state["dispatched"]) == ["T1", "T2"] and all(state["dispatched"].values()), state)
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

WAIVE = ".superpowers/waive.jsonl"
run("start", "--slug", "waive", ledger=WAIVE)
for agent, verdict, task, count in (("dev", "DONE", "T1", 0), ("reviewer", "FAIL", None, 1), ("qa", "PASS", None, 0)):
    add(agent, verdict, task, count, ledger=WAIVE)
r = run("waive", "--agent", "qa", "--reason", "x", ledger=WAIVE)
check("waive refuses an agent whose latest run is not a FAIL", r.returncode != 0 and "FAIL" in r.stderr, r.stderr)
check("waive needs a reason", run("waive", "--agent", "reviewer", ledger=WAIVE).returncode != 0)
unmeasured = status(WAIVE)["metrics"]["time"]["unmeasured"]
failed_head = status(WAIVE)["reviewer"][0]["head"]
subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "after the review"], cwd=repo, check=True,
               capture_output=True)
r = run("waive", "--agent", "reviewer", "--reason", "the finding is wrong: the caller validates", ledger=WAIVE)
state = status(WAIVE)
check("waive accepts the open findings of the latest FAIL: the cycle closes and the ruling is a note",
      r.returncode == 0 and state["ready_for_gate"] is True
      and state["notes"] == ["waived reviewer FAIL: the finding is wrong: the caller validates"], (r.stderr, state))
check("a waiver is not an agent run in the time metrics",
      state["metrics"]["time"]["unmeasured"] == unmeasured, state["metrics"]["time"])
check("a waiver keeps the head the agent reviewed",
      state["reviewer"][0].get("waived") and state["reviewer"][0]["head"] == failed_head, state["reviewer"])
WAIVE2 = ".superpowers/waive2.jsonl"
run("start", "--slug", "waive2", ledger=WAIVE2)
for agent, verdict, task, count in (("dev", "DONE", "T1", 0), ("reviewer", "FAIL", None, 1), ("dev", "DONE", "fix-1", 0)):
    add(agent, verdict, task, count, ledger=WAIVE2)
r = run("waive", "--agent", "reviewer", "--reason", "x", ledger=WAIVE2)
check("waive refuses a FAIL that a later dev run already answered: the fix needs its review",
      r.returncode != 0 and "review" in r.stderr, r.stderr)
run("mode", "autonomous", ledger=WAIVE2)
add("reviewer", "FAIL", None, 1, ledger=WAIVE2)
run("waive", "--agent", "reviewer", "--reason", "ruled out", ledger=WAIVE2)
check("in autonomous mode a waiver goes to the VALIDAR list",
      [item["text"] for item in status(WAIVE2)["validar"]] == ["waived reviewer FAIL: ruled out"], status(WAIVE2))

CAP = ".superpowers/cap.jsonl"
run("start", "--slug", "cap", ledger=CAP)
run("mode", "autonomous", ledger=CAP)
add("dev", "DONE", "T1", ledger=CAP)
add("reviewer", "FAIL", None, 1, ledger=CAP)
for number in (1, 2):
    add("dev", "DONE", f"fix-{number}", ledger=CAP)
    add("reviewer", "FAIL", None, 1, ledger=CAP)
check("autonomous: the fix rounds go on up to the third",
      not any("stop the delivery" in item for item in status(CAP)["pending"]), status(CAP)["pending"])
add("dev", "DONE", "fix-3", ledger=CAP)
add("reviewer", "FAIL", None, 1, ledger=CAP)
check("autonomous: still failing after three fix rounds stops the delivery",
      any("stop the delivery" in item and "note --validar" in item for item in status(CAP)["pending"]),
      status(CAP)["pending"])

PLAN = ".superpowers/plan.jsonl"
check("plan before start is refused", run("plan", "--path", "x.md", ledger=PLAN).returncode != 0)
run("start", "--slug", "plan", ledger=PLAN)
check("a delivery started before its plan has no plan yet", status(PLAN)["plan"] is None)
r = run("plan", "--path", "docs/plans/plan.md", ledger=PLAN)
check("plan records the approved plan for the gate", r.returncode == 0 and status(PLAN)["plan"] == "docs/plans/plan.md",
      r.stderr)

INPUT = ".superpowers/input.jsonl"
run("start", "--slug", "input", ledger=INPUT)
add("dev", "DONE", "T1", ledger=INPUT)
r = run("add", "--agent", "reviewer", "--verdict", "PASS", "--critical", "1", "--important", "-1", "--origin",
        "execution=0", ledger=INPUT)
check("a negative finding count is refused", r.returncode != 0, r.stdout)
for text in ("1h30", "12m30", "1h5", "m", "h"):
    check(f"--seconds {text} without the unit of its last number is refused",
          add("dev", "DONE", "T2", ledger=INPUT, seconds=text).returncode != 0)
for text, expected in (("90", 90), ("1h", 3600), ("1h30m", 5400), ("12m30s", 750), ("45s", 45)):
    add("dev", "DONE", f"S{expected}", ledger=INPUT, seconds=text)
check("durations with units are read", status(INPUT)["metrics"]["time"]["tasks"] == {
    "S90": 90, "S3600": 3600, "S5400": 5400, "S750": 750, "S45": 45}, status(INPUT)["metrics"]["time"]["tasks"])
with open(os.path.join(repo, INPUT), "a", encoding="utf-8") as handle:
    handle.write('{"type": "note", "text": "cut sh\n')
r = run("status", ledger=INPUT)
check("a truncated ledger line stops every command with its line number, not a traceback",
      r.returncode != 0 and "Traceback" not in r.stderr and ":8:" in r.stderr, r.stderr)

worktrees = tempfile.mkdtemp(prefix="ledger_wt_")
atexit.register(shutil.rmtree, worktrees, True)
task_tree, front_tree = os.path.join(worktrees, "task"), os.path.join(worktrees, "front")
for tree in (task_tree, front_tree):
    subprocess.run(["git", "worktree", "add", "-q", "--detach", tree], cwd=repo, check=True, capture_output=True)


def slug_at(cwd):
    try:
        return json.loads(run("status", "--json", cwd=cwd).stdout)["slug"]
    except ValueError:
        return None


os.makedirs(os.path.join(repo, "src", "deep"), exist_ok=True)
check("from a subfolder, the ledger of the worktree root is used", slug_at(os.path.join(repo, "src", "deep")) == "feature")
r = run("claim", "--task", "W1", cwd=task_tree)
check("from a task worktree with no ledger, claim writes to the main worktree's ledger",
      r.returncode == 0 and "W1" in status()["in_flight"], r.stderr)
run("release", "--task", "W1", cwd=task_tree)
subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "task commit"], cwd=task_tree, check=True,
               capture_output=True)
run("add", "--agent", "dev", "--task", "W2", "--verdict", "DONE", cwd=task_tree)
main_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
check("a run added from a task worktree records the head of the worktree that owns the ledger",
      [entry for entry in map(json.loads, open(os.path.join(repo, ".superpowers", "ledger.jsonl"), encoding="utf-8"))
       if entry.get("task") == "W2"][0]["head"] == main_head)
r = run("start", "--slug", "front", cwd=front_tree)
check("start in a worktree creates that worktree's own ledger",
      r.returncode == 0 and os.path.exists(os.path.join(front_tree, ".superpowers", "ledger.jsonl")), r.stderr)
check("a front worktree with its own ledger keeps using it",
      slug_at(front_tree) == "front" and status()["slug"] == "feature")

run("note", "--text", "decisão não óbvia")
raw = subprocess.run([sys.executable, LEDGER, "status"], cwd=repo, capture_output=True,
                     env={**os.environ, "PYTHONIOENCODING": "latin-1", "PYTHONUTF8": "0"})
try:
    utf8 = "decisão não óbvia" in raw.stdout.decode("utf-8")
except UnicodeDecodeError:
    utf8 = False
check("status prints UTF-8 whatever the console encoding", utf8, raw.stdout[-200:])

TOKENS = ".superpowers/tokens.jsonl"
run("start", "--slug", "tokens", ledger=TOKENS)
r = run("add", "--agent", "dev", "--task", "T1", "--verdict", "DONE", "--seconds", "211", "--tokens", "98357",
        ledger=TOKENS)
run("add", "--agent", "reviewer", "--verdict", "PASS", "--tokens", "40000", ledger=TOKENS)
run("add", "--agent", "dev", "--task", "fix-1", "--verdict", "DONE", ledger=TOKENS)
tokens = status(TOKENS)["metrics"]["tokens"]
check("add --tokens records the tokens of a run, summed per agent, task and cycle",
      r.returncode == 0 and tokens["agents"] == {"dev": 98357, "reviewer": 40000} and tokens["tasks"] == {"T1": 98357}
      and status(TOKENS)["metrics"]["cycles"][0]["tokens"] == 138357 and tokens["unmeasured"] == 1, (r.stderr, tokens))
state = status(TOKENS)
check("status --json gives the ledger's path and the current cycle's runs, for a progress table",
      os.path.samefile(state["ledger"], os.path.join(repo, TOKENS))
      and [(run["agent"], run["task"], run["verdict"], run.get("seconds"), run.get("tokens")) for run in state["runs"]]
      == [("dev", "T1", "DONE", 211, 98357), ("reviewer", "", "PASS", None, 40000), ("dev", "fix-1", "DONE", None, None)],
      state.get("runs"))
for bad in ("-5", "many", "1.5"):
    check(f"--tokens {bad} is refused", run("add", "--agent", "dev", "--task", "T2", "--verdict", "DONE", "--tokens", bad,
                                            ledger=TOKENS).returncode != 0)
legacy = status(".superpowers/legacy.jsonl")
check("an old ledger without tokens reads with no tokens measured",
      legacy["metrics"]["tokens"]["agents"] == {} and legacy["dispatched"] == {}, legacy["metrics"])

STEPS = ".superpowers/steps.jsonl"
run("start", "--slug", "steps", ledger=STEPS)
check("status --json gives the next steps as data: no dev task yet", status(STEPS)["steps"] == [{"step": "dev"}],
      status(STEPS).get("steps"))
add("dev", "NEEDS_CONTEXT", "T1", ledger=STEPS)
check("an unfinished task is a dev step with its verdict",
      status(STEPS)["steps"] == [{"step": "dev", "task": "T1", "verdict": "NEEDS_CONTEXT"}], status(STEPS)["steps"])
add("dev", "DONE", "T1", ledger=STEPS)
check("after the tasks, the steps are the review and qa", status(STEPS)["steps"] == [{"step": "reviewer"}, {"step": "qa"}],
      status(STEPS)["steps"])
add("reviewer", "FAIL", open_count=2, ledger=STEPS)
add("qa", "PASS", ledger=STEPS)
check("a failed review is a fix step with the agent and its open findings",
      status(STEPS)["steps"] == [{"step": "fix", "agent": "reviewer", "open": 2}], status(STEPS)["steps"])
add("dev", "DONE", "fix-1", ledger=STEPS)
check("after a fix of a FAIL, the steps are the review and the qa re-run",
      status(STEPS)["steps"] == [{"step": "reviewer"}, {"step": "qa", "rerun": True}], status(STEPS)["steps"])
add("reviewer", "FAIL", open_count=1, ledger=STEPS)
check("a review still failing after the fix round asks the user (supervised)",
      {"step": "ask", "agent": "reviewer"} in status(STEPS)["steps"], status(STEPS)["steps"])
run("claim", "--task", "T2", ledger=STEPS)
run("defer", "--text", "page size", ledger=STEPS)
steps = status(STEPS)["steps"]
check("a task in flight is no step (the band shows it running), a deferred item with no decision is",
      not any(step.get("task") == "T2" for step in steps) and {"step": "decide", "id": "D1", "text": "page size"} in steps,
      steps)

SCOPE = ".superpowers/scope.jsonl"
check("scope before start is refused",
      run("scope", "--cycle", "1", "--tasks", "T1", ledger=".superpowers/none.jsonl").returncode != 0)
run("start", "--slug", "scope", ledger=SCOPE)
check("a ledger with no scope has none in status", status(SCOPE)["scope"] is None, status(SCOPE).get("scope"))
for name, tasks in (("1", "T1.1, T1.2"), ("R", "TR.1"), ("2", "T2.1")):
    r = run("scope", "--cycle", name, "--tasks", tasks, ledger=SCOPE)
check("scope records the tasks of one plan cycle", r.returncode == 0 and "2" in r.stdout, r.stderr)
check("status --json gives the plan cycles in order, the tasks left, and where the delivery is",
      status(SCOPE)["scope"] == {"cycles": [{"cycle": "1", "tasks": ["T1.1", "T1.2"], "left": ["T1.1", "T1.2"]},
                                            {"cycle": "R", "tasks": ["TR.1"], "left": ["TR.1"]},
                                            {"cycle": "2", "tasks": ["T2.1"], "left": ["T2.1"]}],
                                 "current": "1", "position": 1, "total": 3, "tasks_left": 4, "cycles_left": 3},
      status(SCOPE)["scope"])
run("scope", "--cycle", "R", "--tasks", "TR.1,TR.2", ledger=SCOPE)
run("scope", "--cycle", "2", "--tasks", "", ledger=SCOPE)
scope = status(SCOPE)["scope"]
check("scope again replaces that cycle in place, and with no tasks removes it",
      [(item["cycle"], item["tasks"]) for item in scope["cycles"]] == [("1", ["T1.1", "T1.2"]), ("R", ["TR.1", "TR.2"])]
      and scope["total"] == 2, scope)
add("dev", "DONE", "T1.1", ledger=SCOPE)
add("dev", "DONE_WITH_CONCERNS", "T1.2", ledger=SCOPE)
scope = status(SCOPE)["scope"]
check("a cycle whose tasks are done still counts as left until its review and qa pass",
      scope["tasks_left"] == 2 and scope["cycles_left"] == 2 and scope["current"] == "1", scope)
add("reviewer", "PASS", ledger=SCOPE)
add("qa", "PASS", ledger=SCOPE)
check("a closed cycle is no longer left", status(SCOPE)["scope"]["cycles_left"] == 1, status(SCOPE)["scope"])
run("claim", "--task", "TR.1", ledger=SCOPE)
scope = status(SCOPE)["scope"]
check("the current cycle is the one of the task in flight or the latest task",
      scope["current"] == "R" and scope["position"] == 2, scope)

REDO = ".superpowers/redo.jsonl"
run("start", "--slug", "redo", ledger=REDO)
add("dev", "BLOCKED", "T1", ledger=REDO)
run("claim", "--task", "T1", ledger=REDO)
redo = status(REDO)
check("a task sent back to the dev and in flight again is no step and no pending verdict",
      redo["in_flight"] == ["T1"] and not any(step.get("task") == "T1" for step in redo["steps"])
      and not any(item.startswith("dev T1: BLOCKED") for item in redo["pending"]), redo)

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
