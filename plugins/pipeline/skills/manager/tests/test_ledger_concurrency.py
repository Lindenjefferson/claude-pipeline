import os, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER_PY = os.path.join(HERE, "..", "ledger.py")
repo = tempfile.mkdtemp(prefix="ledgerconcurrency_")
os.makedirs(repo, exist_ok=True)
LEDGER = os.path.join(repo, ".superpowers", "ledger.jsonl")
REPORTS = os.path.join(repo, ".superpowers", "reports")
AGENTS = ("code-review", "code-review", "code-review", "design", "audit", "qa", "security", "design")
ROUNDS = 5
results = []

sys.path.insert(0, os.path.join(HERE, ".."))
from ledger import read_sums, report_file_problems


def sh(*args):
    return subprocess.run(args, cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def ledger(*args, stdin=""):
    return subprocess.run([sys.executable, LEDGER_PY, "--ledger", LEDGER, *args], cwd=repo, capture_output=True,
                          input=stdin, encoding="utf-8")


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS" if ok else "FAIL"), name, "" if ok else f"| {detail[:400]}")


def body(marker):
    return f"# {marker}\n\n" + f"{marker} finding line with enough text to take a moment to write.\n" * 400


sh("git", "init", "-q")
sh("git", "config", "user.email", "t@t.com")
sh("git", "config", "user.name", "t")
sh("git", "commit", "-q", "--allow-empty", "-m", "base")
base = sh("git", "rev-parse", "HEAD")
sh("git", "commit", "-q", "--allow-empty", "-m", "task")
ledger("start", "--slug", "x", "--base", base)
os.makedirs(os.path.join(repo, "in"))

all_ok = True
for round_number in range(ROUNDS):
    task = f"T{round_number}"
    processes = []
    for index, agent in enumerate(AGENTS):
        marker = f"MARK-{round_number}-{index}"
        source = os.path.join(repo, "in", f"{marker}.md")
        with open(source, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body(marker))
        processes.append((marker, subprocess.Popen(
            [sys.executable, LEDGER_PY, "--ledger", LEDGER, "save-report", "--task", task, "--agent", agent,
             "--from", base, "--file", source], cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8")))
    outcomes = [(marker, process.communicate(), process.returncode) for marker, process in processes]
    failed = [(marker, err) for marker, (_, err), code in outcomes if code != 0]
    refs = {marker: out.strip() for marker, (out, _), code in outcomes if code == 0}
    path = os.path.join(REPORTS, f"{task}.md")
    problems = report_file_problems(path)
    sections = read_sums(path) or []
    mixed = []
    for marker, ref in refs.items():
        shown = ledger("show-report", ref).stdout
        others = [m for m in refs if m != marker and m + " " in shown]
        if f"{marker} finding line" not in shown or others or shown.count(" finding line") != 400:
            mixed.append(marker)
    ok = (not failed and len(set(refs.values())) == len(AGENTS) and not problems
          and len(sections) == len(AGENTS) and not mixed and not os.path.exists(path + ".lock"))
    all_ok = all_ok and ok
    check(f"round {round_number + 1}: {len(AGENTS)} concurrent save-report calls on one task keep the file intact",
          ok, f"failed={failed} refs={len(set(refs.values()))} problems={problems} sections={len(sections)} "
              f"mixed={mixed}")
anchors = sorted(section["anchor"] for section in read_sums(os.path.join(REPORTS, "T0.md")))
check("the same agent saving concurrently gets consecutive rounds",
      [a for a in anchors if a.startswith("code-review")] == ["code-review-r1", "code-review-r2", "code-review-r3"]
      and [a for a in anchors if a.startswith("design")] == ["design-r1", "design-r2"], str(anchors))
check("verify-reports stays clean", ledger("verify-reports").returncode == 0)

LOCK = os.path.join(REPORTS, "T0.md.lock")
dead = subprocess.Popen([sys.executable, "-c", "pass"])
dead.wait()
with open(LOCK, "w") as handle:
    handle.write(f"{dead.pid} {time.time():.3f}\n")
began = time.monotonic()
r = ledger("save-report", "--task", "T0", "--agent", "qa", "--from", base, "--stdin", stdin="took over")
check("a lock left by a process that died is taken over", r.returncode == 0 and time.monotonic() - began < 5
      and not os.path.exists(LOCK), r.stderr)

with open(LOCK, "w") as handle:
    handle.write(f"{os.getpid()} {time.time() - 3600:.3f}\n")
r = ledger("save-report", "--task", "T0", "--agent", "qa", "--from", base, "--stdin", stdin="took over")
check("a lock older than the stale limit is taken over", r.returncode == 0, r.stderr)

with open(LOCK, "w") as handle:
    handle.write(f"{os.getpid()} {time.time():.3f}\n")
threading.Timer(1.0, os.remove, [LOCK]).start()
began = time.monotonic()
r = subprocess.run([sys.executable, LEDGER_PY, "--ledger", LEDGER, "save-report", "--task", "T0", "--agent", "qa",
                    "--from", base, "--stdin"], cwd=repo, capture_output=True, input="waited\n", encoding="utf-8")
waited = time.monotonic() - began
check("a live lock makes save-report wait for it, then append", r.returncode == 0 and waited >= 0.9, f"{waited} {r.stderr}")
check("the file is still intact after the lock scenarios", report_file_problems(os.path.join(REPORTS, "T0.md")) == [])

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
