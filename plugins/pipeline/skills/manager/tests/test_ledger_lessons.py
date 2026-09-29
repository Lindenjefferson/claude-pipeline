import json, os, subprocess, sys, tempfile, time

LEDGER_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ledger.py")
repo = os.path.join(tempfile.gettempdir(), f"ledgerlessons_{int(time.time() * 1000)}")
GLOBAL_DIR = os.path.join(repo, "plugin", "lessons")
os.makedirs(GLOBAL_DIR)
DELIVERY = os.path.join(repo, ".superpowers", "lessons.jsonl")
results = []


def lesson(*args):
    return subprocess.run([sys.executable, LEDGER_PY, "lesson", *args], cwd=repo, capture_output=True,
                          encoding="utf-8")


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS" if ok else "FAIL"), name, "" if ok else f"| {detail[:300]}")


def add(lesson_id, text="Assert the row count after an RLS-filtered update.", stack="postgres-supabase", paths=""):
    return lesson("add", "--id", lesson_id, "--stack", stack, "--paths", paths, "--text", text,
                  "--task", "T1.1", "--agent", "code-review", "--finding", "lives_ok passed with zero rows",
                  "--project", "demo")


def rows(path):
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


r = add("pg-rls-count-rows", paths="supabase/**/*.sql, **/*.sql")
data = json.loads(lesson("list", "--json").stdout)
check("lesson add writes the delivery file", r.returncode == 0 and os.path.isfile(DELIVERY), r.stderr)
check("the lesson has the shared format", data and data[0] == {
    "id": "pg-rls-count-rows", "stack": "postgres-supabase", "paths": ["supabase/**/*.sql", "**/*.sql"],
    "text": "Assert the row count after an RLS-filtered update.",
    "source": {"project": "demo", "task": "T1.1", "agent": "code-review", "finding": "lives_ok passed with zero rows"},
    "counters": {"injected": 0, "held": 0, "recurred": 0}, "status": "active", "created": data[0]["created"]},
    json.dumps(data))
check("created is today's date", data and data[0]["created"] == time.strftime("%Y-%m-%d"), json.dumps(data))
before = open(DELIVERY, encoding="utf-8").read()
r = add("pg-rls-count-rows", text="Another rule.")
check("lesson add refuses a duplicate id", r.returncode != 0 and "already exists" in r.stderr, r.stderr)
r = add("too-long", text="x" * 281)
check("lesson add refuses a text over 280 characters", r.returncode != 0 and "280" in r.stderr, r.stderr)
check("refused lessons leave the file untouched", open(DELIVERY, encoding="utf-8").read() == before)
r = add("exactly-280", text="y" * 280, stack="general")
check("a 280-character lesson is accepted, empty paths become []",
      r.returncode == 0 and rows(DELIVERY)[-1]["paths"] == [], r.stderr)
check("lesson add refuses a bad id", add("bad id").returncode != 0)

lesson("mark", "--id", "pg-rls-count-rows", "--held")
lesson("mark", "--id", "pg-rls-count-rows", "--held")
r = lesson("mark", "--id", "pg-rls-count-rows", "--recurred")
counters = rows(DELIVERY)[0]["counters"]
check("mark increments held and recurred",
      r.returncode == 0 and counters == {"injected": 0, "held": 2, "recurred": 1}, json.dumps(counters))
check("mark leaves other lessons alone", rows(DELIVERY)[1]["counters"]["held"] == 0)
check("mark refuses an unknown id", lesson("mark", "--id", "nope", "--held").returncode != 0)
check("mark needs --held or --recurred", lesson("mark", "--id", "pg-rls-count-rows").returncode != 0)
r = lesson("list")
check("list prints each lesson with its counters",
      "pg-rls-count-rows" in r.stdout and "held 2" in r.stdout and "exactly-280" in r.stdout, r.stdout)

target = os.path.join(GLOBAL_DIR, "postgres-supabase.jsonl")
with open(target, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(json.dumps({"id": "pg-existing", "stack": "postgres-supabase", "paths": [], "text": "old",
                             "counters": {"injected": 0, "held": 0, "recurred": 0}, "status": "active"}) + "\n")
r = lesson("promote", "--id", "pg-rls-count-rows", "--to", target)
promoted = rows(target)
check("promote appends the lesson with its counters",
      r.returncode == 0 and [p["id"] for p in promoted] == ["pg-existing", "pg-rls-count-rows"]
      and promoted[1]["counters"]["held"] == 2, r.stderr + json.dumps(promoted))
before = open(target, encoding="utf-8").read()
r = lesson("promote", "--id", "pg-rls-count-rows", "--to", target)
check("promote refuses an id already in the global file",
      r.returncode != 0 and "already exists" in r.stderr and open(target, encoding="utf-8").read() == before, r.stderr)
r = lesson("promote", "--id", "exactly-280", "--to", target)
check("promote refuses the file of another stack", r.returncode != 0 and "general" in r.stderr, r.stderr)
r = lesson("promote", "--id", "exactly-280", "--to", os.path.join(GLOBAL_DIR, "general.jsonl"))
check("promote creates a missing stack file", r.returncode == 0 and rows(os.path.join(GLOBAL_DIR, "general.jsonl"))[0]["id"] == "exactly-280", r.stderr)
check("promote refuses an unknown id", lesson("promote", "--id", "nope", "--to", target).returncode != 0)
custom = os.path.join(repo, "other.jsonl")
r = lesson("--lessons", custom, "list", "--json")
check("--lessons points at another file; a missing file lists nothing", r.returncode == 0 and json.loads(r.stdout) == [],
      r.stderr)

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
