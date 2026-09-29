import json, os, subprocess, sys, tempfile, time

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
ledger("start", "--slug", "x", "--base", base)

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
r = append(DEV, unlisted, extra=("--allow-unlisted",))
check("--allow-unlisted works without a reason", r.returncode == 0, r.stderr)
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
check("explicit round is used as given", r.returncode == 0 and r.stdout.strip().endswith("spec-db-r3.md"), r.stdout)
check("save-report refuses an empty report",
      ledger("save-report", "--task", "2", "--agent", "qa", "--stdin", stdin="  \n").returncode != 0)
check("save-report refuses a task id with a path",
      ledger("save-report", "--task", "../x", "--agent", "qa", "--stdin", stdin="x\n").returncode != 0)
check("save-report refuses an unknown agent",
      ledger("save-report", "--task", "2", "--agent", "nobody", "--stdin", stdin="x\n").returncode != 0)
check("save-report refuses a bad round",
      ledger("save-report", "--task", "2", "--agent", "qa", "--round", "0", "--stdin", stdin="x\n").returncode != 0)

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
