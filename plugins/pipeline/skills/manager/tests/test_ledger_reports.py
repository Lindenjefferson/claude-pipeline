import re, json, os, subprocess, sys, tempfile, time

LEDGER_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ledger.py")
repo = os.path.join(tempfile.gettempdir(), f"ledgerreports_{int(time.time() * 1000)}")
os.makedirs(os.path.join(repo, "src"))
LEDGER = os.path.join(repo, ".superpowers", "ledger.jsonl")
REPORTS = os.path.join(repo, ".superpowers", "reports")
REVIEW_REPORT = os.path.join(repo, "review.md")
open(REVIEW_REPORT, "w").write("review\n")
PAD = "The change follows the brief and the tests pass. " * 6
results = []


def sh(*args):
    return subprocess.run(args, cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def ledger(*args, stdin=None):
    return subprocess.run([sys.executable, LEDGER_PY, "--ledger", LEDGER, *args], cwd=repo,
                          capture_output=True, input=stdin, encoding="utf-8")


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS" if ok else "FAIL"), name, "" if ok else f"| {detail[:300]}")


def report(name, text):
    path = os.path.join(repo, ".superpowers", name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


def append(line, path, task="1", frm=None, head="HEAD", extra=()):
    return ledger("append", "--task", task, "--from", frm or base, "--head", head, "--report", path,
                  "--line", line, *extra)


def entries():
    return [json.loads(line) for line in open(LEDGER, encoding="utf-8") if line.strip()]


def reviewer(agent, verdict):
    zero = {"critical": 0, "important": 0, "minor": 0}
    return "LEDGER " + json.dumps({"agent": agent, "verdict": verdict, "new": zero, "open": zero})


DEV = 'LEDGER {"agent":"dev","verdict":"DONE"}'
sh("git", "init", "-q")
sh("git", "config", "user.email", "t@t.com")
sh("git", "config", "user.name", "t")
open(os.path.join(repo, "README.md"), "w").write("readme\n")
open(os.path.join(repo, "src", "a.py"), "w").write("a = 1\n")
sh("git", "add", ".")
sh("git", "commit", "-q", "-m", "base")
base = sh("git", "rev-parse", "HEAD")
open(os.path.join(repo, "src", "a.py"), "w").write("a = 2\n")
sh("git", "commit", "-q", "-am", "task 1")
c1 = sh("git", "rev-parse", "HEAD")
ledger("start", "--slug", "x", "--base", base, "--layout", "per-file")

good = report("good.md", f"Committed {c1[:8]}.\n\n**Files:**\n- Modify: `src/a.py:1-2`\n\n{PAD}\n{DEV}\n")
r = append(DEV, good, frm="HEAD~1")
last = entries()[-1]
check("append accepts --head HEAD and --from HEAD~1", r.returncode == 0, r.stdout + r.stderr)
check("the entry stores the resolved SHAs", last.get("head") == c1 and last.get("from") == base, json.dumps(last))

before = open(LEDGER).read()
no_line = report("noline.md", f"Committed {c1[:8]}.\n{PAD}\n")
r = append(DEV, no_line)
check("rejects an implementer report without a LEDGER line", r.returncode != 0 and "LEDGER" in r.stderr, r.stderr)
r = append(DEV, report("placeholder.md", f"placeholder\n{DEV}\n"))
check("rejects a placeholder report", r.returncode != 0 and "placeholder" in r.stderr, r.stderr)
r = append(DEV, report("todo.md", "TODO " * 60 + f"\n{DEV}\n"))
check("rejects a report made only of TODO", r.returncode != 0 and "placeholder" in r.stderr, r.stderr)
r = append(DEV, report("nosha.md", f"Files:\n- `src/a.py`\n\n{PAD}\n{DEV}\n"))
check("rejects a dev DONE report that names no commit", r.returncode != 0 and "commit" in r.stderr, r.stderr)
r = append(DEV, report("oldsha.md", f"Committed {base[:8]}.\n{PAD}\n{DEV}\n"))
check("rejects a SHA outside FROM..HEAD", r.returncode != 0 and "commit" in r.stderr, r.stderr)
unlisted = report("unlisted.md", f"Committed {c1[:8]}.\n\n**Files:**\n- Modify: `src/a.py`\n- Modify: `README.md`\n\n"
                                  f"{PAD}\n{DEV}\n")
r = append(DEV, unlisted)
check("rejects an unchanged file in the Files section and names only it",
      r.returncode != 0 and "README.md" in r.stderr and "src/a.py" not in r.stderr, r.stderr)
r = append(DEV, report("listed.md", f"Committed {c1[:8]}.\nChanged files:\n- Modify: README.md\n\n{PAD}\n{DEV}\n"))
check("rejects a plain path in a Changed files list outside the diff", r.returncode != 0 and "README.md" in r.stderr,
      r.stderr)
r = append('LEDGER {"agent":"db","verdict":"DONE"}',
           report("dbnosha.md", f"Migration done.\n{PAD}\n" + 'LEDGER {"agent":"db","verdict":"DONE"}\n'))
check("rejects a db DONE report that names no commit", r.returncode != 0 and "commit" in r.stderr, r.stderr)
check("rejected reports leave the ledger untouched", open(LEDGER).read() == before)

r = append(DEV, unlisted, extra=("--allow-unlisted", "read only, for context"))
last = entries()
check("--allow-unlisted accepts the report", r.returncode == 0, r.stdout + r.stderr)
check("--allow-unlisted records the files and a ruling note",
      last[-2].get("unlisted") == ["README.md"] and last[-1].get("kind") == "ruling"
      and "README.md" in last[-1].get("text", "") and "read only" in last[-1]["text"], json.dumps(last[-2:]))
count = len(entries())
r = append(DEV, unlisted, extra=("--allow-unlisted",))
check("--allow-unlisted without a reason is refused", r.returncode != 0 and len(entries()) == count, r.stderr)
r = append(DEV, unlisted, extra=("--allow-unlisted", "   "))
check("--allow-unlisted with a blank reason is refused",
      r.returncode != 0 and "reason" in r.stderr and len(entries()) == count, r.stderr)
r = append(DEV, report("ignored.md", f"Committed {c1}.\nFiles:\n- `src/a.py`\n- `.superpowers/good.md`\n"
                                      f"- docs/none.md\n\n{PAD}\n{DEV}\n"))
check("untracked and missing paths in the Files section are not checked", r.returncode == 0, r.stderr)
r = append(DEV, report("readonly.md", f"Committed {c1[:8]}. I read `README.md` and `src/a.py` before editing.\n\n"
                                       f"Files changed:\n- `src/a.py`\n\n{PAD}\n{DEV}\n"))
last = entries()[-1]
check("a backticked unchanged file outside the Files section is accepted",
      r.returncode == 0 and "unlisted" not in last and last.get("event") != "note", r.stdout + r.stderr)
r = append(DEV, report("headingfiles.md", f"Committed {c1[:8]}.\n\n## Changed files\n- src/a.py\n- README.md\n\n"
                                           f"{PAD}\n{DEV}\n"))
check("an unchanged file under a Changed files heading is still rejected",
      r.returncode != 0 and "README.md" in r.stderr, r.stderr)
r = append('LEDGER {"agent":"docs","verdict":"DONE"}',
           report("docs.md", f"Nothing to commit here, docs are fine.\n{PAD}\n" + 'LEDGER {"agent":"docs","verdict":"DONE"}\n'))
check("docs reports need no SHA", r.returncode == 0, r.stderr)
r = append('LEDGER {"agent":"dev","verdict":"BLOCKED"}',
           report("blocked.md", f"Blocked before committing.\n{PAD}\n" + 'LEDGER {"agent":"dev","verdict":"BLOCKED"}\n'))
check("a BLOCKED dev report needs no SHA", r.returncode == 0, r.stderr)
r = append('LEDGER {"agent":"docs","verdict":"NO_DOC_CHANGE_NEEDED"}', report("docsshort.md", "ok\n"))
check("docs reports are still checked for placeholders", r.returncode != 0 and "placeholder" in r.stderr, r.stderr)
r = append(reviewer("db", "PASS"), REVIEW_REPORT)
check("reviewer reports keep the old validation (db in review mode)", r.returncode == 0, r.stderr)
r = append(reviewer("code-review", "PASS"), REVIEW_REPORT)
check("reviewer reports keep the old validation", r.returncode == 0, r.stderr)
check("status still works on the extended ledger", ledger("status").returncode == 0)

r = ledger("save-report", "--task", "T1.1", "--agent", "security", "--stdin", stdin="# Security\nPASS é\r\n")
path = os.path.join(REPORTS, "T1.1-security-r1.md")
check("save-report writes <task>-<agent>-r1 from stdin and prints the path",
      r.returncode == 0 and os.path.isfile(path) and r.stdout.strip().endswith("T1.1-security-r1.md"),
      r.stdout + r.stderr)
check("save-report keeps UTF-8 and writes LF",
      open(path, "rb").read() == "# Security\nPASS é\n".encode("utf-8"), repr(open(path, "rb").read()))
r = ledger("save-report", "--task", "T1.1", "--agent", "security", "--stdin", stdin="second\n")
check("auto round skips a file that already exists", r.returncode == 0 and r.stdout.strip().endswith("-r2.md"),
      r.stdout + r.stderr)
r = ledger("save-report", "--task", "T1.1", "--agent", "security", "--round", "1", "--stdin", stdin="other\n")
check("save-report refuses to overwrite", r.returncode != 0 and open(path, encoding="utf-8").read().startswith("# Security"),
      r.stdout + r.stderr)
r = ledger("save-report", "--task", "1", "--agent", "code-review", "--file", REVIEW_REPORT)
check("auto round follows the ledger (one code-review entry for task 1 -> r2)",
      r.returncode == 0 and r.stdout.strip().endswith("1-code-review-r2.md"), r.stdout + r.stderr)
r = ledger("save-report", "--task", "spec", "--agent", "db", "--round", "3", "--file", REVIEW_REPORT)
check("explicit round is used as given (db on the spec task is a reviewer)",
      r.returncode == 0 and r.stdout.strip().endswith("spec-db-review-r3.md"), r.stdout)
check("save-report refuses an empty report",
      ledger("save-report", "--task", "2", "--agent", "qa", "--stdin", stdin="  \n").returncode != 0)
check("save-report refuses a task id with a path",
      ledger("save-report", "--task", "../x", "--agent", "qa", "--stdin", stdin="x\n").returncode != 0)
check("save-report refuses an unknown agent",
      ledger("save-report", "--task", "2", "--agent", "nobody", "--stdin", stdin="x\n").returncode != 0)
check("save-report refuses a bad round",
      ledger("save-report", "--task", "2", "--agent", "qa", "--round", "0", "--stdin", stdin="x\n").returncode != 0)

sys.path.insert(0, os.path.dirname(LEDGER_PY))
from ledger import cited_paths

AGENTS = os.path.join(os.path.dirname(LEDGER_PY), "..", "..", "agents")


def template(agent, path):
    text = open(os.path.join(AGENTS, agent), encoding="utf-8").read()
    start = text.index("```\nCommit:") + 4
    block = text[start:text.index("```", start)]
    return re.sub(r"^Commit: <[^\n]*>$", f"Commit: {c1[:7]}", block, count=1, flags=re.MULTILINE) \
        .replace("<path>", path)


for agent, line in (("dev.md", DEV), ("db.md", 'LEDGER {"agent":"db","verdict":"DONE"}')):
    text = open(os.path.join(AGENTS, agent), encoding="utf-8").read()
    start = text.index("```\nCommit:") + 4
    raw = text[start:text.index("```", start)].replace("<path>", "src/a.py")
    r = append(line, report(f"tpl-raw-{agent}", f"{raw}\nCommitted {c1[:8]}.\n{PAD}\n{line}\n"))
    check(f"the {agent} template's unfilled Commit line is rejected as a placeholder",
          r.returncode != 0 and "placeholder" in r.stderr and "git rev-parse --short HEAD" in r.stderr, r.stderr)
    r = append(line, report(f"tpl-bad-{agent}", f"{template(agent, 'README.md')}\n{PAD}\n{line}\n"))
    check(f"the literal {agent} template: an unchanged file is rejected",
          r.returncode != 0 and "README.md" in r.stderr, r.stderr)
    r = append(line, report(f"tpl-good-{agent}", f"{template(agent, 'src/a.py')}\n{PAD}\n{line}\n"))
    check(f"the literal {agent} template: a changed file is accepted", r.returncode == 0, r.stderr)

for label in ("Files changed (from `git show --stat HEAD`, or `git diff --stat <task start>..HEAD` for several commits):",
              "**Files changed** (3):", "Files changed (2 files):", "## Files changed (2)"):
    r = append(DEV, report("paren.md", f"Committed {c1[:8]}.\n\n{label}\n- `src/a.py`\n- README.md\n\n{PAD}\n{DEV}\n"))
    check(f"a Files label with a parenthetical or count is still checked: {label[:30]}",
          r.returncode != 0 and "README.md" in r.stderr, r.stderr)

for item, expected in (("- `app/page.tsx`: now calls `lib/format.ts`", {"app/page.tsx"}),
                       ("- src/b.ts: added x", {"src/b.ts"}),
                       ("- Modify: src/c.ts", {"src/c.ts"}),
                       ("- Modify: `src/d.ts:3-9`", {"src/d.ts"}),
                       ("- src/e.ts", {"src/e.ts"}),
                       ("- Makefile: added target", {"Makefile"}),
                       ("- modified: Makefile", {"Makefile"}),
                       ("- **Created**: docs/x.md", {"docs/x.md"}),
                       ("- `src/a.ts`, `README.md`", {"src/a.ts", "README.md"}),
                       ("- Modify: `src/f.ts`, `src/g.ts:4` and `lib/h.ts`", {"src/f.ts", "src/g.ts", "lib/h.ts"}),
                       ("- `src/i.ts` (new), `src/j.ts`: both export `k.ts`", {"src/i.ts", "src/j.ts"}),
                       ("- `src/l.ts` now uses `lib/m.ts`", {"src/l.ts"}),
                       ("- `src/n.ts`, `true`", {"src/n.ts"}),
                       ("- src/o.ts, src/p.ts", {"src/o.ts", "src/p.ts"}),
                       ("- Create: src/q.ts, src/r.ts", {"src/q.ts", "src/r.ts"}),
                       ("- Modify: src/s.ts, lib/t.ts and README.md: renamed", {"src/s.ts", "lib/t.ts", "README.md"}),
                       ("- src/u.ts, then run tests", {"src/u.ts"}),
                       ("- Makefile, src/v.ts: targets", {"Makefile", "src/v.ts"}),
                       ("- Create: app/a.ts,app/b.ts", {"app/a.ts", "app/b.ts"}),
                       ("- src/w.ts, e.g. a helper", {"src/w.ts"})):
    found = cited_paths(f"Files:\n{item}\n", files_section_only=True)
    check(f"a Files item yields its leading paths: {item}", found == expected, str(found))
r = append(DEV, report("multi.md", f"Committed {c1[:8]}.\n\nFiles changed:\n- `src/a.py`, `README.md`\n\n{PAD}\n{DEV}\n"))
check("every path of a comma-separated Files item is checked", r.returncode != 0 and "README.md" in r.stderr, r.stderr)

short = "Nothing in this task changes documented behavior."
r = append('LEDGER {"agent":"docs","verdict":"NO_DOC_CHANGE_NEEDED"}',
           report("nodoc.md", short + '\nLEDGER {"agent":"docs","verdict":"NO_DOC_CHANGE_NEEDED"}\n'))
check("NO_DOC_CHANGE_NEEDED with a 40+ character reason is accepted", r.returncode == 0, r.stderr)
r = append('LEDGER {"agent":"dev","verdict":"BLOCKED"}',
           report("blockedshort.md", "Blocked: the RPC signature is missing from the approved plan.\n" + 'LEDGER {"agent":"dev","verdict":"BLOCKED"}\n'))
check("BLOCKED with a short concrete reason is accepted", r.returncode == 0, r.stderr)
for name, body in (("tiny.md", "Blocked, no access."), ("ph.md", "placeholder placeholder placeholder placeholder TODO")):
    r = append('LEDGER {"agent":"dev","verdict":"BLOCKED"}',
               report(name, body + '\nLEDGER {"agent":"dev","verdict":"BLOCKED"}\n'))
    check(f"BLOCKED with a reason under 40 characters or a placeholder is rejected ({name})",
          r.returncode != 0 and "placeholder" in r.stderr, r.stderr)
r = append(DEV, report("doneshort.md", f"Committed {c1[:8]}.\n{short}\n{DEV}\n"))
check("DONE still needs 200 characters", r.returncode != 0 and "200" in r.stderr, r.stderr)

DB_DONE = 'LEDGER {"agent":"db","verdict":"DONE"}'
impl = ledger("save-report", "--task", "7", "--agent", "db", "--role", "implementer", "--stdin",
              stdin=f"Committed {c1}.\nFiles changed:\n- `src/a.py`\n\n{PAD}\n{DB_DONE}\n")
check("db implementer report r1", impl.returncode == 0 and impl.stdout.strip().endswith("7-db-r1.md"), impl.stdout + impl.stderr)
append(DB_DONE, impl.stdout.strip(), task="7")
r = ledger("save-report", "--task", "7", "--agent", "db", "--stdin", stdin="review\n")
check("save-report refuses db without --role outside the spec task", r.returncode != 0 and "--role" in r.stderr, r.stderr)
r = ledger("save-report", "--task", "7", "--agent", "db", "--role", "reviewer", "--stdin", stdin="review\n")
check("the first db review after an implementer round is review r1, in its own file name",
      r.returncode == 0 and r.stdout.strip().endswith("7-db-review-r1.md"), r.stdout + r.stderr)
append(reviewer("db", "PASS"), r.stdout.strip(), task="7")
check("the ledger round of that review is 1", entries()[-1].get("round") == 1, json.dumps(entries()[-1]))
r = ledger("save-report", "--task", "7", "--agent", "db", "--role", "implementer", "--stdin", stdin="fix\n")
check("the next db implementer report is r2", r.returncode == 0 and r.stdout.strip().endswith("7-db-r2.md"), r.stdout)
r = ledger("save-report", "--task", "7", "--agent", "security", "--role", "implementer", "--stdin", stdin="x\n")
check("--role must fit the agent", r.returncode != 0, r.stdout)
r = ledger("save-report", "--task", "7", "--agent", "security", "--stdin", stdin="x\n")
check("the role is inferred for single-role agents", r.returncode == 0 and r.stdout.strip().endswith("7-security-r1.md"),
      r.stdout + r.stderr)

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
