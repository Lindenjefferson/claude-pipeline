import os, subprocess, sys, tempfile

PACKAGE_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "package.py")
repo = tempfile.mkdtemp(prefix="packagetest_")
os.makedirs(repo, exist_ok=True)
results = []


def sh(*args):
    return subprocess.run(args, cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def package(*args):
    return subprocess.run([sys.executable, PACKAGE_PY, *args], cwd=repo, capture_output=True, text=True)


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS" if ok else "FAIL"), name, "" if ok else f"| {detail[:300]}")


def brief(task):
    out = os.path.join(repo, f"brief-{task}.md")
    r = package("brief", "--plan", "plan.md", "--task", str(task), "--out", out)
    return r, (open(out, encoding="utf-8").read() if os.path.exists(out) else "")


open(os.path.join(repo, "plan.md"), "w", encoding="utf-8").write(
    "# Plan\n\nIntro\n\n"
    "## Task 1: first\nfoo\n### Step 1\nx\n\n"
    "## Task 2: second\nbar\n### Step\ny\n```\n## Task 9 inside a fence\n```\n\n"
    "## Task 10: tenth\nten\n\n"
    "## Self-review checklist\nNOT PART OF ANY TASK\n")

r, text = brief(1)
check("brief keeps the task's own sub-headings", r.returncode == 0 and "### Step 1" in text and "x" in text, text)
check("brief stops at the next task", "Task 2" not in text, text)
r, text = brief(2)
check("brief ignores a heading inside a code fence", "## Task 9 inside a fence" in text and "Task 10" not in text, text)
r, text = brief(10)
check("brief tells Task 1 from Task 10", r.returncode == 0 and text.startswith("## Task 10"), text)
check("brief stops at a later same-level section", "NOT PART OF ANY TASK" not in text, text)
r, _ = brief(3)
check("brief fails for a task that does not exist", r.returncode != 0, r.stdout)

sh("git", "init", "-q")
sh("git", "config", "user.email", "t@t.com")
sh("git", "config", "user.name", "t")
sh("git", "config", "core.autocrlf", "false")
open(os.path.join(repo, "a.txt"), "w").write("one\n")
sh("git", "add", "a.txt")
sh("git", "commit", "-q", "-m", "base")
base = sh("git", "rev-parse", "HEAD")
open(os.path.join(repo, "secret.txt"), "w").write("KEY=added-then-removed\n")
sh("git", "add", "secret.txt")
sh("git", "commit", "-q", "-m", "add")
os.remove(os.path.join(repo, "secret.txt"))
sh("git", "rm", "-q", "--cached", "secret.txt")
sh("git", "commit", "-q", "-m", "remove")
head = sh("git", "rev-parse", "HEAD")

r = package("review", "--base", base, "--head", head, "--name", "t1-r1")
diff = os.path.join(repo, ".superpowers", "reviews", "review-t1-r1.diff")
history = os.path.join(repo, ".superpowers", "reviews", "review-t1-r1.history.patch")
check("review writes both files", r.returncode == 0 and os.path.exists(diff) and os.path.exists(history), r.stderr)
check("review reports the commit count", "2 commit(s)" in r.stdout, r.stdout)
check("final diff no longer shows the removed secret",
      "added-then-removed" not in open(diff, encoding="utf-8").read())
check("history patch still shows the removed secret",
      "added-then-removed" in open(history, encoding="utf-8").read())
check("review rejects an empty range", package("review", "--base", head, "--head", head).returncode != 0)
check("review rejects a head that is not a descendant",
      package("review", "--base", head, "--head", base).returncode != 0)
check("review rejects an unknown revision", package("review", "--base", "nope", "--head", head).returncode != 0)

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
