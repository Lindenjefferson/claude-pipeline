import json, os, subprocess, sys, tempfile

LEDGER_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ledger.py")
root = tempfile.mkdtemp(prefix="ledgerrequired_")
repo = os.path.join(root, "repo")
empty = os.path.join(root, "no-checklists")
lists = os.path.join(root, "checklists")
for folder in (repo, empty, lists):
    os.makedirs(folder)
with open(os.path.join(lists, "lib.md"), "w") as handle:
    handle.write('---\nstack: lib\npaths: ["lib/**"]\nagents: [audit]\n---\n\n# Lib checklist\n')
LEDGER = os.path.join(repo, ".superpowers", "ledger.jsonl")
REPORT = os.path.join(repo, "report.md")
open(REPORT, "w").write("# Review\n\n## Important\n1. `lib/util.ts:1` misses a guard.\n\n## Minor\n- `lib/util.ts:2` name\n")
open(os.path.join(repo, ".gitignore"), "w").write(".superpowers/\nreport.md\n")
results = []


def sh(*args):
    return subprocess.run(args, cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def ledger(*args):
    return subprocess.run([sys.executable, LEDGER_PY, "--ledger", LEDGER, *args], cwd=repo,
                          capture_output=True, encoding="utf-8")


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS" if ok else "FAIL"), name, "" if ok else f"| {str(detail)[:400]}")


def reviewer(agent, verdict="PASS", important=0, minor=0):
    counts = {"critical": 0, "important": important, "minor": minor}
    return "LEDGER " + json.dumps({"agent": agent, "verdict": verdict, "new": counts, "open": counts})


def append(line, frm, head, task):
    return ledger("append", "--task", task, "--from", frm, "--head", head, "--report", REPORT, "--line", line)


def commit(files, message):
    for name, text in files.items():
        path = os.path.join(repo, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as handle:
            handle.write(text + "\n")
    sh("git", "add", ".")
    sh("git", "commit", "-q", "-m", message)
    return sh("git", "rev-parse", "HEAD")


def status(directory=empty):
    return json.loads(ledger("status", "--json", "--checklists-dir", directory).stdout)


def missing(data, task):
    return {item["agent"] for item in data["missing_reviewers"] if item["task"] == task}


sh("git", "init", "-q")
sh("git", "config", "user.email", "t@t.com")
sh("git", "config", "user.name", "t")
sh("git", "commit", "-q", "--allow-empty", "-m", "base")
base = sh("git", "rev-parse", "HEAD")
ledger("start", "--slug", "x", "--base", base)

c1 = commit({"app/page.tsx": "export default 1", "lib/env.ts": "export const a = 1",
             "supabase/migrations/0001_a.sql": "create or replace function f() returns int as $$ select 1 $$"},
            "task 1")
append(reviewer("code-review"), base, c1, "1")
append(reviewer("qa"), base, c1, "1")
data = status()
check("SQL, env and UI paths require db, security, audit and design",
      missing(data, "1") == {"db", "security", "audit", "design"}, data["missing_reviewers"])
item = next(i for i in data["missing_reviewers"] if i["task"] == "1" and i["agent"] == "security")
check("a missing reviewer names the commit and its files",
      item["commits"][0]["commit"] == c1 and "lib/env.ts" in item["commits"][0]["files"], item)
text = ledger("status", "--checklists-dir", empty).stdout
check("text status prints the advisory MISSING lines", "MISSING security" in text and "(advisory)" in text, text)
for agent in ("security", "db", "audit", "design"):
    append(reviewer(agent), base, c1, "1")
check("PASS entries covering the commit clear every missing reviewer", missing(status(), "1") == set(),
      status()["missing_reviewers"])

c2 = commit({"lib/util.ts": "export const b = 2"}, "task 2")
append(reviewer("code-review"), c1, c2, "2")
append(reviewer("qa"), c1, c2, "2")
check("plain code only needs code-review and qa", missing(status(), "2") == set(), status()["missing_reviewers"])
check("a checklist's paths add its agents", missing(status(lists), "2") == {"audit"},
      status(lists)["missing_reviewers"])
c3 = commit({"lib/actions.ts": "export async function salvar() {}"}, "task 3")
append(reviewer("code-review"), c2, c3, "3")
append(reviewer("qa"), c2, c3, "3")
check("an actions file needs audit", missing(status(), "3") == {"audit"}, status()["missing_reviewers"])
append(reviewer("audit"), c1, c3, "2")
check("a PASS of the same agent from any task covers it", missing(status(), "3") == set(),
      status()["missing_reviewers"])
c4 = commit({"docs/m.md": "text"}, "docs only")
ledger("append", "--task", "4", "--from", c3, "--head", c4, "--report", REPORT, "--line",
       'LEDGER {"agent":"docs","verdict":"NO_DOC_CHANGE_NEEDED"}')
check("a docs-only commit needs no reviewer", missing(status(), "4") == set(), status()["missing_reviewers"])

before = status()["totals"].get("code-review", {}).get("important", 0)
c5 = commit({"lib/util.ts": "export const c = 3"}, "tasks 5 and 6")
r = append(reviewer("code-review", "FAIL", 1), c4, c5, "5,6")
lines = [json.loads(line) for line in open(LEDGER).read().splitlines()[-2:]]
check("--task 5,6 writes one line per task sharing a report_group",
      r.returncode == 0 and [line["task"] for line in lines] == ["5", "6"]
      and lines[0].get("report_group") and lines[0]["report_group"] == lines[1]["report_group"], r.stderr + str(lines))
data = status()
check("totals count a shared report once", data["totals"]["code-review"]["important"] == before + 1, data["totals"])
check("open_totals count a shared report once", data["open_totals"]["code-review"]["important"] == 1,
      data["open_totals"])
check("--task with the spec task is refused", append(reviewer("code-review"), c4, c5, "5,spec").returncode != 0)
r = ledger("append", "--task", "5,6", "--from", c5, "--head", c5, "--report", REPORT, "--line",
           reviewer("code-review"), "--scope", "fix")
check("--task with several tasks and --scope fix is refused", r.returncode != 0 and "several tasks" in r.stderr,
      r.stderr)
check("an old single-task line has no report_group", "report_group" not in json.loads(
    open(LEDGER).read().splitlines()[1]))

append(reviewer("design", minor=1), c4, c5, "7")
data = status()
check("open minors with no deferred note are listed",
      {"task": "7", "agents": {"design": 1}} in data["undeferred_minors"], data["undeferred_minors"])
check("text status warns about them", "open minors without a deferred note (design 1)" in
      ledger("status", "--checklists-dir", empty).stdout)
ledger("note", "--kind", "deferred", "--task", "7", "--text", "design minor goes to the next module")
check("a deferred note on the task clears the warning",
      not any(item["task"] == "7" for item in status()["undeferred_minors"]), status()["undeferred_minors"])

r = append(reviewer("code-review"), c4, c5, "8,bad/name")
check("--task checks every task name", r.returncode != 0 and "bad/name" in r.stderr, r.stderr)
before = status()
lines = open(LEDGER).read().splitlines()
grouped = [json.loads(line) for line in lines if json.loads(line).get("report_group")]
forged = dict(grouped[-1], open={"critical": 0, "important": 3, "minor": 0})
with open(LEDGER, "a") as handle:
    handle.write(json.dumps(forged) + "\n")
data = status()
check("a report_group whose lines disagree is counted per line",
      data["open_totals"]["code-review"]["important"] == before["open_totals"]["code-review"]["important"] + 3
      and data["totals"]["code-review"]["important"] == before["totals"]["code-review"]["important"] + 2,
      (before["open_totals"], data["open_totals"], data["totals"]))
check("an inconsistent report_group is listed in invalid",
      any(item.get("report_group") == forged["report_group"] for item in data["invalid"]), data["invalid"])
text = ledger("status", "--checklists-dir", empty).stdout
check("text status names the inconsistent report_group", f"INVALID report_group {forged['report_group']}" in text,
      text)
with open(LEDGER, "w") as handle:
    handle.write("\n".join(lines) + "\n")

c8 = commit({"app/view.tsx": "export const v = 1", "lib/calc.ts": "export const k = 1"}, "task 8")
for agent in ("design", "code-review"):
    append(reviewer(agent), c5, c8, "8")
commit({"lib/calc.ts": "export const k = 2"}, "server-only change")


def stale_agents():
    data = json.loads(ledger("status", "--json", "--head", "HEAD", "--checklists-dir", empty).stdout)
    return {item["agent"] for item in data["stale"] if item["task"] == "8"}


check("design is not STALE for a later change outside its paths", stale_agents() == {"code-review"},
      stale_agents())
commit({"app/view.tsx": "export const v = 2"}, "ui change")
check("design is STALE for a later change to a UI path", stale_agents() == {"code-review", "design"},
      stale_agents())

for number, path in enumerate(("package.json", "web/package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb",
                                "requirements-dev.txt", "api/pyproject.toml", "poetry.lock", "Cargo.toml",
                                "Cargo.lock", "go.mod", "go.sum", ".github/workflows/ci.yml", "vercel.json",
                                "netlify.toml", "Dockerfile", "docker-compose.prod.yml", "next.config.mjs",
                                "supabase/config.toml"), start=100):
    head = sh("git", "rev-parse", "HEAD")
    tip = commit({path: f"x{number}"}, f"manifest {path}")
    append(reviewer("code-review"), head, tip, str(number))
    append(reviewer("qa"), head, tip, str(number))
    check(f"{path} requires security", "security" in missing(status(), str(number)), status()["missing_reviewers"])
head = sh("git", "rev-parse", "HEAD")
tip = commit({"lib/other.json": "{}"}, "plain json")
append(reviewer("code-review"), head, tip, "130")
append(reviewer("qa"), head, tip, "130")
check("a plain json file does not require security", "security" not in missing(status(), "130"),
      status()["missing_reviewers"])

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
