import json, os, subprocess, sys, tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pre-commit-secret-scan.py")
base = tempfile.mkdtemp(prefix="hooktest_")
os.makedirs(base, exist_ok=True)
repo = base


def sh(*args):
    return subprocess.run(args, cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def run_hook(command):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": repo})
    r = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True)
    out = r.stdout.strip()
    if out:
        d = json.loads(out)["hookSpecificOutput"]
        return "DENY", d["permissionDecisionReason"]
    return "ALLOW", ""


results = []


def check(name, command, expected):
    got, reason = run_hook(command)
    ok = got == expected
    results.append(ok)
    print(("PASS" if ok else "FAIL"), name, "->", got, ("" if ok else "| " + reason[:200]))


sh("git", "init", "-q")
sh("git", "config", "user.email", "t@t.com")
sh("git", "config", "user.name", "t")
sh("git", "config", "core.autocrlf", "false")
open(os.path.join(repo, "a.txt"), "w").write("hello\n")
sh("git", "add", "a.txt")
sh("git", "commit", "-q", "-m", "base")
sh("git", "update-ref", "refs/remotes/origin/master", "HEAD")

# commit cases
open(os.path.join(repo, "cfg.txt"), "w").write("AWS_KEY=AKIAABCDEFGHIJKLMNOP\n")
sh("git", "add", "cfg.txt")
check("commit with staged AWS key", "git commit -m x", "DENY")
sh("git", "reset", "-q")
open(os.path.join(repo, ".env"), "w").write("X=1\n")
sh("git", "add", ".env")
check("commit with staged .env", "git commit -m x", "DENY")
sh("git", "reset", "-q")
sh("git", "rm", "-q", "--cached", ".env") if False else None
os.remove(os.path.join(repo, ".env"))
os.remove(os.path.join(repo, "cfg.txt"))
open(os.path.join(repo, "clean.js"), "w").write("console.log(1)\n")
sh("git", "add", "clean.js")
check("commit clean", "git commit -m x", "ALLOW")
os.environ["HOOKTEST_REPO"] = repo
check("cd through a set env var", 'cd "$HOOKTEST_REPO" && git commit -m x', "ALLOW")
check("cd through an unset env var", 'cd "$HOOKTEST_UNSET_VAR" && git commit -m x', "DENY")
check("cd through command substitution", 'cd "$(pwd)" && git commit -m x', "DENY")
check("cd through a single-quoted literal $", "cd '$HOOKTEST_REPO' && git commit -m x", "DENY")
sh("git", "commit", "-q", "-m", "clean")
sh("git", "update-ref", "refs/remotes/origin/master", "HEAD")

# commit -a picks up unstaged tracked changes
open(os.path.join(repo, "a.txt"), "w").write("token = abcdefghijklmnopqrstuv1234\n")
check("commit -am with unstaged secret", 'git commit -am "x"', "DENY")
check("commit (no -a) ignores unstaged secret", 'git commit -m "x"', "ALLOW")
sh("git", "checkout", "-q", "--", "a.txt")

# push cases: nothing unpushed, not opted in
check("push nothing unpushed, not opted in", "git push", "ALLOW")

# unpushed commit that adds then removes a secret (history leak)
open(os.path.join(repo, "s.txt"), "w").write("password: supersecretvalue12345678\n")
sh("git", "add", "s.txt")
sh("git", "commit", "-q", "-m", "add secret")
sh("git", "rm", "-q", "s.txt")
sh("git", "commit", "-q", "-m", "remove secret")
check("push with secret in unpushed history", "git push origin master", "DENY")
sh("git", "reset", "-q", "--hard", "refs/remotes/origin/master")

# clean unpushed commit, not opted in -> allow
open(os.path.join(repo, "b.js"), "w").write("console.log(2)\n")
sh("git", "add", "b.js")
sh("git", "commit", "-q", "-m", "b")
check("push clean, not opted in", "git push", "ALLOW")
check("push --dry-run always allowed", "git push --dry-run", "ALLOW")

# opt in with docs/quality-reports
os.makedirs(os.path.join(repo, "docs", "quality-reports"))
open(os.path.join(repo, "docs", "quality-reports", ".gitkeep"), "w").write("")
sh("git", "add", "docs")
sh("git", "commit", "-q", "-m", "opt in")
check("push opted in, no approval", "git push", "DENY")
check("push opted in, -C form, no approval", f'git -C "{repo}" push', "DENY")
check("push opted in, dry-run", "git push -n", "ALLOW")
tree = sh("git", "rev-parse", "HEAD^{tree}")
common = os.path.abspath(os.path.join(repo, sh("git", "rev-parse", "--git-common-dir")))
with open(os.path.join(common, "manager-approved"), "a") as f:
    f.write(f"{tree} {sh('git', 'rev-parse', 'HEAD')} test\n")
check("push opted in, tree approved", "git push", "ALLOW")
open(os.path.join(repo, "c.js"), "w").write("console.log(3)\n")
sh("git", "add", "c.js")
sh("git", "commit", "-q", "-m", "after approval")
check("push after new commit needs new approval", "git push", "DENY")

# non-git commands and non-repo dirs
check("unrelated command", "ls -la", "ALLOW")

# a worktree outside the repo folder is scanned like the repo itself
worktree = base + "-wt-outside"
sh("git", "worktree", "add", "-q", "-b", "wtbranch2", worktree)
repo = worktree
open(os.path.join(repo, "cfg.txt"), "w").write("AWS_KEY=AKIAABCDEFGHIJKLMNOP\n")
sh("git", "add", "cfg.txt")
check("worktree outside the repo folder is scanned", "git commit -m x", "DENY")
print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
