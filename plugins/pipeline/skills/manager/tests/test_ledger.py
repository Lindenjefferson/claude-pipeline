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


def run(*args):
    return subprocess.run([sys.executable, LEDGER, *args], cwd=repo, capture_output=True, text=True, encoding="utf-8")


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("PASS" if ok else "FAIL", name, "" if ok else f"| {str(detail)[-300:]}")


def status():
    return json.loads(run("status", "--json").stdout)


for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@t.com"), ("config", "user.name", "t"),
             ("commit", "-q", "--allow-empty", "-m", "base")):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

r = run("add", "--task", "T1", "--agent", "dev", "--verdict", "DONE")
check("add before start is refused", r.returncode != 0 and "start" in r.stderr, r.stderr)
r = run("start", "--slug", "feature")
check("start records the base", r.returncode == 0 and "started feature" in r.stdout, r.stderr)
check("start twice is refused", run("start", "--slug", "again").returncode != 0)

check("unknown verdict is refused", run("add", "--task", "T1", "--agent", "dev", "--verdict", "PASS").returncode != 0)
check("reviewer FAIL without open findings is refused",
      run("add", "--task", "T1", "--agent", "reviewer", "--verdict", "FAIL").returncode != 0)
check("reviewer PASS with open findings is refused",
      run("add", "--task", "T1", "--agent", "reviewer", "--verdict", "PASS", "--open", "1").returncode != 0)

run("add", "--task", "T1", "--agent", "dev", "--verdict", "DONE", "--summary", "form")
check("after dev, the reviewer is pending",
      status()["tasks"]["T1"]["pending"] == ["reviewer has not reviewed the latest dev run"])
run("add", "--task", "T1", "--agent", "reviewer", "--verdict", "FAIL", "--open", "2")
check("reviewer FAIL sends the task back to dev", "back to dev" in status()["tasks"]["T1"]["pending"][0])
run("add", "--task", "T1", "--agent", "dev", "--verdict", "DONE", "--summary", "fix")
check("a dev fix makes the review stale",
      status()["tasks"]["T1"]["pending"] == ["reviewer has not reviewed the latest dev run"])
run("add", "--task", "T1", "--agent", "reviewer", "--verdict", "PASS")
check("after a review PASS, qa is pending", status()["tasks"]["T1"]["pending"] == ["qa has not run after the latest review"])
check("round numbers count per task and agent", status()["tasks"]["T1"]["latest"]["reviewer"]["round"] == 2)
check("status --check exits 1 while a task is pending", run("status", "--check").returncode == 1)
run("add", "--task", "T1", "--agent", "qa", "--verdict", "PASS")
check("dev, reviewer and qa PASS: ready for gate", status()["ready_for_gate"] is True)
check("status --check exits 0 when ready", run("status", "--check").returncode == 0)

run("add", "--task", "T2", "--agent", "dev", "--verdict", "DONE")
for _ in range(3):
    run("add", "--task", "T2", "--agent", "reviewer", "--verdict", "FAIL", "--open", "1")
    run("add", "--task", "T2", "--agent", "dev", "--verdict", "DONE")
run("add", "--task", "T2", "--agent", "reviewer", "--verdict", "FAIL", "--open", "1")
check("a third failed round asks the user", any("ask the user" in item for item in status()["tasks"]["T2"]["pending"]))
check("one pending task keeps the delivery out of the gate", status()["ready_for_gate"] is False)

run("note", "--task", "T2", "--text", "minor deferred")
check("notes are listed", status()["notes"][0]["text"] == "minor deferred")
check("text status names pending items", "pending:" in run("status").stdout)
run("add", "--task", "gate", "--agent", "gate", "--verdict", "BLOCKED")
check("gate runs are kept apart from the tasks", "gate" not in status()["tasks"] and status()["gate"])

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
