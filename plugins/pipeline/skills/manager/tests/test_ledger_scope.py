import json, os, subprocess, sys, tempfile, time

LEDGER_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ledger.py")
repo = os.path.join(tempfile.gettempdir(), f"ledgerscope_{int(time.time() * 1000)}")
os.makedirs(os.path.join(repo, "src"))
LEDGER = os.path.join(repo, ".superpowers", "ledger.jsonl")
REPORT = os.path.join(repo, "report.md")
open(REPORT, "w").write("report\n")
open(os.path.join(repo, ".gitignore"), "w").write(".superpowers/\nreport.md\n")
results = []


def sh(*args):
    return subprocess.run(args, cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def ledger(*args):
    return subprocess.run([sys.executable, LEDGER_PY, "--ledger", LEDGER, *args], cwd=repo,
                          capture_output=True, encoding="utf-8")


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS" if ok else "FAIL"), name, "" if ok else f"| {detail[:400]}")


def reviewer(agent, verdict="PASS", important=0):
    counts = {"critical": 0, "important": important, "minor": 0}
    return "LEDGER " + json.dumps({"agent": agent, "verdict": verdict, "new": counts, "open": counts})


def append(line, frm, head, task="1", scope=None):
    extra = ["--scope", scope] if scope else []
    return ledger("append", "--task", task, "--from", frm, "--head", head, "--report", REPORT, "--line", line, *extra)


def commit(files, message):
    for name in files:
        with open(os.path.join(repo, "src", name), "a") as handle:
            handle.write(f"{message}\n")
    sh("git", "add", ".")
    sh("git", "commit", "-q", "-m", message)
    return sh("git", "rev-parse", "HEAD")


def stale():
    data = json.loads(ledger("status", "--json", "--head", "HEAD").stdout)
    return {(s["task"], s["agent"]): s for s in data["stale"]}, data


sh("git", "init", "-q")
sh("git", "config", "user.email", "t@t.com")
sh("git", "config", "user.name", "t")
sh("git", "commit", "-q", "--allow-empty", "-m", "base")
base = sh("git", "rev-parse", "HEAD")
ledger("start", "--slug", "x", "--base", base)

c1 = commit(["a.py", "b.py"], "task 1")
check("a first review is recorded full", append(reviewer("code-review", "FAIL", 1), base, c1).returncode == 0)
entry = json.loads(open(LEDGER).read().splitlines()[-1])
check("a reviewer entry records scope full and covers_from = from",
      entry.get("scope") == "full" and entry.get("covers_from") == base, json.dumps(entry))

c2 = commit(["a.py"], "fix a")
r = append(reviewer("code-review"), base, c2, scope="fix")
check("--scope fix refuses a --from that is not the previous head", r.returncode != 0 and c1[:8] in r.stderr, r.stderr)
r = append(reviewer("design"), c1, c2, scope="fix")
check("--scope fix refuses a first review", r.returncode != 0 and "earlier entry" in r.stderr, r.stderr)
r = append('LEDGER {"agent":"dev","verdict":"DONE"}', c1, c2, scope="fix")
check("--scope is refused on implementer lines", r.returncode != 0 and "reviewer" in r.stderr, r.stderr)
r = append(reviewer("code-review"), c1, c2, scope="fix")
entry = json.loads(open(LEDGER).read().splitlines()[-1])
check("a contiguous fix entry is accepted with covers_from = the chain start",
      r.returncode == 0 and entry.get("scope") == "fix" and entry.get("covers_from") == base
      and "round=2" in r.stdout, r.stdout + r.stderr + json.dumps(entry))
table, data = stale()
check("the chain full(base..c1) + fix(c1..c2) covers base..c2: not stale", ("1", "code-review") not in table,
      json.dumps(data["stale"]))
latest = {e["agent"]: e for e in data["latest"] if e.get("task") == "1"}
check("status --json reports the chain start as covers_from", latest["code-review"]["covers_from"] == base,
      json.dumps(latest))
text = ledger("status", "--head", "HEAD").stdout
check("text status shows the whole covered range and marks the fix scope",
      f"{base[:8]}..{c2[:8]}" in text and "fix-scoped" in text, text)
c3 = commit(["a.py"], "fix a again")
check("a second fix entry extends the chain", append(reviewer("code-review"), c2, c3, scope="fix").returncode == 0)
table, _ = stale()
check("a three-link chain still covers the task", ("1", "code-review") not in table, str(table))

c4 = commit(["c.py"], "task 2")
table, _ = stale()
check("an unreviewed later commit makes the entry stale, named as not reviewed",
      table.get(("1", "code-review"), {}).get("uncovered") == [c4], str(table))
text = ledger("status", "--head", "HEAD").stdout
check("text status names the uncovered commit", f"{c4[:8]} is reviewed by no other task" in text, text)
append(reviewer("code-review"), c3, c4, task="2")
table, _ = stale()
check("a later commit of another task touching none of its files, reviewed there, keeps it current",
      ("1", "code-review") not in table and ("2", "code-review") not in table, str(table))

c5 = commit(["a.py", "c.py"], "task 2 touches a")
append(reviewer("code-review"), c3, c5, task="2")
table, _ = stale()
item = table.get(("1", "code-review"), {})
check("a later commit of another task touching one of its files makes it stale, with file and commit",
      item.get("touched") == [{"commit": c5, "files": ["src/a.py"]}] and item.get("commits_after") == 2,
      str(table))
text = ledger("status", "--head", "HEAD").stdout
check("text status shows which commit touched which file", f"{c5[:8]} touches src/a.py" in text, text)
check("the other task's own review is current", ("2", "code-review") not in table, str(table))

append(reviewer("security"), base, c5, task="1")
table, _ = stale()
check("a full re-review up to HEAD clears it", ("1", "security") not in table, str(table))

with open(LEDGER, "a") as handle:
    handle.write(json.dumps({"agent": "design", "verdict": "PASS", "task": "1", "from": c4, "head": c5, "round": 1,
                             "report": REPORT, "scope": "fix", "covers_from": base,
                             "new": {"critical": 0, "important": 0, "minor": 0},
                             "open": {"critical": 0, "important": 0, "minor": 0}}) + "\n")
table, data = stale()
check("a fix entry with no earlier entry ending at its --from is a broken chain",
      table.get(("1", "design"), {}).get("chain_broken") is True and not data["invalid"], str(table))
check("text status flags the broken chain", "chain broken" in ledger("status", "--head", "HEAD").stdout)
with open(LEDGER, "a") as handle:
    handle.write(json.dumps({"agent": "audit", "verdict": "PASS", "task": "1", "from": c4, "head": c5, "round": 1,
                             "report": REPORT, "scope": "partial",
                             "new": {"critical": 0, "important": 0, "minor": 0},
                             "open": {"critical": 0, "important": 0, "minor": 0}}) + "\n")
check("an unknown scope is an invalid line", len(json.loads(ledger("status", "--json").stdout)["invalid"]) == 1)

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
