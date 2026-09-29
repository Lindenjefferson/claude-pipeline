import json, os, subprocess, sys, tempfile, time

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

r, text = brief("T0.1")
section = text[text.find("## Lessons (from past deliveries)"):]
order = [lesson_id for lesson_id in ("g-sql-high", "g-tsx", "d-sql", "g-general", "g-sql-low", "g-sql-zzz")
         if f"[{lesson_id}]" in section]
check("lessons section comes after the addenda", text.find("Applies to every task.") < text.find("## Lessons"), text)
check("path-matched lessons are ranked: score (held - 2*recurred, +0.25 delivery), then id",
      order == ["g-sql-high", "g-tsx", "d-sql", "g-general", "g-sql-low", "g-sql-zzz"]
      and [section.find(f"[{i}]") for i in order] == sorted(section.find(f"[{i}]") for i in order), section)
check("at most 6 lessons, with the truncation line",
      section.count("\n- ") == 6 and "[lessons truncated: 1 more]" in section and "[g-sql-recurred]" not in section,
      section)
check("retired, non-matching, and empty-path non-general lessons are left out",
      all(f"[{i}]" not in section for i in ("g-retired", "g-lib", "pg-empty", "d-other")), section)
delivery = {item["id"]: item for item in (json.loads(l) for l in open(DELIVERY, encoding="utf-8"))}
check("injected counts only in the delivery file, only for injected lessons",
      delivery["d-sql"]["counters"]["injected"] == 1 and delivery["d-other"]["counters"]["injected"] == 0,
      json.dumps(delivery))
check("global lesson files are never written",
      all(open(os.path.join(GLOBAL, n), encoding="utf-8").read() == t for n, t in global_before.items()))
check("brief reports the lessons count", "6 lessons" in r.stdout, r.stdout)
brief("T0.1")
check("each brief counts again", json.loads(open(DELIVERY).readline())["counters"]["injected"] == 2)
r, text = brief("T0.1", "--no-lessons")
check("--no-lessons leaves the section and the counters out",
      "## Lessons" not in text and json.loads(open(DELIVERY).readline())["counters"]["injected"] == 2, text)
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

sh("git", "init", "-q")
sh("git", "config", "user.email", "t@t.com")
sh("git", "config", "user.name", "t")
sh("git", "config", "core.autocrlf", "false")
save(os.path.join(repo, "README.md"), "readme\n")
sh("git", "add", "README.md")
sh("git", "commit", "-q", "-m", "base")
base = sh("git", "rev-parse", "HEAD")
save(os.path.join(repo, "package-lock.json"), '{"LOCKMARKER": 1}\n')
save(os.path.join(repo, "web", "yarn.lock"), "YARNMARKER\n")
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
