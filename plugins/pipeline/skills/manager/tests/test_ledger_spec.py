import json, os, subprocess, sys, tempfile

LEDGER_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ledger.py")
repo = tempfile.mkdtemp(prefix="ledgerspec_")
os.makedirs(os.path.join(repo, "docs", "specs"))
LEDGER = os.path.join(repo, ".superpowers", "ledger.jsonl")
REPORT = os.path.join(repo, "report.md")
SPEC = "docs/specs/module-design.md"
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


def reviewer(agent, verdict, new=(0, 0, 0), opened=(0, 0, 0)):
    keys = ("critical", "important", "minor")
    return "LEDGER " + json.dumps({"agent": agent, "verdict": verdict,
                                   "new": dict(zip(keys, new)), "open": dict(zip(keys, opened))})


def append(line, head, task="spec", spec=SPEC):
    extra = ["--spec", spec] if spec else []
    return ledger("append", "--task", task, "--from", base, "--head", head, "--report", REPORT,
                  "--line", line, *extra)


def commit_file(path, text, message):
    with open(os.path.join(repo, path), "w") as handle:
        handle.write(text)
    sh("git", "add", path)
    sh("git", "commit", "-q", "-m", message)
    return sh("git", "rev-parse", "HEAD")


sh("git", "init", "-q")
sh("git", "config", "user.email", "t@t.com")
sh("git", "config", "user.name", "t")
sh("git", "commit", "-q", "--allow-empty", "-m", "base")
base = sh("git", "rev-parse", "HEAD")
spec1 = commit_file(SPEC, "# Design\n", "spec")
ledger("start", "--slug", "x", "--base", base)

r = append(reviewer("security", "FAIL", new=(1, 2, 3), opened=(1, 2, 3)), spec1)
check("spec review line accepted with --spec", r.returncode == 0 and "round=1" in r.stdout, r.stdout + r.stderr)
entry = json.loads(open(LEDGER).read().splitlines()[-1])
check("the entry records the reviewed spec", entry.get("spec") == SPEC and entry["task"] == "spec", json.dumps(entry))

before = open(LEDGER).read()
rejected = [
    ("a spec line without --spec", append(reviewer("db", "PASS"), spec1, spec=None)),
    ("--spec on a code task", append(reviewer("db", "PASS"), spec1, task="1")),
    ("qa on the spec task", append(reviewer("qa", "PASS"), spec1)),
    ("an implementer on the spec task", append('LEDGER {"agent":"db","verdict":"DONE"}', spec1)),
    ("a spec path missing from --head", append(reviewer("db", "PASS"), spec1, spec="docs/specs/other.md")),
    ("a spec path given in the agent line", append(
        'LEDGER {"agent":"db","verdict":"PASS","spec":"x.md","new":{"critical":0,"important":0,"minor":0},'
        '"open":{"critical":0,"important":0,"minor":0}}', spec1, spec=None)),
]
for name, r in rejected:
    check(f"rejects {name}", r.returncode != 0, r.stdout + r.stderr)
check("rejected spec lines leave the ledger untouched", open(LEDGER).read() == before)

r = append(reviewer("db", "PASS", new=(0, 0, 1), opened=(0, 0, 1)), spec1, spec="./docs\\specs/module-design.md")
check("spec path is normalized", r.returncode == 0 and json.loads(
    open(LEDGER).read().splitlines()[-1]).get("spec") == SPEC, r.stdout + r.stderr)

spec2 = commit_file(SPEC, "# Design\n\nfixed\n", "spec fixes")
r = append(reviewer("security", "PASS"), spec2)
check("the re-review of the fixed spec is round 2", r.returncode == 0 and "round=2" in r.stdout, r.stdout + r.stderr)
data = json.loads(ledger("status", "--json", "--head", "HEAD").stdout)
check("a reviewer that did not see the spec fix is stale",
      [(s["agent"], s["commits_after"]) for s in data["stale"]] == [("db", 1)], json.dumps(data["stale"]))
append(reviewer("db", "PASS", opened=(0, 0, 1)), spec2)

sh("git", "commit", "-q", "--allow-empty", "-m", "task 1 code")
code = sh("git", "rev-parse", "HEAD")
r = ledger("append", "--task", "1", "--from", spec2, "--head", code, "--report", REPORT,
           "--line", reviewer("security", "PASS", new=(0, 1, 0)))
check("code task line still accepted without --spec", r.returncode == 0, r.stdout + r.stderr)

data = json.loads(ledger("status", "--json", "--head", "HEAD").stdout)
stale = {(s["task"], s["agent"]) for s in data["stale"]}
check("code commits after a spec review do not make it stale", ("spec", "security") not in stale
      and ("spec", "db") not in stale, json.dumps(data["stale"]))
check("spec findings stay out of the delivery totals",
      data["totals"]["security"] == {"critical": 0, "important": 1, "minor": 0, "rounds": 1},
      json.dumps(data["totals"]))
check("spec findings are counted in spec_totals",
      data["spec_totals"]["security"] == {"critical": 1, "important": 2, "minor": 3, "rounds": 2}
      and data["spec_totals"]["db"]["minor"] == 1, json.dumps(data["spec_totals"]))

commit_file(SPEC, "# Design\n\nchanged after review\n", "spec change")
data = json.loads(ledger("status", "--json", "--head", "HEAD").stdout)
stale = {(s["task"], s["agent"]): s for s in data["stale"]}
check("a spec edit after the review makes it stale",
      stale.get(("spec", "security"), {}).get("commits_after") == 1
      and stale[("spec", "security")].get("spec") == SPEC, json.dumps(data["stale"]))
text = ledger("status", "--head", "HEAD").stdout
check("text status separates spec totals and flags the stale spec review",
      "spec  security" in text and "STALE (+1 commits)" in text, text)

with open(LEDGER, "a") as handle:
    handle.write(json.dumps({"agent": "qa", "verdict": "PASS", "task": "spec", "from": base, "head": spec1,
                             "round": 1, "report": REPORT, "spec": SPEC,
                             "new": {"critical": 0, "important": 0, "minor": 0},
                             "open": {"critical": 0, "important": 0, "minor": 0}}) + "\n")
data = json.loads(ledger("status", "--json").stdout)
check("status flags a spec line written around the validation", len(data["invalid"]) == 1, json.dumps(data["invalid"]))

with open(LEDGER, "a") as handle:
    handle.write(json.dumps({"agent": "design", "verdict": "PASS", "task": "spec", "from": spec1,
                             "head": sh("git", "rev-parse", "HEAD"), "round": 1, "report": REPORT, "spec": SPEC,
                             "scope": "fix", "covers_from": base,
                             "new": {"critical": 0, "important": 0, "minor": 0},
                             "open": {"critical": 0, "important": 0, "minor": 0}}) + "\n")
data = json.loads(ledger("status", "--json", "--head", "HEAD").stdout)
item = next((s for s in data["stale"] if (s["task"], s["agent"]) == ("spec", "design")), {})
check("a spec review whose fix-scoped chain is broken is flagged even with the spec unchanged",
      item.get("chain_broken") is True and item.get("commits_after") == 0, json.dumps(data["stale"]))
text = ledger("status", "--head", "HEAD").stdout
row = next((line for line in text.splitlines() if line.startswith("spec") and " design " in line), "")
check("text status says 'chain broken' for it", "chain broken" in row and "None" not in row, text)

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
