import json, os, subprocess, sys, tempfile, time

LEDGER_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ledger.py")
repo = os.path.join(tempfile.gettempdir(), f"ledgerroles_{int(time.time() * 1000)}")
os.makedirs(repo)
LEDGER = os.path.join(repo, "ledger.jsonl")
REPORT = os.path.join(repo, "report.md")
open(REPORT, "w").write("report\n")
results = []
DB_DONE = 'LEDGER {"agent":"db","verdict":"DONE"}'


def db_review(verdict, opened=(0, 0, 0)):
    keys = ("critical", "important", "minor")
    return "LEDGER " + json.dumps({"agent": "db", "verdict": verdict, "new": dict(zip(keys, opened)),
                                   "open": dict(zip(keys, opened))})


def sh(*args):
    return subprocess.run(args, cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def ledger(*args):
    return subprocess.run([sys.executable, LEDGER_PY, "--ledger", LEDGER, *args],
                          cwd=repo, capture_output=True, text=True)


def append(line, head):
    return ledger("append", "--task", "1", "--from", base, "--head", head, "--report", REPORT,
                  "--line", line)


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS" if ok else "FAIL"), name, "" if ok else f"| {detail[:300]}")


def latest_db():
    data = json.loads(ledger("status", "--json").stdout)
    return sorted(e["verdict"] for e in data["latest"] if e["agent"] == "db")


sh("git", "init", "-q")
sh("git", "config", "user.email", "t@t.com")
sh("git", "config", "user.name", "t")
sh("git", "commit", "-q", "--allow-empty", "-m", "base")
base = sh("git", "rev-parse", "HEAD")
sh("git", "commit", "-q", "--allow-empty", "-m", "migration")
head1 = sh("git", "rev-parse", "HEAD")
ledger("start", "--slug", "x", "--base", base)

r = append(DB_DONE, head1)
check("db as implementer starts at round 1", "round=1" in r.stdout, r.stdout + r.stderr)
r = append(db_review("FAIL", opened=(0, 1, 0)), head1)
check("db as reviewer counts its own rounds", "round=1" in r.stdout, r.stdout + r.stderr)
check("status keeps the latest entry of each role", latest_db() == ["DONE", "FAIL"], str(latest_db()))

sh("git", "commit", "-q", "--allow-empty", "-m", "fix")
head2 = sh("git", "rev-parse", "HEAD")
r = append(DB_DONE, head2)
check("the fix is implementer round 2", "round=2" in r.stdout, r.stdout + r.stderr)
check("a later implementer entry does not hide the review", latest_db() == ["DONE", "FAIL"], str(latest_db()))
data = json.loads(ledger("status", "--json", "--head", "HEAD").stdout)
check("the review behind the fix is stale",
      [(s["agent"], s["commits_after"]) for s in data["stale"]] == [("db", 1)], json.dumps(data["stale"]))

r = append(db_review("PASS"), head2)
check("the re-review is reviewer round 2", "round=2" in r.stdout, r.stdout + r.stderr)
check("status shows the passing review", latest_db() == ["DONE", "PASS"], str(latest_db()))
check("text status tells the two roles apart", "db (review)" in ledger("status").stdout, ledger("status").stdout)

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
