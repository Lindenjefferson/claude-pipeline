import json, os, re, subprocess, sys, tempfile, time

PACKAGE_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "package.py")
repo = os.path.join(tempfile.gettempdir(), f"packagecontext_{int(time.time() * 1000)}")
BRIEFS = os.path.join(repo, ".superpowers", "briefs")
GLOBAL = os.path.join(repo, "global-lessons")
DELIVERY = os.path.join(repo, ".superpowers", "lessons.jsonl")
CHECKLISTS = os.path.join(repo, "checklists")
for folder in (BRIEFS, GLOBAL, CHECKLISTS):
    os.makedirs(folder)
results = []


def sh(*args):
    return subprocess.run(args, cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def package(*args):
    return subprocess.run([sys.executable, PACKAGE_PY, *args], cwd=repo, capture_output=True, encoding="utf-8")


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS" if ok else "FAIL"), name, "" if ok else f"| {detail[:400]}")


def save(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def jsonl(path, lessons):
    save(path, "".join(json.dumps(item) + "\n" for item in lessons))


def make(lesson_id, text=None, stack="postgres-supabase", paths=("supabase/**/*.sql",), held=0, recurred=0,
         status="active"):
    return {"id": lesson_id, "stack": stack, "paths": list(paths), "text": text or f"Rule of {lesson_id}.",
            "counters": {"injected": 0, "held": held, "recurred": recurred}, "status": status}


def brief(task, *extra):
    out = os.path.join(repo, "out", f"{task}.md")
    r = package("brief", "--plan", "plan.md", "--task", task, "--out", out, "--lessons-dir", GLOBAL, *extra)
    return r, (open(out, encoding="utf-8").read() if os.path.exists(out) else "")


save(os.path.join(repo, "plan.md"),
     "# Plan\n\n"
     "## Task T0.1: setup\n**Files:**\n- Create: `supabase/migrations/0001_init.sql`\n- Modify: `app/page.tsx:10-20`\n\nDo it.\n\n"
     "## Task T0.10: other\nten\n\n"
     "### Task A-1: lettered\nletters\n\n"
     "## Task 4. dotted\ndotted body\n\n"
     "## Task 5: no files\nJust words.\n")

r, text = brief("T0.1", "--no-lessons")
check("brief finds a T0.1 id", r.returncode == 0 and text.startswith("## Task T0.1") and "Do it." in text, r.stderr)
check("T0.1 does not run into T0.10", "T0.10" not in text, text)
r, text = brief("T0.10", "--no-lessons")
check("brief tells T0.10 from T0.1", r.returncode == 0 and text.startswith("## Task T0.10") and "setup" not in text, text)
r, text = brief("A-1", "--no-lessons")
check("brief finds an id with a dash", r.returncode == 0 and "letters" in text, r.stderr)
r, text = brief("4", "--no-lessons")
check("brief finds a numeric id followed by a dot", r.returncode == 0 and "dotted body" in text, r.stderr)
check("brief fails for T0", brief("T0", "--no-lessons")[0].returncode != 0)

save(os.path.join(BRIEFS, "T0.1.addenda", "02-second.md"), "Second addendum.\n")
save(os.path.join(BRIEFS, "T0.1.addenda", "01-first.md"), "First addendum.\r\n")
save(os.path.join(BRIEFS, "all.addenda", "00-global.md"), "Applies to every task.\n")
save(os.path.join(BRIEFS, "T0.10.addenda", "x.md"), "Only for T0.10.\n")
save(os.path.join(BRIEFS, "T0.1.addenda", "notes.txt"), "Not markdown.\n")
r, text = brief("T0.1", "--no-lessons")
first, second, common = (text.find(s) for s in ("First addendum.", "Second addendum.", "Applies to every task."))
check("addenda follow the task in name order, then all.addenda", 0 < text.find("Do it.") < first < second < common,
      text)
check("each addendum sits under its own separator", text.count("\n---\n") == 3, text)
check("addenda of other tasks and non-.md files are left out",
      "Only for T0.10" not in text and "Not markdown" not in text, text)
check("brief reports the addenda count", "3 addenda" in r.stdout, r.stdout)

jsonl(os.path.join(GLOBAL, "postgres-supabase.jsonl"), [
    make("g-sql-high", held=3), make("g-sql-low"), make("g-sql-zzz"), make("g-sql-recurred", held=3, recurred=2),
    make("g-retired", held=9, status="retired"), make("g-lib", paths=("lib/**",), held=9),
    make("pg-empty", paths=(), held=9)])
jsonl(os.path.join(GLOBAL, "nextjs-react.jsonl"), [make("g-tsx", stack="nextjs-react", paths=("**/*.tsx",), held=1)])
jsonl(os.path.join(GLOBAL, "general.jsonl"), [make("g-general", stack="general", paths=())])
jsonl(DELIVERY, [make("d-sql", paths=("**/*.sql",)), make("d-other", paths=("docs/**",))])
global_before = {name: open(os.path.join(GLOBAL, name), encoding="utf-8").read() for name in os.listdir(GLOBAL)}

os.remove(os.path.join(repo, "out", "T0.1.md"))
r, text = brief("T0.1")
section = text[text.find("## Lessons (from past deliveries)"):]
expected = ["g-sql-high", "g-tsx", "g-sql-low", "g-sql-zzz", "g-sql-recurred", "d-sql"]
check("lessons section comes after the addenda", text.find("Applies to every task.") < text.find("## Lessons"), text)
check("lessons take turns by stack, each stack ranked by glob specificity, match count, score (held - 2*recurred, +0.25 delivery), id",
      [section.find(f"[{i}]") for i in expected] == sorted(section.find(f"[{i}]") for i in expected)
      and all(f"[{i}]" in section for i in expected), section)
check("at most 6 lessons, with the truncation line",
      section.count("\n- ") == 6 and "[lessons truncated: 1 more]" in section and "[g-general]" not in section,
      section)
check("retired, non-matching, and empty-path non-general lessons are left out",
      all(f"[{i}]" not in section for i in ("g-retired", "g-lib", "pg-empty", "d-other")), section)
delivery = {item["id"]: item for item in (json.loads(l) for l in open(DELIVERY, encoding="utf-8"))}
check("injected counts in the delivery file, only for injected lessons",
      delivery["d-sql"]["counters"]["injected"] == 1 and delivery["d-other"]["counters"]["injected"] == 0,
      json.dumps(delivery))
check("an injected global lesson is counted in a delivery override row",
      delivery.get("g-sql-high", {}).get("override") is True and delivery["g-sql-high"]["counters"]["injected"] == 1
      and "g-general" not in delivery, json.dumps(delivery))
check("global lesson files are never written",
      all(open(os.path.join(GLOBAL, n), encoding="utf-8").read() == t for n, t in global_before.items()))
check("the delivery file is replaced atomically", not os.path.exists(DELIVERY + ".tmp"))
check("brief reports the lessons count", "6 lessons" in r.stdout, r.stdout)
save(os.path.join(BRIEFS, "T0.1.addenda", "03-fix.md"), "Fix round.\n")
r, text = brief("T0.1")
check("regenerating an existing brief (new addenda) does not count again",
      "Fix round." in text and json.loads(open(DELIVERY).readline())["counters"]["injected"] == 1, r.stderr)
with open(DELIVERY, "a", encoding="utf-8", newline="\n") as handle:
    handle.write(json.dumps(dict(make("d-new"), priority=1)) + "\n")
r, text = brief("T0.1")
delivery = {item["id"]: item for item in (json.loads(l) for l in open(DELIVERY, encoding="utf-8"))}
check("regenerating after a new delivery lesson counts only the new one",
      "[d-new]" in text and delivery["d-new"]["counters"]["injected"] == 1
      and delivery["d-sql"]["counters"]["injected"] == 1 and delivery["g-sql-high"]["counters"]["injected"] == 1,
      json.dumps(delivery))
check("the injected ids of the task are kept next to the brief",
      "d-new" in open(os.path.join(repo, "out", "T0.1.md.lessons"), encoding="utf-8").read().split())
os.remove(os.path.join(repo, "out", "T0.1.md.lessons"))
r, text = brief("T0.1")
delivery = {item["id"]: item for item in (json.loads(l) for l in open(DELIVERY, encoding="utf-8"))}
check("without the id list, the ids in the existing brief are not counted again",
      delivery["d-new"]["counters"]["injected"] == 1 and delivery["d-sql"]["counters"]["injected"] == 1,
      json.dumps(delivery))
os.remove(os.path.join(BRIEFS, "T0.1.addenda", "03-fix.md"))
os.remove(os.path.join(repo, "out", "T0.1.md"))
r, text = brief("T0.1")
delivery = {item["id"]: item for item in (json.loads(l) for l in open(DELIVERY, encoding="utf-8"))}
check("a deleted and regenerated brief does not count again",
      delivery["d-new"]["counters"]["injected"] == 1 and delivery["g-sql-high"]["counters"]["injected"] == 1,
      json.dumps(delivery))
os.remove(os.path.join(repo, "out", "T0.1.md"))
r, text = brief("T0.1", "--no-lessons")
check("--no-lessons leaves the section and the counters out",
      "## Lessons" not in text and json.loads(open(DELIVERY).readline())["counters"]["injected"] == 1, text)
r, text = brief("5")
check("a task without paths gets only general lessons with empty paths",
      "[g-general]" in text and text.count("\n- ") == 1 and "truncated" not in text, text)
r, text = brief("T0.1", "--delivery-lessons", os.path.join(repo, "missing.jsonl"))
check("a missing delivery file is fine", r.returncode == 0 and "[d-sql]" not in text, r.stderr)

big = os.path.join(repo, "big-lessons")
jsonl(os.path.join(big, "postgres-supabase.jsonl"),
      [make(f"big-{n}", text=f"{n} " + "long rule " * 300, held=3 - n) for n in range(3)])
out = os.path.join(repo, "out", "big.md")
r = package("brief", "--plan", "plan.md", "--task", "T0.1", "--out", out, "--lessons-dir", big,
            "--delivery-lessons", os.path.join(repo, "missing.jsonl"))
text = open(out, encoding="utf-8").read()
section = text[text.find("## Lessons"):]
check("the lessons section stays within 8000 characters",
      len(section) <= 8000 and "[big-0]" in section and "[big-1]" in section and "[big-2]" not in section, str(len(section)))
check("the character cap is reported as truncation", "[lessons truncated: 1 more]" in section, section[-80:])
r = package("brief", "--plan", "plan.md", "--task", "T0.1", "--out", out,
            "--delivery-lessons", os.path.join(repo, "missing.jsonl"))
check("the default lessons dir (next to the plugin) works whether or not it exists", r.returncode == 0, r.stderr)

save(os.path.join(repo, "rls-plan.md"),
     "## Task R1: rls\n**Files:**\n- Create: `supabase/migrations/0002_x.sql`\n- Create: `supabase/tests/rls.sql`\n")
out = os.path.join(repo, "out", "R1.md")
r = package("brief", "--plan", "rls-plan.md", "--task", "R1", "--out", out,
            "--delivery-lessons", os.path.join(repo, "none.jsonl"))
text = open(out, encoding="utf-8").read()
injected = re.findall(r"\[([\w-]+)\]\n", text)
priority_lessons = {"pg-revoke-default-execute", "pg-security-definer-search-path", "pg-rpc-null-args"}
rls_lessons = {"pg-rls-assert-row-count", "pg-rls-negative-test"}
check("a migration + test task gets the priority lessons and the pg-rls-* test lessons first",
      r.returncode == 0 and set(injected[:5]) == priority_lessons | rls_lessons and len(injected) == 6
      and "gen-fix-interactions" not in injected, text)

save(os.path.join(repo, "fn-plan.md"), "## Task F1: fn\n**Files:**\n- Create: `supabase/migrations/0007_fn.sql`\n")
out = os.path.join(repo, "out", "F1.md")
r = package("brief", "--plan", "fn-plan.md", "--task", "F1", "--out", out,
            "--delivery-lessons", os.path.join(repo, "none-fn.jsonl"))
injected = re.findall(r"\[([\w-]+)\]\n", open(out, encoding="utf-8").read())
check("a migration-only task gets the priority-1 lessons, not the pgTAP test lessons",
      r.returncode == 0 and set(injected[:3]) == priority_lessons and len(injected) == 6
      and not rls_lessons & set(injected) and "pg-pgtap-no-modifying-with" not in injected, str(injected))

save(os.path.join(repo, "test-plan.md"), "## Task Q1: tests\n**Files:**\n- Create: `supabase/tests/rls_test.sql`\n")
out = os.path.join(repo, "out", "Q1.md")
r = package("brief", "--plan", "test-plan.md", "--task", "Q1", "--out", out,
            "--delivery-lessons", os.path.join(repo, "none-q.jsonl"))
injected = re.findall(r"\[([\w-]+)\]\n", open(out, encoding="utf-8").read())
check("a test-only task gets the pgTAP test lessons, not the migration-writing ones",
      r.returncode == 0 and set(injected[:2]) == rls_lessons
      and not {"pg-revoke-default-execute", "pg-security-definer-search-path"} & set(injected), str(injected))


def seed_brief(name, paths):
    save(os.path.join(repo, f"{name}-plan.md"),
         f"## Task {name}: x\n**Files:**\n" + "".join(f"- Create: `{path}`\n" for path in paths))
    out = os.path.join(repo, "out", f"{name}.md")
    result = package("brief", "--plan", f"{name}-plan.md", "--task", name, "--out", out,
                     "--delivery-lessons", os.path.join(repo, f"none-{name}.jsonl"))
    return result, re.findall(r"\[([\w-]+)\]\n", open(out, encoding="utf-8").read())


def stacks_of(ids):
    return {"auth" if i.startswith("auth-") else "general" if i.startswith("gen-") else
            "postgres-supabase" if i.startswith("pg-") else "nextjs-react" for i in ids}


auth_core = {"auth-account-oracles", "auth-preregistration-takeover", "auth-sessions-after-password-change"}
r, injected = seed_brief("LOGIN", ["app/(auth)/login/actions.ts", "app/(auth)/login/page.tsx"])
check("a login action + page task fills its first slots with the core auth and Next.js security lessons",
      r.returncode == 0 and len(injected) == 6
      and set(injected[:5]) == auth_core | {"next-server-action-auth", "next-page-level-guard"}, str(injected))
r, injected = seed_brief("ACTION", ["app/(app)/pessoas/actions.ts"])
check("a server-only action task gets no ui-*/a11y-* lessons",
      r.returncode == 0 and "next-server-action-auth" in injected
      and not [i for i in injected if i.startswith(("ui-", "a11y-", "react19-"))], str(injected))
r, injected = seed_brief("COMPONENT", ["components/pessoas/person-form.tsx"])
check("a .tsx component task gets the ui and a11y lessons",
      r.returncode == 0 and {"ui-touch-target-44", "ui-alertdialog-from-menu", "a11y-aria-live-persistent"} <= set(injected)
      and "next-server-action-auth" not in injected, str(injected))
r, injected = seed_brief("MIXED", ["supabase/migrations/0003_p.sql", "app/(app)/pessoas/actions.ts",
                                   "app/(app)/pessoas/page.tsx"])
check("a migration + action + page task gives every matching stack a slot",
      r.returncode == 0 and len(injected) == 6 and stacks_of(injected) == {"postgres-supabase", "nextjs-react", "general"}
      and {"pg-revoke-default-execute", "pg-security-definer-search-path"} <= set(injected), str(injected))
r, injected = seed_brief("CROWDED", ["supabase/migrations/0004_auth.sql", "supabase/tests/auth_test.sql",
                                     "app/(auth)/login/actions.ts", "components/login-form.tsx"])
check("priority lessons from several stacks still leave a slot for every matching stack",
      r.returncode == 0 and len(injected) == 6
      and stacks_of(injected) == {"postgres-supabase", "nextjs-react", "general", "auth"}, str(injected))

ranked = os.path.join(repo, "ranked-lessons")
jsonl(os.path.join(ranked, "postgres-supabase.jsonl"), [
    make("r-a-any", paths=("**/*.sql",)), make("r-b-both", paths=("supabase/migrations/**", "supabase/tests/**")),
    make("r-c-mig", paths=("supabase/migrations/*.sql",)), make("r-d-root", paths=("supabase/**",)),
    make("r-e-deep", paths=("supabase/migrations/0002_*.sql",)), make("r-f-tests", paths=("supabase/tests/**",)),
    make("r-g-any2", paths=("**",)), make("r-h-prio", paths=("supabase/**",)), make("r-i-sql2", paths=("**/*.sql",))])
rows_before = open(os.path.join(ranked, "postgres-supabase.jsonl"), encoding="utf-8").read()
data = [json.loads(line) for line in rows_before.splitlines()]
data[7]["priority"] = 2
jsonl(os.path.join(ranked, "postgres-supabase.jsonl"), data)
orders = []
for attempt in range(2):
    out = os.path.join(repo, "out", f"ranked-{attempt}.md")
    package("brief", "--plan", "rls-plan.md", "--task", "R1", "--out", out, "--lessons-dir", ranked,
            "--delivery-lessons", os.path.join(repo, "none-ranked.jsonl"))
    orders.append(re.findall(r"\[([\w-]+)\]\n", open(out, encoding="utf-8").read()))
check("more than 6 equal-counter matches: priority, then glob specificity (an exact glob beats **), deterministic",
      orders[0] == orders[1] == ["r-h-prio", "r-e-deep", "r-c-mig", "r-b-both", "r-f-tests", "r-d-root"]
      and "[lessons truncated: 3 more]" in open(os.path.join(repo, "out", "ranked-0.md"), encoding="utf-8").read(), str(orders))

overrides = os.path.join(repo, "override-lessons.jsonl")
jsonl(overrides, [{"id": "r-i-sql2", "stack": "postgres-supabase", "override": True,
                   "counters": {"injected": 0, "held": 3, "recurred": 0}}])
out = os.path.join(repo, "out", "ranked-override.md")
save(os.path.join(repo, "sql-plan.md"), "## Task S1: sql\n**Files:**\n- Create: `db/x.sql`\n")
package("brief", "--plan", "sql-plan.md", "--task", "S1", "--out", out, "--lessons-dir", ranked,
        "--delivery-lessons", overrides)
order = re.findall(r"\[([\w-]+)\]\n", open(out, encoding="utf-8").read())
check("delivery override counters add to the global counters in the ranking",
      order == ["r-i-sql2", "r-a-any", "r-g-any2"], str(order))
row = json.loads(open(overrides, encoding="utf-8").readline())
check("the override row counts the injection", row["counters"] == {"injected": 1, "held": 3, "recurred": 0}, str(row))

sh("git", "init", "-q")
sh("git", "config", "user.email", "t@t.com")
sh("git", "config", "user.name", "t")
sh("git", "config", "core.autocrlf", "false")
save(os.path.join(repo, "README.md"), "readme\n")
sh("git", "add", "README.md")
sh("git", "commit", "-q", "-m", "base")
base = sh("git", "rev-parse", "HEAD")
save(os.path.join(repo, "package-lock.json"),
     '{"LOCKMARKER": 1,\n  "node_modules/left-pad": {\n    "version": "1.3.0",\n'
     '    "resolved": "https://registry.npmjs.org/left-pad/-/left-pad-1.3.0.tgz"\n  }\n}\n')
save(os.path.join(repo, "web", "yarn.lock"),
     "YARNMARKER\n" + "".join(f'pkg{n}@^1.0.0:\n  version "1.0.{n}"\n  dependencies-marker\n' for n in range(50)))
save(os.path.join(repo, "supabase", "migrations", "0001.sql"), "create table t (id int);\n")
save(os.path.join(repo, "app", "page.tsx"), "export default function Page() {}\n")
sh("git", "add", "package-lock.json", "web/yarn.lock", "supabase", "app")
sh("git", "commit", "-q", "-m", "work")
head = sh("git", "rev-parse", "HEAD")
save(os.path.join(CHECKLISTS, "postgres-supabase.md"),
     '---\nstack: postgres-supabase\npaths: ["supabase/**", "**/*.sql"]\nagents: [db, security, code-review]\n---\n- check\n')
save(os.path.join(CHECKLISTS, "nextjs-react.md"),
     "---\nstack: nextjs-react\npaths:\n  - \"app/**\"\n  - '**/*.tsx'\nagents: [design, code-review]\n---\n- check\n")
save(os.path.join(CHECKLISTS, "auth.md"), '---\nstack: auth\npaths: ["**/auth/**"]\nagents: [security]\n---\n- check\n')
save(os.path.join(CHECKLISTS, "loose.md"), "# no frontmatter\npaths: [\"**\"]\n")

r = package("review", "--base", base, "--head", head, "--name", "ctx", "--checklists-dir", CHECKLISTS)
diff = open(os.path.join(repo, ".superpowers", "reviews", "review-ctx.diff"), encoding="utf-8").read()
history = open(os.path.join(repo, ".superpowers", "reviews", "review-ctx.history.patch"), encoding="utf-8").read()
body = diff[diff.find("## Diff"):]
check("review succeeds with lockfiles in the range", r.returncode == 0, r.stderr)
check("lockfiles are left out of the diff body", "LOCKMARKER" not in body and "YARNMARKER" not in body, body)
check("lockfiles stay in the stat, with a note",
      "package-lock.json" in diff[:diff.find("## Diff")] and "Lockfiles left out" in diff
      and "web/yarn.lock" in diff[:diff.find("## Diff")], diff[:1500])
check("the rest of the diff is kept", "create table t" in body and "export default function Page" in body, body)
check("the history patch still carries the lockfiles", "LOCKMARKER" in history)
deps = diff[diff.find("## Dependency changes"):diff.find("## Diff")]
check("a Dependency changes section sits between the stat and the diff",
      diff.find("## Files changed") < diff.find("## Dependency changes") < diff.find("## Diff"), diff[:2000])
npm = deps[deps.find("### package-lock.json"):deps.find("### web/yarn.lock")]
check("it lists the package lines of each lockfile, not the rest",
      '+  "node_modules/left-pad": {' in npm and '+    "version": "1.3.0",' in npm and "left-pad-1.3.0.tgz" in npm
      and "LOCKMARKER" not in deps and "dependencies-marker" not in deps and "YARNMARKER" not in deps, deps)
yarn = deps[deps.find("### web/yarn.lock"):]
check("a long lockfile is capped at 80 lines, then truncated",
      yarn.count("\n+") == 80 and "+pkg0@^1.0.0:" in yarn and "[truncated: 20 more lines]" in yarn, yarn[-300:])
checklists = diff[diff.find("## Checklists"):diff.find("## Commits")]
check("the Checklists section is in the header, before the commits", 0 < diff.find("## Checklists") < diff.find("## Commits"),
      diff[:600])
check("matching checklists are listed by absolute path",
      os.path.abspath(os.path.join(CHECKLISTS, "postgres-supabase.md")) in checklists
      and os.path.abspath(os.path.join(CHECKLISTS, "nextjs-react.md")) in checklists, checklists)
check("checklists list their agents (flow and block YAML lists)",
      "agents: db, security, code-review" in checklists and "agents: design, code-review" in checklists, checklists)
check("non-matching and frontmatter-less checklists are not listed",
      "auth.md" not in checklists and "loose.md" not in checklists, checklists)
r = package("review", "--base", base, "--head", head, "--name", "full", "--include-lockfiles",
            "--checklists-dir", os.path.join(repo, "no-such-dir"))
full = open(os.path.join(repo, ".superpowers", "reviews", "review-full.diff"), encoding="utf-8").read()
check("--include-lockfiles keeps them in the diff",
      r.returncode == 0 and "LOCKMARKER" in full[full.find("## Diff"):] and "Lockfiles left out" not in full, r.stderr)
check("no matching checklist says so", "none matched" in full, full[:400])

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
