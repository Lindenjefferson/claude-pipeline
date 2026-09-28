import tempfile
import os, subprocess, sys, time

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pre-commit-secret-scan.py")
base = os.path.join(tempfile.gettempdir(), f"prepush_{int(time.time())}")
os.makedirs(base)
remote = os.path.join(base, "remote.git")
repo = os.path.join(base, "repo")
wt = os.path.join(base, "wt")
os.makedirs(repo)
results = []


def run(cwd, *a, check=True):
    return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True, check=check)


def check(name, ok):
    results.append(ok)
    print("PASS" if ok else "FAIL", name)


run(base, "git", "init", "-q", "--bare", remote)
run(repo, "git", "init", "-q")
for k, v in (("user.email", "t@t.com"), ("user.name", "t"), ("core.autocrlf", "false")):
    run(repo, "git", "config", k, v)
run(repo, "git", "remote", "add", "origin", remote)

r = run(repo, sys.executable, HOOK, "--install-pre-push", check=False)
check("install prints path, exit 0", r.returncode == 0 and "pre-push" in r.stdout)
hook_path = os.path.join(repo, ".git", "hooks", "pre-push")
check("hook file has marker", "secretscan-managed" in open(hook_path).read())
r = run(repo, sys.executable, HOOK, "--install-pre-push", check=False)
check("install is idempotent", r.returncode == 0)

open(os.path.join(repo, "a.txt"), "w").write("hello\n")
run(repo, "git", "add", "-A"); run(repo, "git", "commit", "-q", "-m", "clean")
r = run(repo, "git", "push", "-q", "origin", "HEAD:refs/heads/main", check=False)
check("clean first push succeeds", r.returncode == 0)

open(os.path.join(repo, "s.txt"), "w").write("password: supersecretvalue12345678\n")
run(repo, "git", "add", "-A"); run(repo, "git", "commit", "-q", "-m", "add secret")
run(repo, "git", "rm", "-q", "s.txt"); run(repo, "git", "commit", "-q", "-m", "remove secret")
r = run(repo, "git", "push", "origin", "HEAD:refs/heads/main", check=False)
check("push with secret in outgoing history is rejected", r.returncode != 0 and "Secret scan blocked" in r.stderr)
r = run(remote, "git", "log", "--oneline", "main")
check("remote did not receive the secret commits", len(r.stdout.strip().splitlines()) == 1)

run(repo, "git", "reset", "-q", "--hard", "HEAD~2")
open(os.path.join(repo, "b.txt"), "w").write("fine\n")
run(repo, "git", "add", "-A"); run(repo, "git", "commit", "-q", "-m", "fine")
r = run(repo, "git", "push", "-q", "origin", "HEAD:refs/heads/main", check=False)
check("clean push after rewriting history succeeds", r.returncode == 0)

run(repo, "git", "worktree", "add", "-q", "-b", "wtbranch", wt)
open(os.path.join(wt, "k.txt"), "w").write("token = abcdefghijklmnopqrstuv1234\n")
run(wt, "git", "add", "-A"); run(wt, "git", "commit", "-q", "-m", "wt secret")
r = run(wt, "git", "push", "origin", "wtbranch", check=False)
check("push from a worktree is rejected too", r.returncode != 0 and "Secret scan blocked" in r.stderr)

# a foreign pre-push hook is never overwritten
other = os.path.join(base, "other"); os.makedirs(other)
run(other, "git", "init", "-q")
open(os.path.join(other, ".git", "hooks", "pre-push"), "w").write("#!/bin/sh\necho mine\n")
r = run(other, sys.executable, HOOK, "--install-pre-push", check=False)
check("foreign hook is not overwritten", r.returncode == 2 and "mine" in open(os.path.join(other, ".git", "hooks", "pre-push")).read())

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
