import json, os, subprocess, sys, tempfile, time

LEDGER_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ledger.py")
repo = os.path.join(tempfile.gettempdir(), f"ledgertest_{int(time.time())}")
os.makedirs(repo)
LEDGER = os.path.join(repo, "ledger.jsonl")
REPORT = os.path.join(repo, "report.md")
open(REPORT, "w").write("report\n")

results = []


def sh(*args):
    return subprocess.run(args, cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def ledger(*args):
    return subprocess.run([sys.executable, LEDGER_PY, "--ledger", LEDGER, *args],
                          cwd=repo, capture_output=True, text=True)


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS" if ok else "FAIL"), name, "" if ok else f"| {detail[:300]}")


def append(line, frm=None, head=None, report=REPORT, task="1"):
    return ledger("append", "--task", task, "--from", frm or base, "--head", head or head1,
                  "--report", report, "--line", line)


def reviewer(agent, verdict, new=(0, 0, 0), opened=(0, 0, 0)):
    keys = ("critical", "important", "minor")
    return "LEDGER " + json.dumps({"agent": agent, "verdict": verdict,
                                   "new": dict(zip(keys, new)), "open": dict(zip(keys, opened))})


sh("git", "init", "-q")
sh("git", "config", "user.email", "t@t.com")
sh("git", "config", "user.name", "t")
sh("git", "commit", "-q", "--allow-empty", "-m", "base")
base = sh("git", "rev-parse", "HEAD")
sh("git", "commit", "-q", "--allow-empty", "-m", "task 1")
head1 = sh("git", "rev-parse", "HEAD")

r = ledger("start", "--slug", "x", "--base", "not-a-commit")
check("start rejects a base that is not a commit", r.returncode != 0 and not os.path.exists(LEDGER), r.stderr)
r = ledger("start", "--slug", "x", "--base", "HEAD~1")
check("start accepts a revision and stores its full sha",
      r.returncode == 0 and json.loads(open(LEDGER).readline())["base"] == base, r.stderr)
check("start refuses an existing ledger", ledger("start", "--slug", "x", "--base", base).returncode != 0)

r = append('LEDGER {"agent":"dev","verdict":"DONE"}')
check("implementer line accepted", r.returncode == 0 and "round=1" in r.stdout, r.stderr)
r = append(reviewer("code-review", "PASS", new=(0, 0, 1), opened=(0, 0, 1)))
check("reviewer PASS with only a minor open accepted", r.returncode == 0, r.stderr)

rejected = [
    ("unknown verdict", 'LEDGER {"agent":"code-review","verdict":"TALVEZ"}'),
    ("unknown agent", 'LEDGER {"agent":"reviewer","verdict":"PASS"}'),
    ("implementer verdict on a reviewer", 'LEDGER {"agent":"qa","verdict":"DONE"}'),
    ("reviewer verdict on an implementer", reviewer("dev", "PASS")),
    ("reviewer without counts", 'LEDGER {"agent":"security","verdict":"PASS"}'),
    ("non-numeric count", 'LEDGER {"agent":"security","verdict":"PASS","new":{"critical":"x","important":0,"minor":0},"open":{"critical":0,"important":0,"minor":0}}'),
    ("negative count", reviewer("security", "PASS", new=(-1, 0, 0))),
    ("boolean count", 'LEDGER {"agent":"security","verdict":"PASS","new":{"critical":true,"important":0,"minor":0},"open":{"critical":0,"important":0,"minor":0}}'),
    ("missing severity", 'LEDGER {"agent":"security","verdict":"PASS","new":{"critical":0,"important":0},"open":{"critical":0,"important":0,"minor":0}}'),
    ("PASS with an open important finding", reviewer("security", "PASS", opened=(0, 1, 0))),
    ("FAIL with nothing blocking open", reviewer("security", "FAIL", opened=(0, 0, 2))),
    ("not JSON", "LEDGER {agent: dev}"),
    ("JSON that is not an object", 'LEDGER ["dev"]'),
]
before = open(LEDGER).read()
for name, line in rejected:
    r = append(line)
    check(f"rejects {name}", r.returncode != 0, r.stdout + r.stderr)
check("rejected lines leave the ledger untouched", open(LEDGER).read() == before)

check("rejects a --from that is not a commit", append('LEDGER {"agent":"dev","verdict":"DONE"}', frm="nope").returncode != 0)
check("rejects a --head that is not a commit", append('LEDGER {"agent":"dev","verdict":"DONE"}', head="nope").returncode != 0)
check("rejects --from after --head",
      append('LEDGER {"agent":"dev","verdict":"DONE"}', frm=head1, head=base).returncode != 0)
check("rejects a report file that does not exist",
      append('LEDGER {"agent":"dev","verdict":"DONE"}', report=os.path.join(repo, "missing.md")).returncode != 0)

r = append(reviewer("code-review", "FAIL", new=(0, 1, 0), opened=(0, 1, 0)))
check("round counts per task and agent", r.returncode == 0 and "round=2" in r.stdout, r.stdout + r.stderr)
r = append(reviewer("code-review", "PASS"), task="2")
check("round restarts for another task", r.returncode == 0 and "round=1" in r.stdout, r.stdout + r.stderr)

with open(LEDGER, "a") as handle:
    handle.write("not json\n")
    handle.write('{"agent":"qa","verdict":"TALVEZ","task":"1","from":"a","head":"b","round":1,"report":"r"}\n')
r = ledger("status")
check("status survives lines written around the validation", r.returncode == 0, r.stderr)
check("status names each invalid line", r.stdout.count("INVALID line") == 2, r.stdout)
data = json.loads(ledger("status", "--json").stdout)
check("status --json lists invalid lines", len(data["invalid"]) == 2, json.dumps(data["invalid"]))
check("invalid lines are left out of the totals", "qa" not in data["totals"], json.dumps(data["totals"]))
r = append('LEDGER {"agent":"docs","verdict":"NO_DOC_CHANGE_NEEDED"}')
check("append still works after an invalid line, with a warning",
      r.returncode == 0 and "ignored" in r.stderr, r.stdout + r.stderr)

sh("git", "commit", "-q", "--allow-empty", "-m", "fix after review")
data = json.loads(ledger("status", "--json", "--head", "HEAD").stdout)
stale = {(s["task"], s["agent"]): s["commits_after"] for s in data["stale"]}
check("reviewer entries behind HEAD are stale", stale.get(("1", "code-review")) == 1, json.dumps(data["stale"]))
check("implementer entries are never stale", ("1", "dev") not in stale and ("1", "docs") not in stale,
      json.dumps(data["stale"]))
check("totals count findings raised across rounds",
      data["totals"]["code-review"]["important"] == 1 and data["totals"]["code-review"]["minor"] == 1,
      json.dumps(data["totals"]))

r = ledger("note", "--kind", "ruling", "--task", "1", "--text", "accepted the minor")
data = json.loads(ledger("status", "--json").stdout)
check("notes are recorded and listed", r.returncode == 0 and data["notes"][-1]["text"] == "accepted the minor",
      r.stderr)

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
