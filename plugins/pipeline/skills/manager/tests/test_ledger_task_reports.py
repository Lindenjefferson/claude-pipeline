import hashlib, json, os, subprocess, sys, tempfile, time

LEDGER_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ledger.py")
repo = os.path.join(tempfile.gettempdir(), f"ledgertaskreports_{int(time.time() * 1000)}")
os.makedirs(os.path.join(repo, "src"))
LEDGER = os.path.join(repo, ".superpowers", "ledger.jsonl")
TASK_FILE = os.path.join(repo, ".superpowers", "reports", "1.md")
PAD = "The change follows the brief and the tests pass. " * 6
ZERO = {"critical": 0, "important": 0, "minor": 0}
results = []


def sh(*args):
    return subprocess.run(args, cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def ledger(*args, stdin=None, path=LEDGER):
    return subprocess.run([sys.executable, LEDGER_PY, "--ledger", path, *args], cwd=repo,
                          capture_output=True, input=stdin, encoding="utf-8")


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS" if ok else "FAIL"), name, "" if ok else f"| {detail[:300]}")


def save(task, agent, text, *extra, path=LEDGER):
    return ledger("save-report", "--task", task, "--agent", agent, "--from", base, "--stdin", *extra,
                  stdin=text, path=path)


def append(line, ref, task="1", path=LEDGER):
    return ledger("append", "--task", task, "--from", base, "--head", "HEAD", "--report", ref, "--line", line,
                  path=path)


def reviewer(agent, verdict="PASS"):
    return "LEDGER " + json.dumps({"agent": agent, "verdict": verdict, "new": ZERO, "open": ZERO})


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
start = json.loads(open(LEDGER, encoding="utf-8").readline())
check("start records the per-task report layout by default", start.get("report_layout") == "task", json.dumps(start))

r = ledger("save-report", "--task", "1", "--agent", "dev", "--stdin", stdin="x\n")
check("the per-task layout needs --from", r.returncode != 0 and "--from" in r.stderr, r.stderr)

dev_text = f"Committed {c1[:8]}.\n\nFiles changed:\n- `src/a.py`\n\n{PAD}\n{DEV}\n"
r = save("1", "dev", dev_text)
ref = r.stdout.strip()
check("save-report appends a section to reports/<task>.md and prints path#anchor",
      r.returncode == 0 and ref.endswith("reports/1.md#dev-r1") and os.path.isfile(TASK_FILE), r.stdout + r.stderr)
body = open(TASK_FILE, encoding="utf-8").read()
check("the section has an anchor and a heading with the range",
      body.startswith('<a id="dev-r1"></a>\n## dev r1 — ' + f"{base[:7]}..{c1[:7]}\n"), body[:120])
check("a .sums sidecar records the section", len(json.load(open(TASK_FILE + ".sums"))["sections"]) == 1)
r = append(DEV, ref)
check("append accepts path#anchor and validates the section as the implementer report", r.returncode == 0,
      r.stdout + r.stderr)
check("the entry stores the anchored reference", json.loads(open(LEDGER).read().splitlines()[-1])["report"] == ref)

bad = save("1", "dev", f"Committed {c1[:8]}.\n\nFiles changed:\n- `README.md`\n\n{PAD}\n{DEV}\n").stdout.strip()
r = append(DEV, bad)
check("implementer validation reads only its section (unlisted file in r2 rejected)",
      r.returncode != 0 and "README.md" in r.stderr and bad.endswith("#dev-r2"), r.stdout + r.stderr)

review_text = "# Code review\n\nFindings\n- none\n\n" + reviewer("code-review") + "\n"
r = save("1", "code-review", review_text)
cr_ref = r.stdout.strip()
check("a second agent appends its own section", r.returncode == 0 and cr_ref.endswith("#code-review-r1"), r.stderr)
check("append accepts the reviewer section", append(reviewer("code-review"), cr_ref).returncode == 0)
r = ledger("save-report", "--task", "1", "--agent", "db", "--role", "reviewer", "--from", base, "--stdin",
           stdin="db review\n")
check("a db review gets its own anchor", r.returncode == 0 and r.stdout.strip().endswith("#db-review-r1"), r.stdout)
db_ref = r.stdout.strip()
entry = json.loads(open(LEDGER).read().splitlines()[-1])
section = open(TASK_FILE, "rb").read()
bounds = next(s for s in json.load(open(TASK_FILE + ".sums"))["sections"] if s["anchor"] == "code-review-r1")
check("append records the sha256 of the section's bytes",
      entry.get("report_sha256") == hashlib.sha256(section[bounds["start"]:bounds["end"]]).hexdigest(), json.dumps(entry))
r = append(reviewer("design"), cr_ref)
check("append refuses a section saved for another agent", r.returncode != 0 and "#code-review-r1" in r.stderr, r.stderr)
r = append('LEDGER {"agent":"db","verdict":"DONE"}', db_ref)
check("append refuses a db review section for a db implementer line",
      r.returncode != 0 and "expected #db-r" in r.stderr, r.stderr)
r = ledger("append", "--task", "1", "--from", c1, "--head", "HEAD", "--report", cr_ref, "--line", reviewer("code-review"))
check("append refuses a section whose heading names another range",
      r.returncode != 0 and f"{base[:7]}..{c1[:7]}" in r.stderr, r.stderr)
r = save("1", "code-review", "again\n", "--round", "1")
check("an explicit round that already exists is refused", r.returncode != 0 and "already exists" in r.stderr, r.stderr)
r = append(reviewer("code-review"), TASK_FILE + "#nope")
check("append refuses an anchor that was never saved", r.returncode != 0 and "#nope" in r.stderr, r.stderr)

r = ledger("show-report", cr_ref)
check("show-report prints exactly that section", r.returncode == 0 and "# Code review" in r.stdout
      and "dev r1" not in r.stdout and "db review" not in r.stdout, r.stdout + r.stderr)
r = ledger("verify-reports")
check("verify-reports passes on an untouched file", r.returncode == 0 and "OK" in r.stdout, r.stdout + r.stderr)

pristine = open(TASK_FILE, "rb").read()
with open(TASK_FILE, "ab") as handle:
    handle.write(b"\nappended by hand\n")
r = ledger("verify-reports")
check("verify-reports flags bytes appended outside save-report", r.returncode != 0 and "bytes" in r.stdout, r.stdout)
r = save("1", "qa", "qa report\n")
check("save-report refuses to append to a file changed by hand", r.returncode != 0 and "refusing" in r.stderr, r.stderr)
open(TASK_FILE, "wb").write(pristine.replace(b"a = 2", b"a = 9").replace(b"Committed", b"Committer"))
r = ledger("verify-reports", "--json")
data = json.loads(r.stdout)
check("verify-reports flags an edited earlier section (prefix hash)",
      r.returncode != 0 and any("prefix hash" in p for p in data["problems"]), r.stdout)
r = append(reviewer("code-review"), cr_ref)
check("append refuses a reference into a tampered file", r.returncode != 0 and "prefix hash" in r.stderr, r.stderr)
open(TASK_FILE, "wb").write(pristine)
check("restoring the bytes makes it verify again", ledger("verify-reports").returncode == 0)
pristine_sums = open(TASK_FILE + ".sums", "rb").read()
forged = pristine.replace(b"- none", b"- NONE")
sums = json.loads(pristine_sums)
for item in sums["sections"]:
    item["sha256"] = hashlib.sha256(forged[:item["end"]]).hexdigest()
open(TASK_FILE, "wb").write(forged)
open(TASK_FILE + ".sums", "w").write(json.dumps(sums))
data = json.loads(ledger("verify-reports", "--json").stdout)
check("verify-reports flags a section rewritten together with its .sums (ledger sha256)",
      len(data["problems"]) == 1 and "code-review r1" in data["problems"][0] and "sha256" in data["problems"][0],
      json.dumps(data))
open(TASK_FILE, "wb").write(pristine)
open(TASK_FILE + ".sums", "wb").write(pristine_sums)
os.remove(TASK_FILE + ".sums")
r = ledger("verify-reports")
check("a missing sidecar is a problem", r.returncode != 0 and ".sums" in r.stdout, r.stdout)

OLD = os.path.join(repo, ".old", "ledger.jsonl")
os.makedirs(os.path.dirname(OLD))
with open(OLD, "w", encoding="utf-8") as handle:
    handle.write(json.dumps({"event": "start", "ts": "t", "slug": "old", "base": base}) + "\n")
r = ledger("save-report", "--task", "1", "--agent", "code-review", "--stdin", stdin="old style\n", path=OLD)
old_ref = r.stdout.strip()
check("a ledger started before 1.5.0 keeps the per-file layout",
      r.returncode == 0 and old_ref.endswith("1-code-review-r1.md"), r.stdout + r.stderr)
check("its per-file report appends as before", append(reviewer("code-review"), old_ref, path=OLD).returncode == 0)
r = ledger("verify-reports", path=OLD)
check("verify-reports accepts per-file references", r.returncode == 0, r.stdout + r.stderr)
check("status shows per-file entries", "code-review" in ledger("status", path=OLD).stdout)
r = ledger("save-report", "--task", "2", "--agent", "qa", "--from", base, "--layout", "task", "--stdin",
           stdin="forced\n", path=OLD)
check("--layout task overrides the ledger's layout", r.returncode == 0 and r.stdout.strip().endswith("2.md#qa-r1"),
      r.stdout + r.stderr)
os.remove(old_ref)
r = ledger("verify-reports", path=OLD)
check("a missing per-file report is a problem", r.returncode != 0 and "does not exist" in r.stdout, r.stdout)

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
