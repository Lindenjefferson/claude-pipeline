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


def add(agent, verdict, task=None, open_count=0):
    args = ["add", "--agent", agent, "--verdict", verdict, "--open", str(open_count)]
    return run(*(args + (["--task", task] if task else [])))


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("PASS" if ok else "FAIL", name, "" if ok else f"| {str(detail)[-300:]}")


def status():
    return json.loads(run("status", "--json").stdout)


for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@t.com"), ("config", "user.name", "t"),
             ("commit", "-q", "--allow-empty", "-m", "base")):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

check("add before start is refused", add("dev", "DONE", "T1").returncode != 0)
r = run("start", "--slug", "feature")
check("start records the base", r.returncode == 0 and "started feature" in r.stdout, r.stderr)
check("start twice is refused", run("start", "--slug", "again").returncode != 0)
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

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
