import atexit, datetime, json, os, re, shutil, stat, subprocess, sys, tempfile

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


def head():
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()


def report_file(name, verdict="PASS", commit=None, lines=None):
    """A saved report; a qa report needs these lines, so every one written here has them unless lines says otherwise."""
    path = f".superpowers/reports/{name}"
    os.makedirs(os.path.join(repo, ".superpowers", "reports"), exist_ok=True)
    body = lines if lines is not None else [f"Verdict: {verdict}", f"Commit: {(commit or head())[:7]}",
                                            "Interface: n/a", "Processes: none left running"]
    with open(os.path.join(repo, path), "w", encoding="utf-8") as handle:
        handle.write("\n".join(body) + "\n")
    return path


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
folder = sorted(name for name in os.listdir(os.path.join(repo, ".superpowers", "archive"))
                if name.endswith(".jsonl"))
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
clocked = metrics["time"]
check("metrics add up measured time per agent, task and cycle",
      clocked["agents"] == {"reviewer": 300, "dev": 630} and clocked["tasks"] == {"fix-1": 630}
      and metrics["cycles"][0]["seconds"] == 930 and clocked["unmeasured"] == 8, clocked)
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
check("defer without --recommend is refused: a decision that waits for the user says what I would do",
      r.returncode != 0 and "--recommend" in r.stderr, r.stderr)
r = run("defer", "--text", "long names wrap badly at the smallest width", "--recommend",
        "truncate with an ellipsis: the full name is already in the tooltip", ledger=DEFER)
check("defer gives the item an id", r.returncode == 0 and "D1" in r.stdout, r.stdout + r.stderr)
state = status(DEFER)
check("an undecided deferred item blocks the gate",
      state["ready_for_gate"] is False and any("D1" in item for item in state["pending"])
      and run("status", "--check", ledger=DEFER).returncode == 1, state)
check("the deferred item and its decide step carry the recommendation",
      state["deferred"][0]["recommend"] == "truncate with an ellipsis: the full name is already in the tooltip"
      and state["steps"][-1] == {"step": "decide", "id": "D1", "text": "long names wrap badly at the smallest width",
                                 "recommend": "truncate with an ellipsis: the full name is already in the tooltip"},
      (state["deferred"], state["steps"]))
check("the pending text of a deferred item names the recommendation",
      "recommend: truncate with an ellipsis" in run("status", ledger=DEFER).stdout, run("status", ledger=DEFER).stdout)
check("resolve refuses an unknown id",
      run("resolve", "--id", "D7", "--decision", "x", ledger=DEFER).returncode != 0)
run("resolve", "--id", "D1", "--decision", "user: backlog item 12", ledger=DEFER)
state = status(DEFER)
check("a decided deferred item no longer blocks and keeps its decision",
      state["ready_for_gate"] is True and state["deferred"] == [
          {"id": "D1", "text": "long names wrap badly at the smallest width", "decision": "user: backlog item 12",
           "recommend": "truncate with an ellipsis: the full name is already in the tooltip"}],
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
check("a 1.2 ledger is still read: closed cycle, findings unclassified, time unmeasured",
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
r = run("note", "--text", "page size 50", "--validar", ledger=AUTO)
check("note --validar without --recommend is refused", r.returncode != 0 and "--recommend" in r.stderr, r.stderr)
r = run("note", "--text", "ruled out a finding", "--recommend", "keep it", ledger=AUTO)
check("--recommend without --validar is refused: a plain note waits for nobody",
      r.returncode != 0 and "--validar" in r.stderr, r.stderr)
run("note", "--text", "page size 50", "--validar", "--recommend", "confirm: 50 fits the smallest screen", ledger=AUTO)
run("note", "--text", "ruled out a finding", ledger=AUTO)
state = status(AUTO)
check("note --validar goes to the VALIDAR list with an id and its recommendation, apart from plain notes",
      state["validar"] == [{"id": "V1", "text": "page size 50", "decision": None,
                            "recommend": "confirm: 50 fits the smallest screen"}]
      and state["notes"] == ["ruled out a finding"], state)
text = run("status", ledger=AUTO).stdout
check("text status shows the VALIDAR list with ids and the recommendation",
      "VALIDAR V1: page size 50" in text and "recommend: confirm: 50 fits the smallest screen" in text, text)
run("note", "--text", "sort by date", "--validar", "--recommend", "confirm", ledger=AUTO)
r = run("validate", "--id", "V2", "--decision", "user: sort by name", ledger=AUTO)
state = status(AUTO)
check("validate records the user's decision on a VALIDAR item",
      r.returncode == 0 and state["validar"][1] == {"id": "V2", "text": "sort by date", "decision": "user: sort by name",
                                                    "recommend": "confirm"}
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
add("dev", "DONE", "fix-4", ledger=CAP)
check("a fix the user asked for past the limit leaves the stop in place until extend",
      any(step["step"] == "stop" for step in status(CAP)["steps"]), status(CAP)["steps"])
r = run("extend", "--reason", "the user lets the fixes go on (V5)", ledger=CAP)
state = status(CAP)
check("extend records the user's decision to go on past the fix rounds: no stop, the review of the fix is next",
      r.returncode == 0 and not any(step["step"] in ("stop", "ask") for step in state["steps"])
      and state["pending"][0] == "reviewer has not reviewed the latest changes", (r.stderr, state["pending"]))
check("in autonomous mode extend goes to the VALIDAR list",
      [item["text"] for item in state["validar"]][-1:] == ["extra fix round: the user lets the fixes go on (V5)"],
      state["validar"])
add("reviewer", "FAIL", None, 1, ledger=CAP)
check("extend gives one more round: still failing after it stops the delivery again, counting every fix round",
      any(step["step"] == "stop" and step["rounds"] == 4 for step in status(CAP)["steps"]), status(CAP)["steps"])
run("extend", "--reason", "one more", ledger=CAP)
add("dev", "DONE", "fix-5", ledger=CAP)
add("reviewer", "PASS", ledger=CAP)
add("qa", "PASS", ledger=CAP)
check("a cycle that passes after an extend closes", status(CAP)["ready_for_gate"] is True, status(CAP)["pending"])
check("extend within the fix rounds is refused",
      run("extend", "--reason", "x", ledger=CAP).returncode != 0)
add("dev", "DONE", "T2", ledger=CAP)
add("reviewer", "FAIL", None, 1, ledger=CAP)
add("dev", "DONE", "fix-6", ledger=CAP)
add("reviewer", "FAIL", None, 1, ledger=CAP)
check("an extend of an earlier cycle does not shorten the next one",
      not any(step["step"] == "stop" for step in status(CAP)["steps"]), status(CAP)["pending"])

NEXT = ".superpowers/next.jsonl"
run("start", "--slug", "next", ledger=NEXT)
run("scope", "--cycle", "R", "--tasks", "TR.1", ledger=NEXT)
run("scope", "--cycle", "3", "--tasks", "T3.1,T3.2", ledger=NEXT)
add("dev", "DONE", "TR.1", ledger=NEXT)
add("reviewer", "FAIL", None, 1, ledger=NEXT)
add("qa", "PASS", ledger=NEXT)
add("dev", "DONE", "fix-1", ledger=NEXT)
r = run("claim", "--task", "T3.2", ledger=NEXT)
state = status(NEXT)
check("a task of the next plan cycle can start while the fix round of this one runs",
      r.returncode == 0 and state["in_flight"] == ["T3.2"], r.stderr)
check("while this cycle is open, the progress stays on its plan cycle",
      state["scope"]["current"] == "R" and state["scope"]["cycles_left"] == 2, state["scope"])
check("status says the next cycle's task is added once this cycle closes",
      any("T3.2" in item and "once this cycle closes" in item for item in state["pending"]), state["pending"])
r = add("dev", "DONE", "T3.2", ledger=NEXT)
check("add of a task of a later plan cycle is refused while this cycle is open",
      r.returncode != 0 and "once this cycle closes" in r.stderr, r.stdout + r.stderr)
add("reviewer", "PASS", ledger=NEXT)
add("qa", "PASS", ledger=NEXT)
closing = status(NEXT)["runs"][-1]["head"]
r = add("dev", "DONE", "T3.2", ledger=NEXT)
state = status(NEXT)
check("once the cycle closes, the next cycle's task opens the next cycle from the closing head",
      r.returncode == 0 and state["cycle"] == 2 and state["from"] == closing and state["scope"]["current"] == "3",
      (r.stderr, state["cycle"], state["scope"]))
check("a task of the same plan cycle is still added while its cycle is open",
      add("dev", "DONE", "T3.1", ledger=NEXT).returncode == 0)

EXTEND = ".superpowers/extend.jsonl"
run("start", "--slug", "extend", ledger=EXTEND)
add("dev", "DONE", "T1", ledger=EXTEND)
add("reviewer", "FAIL", None, 1, ledger=EXTEND)
add("dev", "DONE", "fix-1", ledger=EXTEND)
add("reviewer", "FAIL", None, 1, ledger=EXTEND)
run("extend", "--reason", "the user asked for one more round", ledger=EXTEND)
state = status(EXTEND)
check("supervised: extend stops asking the user and keeps the decision as a plain note",
      not any(step["step"] == "ask" for step in state["steps"])
      and state["notes"][-1:] == ["extra fix round: the user asked for one more round"], state)

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
run("defer", "--text", "page size", "--recommend", "50", ledger=STEPS)
steps = status(STEPS)["steps"]
check("a task in flight is no step (the band shows it running), a deferred item with no decision is",
      not any(step.get("task") == "T2" for step in steps)
      and {"step": "decide", "id": "D1", "text": "page size", "recommend": "50"} in steps,
      steps)

OLD = ".superpowers/old-pending.jsonl"
run("start", "--slug", "old-pending", ledger=OLD)
with open(os.path.join(repo, OLD), "a", encoding="utf-8") as handle:
    handle.write(json.dumps({"type": "defer", "id": "D1", "text": "old item", "at": "2026-01-01T00:00:00+00:00"}) + "\n")
    handle.write(json.dumps({"type": "note", "text": "old call", "validar": True,
                             "at": "2026-01-01T00:00:00+00:00"}) + "\n")
state = status(OLD)
check("a ledger of an earlier version, with no recommendation, still reads",
      state["deferred"][0] == {"id": "D1", "text": "old item", "decision": None}
      and state["validar"][0] == {"id": "V1", "text": "old call", "decision": None}
      and {"step": "decide", "id": "D1", "text": "old item"} in state["steps"], state)

SCOPE = ".superpowers/scope.jsonl"
check("scope before start is refused",
      run("scope", "--cycle", "1", "--tasks", "T1", ledger=".superpowers/none.jsonl").returncode != 0)
run("start", "--slug", "scope", ledger=SCOPE)
check("a ledger with no scope has none in status", status(SCOPE)["scope"] is None, status(SCOPE).get("scope"))
for name, tasks in (("1", "T1.1, T1.2"), ("R", "TR.1"), ("2", "T2.1")):
    r = run("scope", "--cycle", name, "--tasks", tasks, ledger=SCOPE)
check("scope records the tasks of one plan cycle", r.returncode == 0 and "2" in r.stdout, r.stderr)
check("status --json gives the plan cycles in order, the tasks left, and where the delivery is",
      {key: value for key, value in status(SCOPE)["scope"].items() if key not in ("tasks", "median_task_seconds")}
      == {"cycles": [{"cycle": "1", "tasks": ["T1.1", "T1.2"], "left": ["T1.1", "T1.2"]},
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

REPORTS = ".superpowers/reports.jsonl"
run("start", "--slug", "reports", ledger=REPORTS)
add("dev", "DONE", "T1", ledger=REPORTS)
r = run("add", "--agent", "dev", "--task", "T2", "--verdict", "DONE", "--summary", "x", ledger=REPORTS)
check("--summary is gone", r.returncode != 0, r.stdout)
r = run("add", "--agent", "dev", "--task", "T2", "--verdict", "DONE", "--report", "x.md", ledger=REPORTS)
check("a dev run has no report file: --report is refused", r.returncode != 0 and "--report" in r.stderr, r.stderr)
r = run("add", "--agent", "reviewer", "--verdict", "FAIL", "--important", "2", "--origin", "execution=2", "--report",
        "reports/1-reviewer.md", ledger=REPORTS)
check("--report is refused when no file was saved there: the agents cannot write it, the manager does",
      r.returncode != 0 and "no file" in r.stderr and not status(REPORTS)["reviewer"], (r.stderr, status(REPORTS)))
REVIEW_REPORT, QA_REPORT = report_file("1-reviewer.md"), report_file("1-qa.md", "FAIL")
r = run("add", "--agent", "reviewer", "--verdict", "FAIL", "--important", "2", "--origin", "execution=2", "--report",
        REVIEW_REPORT, ledger=REPORTS)
run("add", "--agent", "qa", "--verdict", "FAIL", "--important", "1", "--origin", "execution=1", "--report",
    QA_REPORT, ledger=REPORTS)
state = status(REPORTS)
check("add --report keeps the report path with the run and in its fix step",
      r.returncode == 0 and state["reviewer"][0]["report"] == REVIEW_REPORT
      and state["steps"] == [{"step": "fix", "agent": "reviewer", "open": 2, "report": REVIEW_REPORT},
                             {"step": "fix", "agent": "qa", "open": 1, "report": QA_REPORT}],
      (r.stderr, state["steps"]))
text = run("status", ledger=REPORTS).stdout
check("the pending text names the report of each open FAIL",
      f"reviewer FAIL (2 open, report {REVIEW_REPORT})" in text and "1-qa.md" in text, text)
add("dev", "DONE", "fix-1", ledger=REPORTS)
check("a run without --report has no report key", "report" not in status(REPORTS)["runs"][0]
      and not any("report" in step for step in status(REPORTS)["steps"]), status(REPORTS)["steps"])
for flag in ("--seconds", "--tokens"):
    r = run("add", "--agent", "dev", "--task", "T3", "--verdict", "DONE", flag, "0", ledger=REPORTS)
    check(f"{flag} 0 is refused: leave it out when unmeasured", r.returncode != 0 and "leave it out" in r.stderr, r.stderr)

LOOP = ".superpowers/loop.jsonl"
run("start", "--slug", "loop", ledger=LOOP)
r = run("add", "--agent", "qa", "--task", "plan", "--verdict", "PASS", ledger=LOOP)
check("only the reviewer reviews a plan or a spec", r.returncode != 0 and "--task" in r.stderr, r.stderr)
check("a reviewer task other than spec or plan is refused",
      run("add", "--agent", "reviewer", "--task", "T1", "--verdict", "PASS", ledger=LOOP).returncode != 0)


def review(verdict, task="plan", open_count=0, ledger=LOOP, report=None, critical=0, minor=0):
    args = ["add", "--agent", "reviewer", "--task", task, "--verdict", verdict]
    if open_count:
        args += ["--important", str(open_count)]
    if critical:
        args += ["--critical", str(critical)]
    if minor:
        args += ["--minor", str(minor)]
    if open_count + critical + minor:
        args += ["--origin", f"plan={open_count + critical + minor}"]
    return run(*(args + (["--report", report] if report else [])), "--seconds", "5m", ledger=ledger)


LOOP_HEAD = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
LOOP_REPORT = report_file("loop-1.md")
r = review("FAIL", open_count=2, minor=1, report=LOOP_REPORT)
state = status(LOOP)
check("a plan review FAIL is a review step with its round and the range of the next one, outside the cycles",
      r.returncode == 0 and state["cycle"] == 1 and state["tasks"] == {} and state["reviewer"] == []
      and state["steps"] == [{"step": "review", "task": "plan", "round": 2, "open": 2, "from": LOOP_HEAD,
                              "report": LOOP_REPORT}, {"step": "dev"}]
      and state["pending"][0] == f"plan review round 1 FAIL (2 open, report {LOOP_REPORT}): triage every finding "
                                 "(applied, refused or errata), commit the plan and dispatch the reviewer on "
                                 f"{LOOP_HEAD[:12]}..HEAD, the corrections only", (r.stderr, state["steps"], state["pending"]))
check("status --check fails while the plan review is open", run("status", "--check", ledger=LOOP).returncode == 1)
r = review("FAIL", open_count=1)
check("the next round is added with no triage counts", r.returncode == 0
      and status(LOOP)["metrics"]["reviews"]["plan"]["rounds"] == 2, r.stderr)
check("--triage is gone", run("add", "--agent", "reviewer", "--task", "plan", "--verdict", "PASS", "--triage",
                              "applied=1", ledger=LOOP).returncode != 0)
review("FAIL", open_count=1)
state = status(LOOP)
check("supervised: three rounds with no Critical open go on without asking: carry the open findings and waive",
      state["steps"][0] == {"step": "waive", "task": "plan", "rounds": 3, "open": 1}
      and state["pending"][0] == "plan review still fails after 3 rounds with no Critical: carry each open finding "
                                 "to the plan's Errata and waive --task plan; extend only on the user's word", state)
run("mode", "autonomous", ledger=LOOP)
check("autonomous: the same three rounds and the same waiver, which becomes a VALIDAR item",
      status(LOOP)["steps"][0] == {"step": "waive", "task": "plan", "rounds": 3, "open": 1}, status(LOOP)["steps"])
run("waive", "--agent", "reviewer", "--task", "plan", "--reason", "1 Important carried to the Errata", ledger=LOOP)
state = status(LOOP)
check("the waiver closes the loop and the cycle steps stay",
      state["steps"] == [{"step": "dev"}] and state["pending"] == ["no dev task yet"]
      and state["validar"][-1]["text"] == "waived reviewer plan FAIL: 1 Important carried to the Errata", state)
check("plan reviews are counted in the metrics by rounds, findings and time, apart from the cycles",
      state["metrics"]["reviews"] == {"plan": {"rounds": 3, "critical": 0, "important": 4, "minor": 1,
                                               "seconds": 900, "tokens": 0}}
      and state["metrics"]["time"]["agents"] == {"reviewer": 900} and state["metrics"]["origins"]["plan"] == 5
      and state["metrics"]["cycles"][0]["seconds"] == 0, state["metrics"])
r = review("FAIL", open_count=1)
check("a review after a PASS (a change of scope) is a new loop: its counter starts again at round 1",
      status(LOOP)["steps"][0]["round"] == 2 and "(round 1)" in r.stdout, (r.stdout, status(LOOP)["steps"]))
review("FAIL", task="spec", open_count=1)
check("a spec review has its own loop",
      {step["task"] for step in status(LOOP)["steps"] if step["step"] == "review"} == {"plan", "spec"}, status(LOOP)["steps"])
r = run("waive", "--agent", "reviewer", "--task", "spec", "--reason", "user approved the spec with the finding", ledger=LOOP)
state = status(LOOP)
check("waive --task closes a review loop the user accepted as it is",
      r.returncode == 0 and not any(step.get("task") == "spec" for step in state["steps"])
      and state["validar"][-1]["text"] == "waived reviewer spec FAIL: user approved the spec with the finding",
      (r.stderr, state))
check("waive --task of a review that passed is refused",
      run("waive", "--agent", "reviewer", "--task", "spec", "--reason", "x", ledger=LOOP).returncode != 0)

EXT = ".superpowers/extend-review.jsonl"
run("start", "--slug", "extend-review", ledger=EXT)
r = run("extend", "--task", "plan", "--reason", "x", ledger=EXT)
check("extend --task of a review loop that never failed is refused",
      r.returncode != 0 and "nothing to extend" in r.stderr, r.stderr)
review("FAIL", critical=1, ledger=EXT)
for _ in range(2):
    review("FAIL", critical=1, ledger=EXT)
check("supervised: a Critical still open after three rounds asks the user",
      status(EXT)["steps"][0] == {"step": "ask", "task": "plan", "rounds": 3}
      and status(EXT)["pending"][0] == "plan review still fails after 3 rounds: ask the user", status(EXT)["steps"])
r = run("extend", "--task", "plan", "--reason", "user wants the corrections checked", ledger=EXT)
state = status(EXT)
check("extend --task records the user's extra review round and the loop goes on",
      r.returncode == 0 and state["steps"][0]["step"] == "review" and state["steps"][0]["round"] == 4
      and state["notes"][-1] == "extra plan review round: user wants the corrections checked", (r.stderr, state))
check("a review extension does not extend the cycle's fix rounds",
      run("extend", "--reason", "y", ledger=EXT).returncode != 0)
review("FAIL", critical=1, ledger=EXT)
state = status(EXT)
check("the extra round failing asks the user again, naming it as the extra one",
      state["steps"][0] == {"step": "ask", "task": "plan", "rounds": 4, "extended": True}
      and state["pending"][0] == "plan review still fails after the extra round: ask the user", state)
run("mode", "autonomous", ledger=EXT)
check("in autonomous mode a Critical still open stops the delivery",
      status(EXT)["steps"][0]["step"] == "stop" and "note --validar" in status(EXT)["pending"][0], status(EXT))
r = run("extend", "--task", "plan", "--reason", "one more", ledger=EXT)
check("the user may authorize another round after the extra one",
      r.returncode == 0 and status(EXT)["steps"][0]["step"] == "review", (r.stderr, status(EXT)["steps"]))
check("the note of an extension in autonomous mode is a VALIDAR item",
      status(EXT)["validar"][-1]["text"] == "extra plan review round: one more", status(EXT)["validar"])
review("FAIL", open_count=1, ledger=EXT)
check("the extra round with no Critical left is waived, not asked",
      status(EXT)["steps"][0] == {"step": "waive", "task": "plan", "rounds": 5, "open": 1, "extended": True},
      status(EXT)["steps"])
r = run("extend", "--task", "plan", "--reason", "the user overrules the waiver", ledger=EXT)
check("extend --task also lets the user overrule the waiver with one more round",
      r.returncode == 0 and status(EXT)["steps"][0]["step"] == "review", (r.stderr, status(EXT)["steps"]))
r = run("extend", "--task", "spec", "--reason", "x", ledger=EXT)
check("extend --task names the review loop that ran out, not another",
      r.returncode != 0 and "spec" in r.stderr, r.stderr)

FROM = ".superpowers/from.jsonl"
base_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
run("start", "--slug", "from", ledger=FROM)
check("cycle 1 starts at the base", status(FROM)["from"] == base_head, status(FROM).get("from"))
subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "T1"], cwd=repo, check=True, capture_output=True)
add("dev", "DONE", "T1", ledger=FROM)
add("reviewer", "PASS", ledger=FROM)
add("qa", "PASS", ledger=FROM)
closing_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
check("a closed cycle still reports its own from", status(FROM)["from"] == base_head)
subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "T2"], cwd=repo, check=True, capture_output=True)
add("dev", "DONE", "T2", ledger=FROM)
check("the next cycle starts at the head recorded by the run that closed the previous one",
      status(FROM)["from"] == closing_head, status(FROM).get("from"))
check("text status names the cycle's from", f"from {closing_head[:12]}" in run("status", ledger=FROM).stdout)
check("an old ledger without heads has no from for a later cycle",
      status(".superpowers/legacy.jsonl").get("from") == "abc")


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def ledger_lines(ledger):
    with open(os.path.join(repo, ledger), encoding="utf-8") as handle:
        return len(handle.readlines())


PAUSE = ".superpowers/pause.jsonl"
run("start", "--slug", "pause", ledger=PAUSE)
pause_tree = os.path.join(worktrees, "pause")
git(repo, "worktree", "add", "-q", "--detach", pause_tree)
r = run("claim", "--task", "P1", "--worktree", os.path.join(worktrees, "missing"), ledger=PAUSE)
check("claim refuses a worktree that is no directory", r.returncode != 0 and "worktree" in r.stderr, r.stderr)
r = run("claim", "--task", "P1", "--origin", "no-such-rev", ledger=PAUSE)
check("claim refuses an origin that is no commit", r.returncode != 0 and "no-such-rev" in r.stderr, r.stderr)
check("a refused claim writes nothing", status(PAUSE)["in_flight"] == [] and ledger_lines(PAUSE) == 1)
origin = git(pause_tree, "rev-parse", "HEAD")
r = run("claim", "--task", "P1", "--worktree", pause_tree, "--origin", "HEAD", ledger=PAUSE)
state = status(PAUSE)
check("claim stores the worktree (absolute) and the origin as a full hash, resolved in the worktree",
      r.returncode == 0 and len(state["claims"]) == 1 and state["claims"][0]["task"] == "P1"
      and state["claims"][0]["worktree"] == os.path.abspath(pause_tree) and state["claims"][0]["origin"] == origin
      and state["claims"][0]["at"] and state["claims"][0]["head_moved"] is False, (r.stderr, state.get("claims")))
check("in_flight and dispatched keep their shape", state["in_flight"] == ["P1"]
      and list(state["dispatched"]) == ["P1"] and isinstance(state["dispatched"]["P1"], str), state)
text = run("status", ledger=PAUSE).stdout
check("status text shows the claim's worktree and origin",
      f"in {os.path.abspath(pause_tree)}, from {origin[:12]}" in text and "head moved" not in text, text)
r = run("claim", "--task", "P2", ledger=PAUSE)
claim2 = status(PAUSE)["claims"][1]
check("a claim with neither option is stored without them",
      r.returncode == 0 and claim2 == {"task": "P2", "at": claim2["at"], "worktree": None, "origin": None,
                                       "tip": None, "head_moved": False, "waiting_minutes": 0,
                                       "committed": False, "partial_report": False}, status(PAUSE)["claims"])
run("release", "--task", "P2", ledger=PAUSE)
subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "delivery moved"], cwd=repo, check=True,
               capture_output=True)
new_head = git(repo, "rev-parse", "HEAD")
state = status(PAUSE)
text = run("status", ledger=PAUSE).stdout
check("a new commit on the delivery branch makes the claim's head_moved true",
      state["claims"][0]["head_moved"] is True, state["claims"])
check("status text names the delivery head as a fact, not an instruction",
      f"; the delivery head is now {new_head[:12]}" in text and "integrate its commits" not in text
      and "head moved" not in text, text)

with open(os.path.join(pause_tree, "wip.txt"), "w", encoding="utf-8") as handle:
    handle.write("half done\n")
lines = ledger_lines(PAUSE)
r = run("pause", "--text", "waiting for the user", ledger=PAUSE)
check("pause is refused while a claimed worktree has an untracked file, and names it",
      r.returncode != 0 and f'P1: uncommitted work in {os.path.abspath(pause_tree)}: commit it there as "wip: P1 '
      in r.stderr, r.stderr)
check("a refused pause writes nothing", ledger_lines(PAUSE) == lines and status(PAUSE)["paused"] is None)
git(pause_tree, "add", "-A")
git(pause_tree, "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", "wip: P1 half done")
r = run("pause", "--text", "waiting for the user", ledger=PAUSE)
check("pause passes once the work is committed", r.returncode == 0 and "paused: waiting for the user" in r.stdout,
      r.stderr)
r = run("pause", "--text", "again", ledger=PAUSE)
check("pause twice is refused", r.returncode != 0 and "paused" in r.stderr, r.stderr)
state = status(PAUSE)
check("while paused, the pending line comes first and the resume step too",
      state["pending"][0] == f"delivery paused since {state['paused']['at']}: waiting for the user "
                             "(resume when work restarts)"
      and state["steps"][0] == {"step": "resume", "text": "waiting for the user", "at": state["paused"]["at"]}
      and state["ready_for_gate"] is False, (state["pending"], state["steps"]))
check("while paused, paused is {text, at} in the JSON",
      sorted(state["paused"]) == ["at", "text"] and state["paused"]["text"] == "waiting for the user", state["paused"])
check("while paused, status --check exits 1", run("status", "--check", ledger=PAUSE).returncode == 1)
check("the claim stays held through the pause", state["in_flight"] == ["P1"], state["in_flight"])
r = run("resume", ledger=PAUSE)
tip = git(pause_tree, "rev-parse", "HEAD")
check("resume prints resumed and one line per claim in flight, with its worktree and the tip to continue from",
      r.returncode == 0 and r.stdout.splitlines()[0] == "resumed" and tip != origin
      and f"- P1 in {os.path.abspath(pause_tree)} at {tip[:12]}" in r.stdout.splitlines(), (r.stdout, r.stderr))
state = status(PAUSE)
check("status --json gives each claim's tip (the worktree HEAD after the wip commit) and keeps the origin",
      state["claims"][0]["tip"] == tip and state["claims"][0]["origin"] == origin, state["claims"])
check("the pause text stays in the notes after resume, in ledger order, as paused: <text>",
      state["notes"] == ["paused: waiting for the user"]
      and "note: paused: waiting for the user" in run("status", ledger=PAUSE).stdout, state["notes"])
check("after resume, paused is null and the claim is still in flight",
      state["paused"] is None and state["in_flight"] == ["P1"]
      and not any("paused" in item for item in state["pending"]), state)
r = run("resume", ledger=PAUSE)
check("resume when not paused is refused", r.returncode != 0 and "not paused" in r.stderr, r.stderr)
with open(os.path.join(pause_tree, "wip.txt"), "a", encoding="utf-8") as handle:
    handle.write("more\n")
check("pause is refused with a modified tracked file too",
      run("pause", "--text", "x", ledger=PAUSE).returncode != 0)
check("pause before start is refused",
      run("pause", "--text", "x", ledger=".superpowers/none.jsonl").returncode != 0)

OLD = ".superpowers/nohead.jsonl"
with open(os.path.join(repo, OLD), "w", encoding="utf-8", newline="\n") as handle:
    for entry in ({"type": "start", "slug": "old", "base": "abc", "at": "2026-10-01T10:00:00+00:00"},
                  {"type": "claim", "task": "L1", "at": "2026-10-01T10:01:00+00:00"}):
        handle.write(json.dumps(entry) + "\n")
state = status(OLD)
check("a claim written in the old shape still works: no worktree, no origin, head not moved, nothing committed",
      state["in_flight"] == ["L1"] and len(state["claims"]) == 1
      and {key: value for key, value in state["claims"][0].items() if key != "waiting_minutes"}
      == {"task": "L1", "at": "2026-10-01T10:01:00+00:00", "worktree": None, "origin": None, "tip": None,
          "head_moved": False, "committed": False, "partial_report": True}
      and state["claims"][0]["waiting_minutes"] > 0
      and state["paused"] is None and state["full_qa"] is None, state)
check("the old claim's text line has no place suffix, and says how long it has been waiting",
      re.search(r"dev L1 dispatched at 2026-10-01T10:01:00\+00:00, waiting \d+m, no report yet",
                run("status", ledger=OLD).stdout) is not None, run("status", ledger=OLD).stdout)
run("pause", "--text", "stop here", ledger=OLD)
r = run("resume", ledger=OLD)
check("pause and resume work on a claim with no worktree: the line is just the task",
      r.returncode == 0 and "- L1" in r.stdout.splitlines(), r.stdout + r.stderr)

GONE = ".superpowers/gone.jsonl"
run("start", "--slug", "gone", ledger=GONE)
gone_tree = os.path.join(worktrees, "gone")
git(repo, "worktree", "add", "-q", "-b", "gone-branch", gone_tree)
git(gone_tree, "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "only here")
only_here = git(gone_tree, "rev-parse", "HEAD")
r = run("claim", "--task", "G1", "--worktree", gone_tree, "--origin", "HEAD", ledger=GONE)
check("claim --origin HEAD is resolved in the worktree: a commit that exists only there",
      r.returncode == 0 and status(GONE)["claims"][0]["origin"] == only_here
      and only_here != git(repo, "rev-parse", "HEAD"), (r.stderr, status(GONE)["claims"]))
shutil.rmtree(gone_tree, onerror=lambda func, path, _: (os.chmod(path, stat.S_IWRITE), func(path)))
r = run("pause", "--text", "folder is gone", ledger=GONE)
state = status(GONE)
check("pause is not refused for a claimed worktree whose folder was removed; its tip is null",
      r.returncode == 0 and state["paused"]["text"] == "folder is gone" and state["claims"][0]["tip"] is None,
      (r.stderr, state["claims"]))
r = run("resume", ledger=GONE)
check("resume prints the claim with its worktree and no tip when the folder is gone",
      f"- G1 in {os.path.abspath(gone_tree)}" in r.stdout.splitlines(), r.stdout)

FULL = ".superpowers/full.jsonl"
run("start", "--slug", "full", ledger=FULL)
add("dev", "DONE", "T1", ledger=FULL)
check("a ledger with no full qa run has full_qa null", status(FULL)["full_qa"] is None)
r = run("add", "--agent", "reviewer", "--verdict", "PASS", "--full", ledger=FULL)
check("--full is refused on the reviewer", r.returncode != 0 and "--full" in r.stderr, r.stderr)
r = run("add", "--agent", "dev", "--task", "T2", "--verdict", "DONE", "--full", ledger=FULL)
check("--full is refused on the dev", r.returncode != 0 and "--full" in r.stderr, r.stderr)
check("refused --full runs write nothing", len(status(FULL)["runs"]) == 1)
FIRST, PLAIN, SECOND = report_file("first.md"), report_file("plain.md"), report_file("second.md")
r = run("add", "--agent", "qa", "--verdict", "PASS", "--full", "--report", FIRST, ledger=FULL)
state = status(FULL)
check("--full on qa is stored on the run and shows as full_qa",
      r.returncode == 0 and state["qa"][0].get("full") is True and state["full_qa"] == state["qa"][0]
      and state["full_qa"]["head"], (r.stderr, state["full_qa"]))
run("add", "--agent", "qa", "--verdict", "PASS", "--report", PLAIN, ledger=FULL)
state = status(FULL)
check("a qa run without --full has no full key and does not replace full_qa",
      "full" not in state["qa"][0] and state["full_qa"]["report"] == FIRST, state["full_qa"])
add("dev", "DONE", "T3", ledger=FULL)
run("add", "--agent", "qa", "--verdict", "PASS", "--full", "--report", SECOND, ledger=FULL)
add("reviewer", "PASS", ledger=FULL)
add("dev", "DONE", "T4", ledger=FULL)
state = status(FULL)
check("full_qa is the latest full qa run across the whole delivery, even from an earlier cycle",
      state["cycle"] > 1 and state["full_qa"]["report"] == SECOND, state["full_qa"])

def stamp(hours):
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=hours)).isoformat(timespec="seconds")


def window(percent, hours=2):
    return {"percent": percent, "resets_at": stamp(hours)}


def usage_case(name, windows=None, local=None, raw=None, extra=None, close=False):
    """A ledger in its own folder (repo/u/<name>/.superpowers) so usage.json never leaks into the other cases."""
    root = os.path.join(repo, "u", name)
    os.makedirs(os.path.join(root, ".superpowers"), exist_ok=True)
    if windows is not None or raw is not None:
        with open(os.path.join(root, ".superpowers", "usage.json"), "w", encoding="utf-8") as handle:
            handle.write(raw if raw is not None else json.dumps({"at": stamp(0), "windows": windows, **(extra or {})}))
    if local is not None:
        with open(os.path.join(root, "CLAUDE.local.md"), "w", encoding="utf-8") as handle:
            handle.write(local)
    ledger = f"u/{name}/.superpowers/ledger.jsonl"
    run("start", "--slug", name, ledger=ledger)
    add("dev", "DONE", "T1", ledger=ledger)
    if close:
        add("reviewer", "PASS", ledger=ledger)
        add("qa", "PASS", ledger=ledger)
    return ledger


def advice(name, windows=None, **kwargs):
    return status(usage_case(name, windows, **kwargs))["usage"]


def lines_of(ledger):
    with open(os.path.join(repo, ledger), encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def local(economy=None, five=None, week=None, always=None):
    rows = [("Economia a partir de quanto uso, em %", economy),
            ("Pausa a partir de quanto uso da janela de 5 horas, em %", five),
            ("Pausa a partir de quanto uso da semana, em %", week), ("Sempre econômico", always)]
    return "# Local\n" + "".join(f"- {label}: `{value}`\n" for label, value in rows if value is not None)


ledger = usage_case("none", close=True)
state = status(ledger)
check("no usage.json and no Sempre econômico: usage is null and the cycle is unchanged",
      state["usage"] is None and state["ready_for_gate"] is True and "usage" not in lines_of(ledger)[1],
      state.get("usage"))
check("no usage.json: the text has no usage line", "usage:" not in run("status", ledger=ledger).stdout)

got = advice("low", {"five_hour": window(59), "seven_day": window(59)})
check("under every default threshold: windows as read, no economy, no wait",
      got["economy"] is None and got["wait"] is None and got["windows"]["five_hour"]["percent"] == 59
      and set(got["windows"]["seven_day"]) == {"percent", "resets_at"}, got)
got = advice("e5", {"five_hour": window(60)})
check("economy by the 5-hour window at the default 60", got["economy"] == "five_hour at 60%" and got["wait"] is None, got)
got = advice("e7", {"five_hour": window(10), "seven_day": window(61.5, 48)})
check("economy by the weekly window", got["economy"] == "seven_day at 61%", got)
got = advice("w5", {"five_hour": window(84.9)})
check("the 5-hour pause starts at 85, not before", got["wait"] is None, got)
got = advice("w5b", {"five_hour": window(85)})
wait = got["wait"]
check("wait for the 5-hour window at 85", {k: wait[k] for k in ("window", "percent", "margin", "resets_at")} == {
    "window": "five_hour", "percent": 85, "margin": 0, "resets_at": got["windows"]["five_hour"]["resets_at"]}, got)
got = advice("w7", {"five_hour": window(10), "seven_day": window(95, 48)})
check("wait for the week at 95", got["wait"] and got["wait"]["window"] == "seven_day", got)
got = advice("both", {"five_hour": window(90, 4), "seven_day": window(96, 30)})
check("both over the pause: the one that resets later", got["wait"]["window"] == "seven_day", got)
got = advice("both2", {"five_hour": window(90, 6), "seven_day": window(96, 1)})
check("both over the pause: the later reset wins whichever window it is", got["wait"]["window"] == "five_hour", got)

got = advice("past", {"five_hour": window(99, -1), "seven_day": window(10)})
check("a window past its resets_at is ignored", list(got["windows"]) == ["seven_day"] and got["wait"] is None
      and got["economy"] is None, got)
state = status(usage_case("allpast", {"five_hour": window(99, -1)}))
check("every window past: nothing to advise, usage is null", state["usage"] is None, state.get("usage"))
got = advice("missing", {"seven_day": window(70)})
check("either window may be missing", list(got["windows"]) == ["seven_day"] and got["economy"] == "seven_day at 70%", got)
got = advice("extras", {"five_hour": {**window(70), "label": "x"}, "monthly": window(99)}, extra={"version": 3})
check("unknown fields and windows are ignored", list(got["windows"]) == ["five_hour"]
      and set(got["windows"]["five_hour"]) == {"percent", "resets_at"} and got["economy"] == "five_hour at 70%", got)

z = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)
got = advice("zform", {"five_hour": {"percent": 90, "resets_at": z.strftime("%Y-%m-%dT%H:%M:%S.123Z")},
                       "spend_limit": {"percent": 99, "resets_at": None}})
check("resets_at as toISOString output (milliseconds and Z) is read; an extra kind is ignored",
      got["wait"] and got["wait"]["window"] == "five_hour" and list(got["windows"]) == ["five_hour"], got)
past = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
check("a Z form in the past is ignored", advice("zpast", {"five_hour": {"percent": 90, "resets_at": past}}) is None)
ledger = usage_case("nullreset", {"five_hour": {"percent": 90, "resets_at": None}, "seven_day": window(10)})
got = status(ledger)["usage"]
text = run("status", ledger=ledger).stdout
check("a null resets_at counts as valid: the window stays and can ask to wait",
      got["windows"]["five_hour"]["resets_at"] is None and got["wait"] == {"window": "five_hour", "percent": 90,
                                                                           "margin": 0, "resets_at": None,
                                                                           "seconds_left": None}, got)
check("the text omits the reset time it does not have",
      re.search(r"^usage: 5h 90%, week 10%$", text, re.M) and "until the window resets" in text, text)
got = advice("nullboth", {"five_hour": {"percent": 90, "resets_at": None}, "seven_day": window(96, 48)})
check("when both are over the pause, a known reset beats an unknown one", got["wait"]["window"] == "seven_day", got)

got = advice("always", {"five_hour": window(5)}, local=local(always="sim"))
check("Sempre econômico turns economy on", got["economy"] == "always (CLAUDE.local.md)", got)
state = status(usage_case("always2", local=local(always="Yes")))
check("Sempre econômico works with no usage.json and shows as an empty usage",
      state["usage"] == {"windows": {}, "economy": "always (CLAUDE.local.md)", "wait": None}, state.get("usage"))
check("Sempre econômico `não` and a placeholder keep it off",
      advice("always3", {"five_hour": window(5)}, local=local(always="não"))["economy"] is None
      and advice("always4", {"five_hour": window(5)}, local=local(always="_(sim ou não)_"))["economy"] is None)

got = advice("custom", {"five_hour": window(40), "seven_day": window(75, 48)},
             local=local(economy=30, five=50, week=70))
check("thresholds come from CLAUDE.local.md",
      got["economy"] == "five_hour at 40%" and got["wait"]["window"] == "seven_day", got)
got = advice("labels", {"five_hour": window(40)}, local="- ECONOMIA A PARTIR DE QUANTO USO, EM %: `30`\n"
                                                         "- pausa a partir de quanto uso da janela de 5 horas, em %: `40`\n")
check("labels match ignoring case and accents", got["economy"] == "five_hour at 40%" and got["wait"] is not None, got)
got = advice("placeholder", {"five_hour": window(70)}, local=local(economy="_(60)_", five="_(85)_"))
check("a placeholder falls back to the defaults", got["economy"] == "five_hour at 70%" and got["wait"] is None, got)
got = advice("placeholder2", {"five_hour": window(40)},
             local="- Economia a partir de quanto uso, em %: _(padrão 60: escreva `30` para economizar antes)_\n"
                   "- Pausa a partir de quanto uso da janela de 5 horas, em %: _(padrão 85: `20`)_\n"
                   "- Sempre econômico: _(sim, entre crases, numa conta Pro, ...; padrão não: `sim`)_\n")
check("a placeholder with a backtick inside is still a placeholder: defaults apply",
      got["economy"] is None and got["wait"] is None, got)
for number, bad in enumerate(("0", "101", "-5", "abc", "")):
    got = advice(f"bad{number}", {"five_hour": window(50), "seven_day": window(50)},
                 local=local(economy=bad, five=bad, week=bad))
    check(f"an invalid threshold ({bad!r}) falls back to the defaults",
          got["economy"] is None and got["wait"] is None, got)
got = advice("edge", {"five_hour": window(99)}, local=local(five=100))
check("100 is a valid threshold", got["wait"] is None, got)

ledger = usage_case("broken", raw="{not json")
r = run("status", ledger=ledger)
check("broken usage.json does not stop status and the text says it once",
      r.returncode == 0 and r.stdout.count("usage.json unreadable") == 1 and "ready for gate" in r.stdout
      and status(ledger)["usage"] is None, (r.stderr, r.stdout))
check("broken usage.json does not stop add", add("reviewer", "PASS", ledger=ledger).returncode == 0
      and "usage" not in lines_of(ledger)[-1])
ledger = usage_case("shape", raw=json.dumps({"windows": {"five_hour": "high", "seven_day": {"percent": "x"}}}))
check("a window of the wrong shape is ignored without a traceback",
      run("status", ledger=ledger).returncode == 0 and status(ledger)["usage"] is None)

text = run("status", ledger=usage_case("text", {"five_hour": window(52.5), "seven_day": window(41, 48)})).stdout
fiveh = [row for row in text.splitlines() if row.startswith("usage: 5h")]
check("text: one usage line with both windows", len(fiveh) == 1 and re.fullmatch(
    r"usage: 5h 52% \(resets \d\d:\d\dZ\), week 41%", fiveh[0]) and "usage: economy" not in text
      and "usage: wait" not in text, text)
text = run("status", ledger=usage_case("text2", {"five_hour": window(90), "seven_day": window(65, 48)})).stdout
check("text: economy and wait lines", "usage: economy (five_hour at 90%): reviewer on sonnet, one copy at a time" in text
      and re.search(r"usage: wait \(five_hour at 90%\): dispatch nothing new; pause at the next safe point until "
                    r"\d{4}-\d\d-\d\dT", text), text)

clean = status(usage_case("ref", close=True))
waiting = status(usage_case("ref2", {"five_hour": window(99), "seven_day": window(99, 48)}, close=True))
check("wait does not change the gate: ready_for_gate, pending and steps stay",
      waiting["usage"]["wait"] is not None and waiting["ready_for_gate"] is True
      and waiting["pending"] == clean["pending"] and waiting["steps"] == clean["steps"], waiting["usage"])
check("status --check ignores wait on a closed cycle",
      run("status", "--check", ledger="u/ref2/.superpowers/ledger.jsonl").returncode == 0)
open_cycle = usage_case("ref3", {"five_hour": window(99)})
check("an open cycle stays pending the same way with a wait",
      status(open_cycle)["pending"] == ["reviewer has not reviewed the latest changes", "qa has not run on the cycle's tasks"]
      and run("status", "--check", ledger=open_cycle).returncode == 1)

ledger = usage_case("snap", {"five_hour": window(82.5), "seven_day": window(41, 48), "monthly": window(1)})
check("add stores the snapshot of the valid windows", lines_of(ledger)[1]["usage"] == {"five_hour": 82.5, "seven_day": 41},
      lines_of(ledger))
ledger = usage_case("snap2", {"five_hour": window(82.5, -1), "seven_day": window(41, 48)})
check("the snapshot leaves out a window past its reset", lines_of(ledger)[1]["usage"] == {"seven_day": 41}, lines_of(ledger))
check("add with no usage.json stores no usage key",
      all("usage" not in entry for entry in lines_of(usage_case("snap3"))))

deep = os.path.join(repo, "u", "custom", "deep")
os.makedirs(deep, exist_ok=True)
with open(os.path.join(deep, "usage.json"), "w", encoding="utf-8") as handle:
    json.dump({"windows": {"five_hour": window(90)}}, handle)
with open(os.path.join(repo, "u", "custom", "usage.json"), "w", encoding="utf-8") as handle:
    json.dump({"windows": {"five_hour": window(10)}}, handle)
with open(os.path.join(repo, "u", "custom", "CLAUDE.local.md"), "w", encoding="utf-8") as handle:
    handle.write(local(five=95))
ledger = "u/custom/deep/ledger.jsonl"
run("start", "--slug", "custom", ledger=ledger)
got = status(ledger)["usage"]
check("--ledger at a custom path reads usage.json from that folder and CLAUDE.local.md from its parent",
      got["windows"]["five_hour"]["percent"] == 90 and got["wait"] is None and got["economy"] == "five_hour at 90%", got)

def set_usage(name, percent, hours=2, seven=None):
    windows = {"five_hour": window(percent, hours)}
    if seven is not None:
        windows["seven_day"] = window(seven, 48)
    with open(os.path.join(repo, "u", name, ".superpowers", "usage.json"), "w", encoding="utf-8") as handle:
        json.dump({"windows": windows}, handle)


def margin_case(name, percents, final, hours=2, seven=None):
    """The first percent is the usage_case snapshot; each further one is a run added at that usage; final is what the mod shows last."""
    ledger = usage_case(name, {"five_hour": window(percents[0])})
    for index, percent in enumerate(percents[1:]):
        set_usage(name, percent)
        add("reviewer" if index % 2 == 0 else "qa", "PASS", ledger=ledger)
    set_usage(name, final, hours, seven)
    return status(ledger)


state = margin_case("mg1", [50, 60, 30, 34], 78)
check("margin is the largest positive delta between snapshots; a reset in between is skipped",
      state["usage"]["wait"] and state["usage"]["wait"]["margin"] == 10, state["usage"])
text = run("status", ledger="u/mg1/.superpowers/ledger.jsonl").stdout
check("wait by margin below the threshold: 78% + 10% >= 85%, and the text says it",
      "usage: wait (five_hour at 78% + 10% per run):" in text, text)
state = margin_case("mg2", [50, 60, 30, 34], 70)
check("no wait when percent + margin stays under the threshold", state["usage"]["wait"] is None, state["usage"])
state = margin_case("mg3", [10], 84)
check("no deltas means margin 0: 84% under 85% is no wait", state["usage"]["wait"] is None, state["usage"])
state = margin_case("mg4", [10], 90)
check("no deltas: wait at the threshold carries margin 0 and the old text",
      state["usage"]["wait"]["margin"] == 0
      and "usage: wait (five_hour at 90%):" in run("status", ledger="u/mg4/.superpowers/ledger.jsonl").stdout)
state = margin_case("mg5", [10, 40, 41, 42, 43, 44, 45], 70)
check("margin looks only at the last 5 positive deltas", state["usage"]["wait"] is None, state["usage"])
state = margin_case("mg6", [10, 40, 41, 41, 30, 32, 33], 83)
check("zero and negative deltas are skipped; the last 5 positive deltas are 1, 1, 2, 1 and 30",
      state["usage"]["wait"]["margin"] == 30, state["usage"])

state = margin_case("sl1", [10], 90, hours=2.2)
wait = state["usage"]["wait"]
text = run("status", ledger="u/sl1/.superpowers/ledger.jsonl").stdout
check("seconds_left is in the wait JSON, from now", isinstance(wait.get("seconds_left"), int)
      and 7800 < wait["seconds_left"] <= 7920, wait)
check("the wait text ends with the reset and the time left", re.search(r"until \d{4}-\d\d-\d\dT\S+ \(in 2h1\dm\)$", text, re.M),
      text)
ledger = usage_case("sl2", {"five_hour": {"percent": 90, "resets_at": None}})
check("an unknown reset has no seconds_left and no (in ...)",
      status(ledger)["usage"]["wait"]["seconds_left"] is None
      and "until the window resets" in run("status", ledger=ledger).stdout
      and "(in " not in run("status", ledger=ledger).stdout)

import importlib.util, threading, time
spec = importlib.util.spec_from_file_location("ledger_under_test", LEDGER)
ledger_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ledger_module)
retry_root = os.path.join(repo, "u", "retry", ".superpowers")
os.makedirs(retry_root, exist_ok=True)
usage_path = os.path.join(retry_root, "usage.json")
with open(usage_path, "w", encoding="utf-8") as handle:
    handle.write('{"windows": {"five_hour": {"perc')


def finish_write():
    time.sleep(0.08)
    with open(usage_path, "w", encoding="utf-8") as handle:
        json.dump({"windows": {"five_hour": window(40)}}, handle)


thread = threading.Thread(target=finish_write)
thread.start()
got, unreadable = ledger_module.usage_windows(os.path.join(retry_root, "ledger.jsonl"))
thread.join()
check("a file that becomes valid during the retry is read", not unreadable and got["five_hour"]["percent"] == 40,
      (got, unreadable))
with open(usage_path, "w", encoding="utf-8") as handle:
    handle.write("{broken")
check("a file still broken after the retry is unreadable",
      ledger_module.usage_windows(os.path.join(retry_root, "ledger.jsonl")) == ({}, True))

main_super = os.path.join(repo, ".superpowers")
main_local = os.path.join(repo, "CLAUDE.local.md")
with open(os.path.join(main_super, "usage.json"), "w", encoding="utf-8") as handle:
    json.dump({"windows": {"five_hour": window(90)}}, handle)
with open(main_local, "w", encoding="utf-8") as handle:
    handle.write(local(five=95))
try:
    got = json.loads(run("status", "--json", cwd=task_tree).stdout)["usage"]
finally:
    os.remove(os.path.join(main_super, "usage.json"))
    os.remove(main_local)
check("from a task worktree, the default ledger reads the main worktree's usage.json and CLAUDE.local.md",
      got and got["windows"]["five_hour"]["percent"] == 90 and got["wait"] is None
      and got["economy"] == "five_hour at 90%", got)

# capacity: the measure, the CLAUDE.local.md lines and the decision
capacity_root = tempfile.mkdtemp(prefix="capacity_")
atexit.register(shutil.rmtree, capacity_root, True)
capacity_count = [0]


def parallel(peak=None, floor=None, heavy=None):
    rows = [("Quanto uma cópia ocupa no pico, com a preparação e a verificação", peak),
            ("Memória livre mínima para despachar uma cópia ou um `qa`", floor),
            ("Com o usuário usando a máquina", heavy)]
    return "# Local\n\n## Execução em paralelo\n\n" + "".join(f"- {k}: {v}\n" for k, v in rows if v is not None)


def capacity(local_text=None, memory="10", disk="500", autonomous=False, started=True, extra=()):
    capacity_count[0] += 1
    folder = os.path.join(capacity_root, f"p{capacity_count[0]}")
    os.makedirs(os.path.join(folder, ".superpowers"))
    if local_text is not None:
        with open(os.path.join(folder, "CLAUDE.local.md"), "w", encoding="utf-8") as handle:
            handle.write(local_text)
    path = os.path.join(folder, ".superpowers", "ledger.jsonl")
    if started:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "start", "slug": "x", "base": "abc"}) + "\n")
            if autonomous:
                handle.write(json.dumps({"type": "mode", "mode": "autonomous"}) + "\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith("PIPELINE_CAPACITY")}
    for key, value in (("MEMORY", memory), ("DISK", disk)):
        if value is not None:
            env[f"PIPELINE_CAPACITY_{key}_GB"] = value
    return subprocess.run([sys.executable, LEDGER, "--ledger", path, "capacity", *extra], capture_output=True,
                          text=True, encoding="utf-8", env=env)


def capacity_json(*args, **kwargs):
    result = capacity(*args, extra=("--json",), **kwargs)
    return json.loads(result.stdout) if result.stdout.strip().startswith("{") else {"error": result.stderr}


got = capacity_json(parallel(peak="`5.3`"))
check("capacity peak in backticks", got.get("peak_gb") == 5.3, got)
got = capacity_json(parallel(peak="~5,3 GB no pico"))
check("capacity peak in free text with a comma and ~", got.get("peak_gb") == 5.3, got)
got = capacity_json(parallel(peak="5.3 G"))
check("capacity peak with G and a dot", got.get("peak_gb") == 5.3, got)
got = capacity_json(parallel(peak="~5,3 GB; Disco: 4 GB"))
check("capacity line with a memory peak and a disk peak", got.get("peak_gb") == 5.3 and got.get("disk_peak_gb") == 4, got)
got = capacity_json(parallel(peak="Disco: 4 GB"))
check("capacity line with only a disk peak leaves the memory peak unknown",
      got.get("peak_gb") is None and got.get("disk_peak_gb") == 4, got)
got = capacity_json(parallel(peak='_(memória e disco; ou "a medir")_'))
check("capacity placeholder peak is unknown", got.get("peak_gb") is None and got.get("copies") is None, got)
got = capacity_json(parallel(peak="a medir"))
check("capacity 'a medir' peak is unknown", got.get("peak_gb") is None and got.get("copies") is None, got)
got = capacity_json(parallel(peak="`5`", floor="`2.5`"))
check("capacity floor in backticks", got.get("floor_gb") == 2.5, got)
got = capacity_json(parallel(peak="`5`", floor="_(GB; abaixo disso o manager espera)_"))
check("capacity placeholder floor is missing", got.get("floor_gb") is None, got)
got = capacity_json(parallel(peak="`5`"))
check("capacity missing floor is null", got.get("floor_gb") is None, got)
for text, want in (("`2`", 2), ("uma", 1), ("Duas cópias", 2), ("three", 3), ("quatro", 4), ("2 cópias, e 1 GB livre", 2)):
    got = capacity_json(parallel(peak="`1`", heavy=text))
    check(f"capacity heavy limit from {text!r}", got.get("heavy_limit") == want, got)
got = capacity_json(parallel(peak="`1`", heavy="_(quantas cópias pesadas ao mesmo tempo)_"))
check("capacity placeholder heavy limit is missing", got.get("heavy_limit") is None, got)
got = capacity_json(parallel(peak="`1`"))
check("capacity missing heavy limit is null", got.get("heavy_limit") is None, got)

got = capacity_json(parallel(peak="`2`", floor="`0`"), memory="6")
check("capacity copies just fit (6 - 2n >= 2 gives 2)", got.get("copies") == 2 and got.get("dispatch") is True, got)
got = capacity_json(parallel(peak="`2`", floor="`0`"), memory="5.99")
check("capacity copies just do not fit", got.get("copies") == 1, got)
got = capacity_json(parallel(peak="`2`", floor="`0`"), memory="1.9")
check("capacity copies never negative", got.get("copies") == 0, got)
got = capacity_json(parallel(peak="`2`", floor="`3`"), memory="7")
check("capacity floor above the peak keeps the floor free (7 - 2n >= 3 gives 2)", got.get("copies") == 2, got)
got = capacity_json(parallel(peak="`2`", floor="`3`"), memory="6.9")
check("capacity floor above the peak, just short", got.get("copies") == 1, got)
got = capacity_json(parallel(peak="`5.3`", floor="`2.5`"), memory="4.5")
check("capacity example: no parallel copy, one dispatch fits",
      got.get("copies") == 0 and got.get("dispatch") is True and "no parallel copy" in got.get("reason", ""), got)
got = capacity_json(parallel(peak="`1`", floor="`2`"), memory="2")
check("capacity free memory equal to the floor dispatches", got.get("dispatch") is True, got)
got = capacity_json(parallel(peak="`1`", floor="`0`"), disk="7")
check("capacity without a disk peak ignores the disk", got.get("copies") == 9, got)
got = capacity_json(parallel(peak="`1` GB; disco 4 GB", floor="`0`"), memory="100", disk="12")
check("capacity disk cap (12 - 4n >= 4 gives 2)", got.get("copies") == 2, got)
got = capacity_json(parallel(peak="`1` GB; disco 4 GB", floor="`0`"), memory="100", disk="11.9")
check("capacity disk cap, just short", got.get("copies") == 1, got)
got = capacity_json(parallel(peak="`1`", floor="`0`", heavy="`2`"), memory="100")
check("capacity supervised mode caps by the heavy limit", got.get("copies") == 2 and got.get("autonomous") is False, got)
got = capacity_json(parallel(peak="`1`", floor="`0`", heavy="`2`"), memory="100", autonomous=True)
check("capacity autonomous mode ignores the heavy limit", got.get("copies") == 99 and got.get("autonomous") is True, got)
got = capacity_json(parallel(peak="`1`", floor="`0`", heavy="`2`"), memory="100", started=False)
check("capacity with no ledger is supervised", got.get("autonomous") is False and got.get("copies") == 2, got)
got = capacity_json(parallel(peak="`1`", floor="`0`", heavy="`5`"), memory="3.5")
check("capacity heavy limit above what memory allows does not raise it", got.get("copies") == 2, got)

for value in ("", "abc", "-1"):
    got = capacity_json(parallel(peak="`1`", floor="`2`"), memory=value)
    result = capacity(parallel(peak="`1`", floor="`2`"), memory=value)
    check(f"capacity memory override {value!r} is unknown",
          got.get("memory_free_gb") is None and got.get("dispatch") is None and got.get("copies") is None
          and result.returncode == 0, (got, result.stderr))
got = capacity_json(None, memory="8", started=False)
check("capacity with no ledger and no CLAUDE.local.md",
      got.get("peak_gb") is None and got.get("floor_gb") is None and got.get("heavy_limit") is None
      and got.get("dispatch") is None and got.get("copies") is None and "floor unknown" in got.get("reason", ""), got)
result = capacity(parallel(peak="`1`", floor="`2.5`"), memory="2.4")
check("capacity below the floor exits 1", result.returncode == 1 and result.stdout.startswith("capacity:"), result)
got = capacity_json(parallel(peak="`1`", floor="`2.5`"), memory="2.4")
check("capacity below the floor: dispatch false, no copies", got.get("dispatch") is False and got.get("copies") == 0, got)
result = capacity(parallel(peak="`1`", floor="`2.5`"), memory="2.5")
check("capacity at the floor exits 0 with a single capacity line",
      result.returncode == 0 and result.stdout.startswith("capacity:") and len(result.stdout.splitlines()) == 1, result)
got = capacity_json(parallel(peak="`1`"), memory="4", disk="9")
check("capacity JSON shape", sorted(got) == sorted(["memory_free_gb", "disk_free_gb", "peak_gb", "disk_peak_gb", "floor_gb",
                                                    "heavy_limit", "autonomous", "dispatch", "copies", "reason"])
      and got["memory_free_gb"] == 4 and got["disk_free_gb"] == 9 and isinstance(got["reason"], str), got)
# the real CLAUDE.local.md of Controle Financeiro: the floor and the heavy limit live in free text
CF_LOCAL = """# Controle Financeiro — este computador

## Execução em paralelo

- Quanto uma cópia ocupa no pico, com a preparação, o armazenamento de dados e a verificação (build e suíte): a suíte e2e inteira com 3 workers chegou a ~5,3 GB (node 2,1 GB, WSL/Docker 1,9 GB, Chromium headless 1,3 GB); a pilha de cópia do Supabase soma ao WSL. Disco: medir. A memória livre desta máquina oscila entre 2 e 5 GB, então um despacho novo só sai com mais de ~2 GB livres, e no máximo duas tarefas com pilha, build e Playwright ao mesmo tempo.
- O Lenovo Vantage (`MachineFixSystemAddin`) já chegou a ocupar ~3,9 GB; com a memória baixa e nada da entrega rodando, conferir esse processo primeiro.
- O dono usa a máquina ao mesmo tempo (Chrome, Discord e outros abertos), o que tira de 1 a 2 GB da memória livre. Com o dono presente, rodar uma cópia pesada por vez (pilha, build e Playwright) e tratar menos de ~1 GB livre como falta de recurso.
"""
result = capacity(CF_LOCAL, memory="0.7")
got = capacity_json(CF_LOCAL, memory="0.7")
check("capacity CF lines: 0.7 GB free is below the free-text floor of 2",
      got.get("dispatch") is False and got.get("floor_gb") == 2 and result.returncode == 1, (got, result.stdout))
got = capacity_json(CF_LOCAL, memory="12", disk="9")
check("capacity CF lines: no bogus disk peak from the memory sentence",
      got.get("disk_peak_gb") is None and got.get("peak_gb") == 5.3 and got.get("copies") == 1, got)
got = capacity_json(CF_LOCAL, memory="100")
check("capacity CF lines: heavy limit 1 from 'uma cópia pesada por vez' caps supervised copies",
      got.get("heavy_limit") == 1 and got.get("copies") == 1, got)
got = capacity_json(CF_LOCAL, memory="100", autonomous=True)
check("capacity CF lines: autonomous ignores the free-text heavy limit", got.get("copies") == 17, got)
got = capacity_json(parallel(peak="`1`", floor="`3`", heavy="`2`")
                    + "- Um despacho só sai com mais de ~9 GB livres; uma cópia pesada por vez." + chr(10), memory="100")
check("capacity template labels win over free text", got.get("floor_gb") == 3 and got.get("heavy_limit") == 2, got)
result = capacity(parallel(peak="`1`"), memory="8")
got = capacity_json(parallel(peak="`1`"), memory="8")
check("capacity unknown floor: dispatch null, exit 0, says what to fill",
      got.get("dispatch") is None and result.returncode == 0 and "floor 0" not in got.get("reason", "")
      and 'floor unknown: fill the "Memória livre mínima para despachar" line of CLAUDE.local.md' in got.get("reason", ""), got)
got = capacity_json(parallel(peak="`1`", heavy="Duas cópias, e 1 GB livre"))
check("capacity heavy limit: the word before the digit wins", got.get("heavy_limit") == 2, got)
got = capacity_json(parallel(peak="`1`", floor="`0`", heavy="`0`"), memory="100")
check("capacity heavy limit 0 is unknown, no cap", got.get("heavy_limit") is None and got.get("copies") == 99, got)
got = capacity_json(parallel(peak="`1`", floor="`0`"), memory="8")
check("capacity reason names the memory override", "memory from PIPELINE_CAPACITY_MEMORY_GB" in got.get("reason", ""), got)
got = capacity_json(parallel(peak="~5 GB. Disco: medir. Oscila entre 2 e 5 GB; ou 4.5 GB", floor="`1`"), memory="100")
check("capacity disk 'medir' is unknown", got.get("disk_peak_gb") is None, got)
got = capacity_json(parallel(peak="`1` GB; disco 4.5 GB. Outra frase 9 GB", floor="`1`"), memory="100")
check("capacity disk peak stops at the sentence end and keeps a decimal dot", got.get("disk_peak_gb") == 4.5, got)

result = subprocess.run([sys.executable, LEDGER, "--ledger", os.path.join(capacity_root, "p1", ".superpowers", "ledger.jsonl"),
                         "capacity"], capture_output=True, text=True, encoding="utf-8")
check("capacity measures the machine without overrides",
      result.stdout.startswith("capacity:") and result.returncode in (0, 1), result)


# diff size of each dev task
SIZE = ".superpowers/size.jsonl"
size_tree = os.path.join(worktrees, "size")


def put(cwd, name, text, message):
    with open(os.path.join(cwd, name), "wb") as handle:
        handle.write(text if isinstance(text, bytes) else text.encode("utf-8"))
    git(cwd, "add", name)
    git(cwd, "commit", "-q", "-m", message)


def ledger_entries(ledger):
    with open(os.path.join(repo, ledger), encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def diff_of(ledger, task):
    found = [entry for entry in ledger_entries(ledger) if entry.get("agent") == "dev" and entry.get("task") == task]
    return found[-1].get("diff") if found else "no run"


run("start", "--slug", "size", ledger=SIZE)
put(repo, "s1.txt", "a\nb\nc\n", "S1")
add("dev", "DONE", "S1", ledger=SIZE)
check("a sequential task with no previous run is measured from the delivery base",
      diff_of(SIZE, "S1") == {"files": 1, "added": 3, "removed": 0}, diff_of(SIZE, "S1"))
put(repo, "s1.txt", "a\nb\nX\nY\n", "S2")
add("dev", "DONE", "S2", ledger=SIZE)
check("a sequential task is measured from the head the previous run stored",
      diff_of(SIZE, "S2") == {"files": 1, "added": 2, "removed": 1}, diff_of(SIZE, "S2"))
put(repo, "bin.dat", b"\x00\x01\x02\xff" * 50, "binary")
put(repo, "s3.txt", "one\n", "S3 text")
add("dev", "DONE", "S3", ledger=SIZE)
check("a binary file counts as one file and no lines",
      diff_of(SIZE, "S3") == {"files": 2, "added": 1, "removed": 0}, diff_of(SIZE, "S3"))
add("reviewer", "PASS", ledger=SIZE)
put(repo, "s4.txt", "x\ny\n", "S4")
add("dev", "DONE_WITH_CONCERNS", "fix-1", ledger=SIZE)
check("the previous run of any agent sets the start",
      diff_of(SIZE, "fix-1") == {"files": 1, "added": 2, "removed": 0}, diff_of(SIZE, "fix-1"))

git(repo, "worktree", "add", "-q", "--detach", size_tree)
origin = git(size_tree, "rev-parse", "HEAD")
run("claim", "--task", "W1", "--worktree", size_tree, "--origin", origin, ledger=SIZE)
put(size_tree, "w1.txt", "1\n2\n3\n4\n", "W1 commit")
put(repo, "other.txt", "o\n" * 10, "another task integrated")
r = add("dev", "DONE", "W1", ledger=SIZE)
check("a worktree task counts only its own commits, though the main head moved",
      r.returncode == 0 and diff_of(SIZE, "W1") == {"files": 1, "added": 4, "removed": 0},
      (r.stderr, diff_of(SIZE, "W1")))

def at_head(ledger, task):
    return [entry for entry in ledger_entries(ledger) if entry["type"] == "claim" and entry["task"] == task][-1]


SEQ = ".superpowers/seq.jsonl"
run("start", "--slug", "seq", ledger=SEQ)
put(repo, "plan.md", "p\n" * 200, "docs: plan")
run("claim", "--task", "Q1", ledger=SEQ)
check("claim stores the delivery head at dispatch", at_head(SEQ, "Q1").get("head") == git(repo, "rev-parse", "HEAD"),
      at_head(SEQ, "Q1"))
put(repo, "q1.txt", "one\n", "Q1 commit")
add("dev", "DONE", "Q1", ledger=SEQ)
check("a sequential T1 after a plan commit counts only its own lines",
      diff_of(SEQ, "Q1") == {"files": 1, "added": 1, "removed": 0}, diff_of(SEQ, "Q1"))
put(repo, "errata.md", "e\n" * 5, "docs: errata")
run("claim", "--task", "Q2", ledger=SEQ)
put(repo, "q2.txt", "a\nb\n", "Q2 commit")
add("dev", "DONE", "Q2", ledger=SEQ)
check("an errata commit between runs is not charged to the next task",
      diff_of(SEQ, "Q2") == {"files": 1, "added": 2, "removed": 0}, diff_of(SEQ, "Q2"))

BARE = ".superpowers/bare-claim.jsonl"
run("start", "--slug", "bare-claim", ledger=BARE)
put(repo, "plan2.md", "p\n" * 7, "docs: plan 2")
with open(os.path.join(repo, BARE), "a", encoding="utf-8", newline="\n") as handle:
    handle.write(json.dumps({"type": "claim", "task": "O1", "at": "2026-10-01T10:00:00+00:00"}) + "\n")
put(repo, "o1.txt", "x\n", "O1 commit")
add("dev", "DONE", "O1", ledger=BARE)
check("a claim without head (an old ledger) falls back to the delivery base",
      diff_of(BARE, "O1") == {"files": 2, "added": 8, "removed": 0}, diff_of(BARE, "O1"))
put(repo, "o2.txt", "y\n", "O2 commit")
with open(os.path.join(repo, BARE), "a", encoding="utf-8", newline="\n") as handle:
    handle.write(json.dumps({"type": "claim", "task": "O2", "at": "2026-10-01T10:00:00+00:00"}) + "\n")
add("dev", "DONE", "O2", ledger=BARE)
check("a claim without head falls back to the head the previous run stored",
      diff_of(BARE, "O2") == {"files": 1, "added": 1, "removed": 0}, diff_of(BARE, "O2"))

REBASE = ".superpowers/rebase.jsonl"
rebase_tree = os.path.join(worktrees, "rebase")
run("start", "--slug", "rebase", ledger=REBASE)
git(repo, "worktree", "add", "-q", "--detach", rebase_tree)
run("claim", "--task", "R1", "--worktree", rebase_tree, "--origin", git(rebase_tree, "rev-parse", "HEAD"), ledger=REBASE)
put(rebase_tree, "r1.txt", "1\n2\n", "R1 commit")
put(repo, "integrated.txt", "i\n" * 50, "another task integrated")
git(rebase_tree, "rebase", "-q", git(repo, "rev-parse", "HEAD"))
r = add("dev", "DONE", "R1", ledger=REBASE)
check("a rebased worktree counts only its own lines, not the integration it was rebased onto",
      r.returncode == 0 and diff_of(REBASE, "R1") == {"files": 1, "added": 2, "removed": 0}, (r.stderr, diff_of(REBASE, "R1")))

NOORIGIN = ".superpowers/noorigin.jsonl"
noorigin_tree = os.path.join(worktrees, "noorigin")
run("start", "--slug", "noorigin", ledger=NOORIGIN)
git(repo, "worktree", "add", "-q", "--detach", noorigin_tree)
run("claim", "--task", "N1", "--worktree", noorigin_tree, ledger=NOORIGIN)
put(noorigin_tree, "n1.txt", "1\n2\n3\n", "N1 commit")
put(repo, "integrated2.txt", "i\n" * 20, "another task integrated")
r = add("dev", "DONE", "N1", ledger=NOORIGIN)
check("a worktree claim made without --origin is measured from the merge-base",
      r.returncode == 0 and diff_of(NOORIGIN, "N1") == {"files": 1, "added": 3, "removed": 0}, (r.stderr, diff_of(NOORIGIN, "N1")))

FASTFWD = ".superpowers/fastfwd.jsonl"
fastfwd_tree = os.path.join(worktrees, "fastfwd")
run("start", "--slug", "fastfwd", ledger=FASTFWD)
git(repo, "worktree", "add", "-q", "--detach", fastfwd_tree)
run("claim", "--task", "F1", "--worktree", fastfwd_tree, "--origin", git(fastfwd_tree, "rev-parse", "HEAD"), ledger=FASTFWD)
put(fastfwd_tree, "f1.txt", "1\n2\n3\n4\n5\n", "F1 commit")
git(repo, "merge", "-q", "--ff-only", git(fastfwd_tree, "rev-parse", "HEAD"))
r = add("dev", "DONE", "F1", ledger=FASTFWD)
check("a worktree task integrated by fast-forward before its add is measured from the claim's origin",
      r.returncode == 0 and diff_of(FASTFWD, "F1") == {"files": 1, "added": 5, "removed": 0}, (r.stderr, diff_of(FASTFWD, "F1")))

WIP = ".superpowers/wip.jsonl"
wip_tree = os.path.join(worktrees, "wip")
run("start", "--slug", "wip", ledger=WIP)
git(repo, "worktree", "add", "-q", "--detach", wip_tree)
run("claim", "--task", "P1", "--worktree", wip_tree, "--origin", git(wip_tree, "rev-parse", "HEAD"), ledger=WIP)
put(wip_tree, "p1.txt", "1\n2\n3\n", "wip: P1 first part")
add("dev", "NEEDS_CONTEXT", "P1", ledger=WIP)
first = [e for e in ledger_entries(WIP) if e.get("agent") == "dev"][-1]
check("a worktree run stores the tip it was measured at",
      first.get("tip") == git(wip_tree, "rev-parse", "HEAD") and first["diff"]["added"] == 3, first)
run("claim", "--task", "P1", "--worktree", wip_tree, "--origin", git(wip_tree, "rev-parse", "HEAD"), ledger=WIP)
put(wip_tree, "p1b.txt", "a\nb\n", "P1 second part")
add("dev", "NEEDS_CONTEXT", "P1", ledger=WIP)
check("a re-claimed task does not count its wip lines twice",
      diff_of(WIP, "P1") == {"files": 1, "added": 2, "removed": 0}
      and status(WIP)["metrics"]["lines"]["tasks"] == {"P1": 5}, (diff_of(WIP, "P1"), status(WIP)["metrics"]["lines"]))
run("claim", "--task", "P1", "--worktree", wip_tree, "--origin", git(wip_tree, "rev-parse", "HEAD"), ledger=WIP)
git(wip_tree, "reset", "-q", "--hard", first["tip"])
put(wip_tree, "p2.txt", "q\n", "P1 redone")
add("dev", "DONE_WITH_CONCERNS", "P1", ledger=WIP)
check("a stored tip that is not an ancestor of the tip is ignored",
      diff_of(WIP, "P1") == {"files": 2, "added": 4, "removed": 0}, diff_of(WIP, "P1"))

SIMP = ".superpowers/simpler.jsonl"
run("start", "--slug", "simpler", ledger=SIMP)
r = run("add", "--agent", "dev", "--verdict", "NEEDS_CONTEXT", "--simpler", "--task", "S1", ledger=SIMP)
check("--simpler is gone: add refuses it and writes nothing", r.returncode != 0 and ledger_lines(SIMP) == 1, r.stderr)
with open(os.path.join(repo, SIMP), "a", encoding="utf-8", newline="\n") as handle:
    handle.write(json.dumps({"type": "run", "agent": "dev", "task": "S1", "verdict": "NEEDS_CONTEXT", "open": 0,
                             "head": "", "simpler": True, "at": "2026-10-01T10:00:00+00:00"}) + "\n")
add("dev", "NEEDS_CONTEXT", "S2", ledger=SIMP)
add("dev", "BLOCKED", "S3", ledger=SIMP)
add("dev", "NEEDS_CONTEXT", "S4", ledger=SIMP)
add("dev", "DONE", "S5", ledger=SIMP)
found = status(SIMP)["metrics"].get("verdicts")
check("metrics.verdicts counts the questions and the blocks over the dev runs; an older simpler run is a question",
      found == {"needs_context": 3, "blocked": 1}, found)

BROKEN = ".superpowers/broken.jsonl"
run("start", "--slug", "broken", ledger=BROKEN)
with open(os.path.join(repo, BROKEN), encoding="utf-8") as handle:
    text = handle.read().replace(git(repo, "rev-parse", "HEAD"), "0" * 40)
with open(os.path.join(repo, BROKEN), "w", encoding="utf-8", newline="\n") as handle:
    handle.write(text)
r = add("dev", "DONE", "B1", ledger=BROKEN)
check("a git failure stores no diff and the add still succeeds",
      r.returncode == 0 and "0" * 40 in text and "diff" not in ledger_entries(BROKEN)[-1],
      (r.stderr, ledger_entries(BROKEN)[-1]))

LINES = ".superpowers/lines.jsonl"
at = "2026-10-01T10:00:00+00:00"
with open(os.path.join(repo, LINES), "w", encoding="utf-8", newline="\n") as handle:
    handle.write(json.dumps({"type": "start", "slug": "lines", "base": "abc", "at": at}) + "\n")
    for task, verdict, diff in (("T1", "NEEDS_CONTEXT", {"files": 1, "added": 5, "removed": 5}),
                                ("T1", "DONE", {"files": 3, "added": 90, "removed": 20}),
                                ("T2", "DONE", {"files": 1, "added": 40, "removed": 0}),
                                ("T3", "DONE", None),
                                ("fix-1", "DONE", {"files": 1, "added": 20, "removed": 10}),
                                ("cleanup", "DONE", {"files": 2, "added": 2, "removed": 10})):
        entry = {"type": "run", "agent": "dev", "task": task, "verdict": verdict, "open": 0, "head": "", "at": at}
        handle.write(json.dumps({**entry, **({"diff": diff} if diff else {})}) + "\n")
lines = status(LINES)["metrics"].get("lines")
check("metrics.lines sums the lines per task over its dev runs, the total and the unmeasured runs",
      lines and lines["tasks"] == {"T1": 120, "T2": 40, "fix-1": 30, "cleanup": 12} and lines["total"] == 202
      and lines["unmeasured"] == 1, lines)
check("metrics.lines gives the follow-up lines (fix-N and cleanup) and their share, to 2 decimals",
      lines and lines["follow_up"] == 42 and lines["share"] == 0.21, lines)
old = status(".superpowers/legacy.jsonl")["metrics"].get("lines")
check("an old ledger without diff counts every dev run as unmeasured, total 0 and share null",
      old == {"tasks": {}, "total": 0, "follow_up": 0, "share": None, "unmeasured": 2}, old)

IDLE = ".superpowers/idle.jsonl"
run("start", "--slug", "idle", ledger=IDLE)
run("claim", "--task", "I1", ledger=IDLE)
state = status(IDLE)
check("a claim in flight says how long it has been waiting, and that nothing is committed yet",
      state["claims"][0]["waiting_minutes"] == 0 and state["claims"][0]["committed"] is False, state["claims"])
check("the claim's text line names the waiting time and does not tell the manager to wait for a notification",
      "waiting 0m" in run("status", ledger=IDLE).stdout
      and "notification" not in run("status", ledger=IDLE).stdout, run("status", ledger=IDLE).stdout)
subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "dev work"], cwd=repo, check=True, capture_output=True)
state = status(IDLE)
check("a claim with no worktree whose branch head moved is flagged: the dev's work may already be committed",
      state["claims"][0]["committed"] is True, state["claims"])
check("status then tells the manager to add it and go on, instead of leaving the claim open",
      "add it and go on" in run("status", ledger=IDLE).stdout, run("status", ledger=IDLE).stdout)
r = run("claim", "--task", "I2", "--worktree", repo, "--origin", "HEAD", ledger=IDLE)
state = status(IDLE)
by_task = {claim["task"]: claim for claim in state["claims"]}
check("a claim in a worktree is never flagged as committed: the delivery head moves with every integration",
      r.returncode == 0 and by_task["I2"]["committed"] is False, state["claims"])

UNMEASURED = ".superpowers/unmeasured.jsonl"
at = ["2026-10-01T10:00:00+00:00", "2026-10-01T10:05:00+00:00", "2026-10-01T11:05:00+00:00"]
with open(os.path.join(repo, UNMEASURED), "w", encoding="utf-8", newline="\n") as handle:
    handle.write(json.dumps({"type": "start", "slug": "unmeasured", "base": "abc", "at": at[0]}) + "\n")
    for task, when in (("T1", at[1]), ("T2", at[2])):
        handle.write(json.dumps({"type": "run", "agent": "dev", "task": task, "verdict": "DONE", "open": 0,
                                 "head": "", "at": when}) + "\n")
cycle = status(UNMEASURED)["metrics"]["cycles"][0]
check("a cycle whose runs carry no --seconds still reports its wall-clock elapsed, from the run timestamps",
      cycle["seconds"] == 0 and cycle["elapsed"] == 3600, cycle)

check("an old ledger counts its needs-context runs",
      status(LINES)["metrics"].get("verdicts") == {"needs_context": 1, "blocked": 0},
      status(LINES)["metrics"].get("verdicts"))

MEASURE = ".superpowers/measure.jsonl"
run("start", "--slug", "measure", ledger=MEASURE)
add("dev", "DONE", "M1", ledger=MEASURE)
add("reviewer", "PASS", ledger=MEASURE)
check("a run added before its completion notification arrived counts as unmeasured",
      status(MEASURE)["metrics"]["time"]["unmeasured"] == 2, status(MEASURE)["metrics"]["time"])
r = run("measure", "--agent", "dev", "--task", "M1", "--seconds", "2m", "--tokens", "50000", ledger=MEASURE)
clocked, tokens = status(MEASURE)["metrics"]["time"], status(MEASURE)["metrics"]["tokens"]
check("measure fills the numbers of a run already added, so a late notification is never waited for",
      r.returncode == 0 and clocked["agents"] == {"dev": 120} and clocked["tasks"] == {"M1": 120}
      and tokens["agents"] == {"dev": 50000} and clocked["unmeasured"] == 1, (r.stderr, clocked, tokens))
check("the measure is a line of its own: the ledger stays append-only",
      [entry["type"] for entry in ledger_entries(MEASURE)] == ["start", "run", "run", "measure"],
      [entry["type"] for entry in ledger_entries(MEASURE)])
r = run("measure", "--agent", "dev", "--task", "M1", "--seconds", "3m", ledger=MEASURE)
check("measuring the same number twice is refused: it comes from the notification, never an estimate",
      r.returncode != 0 and "already measured" in r.stderr, r.stderr)
r = run("measure", "--agent", "reviewer", "--tokens", "9000", ledger=MEASURE)
check("measure takes one number alone, for a notification that gives only that one",
      r.returncode == 0 and status(MEASURE)["metrics"]["tokens"]["agents"] == {"dev": 50000, "reviewer": 9000},
      (r.stderr, status(MEASURE)["metrics"]["tokens"]))
r = run("measure", "--agent", "qa", "--seconds", "60", ledger=MEASURE)
check("measure is refused when that agent has no run to complete", r.returncode != 0 and "no qa run" in r.stderr,
      r.stderr)
r = run("measure", "--agent", "dev", "--task", "M1", ledger=MEASURE)
check("measure with neither number is refused", r.returncode != 0, r.stderr)
r = run("measure", "--agent", "dev", "--task", "M1", "--seconds", "0", ledger=MEASURE)
check("measure keeps the rule that 0 is no measurement", r.returncode != 0, r.stderr)

SPAN = ".superpowers/span.jsonl"
run("start", "--slug", "span", ledger=SPAN)
add("dev", "DONE", "S1", ledger=SPAN)
check("a cycle of one unmeasured run has no elapsed: a zero span is not a measurement",
      status(SPAN)["metrics"]["cycles"][0]["elapsed"] is None, status(SPAN)["metrics"]["cycles"][0])

BATCH = ".superpowers/batch.jsonl"
run("start", "--slug", "batch", ledger=BATCH)
add("reviewer", "FAIL", open_count=2, ledger=BATCH)
add("dev", "DONE", "fix-1", ledger=BATCH)
time.sleep(1)  # at is stamped to the second, and these two reviewer runs have to be told apart
add("reviewer", "PASS", ledger=BATCH)
rounds = [entry for entry in ledger_entries(BATCH) if entry["type"] == "run" and entry["agent"] == "reviewer"]
r = run("measure", "--agent", "reviewer", "--seconds", "300", ledger=BATCH)
check("with two runs of that agent unmeasured, measure refuses to guess which one the notification completes",
      r.returncode != 0 and "--at" in r.stderr and all(entry["at"] in r.stderr for entry in rounds), r.stderr)
r = run("measure", "--agent", "reviewer", "--at", rounds[1]["at"], "--seconds", "300", "--tokens", "9000", ledger=BATCH)
check("--at names the run the notification completes, and nothing else is touched",
      r.returncode == 0 and status(BATCH)["metrics"]["time"]["agents"]["reviewer"] == 300
      and status(BATCH)["metrics"]["time"]["unmeasured"] == 2, (r.stderr, status(BATCH)["metrics"]["time"]))
r = run("measure", "--agent", "reviewer", "--at", rounds[0]["at"], "--seconds", "60", "--tokens", "1000", ledger=BATCH)
check("the notification of the earlier run fills that run: a batch of them lands one per run",
      r.returncode == 0 and status(BATCH)["metrics"]["time"]["agents"]["reviewer"] == 360,
      (r.stderr, status(BATCH)["metrics"]["time"]))
r = run("measure", "--agent", "reviewer", "--at", "2020-01-01T00:00:00+00:00", "--seconds", "60", ledger=BATCH)
check("--at that names no run of that agent is refused instead of landing somewhere",
      r.returncode != 0 and "no reviewer run at" in r.stderr, r.stderr)
r = run("measure", "--agent", "reviewer", "--at", rounds[1]["at"], "--seconds", "90", ledger=BATCH)
check("a run already measured is refused even when --at names it",
      r.returncode != 0 and "already measured" in r.stderr, r.stderr)

LOST = ".superpowers/lost.jsonl"
run("start", "--slug", "lost", ledger=LOST)
add("dev", "DONE", "L1", ledger=LOST)
add("qa", "FAIL", open_count=1, ledger=LOST)
add("dev", "DONE", "fix-1", ledger=LOST)
time.sleep(1)
add("qa", "PASS", ledger=LOST)
lost = [entry for entry in ledger_entries(LOST) if entry["type"] == "run" and entry["agent"] == "qa"]
r = run("measure", "--agent", "qa", "--at", lost[1]["at"], "--seconds", "120", ledger=LOST)
qa_runs = [entry for entry in status(LOST)["runs"] if entry["agent"] == "qa"]
check("a notification that never arrived for an earlier run does not shift the later ones",
      r.returncode == 0 and qa_runs[1].get("seconds") == 120 and qa_runs[0].get("seconds") is None,
      [(entry["verdict"], entry.get("seconds")) for entry in qa_runs])

OLD = ".superpowers/old.jsonl"
run("start", "--slug", "old", ledger=OLD)
add("reviewer", "FAIL", open_count=1, ledger=OLD)
add("dev", "DONE", "fix-1", ledger=OLD)
add("reviewer", "PASS", ledger=OLD)
with open(os.path.join(repo, OLD), "a", encoding="utf-8", newline="\n") as handle:
    handle.write(json.dumps({"type": "measure", "agent": "reviewer", "task": "", "seconds": 240,
                             "at": "2026-10-18T12:00:00+00:00"}) + "\n")
old_rounds = [entry for entry in status(OLD)["runs"] if entry["agent"] == "reviewer"]
check("a measure line of 1.9.8, which names no run, still fills the latest one, so those ledgers read the same",
      old_rounds[-1].get("seconds") == 240 and old_rounds[0].get("seconds") is None,
      [(entry["verdict"], entry.get("seconds")) for entry in old_rounds])

TIE = ".superpowers/tie.jsonl"
run("start", "--slug", "tie", ledger=TIE)
SAME = "2026-10-18T12:00:00+00:00"
with open(os.path.join(repo, TIE), "a", encoding="utf-8", newline="\n") as handle:
    for _ in range(2):
        handle.write(json.dumps({"type": "run", "agent": "reviewer", "task": "", "verdict": "PASS", "open": 0,
                                 "critical": 0, "important": 0, "minor": 0, "origin": {}, "head": "",
                                 "at": SAME}) + "\n")
r = run("measure", "--agent", "reviewer", "--at", SAME, "--seconds", "60", ledger=TIE)
check("two runs stamped in the same second are left unmeasured, not measured on a guess",
      r.returncode != 0 and "tells them apart" in r.stderr, r.stderr)

SPLIT = ".superpowers/split.jsonl"
run("start", "--slug", "split", ledger=SPLIT)
add("reviewer", "FAIL", open_count=1, seconds=60, ledger=SPLIT)
add("dev", "DONE", "fix-1", ledger=SPLIT)
time.sleep(1)
add("reviewer", "PASS", ledger=SPLIT)
split = [entry for entry in ledger_entries(SPLIT) if entry["type"] == "run" and entry["agent"] == "reviewer"]
run("measure", "--agent", "reviewer", "--at", split[1]["at"], "--seconds", "100", "--tokens", "5000", ledger=SPLIT)
rounds = [entry for entry in status(SPLIT)["runs"] if entry["agent"] == "reviewer"]
check("one notification fills one run: its two numbers never split between two runs",
      rounds[0].get("tokens") is None and rounds[1].get("seconds") == 100 and rounds[1].get("tokens") == 5000,
      [(entry.get("seconds"), entry.get("tokens")) for entry in rounds])

WAIVED = ".superpowers/waived.jsonl"
run("start", "--slug", "waived", ledger=WAIVED)
add("dev", "DONE", "W1", ledger=WAIVED)
add("qa", "FAIL", open_count=1, ledger=WAIVED)
run("waive", "--agent", "qa", "--reason", "the user accepted it", ledger=WAIVED)
r = run("measure", "--agent", "qa", "--seconds", "120", ledger=WAIVED)
check("the number lands on the run that really ran, never on the waiver the metrics leave out",
      r.returncode == 0 and status(WAIVED)["metrics"]["time"]["agents"].get("qa") == 120,
      (r.stderr, status(WAIVED)["metrics"]["time"]))
r = run("measure", "--agent", "qa", "--seconds", "90", ledger=WAIVED)
check("with the real run measured and only the waiver left, another measure is refused",
      r.returncode != 0 and "already measured" in r.stderr, r.stderr)

CARRY = ".superpowers/carry.jsonl"
QUALITY = os.path.join(repo, "docs", "quality-reports")
os.makedirs(QUALITY, exist_ok=True)
with open(os.path.join(QUALITY, "2026-09-01-a.md"), "w", encoding="utf-8", newline="\n") as handle:
    handle.write("# a\n\n## Deferred\n\n- D1 old thing -> moved to b: later\n")
with open(os.path.join(QUALITY, "2026-10-01-b.md"), "w", encoding="utf-8", newline="\n") as handle:
    handle.write("# b\n\n## Deferred\n\n- D1 export csv -> moved to c: needs the API\n- D2 typo -> fixed in fix-1\n"
                 "- D3 a -> b mapping -> moved to the car test: needs the car\n"
                 "- D4 old csv (moved here by docs/quality-reports/2026-09-01-a.md) -> moved to z-later: not yet\n"
                 "- D5 vague -> moved to backlog\n"
                 "\n## Metrics\n\n- D9 not deferred -> moved to x\n")
r = run("start", "--slug", "c", ledger=CARRY)
state = status(CARRY)
LATEST = "docs/quality-reports/2026-10-01-b.md"
check("start carries the items the latest quality report moved to this delivery or to no named one, each needing "
      "a decision, and passes on, resolved, one moved to another delivery, its chain of reports cut to the last",
      r.returncode == 0 and "carried 3 items moved to a later delivery from " + LATEST in r.stdout
      and "passed on 1 item moved to another delivery" in r.stdout and "- D3 -> z-later: old csv" in r.stdout
      and state["deferred"] == [{"id": "D1", "text": f"export csv (moved here by {LATEST})", "decision": None,
                                 "recommend": "decide whether this delivery takes it: moved to c: needs the API"},
                                {"id": "D2", "text": f"a -> b mapping (moved here by {LATEST})", "decision": None,
                                 "recommend": "decide whether this delivery takes it: moved to the car test: needs the car"},
                                {"id": "D3", "text": f"old csv (moved here by {LATEST})",
                                 "decision": "moved to z-later: not yet", "recommend": "moved to z-later: not yet"},
                                {"id": "D4", "text": f"vague (moved here by {LATEST})", "decision": None,
                                 "recommend": "decide whether this delivery takes it: moved to backlog"}]
      and {"step": "decide", "id": "D1", "text": f"export csv (moved here by {LATEST})",
           "recommend": "decide whether this delivery takes it: moved to c: needs the API"} in state["steps"],
      (r.stdout, state["deferred"], state["steps"]))
check("a carried item numbers the next deferred item after it",
      "deferred D5" in run("defer", "--text", "x", "--recommend", "y", ledger=CARRY).stdout)
with open(os.path.join(QUALITY, "2026-10-01-zeta.md"), "w", encoding="utf-8", newline="\n") as handle:
    handle.write("# zeta\n\n## Deferred\n\n- D1 stale -> moved to alpha: older\n")
with open(os.path.join(QUALITY, "2026-10-01-alpha.md"), "w", encoding="utf-8", newline="\n") as handle:
    handle.write("# alpha\n\n## Deferred\n\n- D1 thing -> moved to d: map a -> b\n- D2 other -> Moved to d: later\n")
for name in ("2026-10-01-zeta.md", "2026-10-01-alpha.md"):
    subprocess.run(["git", "add", "-f", os.path.join("docs", "quality-reports", name)], cwd=repo, check=True,
                   capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", f"docs: quality report {name}"], cwd=repo, check=True,
                   capture_output=True)
r = run("start", "--slug", "e", "--archive", ledger=CARRY)
texts = [item["text"] for item in status(CARRY)["deferred"]]
check("the latest report is the one committed last, not the last by name, and an arrow in a reason or a capital "
      "Moved keeps the item", r.returncode == 0
      and texts == ["thing (moved here by docs/quality-reports/2026-10-01-alpha.md)",
                    "other (moved here by docs/quality-reports/2026-10-01-alpha.md)"], (r.stdout, texts))
subprocess.run(["git", "rm", "-q", "-r", os.path.join("docs", "quality-reports")], cwd=repo, check=True,
               capture_output=True)
subprocess.run(["git", "commit", "-q", "-m", "docs: drop reports"], cwd=repo, check=True, capture_output=True)
for name in os.listdir(QUALITY) if os.path.isdir(QUALITY) else []:
    os.remove(os.path.join(QUALITY, name))
r = run("start", "--slug", "d", "--archive", ledger=CARRY)
check("with no quality report, start carries nothing", r.returncode == 0 and "carried" not in r.stdout
      and status(CARRY)["deferred"] == [], (r.stdout, status(CARRY)["deferred"]))

# runs with no seconds, listed for measure --at
UNM = ".superpowers/unmeasured-list.jsonl"
run("start", "--slug", "unmeasured", ledger=UNM)
add("dev", "DONE", "T1", ledger=UNM)
add("dev", "DONE", "T2", ledger=UNM, seconds=60)
add("reviewer", "PASS", ledger=UNM)
r = run("status", ledger=UNM)
listed = [line for line in r.stdout.splitlines() if line.startswith("unmeasured:")]
first = status(UNM)["unmeasured"]
check("status lists each run with no seconds, with the measure --at that fills it",
      len(listed) == 2 and listed[0].startswith("unmeasured: dev T1 at ")
      and f"measure --agent dev --task T1 --at {first[0]['at']}" in listed[0]
      and listed[1].startswith("unmeasured: reviewer at ") and "--task" not in listed[1], r.stdout)
check("status --json lists them too, oldest first, and a measured run is not there",
      [(item["agent"], item["task"]) for item in first] == [("dev", "T1"), ("reviewer", "")], first)
run("measure", "--agent", "dev", "--task", "T1", "--seconds", "5m", ledger=UNM)
check("a run measured after its add leaves the list",
      [item["agent"] for item in status(UNM)["unmeasured"]] == ["reviewer"], status(UNM)["unmeasured"])

# a dev running past the limit is asked for a partial report
LONG = ".superpowers/long.jsonl"
run("start", "--slug", "long", ledger=LONG)
old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=95)).isoformat(timespec="seconds")
with open(os.path.join(repo, LONG), "a", encoding="utf-8", newline="\n") as handle:
    handle.write(json.dumps({"type": "claim", "task": "L1", "at": old}) + "\n")
run("claim", "--task", "L2", ledger=LONG)
r = run("status", ledger=LONG)
state = status(LONG)
check("a dev claim waiting 90 minutes or more asks for a partial report; a recent one does not",
      "dev L1 dispatched" in r.stdout and "partial report" in r.stdout.split("dev L1 dispatched")[1].split("\n")[0]
      and "partial report" not in r.stdout.split("dev L2 dispatched")[1].split("\n")[0]
      and [claim["partial_report"] for claim in state["claims"]] == [True, False], (r.stdout, state["claims"]))

# the first cycle closes only once qa ran the interface, when the project has a Verificação de interface line
iface = tempfile.mkdtemp(prefix="ledger_iface_", dir=repo)
for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@t.com"), ("config", "user.name", "t"),
             ("commit", "-q", "--allow-empty", "-m", "base")):
    subprocess.run(["git", *args], cwd=iface, check=True, capture_output=True)
IFACE = os.path.join(iface, ".superpowers", "ledger.jsonl")


def iface_line(value):
    with open(os.path.join(iface, "CLAUDE.md"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write("# p\n\n## Comandos\n\n- Testes: `npm test`\n"
                     f"- Verificação de interface (se houver tela): {value}\n\n## Outra\n")


iface_line("_(comando)_")
run("start", "--slug", "iface", ledger=IFACE, cwd=iface)
add("dev", "DONE", "T1", ledger=IFACE)
add("reviewer", "PASS", ledger=IFACE)
add("qa", "PASS", ledger=IFACE)
check("with the interface line still a placeholder, cycle 1 closes on a qa PASS",
      status(IFACE)["ready_for_gate"] is True, status(IFACE)["pending"])
iface_line("`npx maestro test e2e/`")
state = status(IFACE)
check("with an interface command, cycle 1 does not close until a qa ran it, and says the machine is a block",
      state["ready_for_gate"] is False and any("interface" in item and "Preparar uma máquina" in item
                                               for item in state["pending"])
      and {"step": "qa", "interface": True} in state["steps"], state["pending"])
add("dev", "DONE", "T2", ledger=IFACE)
check("a dev task added before the interface ran stays in cycle 1", status(IFACE)["cycle"] == 1, status(IFACE)["cycle"])
r = run("add", "--agent", "reviewer", "--verdict", "PASS", "--interface", ledger=IFACE)
check("--interface is refused on the reviewer", r.returncode != 0 and "--interface" in r.stderr, r.stderr)
add("reviewer", "PASS", ledger=IFACE)
r = run("add", "--agent", "qa", "--verdict", "PASS", "--interface", ledger=IFACE)
state = status(IFACE)
check("a qa added with --interface closes cycle 1 and is stored on the run",
      r.returncode == 0 and state["ready_for_gate"] is True and state["qa"][0].get("interface") is True,
      (r.stderr, state["pending"]))
add("dev", "DONE", "T3", ledger=IFACE)
add("reviewer", "PASS", ledger=IFACE)
add("qa", "PASS", ledger=IFACE)
state = status(IFACE)
check("a later cycle closes on a qa PASS with no interface run", state["cycle"] == 2 and state["ready_for_gate"] is True,
      state["pending"])
IFACE_FULL = os.path.join(iface, ".superpowers", "full.jsonl")
run("start", "--slug", "iface-full", ledger=IFACE_FULL, cwd=iface)
add("dev", "DONE", "T1", ledger=IFACE_FULL)
add("reviewer", "PASS", ledger=IFACE_FULL)
run("add", "--agent", "qa", "--verdict", "PASS", "--full", ledger=IFACE_FULL)
check("a qa of the full suite counts as the interface run", status(IFACE_FULL)["ready_for_gate"] is True,
      status(IFACE_FULL)["pending"])

# each task of the plan with its Goal, Depends on and state, for the progress table
PLANNED = ".superpowers/planned.jsonl"
os.makedirs(os.path.join(repo, "docs", "plans"), exist_ok=True)
with open(os.path.join(repo, "docs", "plans", "planned.md"), "w", encoding="utf-8", newline="\n") as handle:
    handle.write("# Plano\n\n## Ciclo 1\n\n### T1 — Primeira\n- **Goal:** spec §1: a pessoa entra.\n"
                 "- **Depends on:** none.\n- **AC-T1-1** given a.\n\n## T2: Segunda\n\n**Goal:** spec §2: vê o painel.\n\n"
                 "**Depends on:** T1.\n\n### T3 — Terceira\nGoal: a terceira.\nDepends on: T1, T2 (a tela).\n\n"
                 "## Errata\n")
run("start", "--slug", "planned", ledger=PLANNED)
run("plan", "--path", "docs/plans/planned.md", ledger=PLANNED)
run("scope", "--cycle", "1", "--tasks", "T1,T2", ledger=PLANNED)
run("scope", "--cycle", "2", "--tasks", "T3,T4", ledger=PLANNED)
scope = status(PLANNED)["scope"]
check("scope gives each task with the Goal and Depends on read from the plan, and its state",
      scope["tasks"] == [
          {"task": "T1", "cycle": "1", "goal": "spec §1: a pessoa entra.", "depends": "none.", "state": "todo"},
          {"task": "T2", "cycle": "1", "goal": "spec §2: vê o painel.", "depends": "T1.", "state": "blocked"},
          {"task": "T3", "cycle": "2", "goal": "a terceira.", "depends": "T1, T2 (a tela).", "state": "blocked"},
          {"task": "T4", "cycle": "2", "goal": None, "depends": None, "state": "todo"}]
      and scope["median_task_seconds"] is None, scope)
add("dev", "DONE", "T1", ledger=PLANNED, seconds=600)
run("claim", "--task", "T2", ledger=PLANNED)
scope = status(PLANNED)["scope"]
check("a done task, a running one with its minutes, and the median of the measured tasks",
      [(item["task"], item["state"]) for item in scope["tasks"]]
      == [("T1", "done"), ("T2", "running"), ("T3", "blocked"), ("T4", "todo")]
      and scope["tasks"][1]["minutes"] == 0 and scope["median_task_seconds"] == 600, scope)

# the security scan, one review loop counted apart
SEC = ".superpowers/security.jsonl"
run("start", "--slug", "security", ledger=SEC)
add("dev", "DONE", "T1", ledger=SEC)
add("reviewer", "PASS", ledger=SEC)
add("qa", "PASS", ledger=SEC)
SCAN = report_file("security-1.md")
r = run("add", "--agent", "reviewer", "--task", "security", "--verdict", "FAIL", "--important", "1", "--origin",
        "execution=1", "--report", SCAN, ledger=SEC)
state = status(SEC)
check("a security scan is a review loop: its FAIL asks for the next round on the corrections only",
      r.returncode == 0 and state["ready_for_gate"] is False
      and any(step.get("step") == "review" and step.get("task") == "security" for step in state["steps"])
      and state["cycle"] == 1 and state["metrics"]["reviews"]["security"]["important"] == 1, (r.stderr, state["steps"]))
r = run("waive", "--agent", "reviewer", "--task", "security", "--reason", "fixed in fix-1, reviewed", ledger=SEC)
check("waive --task security closes the loop", r.returncode == 0 and status(SEC)["ready_for_gate"] is True,
      (r.stderr, status(SEC)["pending"]))

SENS = ".superpowers/sensitive.jsonl"
run("start", "--slug", "sensitive", ledger=SENS)
check("sensitive needs a reason", run("sensitive", ledger=SENS).returncode != 0)
r = run("sensitive", "--reason", "writes money", ledger=SENS)
add("dev", "DONE", "T1", ledger=SENS)
check("the scan is no step while the cycle is open", not any(step["step"] == "security" for step in status(SENS)["steps"]),
      status(SENS)["steps"])
add("reviewer", "PASS", ledger=SENS)
add("qa", "PASS", ledger=SENS)
state = status(SENS)
check("a delivery marked sensitive is not ready for the gate until its security scan ran",
      r.returncode == 0 and state["ready_for_gate"] is False
      and any("security scan" in item and "writes money" in item for item in state["pending"])
      and {"step": "security", "reason": "writes money"} in state["steps"], (r.stderr, state["pending"], state["steps"]))
run("add", "--agent", "reviewer", "--task", "security", "--verdict", "PASS", "--report", report_file("scan.md"),
    ledger=SENS)
check("its security scan's PASS makes it ready", status(SENS)["ready_for_gate"] is True, status(SENS)["pending"])

# A qa report is checked on add, and a qa that tested a commit before the fix does not count as its re-run
EARLY = ".superpowers/early.jsonl"
run("start", "--slug", "early", ledger=EARLY)
subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "E1"], cwd=repo, check=True, capture_output=True)
add("dev", "DONE", "E1", ledger=EARLY)
for name, lines, words in (
        ("no-interface.md", ["Verdict: PASS", f"Commit: {head()[:7]}", "Processes: none left running"], "Interface:"),
        ("no-lines.md", ["all good, 12 passed"], "Verdict:"),
        ("other-verdict.md", ["Verdict: FAIL", f"Commit: {head()[:7]}", "Interface: n/a", "Processes: none"],
         "FAIL"),
        ("no-commit.md", ["Verdict: PASS", "Commit: zzzzzzz", "Interface: n/a", "Processes: none"], "zzzzzzz")):
    r = run("add", "--agent", "qa", "--verdict", "PASS", "--report", report_file(name, lines=lines), ledger=EARLY)
    check(f"add --agent qa --report refuses a report that lacks what qa.md asks ({name})",
          r.returncode != 0 and words in r.stderr and not status(EARLY)["qa"], r.stderr)
run("add", "--agent", "reviewer", "--verdict", "FAIL", "--important", "1", "--origin", "execution=1", ledger=EARLY)
before = head()
subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "fix-1"], cwd=repo, check=True, capture_output=True)
add("dev", "DONE", "fix-1", ledger=EARLY)
r = run("add", "--agent", "qa", "--verdict", "PASS", "--report", report_file("early-qa.md", commit=before),
        ledger=EARLY)
state = status(EARLY)
check("a qa that tested the commit before the fix is stored as such and does not count as the fix's re-run",
      r.returncode == 0 and state["qa"][0].get("tested", "").startswith(before[:7]) and state["qa"][0].get("stale")
      and "qa has not re-run the scenarios the fix touched" in state["pending"], (r.stderr, state["pending"]))
run("add", "--agent", "qa", "--verdict", "PASS", "--report", report_file("early-qa-2.md"), ledger=EARLY)
check("a qa that tested the fix's commit counts as its re-run",
      "qa has not re-run the scenarios the fix touched" not in status(EARLY)["pending"], status(EARLY)["pending"])

LATE = ".superpowers/late-qa.jsonl"
run("start", "--slug", "late-qa", ledger=LATE)
add("dev", "DONE", "L1", ledger=LATE)
run("add", "--agent", "reviewer", "--verdict", "FAIL", "--important", "1", "--origin", "execution=1", ledger=LATE)
before = head()
subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "fix-1 of the reviewer's findings"], cwd=repo, check=True,
               capture_output=True)
add("dev", "DONE", "fix-1", ledger=LATE)
run("add", "--agent", "qa", "--verdict", "FAIL", "--important", "2", "--origin", "execution=2", "--report",
    report_file("late-qa.md", "FAIL", commit=before), ledger=LATE)
state = status(LATE)
check("qa's FAIL arriving after the fix began asks for the second part of the same fix round",
      {"step": "fix", "agent": "qa", "open": 2, "report": ".superpowers/reports/late-qa.md"} in state["steps"]
      and not any(item.startswith("qa still fails") for item in state["pending"]), (state["steps"], state["pending"]))

# The delivery's own clock: wall-clock with the pauses left out, against the time some agent was running
CLOCK = ".superpowers/clock.jsonl"
with open(os.path.join(repo, CLOCK), "w", encoding="utf-8", newline="\n") as handle:
    for entry in ({"type": "start", "slug": "clock", "base": "abc", "at": "2026-10-01T10:00:00+00:00"},
                  {"type": "run", "agent": "dev", "task": "T1", "verdict": "DONE", "open": 0, "head": "",
                   "seconds": 1200, "at": "2026-10-01T10:30:00+00:00"},
                  {"type": "pause", "text": "window", "at": "2026-10-01T10:40:00+00:00"},
                  {"type": "resume", "at": "2026-10-01T11:40:00+00:00"},
                  {"type": "run", "agent": "qa", "verdict": "PASS", "open": 0, "head": "", "seconds": 900,
                   "at": "2026-10-01T12:00:00+00:00"},
                  {"type": "run", "agent": "reviewer", "verdict": "PASS", "open": 0, "head": "", "seconds": 600,
                   "at": "2026-10-01T12:00:00+00:00"}):
        handle.write(json.dumps(entry) + "\n")
delivery = status(CLOCK)["metrics"]["time"].get("delivery")
check("metrics.time.delivery gives the elapsed time with the pauses out and the union of the agents' runs",
      delivery == {"elapsed": 3600, "paused": 3600, "agents": 2100, "share": 0.58}, delivery)

# The time the user is back (mode autonomous --until): what still fits before it, and when the night is over
NIGHT = ".superpowers/night.jsonl"
past = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3)).isoformat(timespec="seconds")
with open(os.path.join(repo, NIGHT), "w", encoding="utf-8", newline="\n") as handle:
    for entry in ({"type": "start", "slug": "night", "base": "abc", "at": past},
                  {"type": "run", "agent": "dev", "task": "T1", "verdict": "DONE", "open": 0, "head": "",
                   "seconds": 600, "at": past},
                  {"type": "run", "agent": "dev", "task": "T2", "verdict": "DONE", "open": 0, "head": "",
                   "seconds": 1200, "at": past},
                  {"type": "run", "agent": "reviewer", "verdict": "PASS", "open": 0, "head": "", "seconds": 120,
                   "at": past},
                  {"type": "run", "agent": "qa", "verdict": "PASS", "open": 0, "head": "", "seconds": 3000,
                   "at": past},
                  {"type": "run", "agent": "qa", "verdict": "PASS", "open": 0, "head": "", "seconds": 7200,
                   "full": True, "at": past}):
        handle.write(json.dumps(entry) + "\n")
check("without --until, autonomous mode has no night", run("mode", "autonomous", ledger=NIGHT).returncode == 0
      and status(NIGHT)["night"] is None, status(NIGHT).get("night"))
check("--until is refused in supervised mode", run("mode", "supervised", "--until", "08:30", ledger=NIGHT).returncode != 0)
check("an --until that is no time is refused", run("mode", "autonomous", "--until", "soon", ledger=NIGHT).returncode != 0)
check("an --until already past is refused", run("mode", "autonomous", "--until", past, ledger=NIGHT).returncode != 0)
back = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
r = run("mode", "autonomous", "--until", back.isoformat(timespec="seconds"), ledger=NIGHT)
add("dev", "DONE", "T3", ledger=NIGHT, seconds=300)
night, after = status(NIGHT)["night"], status(NIGHT)
check("mode autonomous --until records the time the user is back",
      r.returncode == 0 and night and datetime.datetime.fromisoformat(night["until"]) == back.replace(microsecond=0),
      (r.stdout, r.stderr, night))
check("night gives the seconds left and each agent's expected time, from this delivery's measured runs",
      night and 3400 <= night["seconds_left"] <= 3600
      and night["expected"] == {"dev": 600, "reviewer": 120, "qa": 3000, "qa_full": 7200}, night)
check("night says which runs fit before the user is back",
      night and night["fits"] == {"dev": True, "reviewer": True, "qa": True, "qa_full": False} and not night["over"],
      night)
check("night counts what was done since the time was set, for the morning summary",
      night and night["done_since"] == {"tasks": ["T3"], "runs": 1}, night)
DAY = ".superpowers/day.jsonl"
with open(os.path.join(repo, NIGHT), encoding="utf-8") as source:
    rows = [json.loads(row) for row in source]
with open(os.path.join(repo, DAY), "w", encoding="utf-8", newline="\n") as handle:
    for entry in rows:
        entry.pop("until", None)
        handle.write(json.dumps(entry) + "\n")
day = status(DAY)
check("the night is advice, never pending", after["pending"] == day["pending"] and after["steps"] == day["steps"]
      and after["ready_for_gate"] == day["ready_for_gate"], (day["pending"], after["pending"]))
text = run("status", ledger=NIGHT).stdout
line = next((row for row in text.splitlines() if row.startswith("night:")), "")
check("status names the run that does not fit and says not to dispatch it",
      "does not fit" in line and "qa --full" in line.split("does not fit")[1]
      and "qa --full" not in line.split("does not fit")[0] and "do not dispatch" in line, text)
hhmm = (datetime.datetime.now() - datetime.timedelta(minutes=2)).strftime("%H:%M")
run("mode", "autonomous", "--until", hhmm, ledger=NIGHT)
left = status(NIGHT)["night"]["seconds_left"]
check("an --until of HH:MM already past today is tomorrow at that time", 23 * 3600 < left <= 24 * 3600, left)
with open(os.path.join(repo, NIGHT), "a", encoding="utf-8", newline="\n") as handle:
    soon = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=90)).isoformat(timespec="seconds")
    handle.write(json.dumps({"type": "mode", "mode": "autonomous", "until": soon, "at": past}) + "\n")
night = status(NIGHT)["night"]
check("when no run fits before the user is back, the night is over", night["over"] and not any(night["fits"].values()),
      night)
with open(os.path.join(repo, NIGHT), "a", encoding="utf-8", newline="\n") as handle:
    handle.write(json.dumps({"type": "mode", "mode": "autonomous", "until": past, "at": past}) + "\n")
night, text = status(NIGHT)["night"], run("status", ledger=NIGHT).stdout
check("past the time the user is back, the night is over and status says to pause with the morning summary",
      night["over"] and night["seconds_left"] == 0 and "night over" in text and "pause" in text.split("night over")[1],
      text)
run("mode", "supervised", ledger=NIGHT)
check("mode supervised ends the night", status(NIGHT)["night"] is None)

# The settings that change speed or cost, still a template placeholder, are listed for the user
cfg = tempfile.mkdtemp(prefix="ledger_cfg_", dir=repo)
for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@t.com"), ("config", "user.name", "t"),
             ("commit", "-q", "--allow-empty", "-m", "base")):
    subprocess.run(["git", *args], cwd=cfg, check=True, capture_output=True)
CFG = os.path.join(cfg, ".superpowers", "ledger.jsonl")


def cfg_files(parallel):
    with open(os.path.join(cfg, "CLAUDE.md"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write("# p\n\n## Execução em paralelo\n\nText.\n\n"
                     + ("- Como rodar N cópias ao mesmo tempo: `PORT`\n- Pasta de saída dos testes: `OUT`\n" if parallel
                        else "- Como rodar N cópias ao mesmo tempo: _(porta)_\n- Pasta de saída dos testes: `OUT`\n")
                     + "\n## Outra\n\n- Algo: _(x)_\n")
    with open(os.path.join(cfg, "CLAUDE.local.md"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write("# p\n\n## Execução em paralelo\n\n- Memória livre mínima para despachar uma cópia ou um `qa`: "
                     "_(GB)_\n\n## Uso da conta\n\n- Economia a partir de quanto uso, em %: `70`\n"
                     "- Sempre econômico: _(padrão não)_\n")


cfg_files(parallel=False)
run("start", "--slug", "cfg", ledger=CFG, cwd=cfg)
run("scope", "--cycle", "1", "--tasks", "A1,A2,A3", ledger=CFG, cwd=cfg)
settings = status(CFG)["settings"]
check("status lists each line of the speed and cost sections still holding a placeholder, in file order",
      settings["unfilled"] == [
          {"file": "CLAUDE.md", "section": "Execução em paralelo", "line": "Como rodar N cópias ao mesmo tempo"},
          {"file": "CLAUDE.local.md", "section": "Execução em paralelo",
           "line": "Memória livre mínima para despachar uma cópia ou um `qa`"},
          {"file": "CLAUDE.local.md", "section": "Uso da conta", "line": "Sempre econômico"}], settings)
check("with the parallel section of CLAUDE.md unfilled, status counts the tasks of the cycle that could run together",
      settings["together"] == 3, settings)
text = run("status", ledger=CFG, cwd=cfg).stdout
check("the text asks to take the unfilled settings to the user now, and says the tasks run one at a time",
      "settings:" in text and "ask the user" in text and "3 tasks could run together" in text, text)
check("the settings are advice, never pending",
      not any("settings" in item or "Execução" in item for item in status(CFG)["pending"]), status(CFG)["pending"])
cfg_files(parallel=True)
settings = status(CFG)["settings"]
check("the parallel section filled: no count of tasks together, and its lines leave the list",
      settings["together"] is None and all(item["file"] == "CLAUDE.local.md" for item in settings["unfilled"]), settings)
os.remove(os.path.join(cfg, "CLAUDE.local.md"))
check("a missing CLAUDE.local.md is listed once, as missing",
      {"file": "CLAUDE.local.md", "section": None, "line": None} in status(CFG)["settings"]["unfilled"],
      status(CFG)["settings"])

# Copies left after their task was integrated: worktrees, folders and branches status asks to tear down.
left_root = tempfile.mkdtemp(prefix="ledger_left_")
atexit.register(shutil.rmtree, left_root, True)
proj = os.path.join(left_root, "proj")
copies = os.path.join(left_root, "_temp", "proj-worktrees")
os.makedirs(proj)
os.makedirs(copies)
for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@t.com"), ("config", "user.name", "t"),
             ("commit", "-q", "--allow-empty", "-m", "base"), ("switch", "-q", "-c", "feat/x")):
    git(proj, *args)
git(proj, "branch", "old-merged")
run("start", "--slug", "left", cwd=proj)
done_tree, open_tree, held_tree = (os.path.join(copies, name) for name in ("done", "open", "held"))
inner_tree = os.path.join(proj, ".claude", "worktrees", "agent-1")
git(proj, "worktree", "add", "-q", "-b", "task-done", done_tree)
git(done_tree, "commit", "-q", "--allow-empty", "-m", "done task")
git(proj, "merge", "-q", "--ff-only", "task-done")
git(proj, "worktree", "add", "-q", "-b", "task-open", open_tree)
git(open_tree, "commit", "-q", "--allow-empty", "-m", "open task")
git(proj, "worktree", "add", "-q", "--detach", held_tree)
git(proj, "worktree", "add", "-q", "--detach", inner_tree)
run("claim", "--task", "H1", "--worktree", held_tree, "--origin", "HEAD", cwd=proj)
os.makedirs(os.path.join(copies, "half", "node_modules"))
r = run("status", "--json", cwd=proj)
left = json.loads(r.stdout).get("leftovers") if r.returncode == 0 else None
norm = lambda path: os.path.normcase(os.path.realpath(path))
found = {(item["kind"], norm(item["path"]) if item.get("path") else item.get("branch")) for item in left or []}
check("status lists an integrated worktree of the copies folder, one in .claude/worktrees, a copy folder with no .git "
      "and the integrated branch, and nothing else",
      found == {("worktree", norm(done_tree)), ("worktree", norm(inner_tree)), ("folder", norm(os.path.join(copies, "half"))),
                ("branch", "task-done")}, left)
check("a claimed worktree, a task not integrated, the delivery branch and a branch older than the base are no leftover",
      not any(item.get("branch") in ("task-open", "feat/x", "main", "old-merged") or
              norm(item.get("path") or "") in (norm(open_tree), norm(held_tree)) for item in left or []), left)
state = json.loads(r.stdout) if r.returncode == 0 else {"pending": [], "steps": []}
check("each leftover is pending, with the action, so the gate is not ready",
      any("leftover" in item and "done" in item and "remove" in item for item in state["pending"])
      and any(item["step"] == "leftover" for item in state["steps"]) and not state.get("ready_for_gate", True),
      state["pending"])
check("status --check exits 1 while a copy is left", run("status", "--check", cwd=proj).returncode == 1)
git(proj, "worktree", "remove", "--force", done_tree)
git(proj, "worktree", "remove", "--force", inner_tree)
git(proj, "branch", "-D", "task-done")
shutil.rmtree(os.path.join(copies, "half"))
check("once the copies are torn down and the branch deleted, nothing is left over",
      json.loads(run("status", "--json", cwd=proj).stdout).get("leftovers") == [])

# The free disk against the delivery's highest reading and the declared floor: advice in status, never pending.
disk_root = tempfile.mkdtemp(prefix="ledger_disk_")
atexit.register(shutil.rmtree, disk_root, True)
os.makedirs(os.path.join(disk_root, ".superpowers"))
DISK = os.path.join(disk_root, ".superpowers", "ledger.jsonl")
with open(DISK, "w", encoding="utf-8") as handle:
    handle.write(json.dumps({"type": "start", "slug": "disk", "base": "abc"}) + "\n")
with open(os.path.join(disk_root, "CLAUDE.local.md"), "w", encoding="utf-8") as handle:
    handle.write("# p\n\n## Execução em paralelo\n\n- Quanto uma cópia ocupa no pico: memória `4` GB, disco `5` GB\n"
                 "- Disco livre mínimo: `20`\n")


def disk_at(free):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PIPELINE_CAPACITY")}
    env["PIPELINE_CAPACITY_DISK_GB"] = free
    result = subprocess.run([sys.executable, LEDGER, "--ledger", DISK, "status", "--json"], capture_output=True,
                            text=True, encoding="utf-8", env=env, cwd=disk_root)
    text = subprocess.run([sys.executable, LEDGER, "--ledger", DISK, "status"], capture_output=True, text=True,
                          encoding="utf-8", env=env, cwd=disk_root).stdout
    return (json.loads(result.stdout) if result.returncode == 0 else {}), text


def disk_of(state):
    return state.get("disk") or {}


state, _ = disk_at("100")
check("status gives the free disk and the delivery's highest reading, with no warning at the first one",
      disk_of(state).get("free_gb") == 100 and disk_of(state).get("high_gb") == 100
      and disk_of(state).get("warning") is None, state.get("disk"))
state, text = disk_at("97")
check("a drop within one copy's disk peak is no warning", disk_of(state).get("warning") is None, disk_of(state))
state, text = disk_at("90")
check("a drop since the highest reading larger than the copies in flight (at least one) times the disk peak warns, "
      "pointing at what verification writes outside the worktree",
      disk_of(state).get("dropped_gb") == 10 and "outside the worktree" in (disk_of(state).get("warning") or "")
      and "disk:" in text, (disk_of(state), text))
check("the disk warning is advice, never pending", not any("disk" in item for item in state.get("pending", [])), state.get("pending", []))
state, _ = disk_at("15")
check("below the declared disk floor, status warns naming it", "floor 20" in (disk_of(state).get("warning") or ""),
      disk_of(state))
with open(DISK, "w", encoding="utf-8") as handle:
    handle.write(json.dumps({"type": "start", "slug": "next", "base": "abc"}) + "\n")
state, _ = disk_at("50")
check("a new delivery starts its own highest reading", disk_of(state).get("high_gb") == 50, disk_of(state))
os.remove(os.path.join(disk_root, "CLAUDE.local.md"))
state, _ = disk_at("30")
check("with no disk peak nor floor declared, the reading is kept and nothing warns",
      disk_of(state).get("warning") is None and disk_of(state).get("high_gb") == 50, disk_of(state))

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
sys.exit(0 if all(results) else 1)
