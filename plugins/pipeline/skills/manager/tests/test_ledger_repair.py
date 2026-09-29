import atexit, hashlib, json, os, shutil, stat, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER_PY = os.path.join(HERE, "..", "ledger.py")
sys.path.insert(0, os.path.join(HERE, ".."))
import ledger as lg

repo = tempfile.mkdtemp(prefix="ledgerrepair_")
os.makedirs(os.path.join(repo, "src"))
LEDGER = os.path.join(repo, ".superpowers", "ledger.jsonl")
REPORTS = os.path.join(repo, ".superpowers", "reports")
PAD = "The change follows the brief and the tests pass. " * 6
ZERO = {"critical": 0, "important": 0, "minor": 0}
ONE = {"critical": 0, "important": 1, "minor": 0}
results = []


def remove_tree(path):
    def writable(func, target, _):
        os.chmod(target, stat.S_IWRITE)
        func(target)
    shutil.rmtree(path, onerror=writable)


atexit.register(lambda: os.path.isdir(repo) and remove_tree(repo))


def sh(*args):
    return subprocess.run(args, cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def ledger(*args, stdin=None):
    return subprocess.run([sys.executable, LEDGER_PY, "--ledger", LEDGER, *args], cwd=repo,
                          capture_output=True, input=stdin, encoding="utf-8")


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS" if ok else "FAIL"), name, "" if ok else f"| {detail[:300]}")


def commit(files, message):
    for name in files:
        os.makedirs(os.path.dirname(os.path.join(repo, name)), exist_ok=True)
        with open(os.path.join(repo, name), "a") as handle:
            handle.write(f"{message}\n")
    sh("git", "add", ".")
    sh("git", "commit", "-q", "-m", message)
    return sh("git", "rev-parse", "HEAD")


def line(agent, verdict, counts=ZERO):
    if verdict in ("PASS", "FAIL"):
        return "LEDGER " + json.dumps({"agent": agent, "verdict": verdict, "new": counts, "open": counts})
    return "LEDGER " + json.dumps({"agent": agent, "verdict": verdict})


def record(task, agent, text, frm, verdict, counts=ZERO, scope=None):
    ref = ledger("save-report", "--task", task, "--agent", agent, "--from", frm, "--stdin",
                 stdin=text + "\n" + line(agent, verdict, counts) + "\n").stdout.strip()
    extra = ["--scope", scope] if scope else []
    return ledger("append", "--task", task, "--from", frm, "--head", "HEAD", "--report", ref,
                  "--line", line(agent, verdict, counts), *extra), ref


sh("git", "init", "-q")
sh("git", "config", "user.email", "t@t.com")
sh("git", "config", "user.name", "t")
sh("git", "config", "core.autocrlf", "false")
open(os.path.join(repo, ".gitignore"), "w").write(".superpowers/\n")
base = commit(["README.md"], "base")
ledger("start", "--slug", "x", "--base", base)
c1 = commit(["src/a.ts", "src/b.ts"], "task 1")

for label, sha_line in (("a <sha> placeholder", "Commit: <sha>"),
                        ("'see git rev-parse'", "Commit: see `git rev-parse HEAD`"),
                        ("a bare HEAD", "**Commit:** HEAD")):
    r, _ = record("1", "dev", f"{sha_line}\n\nFiles changed:\n- `src/a.ts`\n\n{PAD}", base, "DONE")
    check(f"append rejects a dev report whose SHA line is {label}",
          r.returncode != 0 and "placeholder" in r.stderr and "git rev-parse --short HEAD" in r.stderr, r.stderr)
r, _ = record("1", "dev", f"Commit: <sha> (real one below)\nCommitted {c1[:8]}.\n\nFiles changed:\n- `src/a.ts`\n\n{PAD}",
              base, "DONE")
check("a placeholder line is rejected even when a real SHA appears elsewhere", r.returncode != 0
      and "placeholder" in r.stderr, r.stderr)
r, _ = record("1", "dev", f"Head: same as r1\nCommitted {c1[:8]}; checked with `git rev-parse HEAD`.\n\n"
              f"Files changed:\n- `src/a.ts`\n\n{PAD}", base, "DONE")
check("a report whose only labelled SHA line carries no SHA is rejected", r.returncode != 0
      and "placeholder" in r.stderr and "Head: same as r1" in r.stderr, r.stderr)
for label, lines in (("prose mentioning git rev-parse",
                      f"Checked the tip with `git rev-parse HEAD` before writing.\nCommit: {c1[:7]}"),
                     ("an extra 'Head: same as r1' line", f"- **Commit:** {c1[:7]}\nHead: same as r1"),
                     ("a bulleted bold SHA label", f"+ **SHA:** {c1}"),
                     ("no labelled line at all", f"Committed {c1[:8]} after checking `git rev-parse HEAD`.")):
    check(f"the SHA check accepts a report with {label}", lg.sha_placeholder(lines) is None,
          str(lg.sha_placeholder(lines)))
r, _ = record("1", "dev", f"Checked the tip with `git rev-parse HEAD`.\nHead: same as r1\nCommit: {c1[:7]}\n\n"
              f"Files changed:\n- `src/a.ts`\n- `src/b.ts`\n\n{PAD}", base, "DONE")
check("append accepts prose about git rev-parse and a 'Head: same as r1' line next to a real Commit line",
      r.returncode == 0, r.stderr)
r, _ = record("1", "dev", f"Commit: {c1[:7]}\n\nFiles changed:\n- `src/a.ts`\n- `src/b.ts`\n\n{PAD}", base, "DONE")
check("a real short SHA on the SHA line is accepted", r.returncode == 0, r.stderr)
r, _ = record("1", "dev", "Commit: none, blocked before any change because the brief lacks the schema.", base,
              "BLOCKED")
check("a BLOCKED report is not held to the SHA line", r.returncode == 0, r.stderr)

record("1", "code-review", "## Important\n1. `src/a.ts:3` misses a check.\n", base, "FAIL", ONE)
record("1", "design", "## Minor\n- `src/b.ts:1` label\n", base, "PASS", {"critical": 0, "important": 0, "minor": 1})
c2 = commit(["src/a.ts", "src/b.ts", "docs/m.md"], "fix a, b and docs")
r, _ = record("1", "code-review", "## Findings\nnone\n", c1, "PASS", scope="fix")
check("append accepts --scope fix when the fix stays in the union of the reviewers' open findings plus docs/",
      r.returncode == 0, r.stderr)
commit(["src/c.ts"], "touch c")
r, _ = record("1", "design", "## Findings\nnone\n", c1, "PASS", scope="fix")
check("append refuses --scope fix when the fix touches a file no reviewer cites",
      r.returncode != 0 and "src/c.ts" in r.stderr, r.stderr)

task_file = os.path.join(REPORTS, "1.md")
before = open(task_file, "rb").read()
sections = lg.read_sums(task_file)
block = b'\n<a id="qa-r1"></a>\n## qa r1 \xe2\x80\x94 x..y\n\ninterrupted\n'
lg.write_sums(task_file, sections, pending={"anchor": "qa-r1", "start": len(before), "end": len(before) + len(block),
                                            "block_sha256": hashlib.sha256(block).hexdigest()})
with open(task_file, "ab") as handle:
    handle.write(block)
r = ledger("verify-reports")
check("verify-reports points at repair-reports for unrecorded trailing bytes",
      r.returncode != 0 and "repair-reports --task 1" in r.stdout, r.stdout + r.stderr)
r = ledger("save-report", "--task", "1", "--agent", "qa", "--from", c1, "--stdin", stdin="x\n")
check("save-report refuses to append and gives the same hint", r.returncode != 0 and "repair-reports" in r.stderr,
      r.stderr)
r = ledger("repair-reports", "--task", "1")
check("repair-reports without --yes shows the bytes, names the interrupted section and changes nothing",
      r.returncode != 0 and "qa-r1" in r.stdout and "interrupted" in r.stdout
      and open(task_file, "rb").read() == before + block, r.stdout + r.stderr)
r = ledger("repair-reports", "--task", "1", "--yes")
check("repair-reports --yes truncates to the last recorded section",
      r.returncode == 0 and open(task_file, "rb").read() == before and "pending" not in json.load(
          open(task_file + ".sums")), r.stdout + r.stderr)
check("verify-reports is clean after the repair", ledger("verify-reports").returncode == 0)
with open(task_file, "ab") as handle:
    handle.write(b"hand edit\n")
r = ledger("repair-reports", "--task", "1")
check("bytes not from an interrupted save are labelled as such", r.returncode != 0 and "something else" in r.stdout,
      r.stdout)
ledger("repair-reports", "--task", "1", "--yes")
data = bytearray(open(task_file, "rb").read())
data[5:6] = b"X"
open(task_file, "wb").write(bytes(data))
r = ledger("repair-reports", "--task", "1", "--yes")
check("repair-reports refuses a file whose saved sections changed", r.returncode != 0 and "prefix hash" in r.stderr,
      r.stderr)
check("repair-reports on a clean or missing file", ledger("repair-reports", "--task", "nope").returncode != 0)

lock = os.path.join(repo, "x.md.lock")
open(lock, "w").write("999999 1.000 dead\n")
check("take_over removes a stale lock it judged", lg.take_over(lock, "999999 1.000 dead\n") and not os.path.exists(lock))
open(lock, "w").write("123 9999999999.000 fresh\n")
check("take_over of a lock replaced since it was judged puts the live lock back and does not take it",
      not lg.take_over(lock, "999999 1.000 dead\n") and open(lock).read() == "123 9999999999.000 fresh\n")
check("take_over leaves no grave file behind", [n for n in os.listdir(repo) if n.endswith(".stale")] == [])
os.remove(lock)
check("take_over of a lock that is already gone is a no-op", not lg.take_over(lock, "x"))
target = os.path.join(repo, "y.md")
with lg.exclusive(target):
    open(target + ".lock", "w").write("777 9999999999.000 other\n")
check("exclusive never removes a lock that is no longer its own",
      open(target + ".lock").read() == "777 9999999999.000 other\n")
os.remove(target + ".lock")
with lg.exclusive(target):
    held = open(target + ".lock").read()
check("exclusive writes a unique token and removes its own lock", len(held.split()) == 3
      and not os.path.exists(target + ".lock"), held)

print(f"\n{'ALL PASS' if all(results) else 'FAILURES'} ({sum(results)}/{len(results)})")
sys.exit(0 if all(results) else 1)
