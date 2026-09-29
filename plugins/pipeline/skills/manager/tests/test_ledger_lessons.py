import hashlib, json, os, subprocess, sys, tempfile, time

LEDGER_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ledger.py")
repo = tempfile.mkdtemp(prefix="ledgerlessons_")
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

r = add("stackless", stack="postgres")
check("lesson add refuses a stack with no lessons file", r.returncode != 0 and "postgres-supabase" in r.stderr, r.stderr)
r = add("pg-rls-assert-row-count")
check("lesson add refuses an id that already exists globally", r.returncode != 0 and "already exists" in r.stderr, r.stderr)
r = lesson("--lessons-dir", GLOBAL_DIR, "add", "--id", "custom-stack", "--stack", "general", "--text", "x",
           "--task", "T1", "--agent", "qa", "--finding", "f")
check("lesson add takes its stacks from --lessons-dir", r.returncode == 0, r.stderr)

own = os.path.join(repo, "own.jsonl")
r = lesson("--lessons", own, "mark", "--id", "pg-rls-assert-row-count", "--held")
first = rows(own)
check("mark works for a plugin global lesson, as a counters-only override row",
      r.returncode == 0 and first == [{"id": "pg-rls-assert-row-count", "stack": "postgres-supabase", "override": True,
                                       "counters": {"injected": 0, "held": 1, "recurred": 0}}], r.stderr + json.dumps(first))
lesson("--lessons", own, "mark", "--id", "pg-rls-assert-row-count", "--recurred")
check("a second mark increments the same override row",
      len(rows(own)) == 1 and rows(own)[0]["counters"] == {"injected": 0, "held": 1, "recurred": 1}, json.dumps(rows(own)))
check("mark still refuses an id that is nowhere",
      lesson("--lessons", own, "mark", "--id", "nowhere", "--held").returncode != 0)
r = lesson("--lessons", own, "promote", "--id", "pg-rls-assert-row-count", "--to", target)
check("promote refuses an override row", r.returncode != 0 and "sync" in r.stderr, r.stderr)
r = lesson("--lessons", own, "list")
check("list shows an override as a global lesson", "global lesson" in r.stdout and "held 1" in r.stdout, r.stdout)

synced_dir = os.path.join(repo, "synced")
os.makedirs(synced_dir)
seed = [{"id": "g-one", "stack": "postgres-supabase", "paths": [], "text": "One é.",
         "counters": {"injected": 2, "held": 1, "recurred": 0}, "status": "active"},
        {"id": "g-two", "stack": "postgres-supabase", "paths": [], "text": "Two.",
         "counters": {"injected": 0, "held": 0, "recurred": 0}, "status": "active"}]
seed_file = os.path.join(synced_dir, "postgres-supabase.jsonl")
with open(seed_file, "w", encoding="utf-8", newline="\n") as handle:
    handle.write("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in seed))
second_line = open(seed_file, encoding="utf-8").read().splitlines()[1]
overrides = os.path.join(repo, "overrides.jsonl")
lesson("--lessons", overrides, "--lessons-dir", synced_dir, "mark", "--id", "g-one", "--held")
lesson("--lessons", overrides, "--lessons-dir", synced_dir, "mark", "--id", "g-one", "--recurred")
r = lesson("--lessons", overrides, "sync", "--to-dir", synced_dir)
after = rows(seed_file)
check("sync adds the override counters into the global file",
      r.returncode == 0 and after[0]["counters"] == {"injected": 2, "held": 2, "recurred": 1}, r.stderr + json.dumps(after))
check("sync keeps untouched lines byte-identical and leaves no temp file",
      open(seed_file, encoding="utf-8").read().splitlines()[1] == second_line
      and not os.path.exists(seed_file + ".tmp"))
check("sync zeroes the synced override and dates it",
      rows(overrides)[0]["counters"] == {"injected": 0, "held": 0, "recurred": 0} and rows(overrides)[0].get("synced"),
      json.dumps(rows(overrides)))
r = lesson("--lessons", overrides, "sync", "--to-dir", synced_dir)
check("a second sync adds nothing", r.returncode == 0 and rows(seed_file)[0]["counters"]["held"] == 2, r.stdout)
lesson("--lessons", overrides, "--lessons-dir", synced_dir, "mark", "--id", "g-two", "--held")
before = open(seed_file, encoding="utf-8").read()
r = lesson("--lessons", overrides, "sync", "--to-dir", GLOBAL_DIR)
check("sync to a folder without the lesson changes nothing",
      r.returncode != 0 and open(seed_file, encoding="utf-8").read() == before and rows(overrides)[1]["counters"]["held"] == 1,
      r.stderr)

check("a finished sync leaves no journal and writes no sync bookkeeping into the global file",
      "sync_pending" not in rows(overrides)[0] and not os.path.exists(os.path.join(repo, "overrides.sync.json"))
      and all(set(row) <= {"id", "stack", "paths", "text", "counters", "status"} for row in rows(seed_file)),
      json.dumps(rows(overrides)) + json.dumps(rows(seed_file)))


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def global_text(items):
    return "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items)


def crash_case(name, held_global, held_pending, held_delivery, file_state, with_journal=True):
    folder = os.path.join(repo, name)
    os.makedirs(folder)
    target = os.path.join(folder, "postgres-supabase.jsonl")
    other = {"id": "g-other", "stack": "postgres-supabase", "paths": [], "text": "Other.",
             "counters": {"injected": 0, "held": 7, "recurred": 0}, "status": "active"}
    base = [{"id": "g-x", "stack": "postgres-supabase", "paths": [], "text": "X.",
             "counters": {"injected": 0, "held": held_global, "recurred": 0}, "status": "active"}, other]
    applied = [dict(base[0], counters={"injected": 0, "held": held_global + held_pending, "recurred": 0}), other]
    before, after = global_text(base), global_text(applied)
    current = {"before": before, "after": after}.get(file_state, file_state)
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(current)
    delivery = os.path.join(folder, "lessons.jsonl")
    with open(delivery, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({"id": "g-x", "stack": "postgres-supabase", "override": True,
                                 "counters": {"injected": 0, "held": held_delivery, "recurred": 0},
                                 "sync_pending": {"id": "s-1", "counters": {"injected": 0, "held": held_pending,
                                                                            "recurred": 0}}}) + "\n")
    journal = os.path.join(folder, "lessons.sync.json")
    if with_journal:
        with open(journal, "w", encoding="utf-8") as handle:
            json.dump({"id": "s-1", "files": {os.path.normcase(os.path.abspath(target)):
                                              {"before": digest(before), "after": digest(after)}}}, handle)
    result = lesson("--lessons", delivery, "sync", "--to-dir", folder)
    return result, target, delivery, journal


r, target, delivery, journal = crash_case("crash-after-write", 5, 2, 3, "after")
check("after a crash past the global write, a rerun does not add the journaled counters again",
      r.returncode == 0 and rows(target)[0]["counters"]["held"] == 7 and rows(target)[1]["counters"]["held"] == 7,
      r.stderr + json.dumps(rows(target)))
check("counters marked after the crash stay in the delivery row, and the journal is gone",
      rows(delivery)[0]["counters"]["held"] == 1 and "sync_pending" not in rows(delivery)[0]
      and not os.path.exists(journal), json.dumps(rows(delivery)))
r = lesson("--lessons", delivery, "sync", "--to-dir", os.path.dirname(target))
check("the delivery row keeps its leftover counters for the next sync",
      r.returncode == 0 and rows(target)[0]["counters"]["held"] == 8 and rows(delivery)[0]["counters"]["held"] == 0,
      r.stderr + json.dumps(rows(target)))
r, target, delivery, journal = crash_case("crash-before-write", 1, 2, 2, "before")
check("after a crash between the journal and the global write, a rerun adds the counters once",
      r.returncode == 0 and rows(target)[0]["counters"]["held"] == 3 and rows(delivery)[0]["counters"]["held"] == 0
      and not os.path.exists(journal), r.stderr + json.dumps(rows(target)))
r, target, delivery, journal = crash_case("crash-before-journal", 1, 2, 2, "before", with_journal=False)
check("after a crash before the journal was written, a rerun adds the counters once",
      r.returncode == 0 and rows(target)[0]["counters"]["held"] == 3 and not os.path.exists(journal),
      r.stderr + json.dumps(rows(target)))
edited = global_text([{"id": "g-x", "stack": "postgres-supabase", "paths": [], "text": "X edited.",
                       "counters": {"injected": 0, "held": 1, "recurred": 0}, "status": "active"}])
r, target, delivery, journal = crash_case("crash-then-edited", 1, 2, 2, edited)
check("a global file changed since the interrupted sync stops the rerun and writes nothing",
      r.returncode != 0 and "changed since the interrupted sync" in r.stderr
      and open(target, encoding="utf-8").read() == edited and "sync_pending" in rows(delivery)[0]
      and os.path.exists(journal), r.stderr)
stale = os.path.join(repo, "stale")
os.makedirs(stale)
with open(os.path.join(stale, "lessons.sync.json"), "w", encoding="utf-8") as handle:
    handle.write('{"id": "old", "files": {}}')
r = lesson("--lessons", os.path.join(stale, "lessons.jsonl"), "sync", "--to-dir", stale)
check("a journal left after the delivery rows were already finished is removed",
      r.returncode == 0 and not os.path.exists(os.path.join(stale, "lessons.sync.json")), r.stderr)

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
