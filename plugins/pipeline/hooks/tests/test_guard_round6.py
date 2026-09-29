import json, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "pre-commit-secret-scan.py")
base = os.path.join(tempfile.gettempdir(), f"guardround6_{int(time.time() * 1000)}")
repo = os.path.join(base, "repo")
remote = os.path.join(base, "remote.git")
xdg = os.path.join(base, "xdg")
os.makedirs(repo)
os.makedirs(os.path.join(xdg, "git"))
GLOBAL = os.path.join(base, "global.gitconfig")
open(GLOBAL, "w").close()
os.environ["GIT_CONFIG_GLOBAL"] = GLOBAL
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
os.environ["XDG_CONFIG_HOME"] = xdg
os.environ["CLAUDE_PIPELINE_HOME"] = os.path.abspath(os.path.join(HERE, "..", ".."))
os.environ["PWD"] = repo
results = []


def sh(cwd, *a, check=True):
    return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=check)


def hook_run(command, tool="Bash"):
    payload = json.dumps({"tool_name": tool, "tool_input": {"command": command}, "cwd": repo})
    r = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True, encoding="utf-8")
    reason = json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"] if r.stdout.strip() else ""
    return ("DENY" if r.stdout.strip() else "ALLOW"), reason, r.stderr


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("PASS" if ok else "FAIL", name, "" if ok else f"| {str(detail)[-400:]}")


def expect(command, expected, reason_has=None, tool="Bash"):
    got, reason, stderr = hook_run(command, tool)
    ok = got == expected and (reason_has is None or reason_has in reason)
    check(f"[{tool}] {command} -> {expected}", ok, f"got {got}: {reason} {stderr}")


sh(base, "git", "init", "-q", "--bare", remote)
sh(repo, "git", "init", "-q", "-b", "main")
for k, v in (("user.email", "t@t.com"), ("user.name", "t"), ("core.autocrlf", "false")):
    sh(repo, "git", "config", k, v)
with open(os.path.join(repo, "a.txt"), "w") as handle:
    handle.write("a\n")
sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-q", "-m", "base")
sh(repo, "git", "remote", "add", "origin", remote)
sh(repo, "git", "push", "-q", "origin", "main")
os.makedirs(os.path.join(repo, "docs", "quality-reports"))
with open(os.path.join(repo, "docs", "quality-reports", "r.txt"), "w") as handle:
    handle.write("report\n")
sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-q", "-m", "gated")

expect("git push origin HEAD", "DENY", reason_has="gate agent")
expect("until git push origin HEAD; do sleep 1; done", "DENY", reason_has="gate agent")
expect("if git push origin HEAD; then echo pushed; fi", "DENY", reason_has="gate agent")
expect("! git push origin HEAD", "DENY", reason_has="gate agent")

for command in ("if git push --no-verify origin HEAD; then echo pushed; fi",
                "if git commit --no-verify -m x; then :; fi", "! git commit --no-verify -m x",
                "while true; do git commit -n -m x; done",
                "if true; then git config core.hooksPath /dev/null; fi",
                "while true; do git -c core.hooksPath=/dev/null commit -m x; done",
                "if true; then git remote add loop .; fi", "if true; then git config --edit; fi",
                "if true; then GIT_CONFIG_GLOBAL=/tmp/x git commit -m x; fi",
                "if false; then :; elif git commit --no-verify -m x; then :; fi",
                "if false; then :; else git push --no-verify origin HEAD; fi",
                "time ! git commit --no-verify -m x"):
    expect(command, "DENY")

with open(os.path.join(repo, "cfg.txt"), "w") as handle:
    handle.write("AWS_KEY=AKIA" "ABCDEFGHIJKLMNOP\n")
sh(repo, "git", "add", "cfg.txt")
expect("if git commit -m x; then :; fi", "DENY", reason_has="Secret scan")
expect("while ! git commit -m x; do sleep 1; done", "DENY", reason_has="Secret scan")
sh(repo, "git", "reset", "-q", "cfg.txt")
os.remove(os.path.join(repo, "cfg.txt"))

with open(os.path.join(repo, "list"), "w") as handle:
    handle.write("a.txt\n")
for command in ("if git diff --quiet; then echo clean; fi", 'while read f; do git add "$f"; done < list',
                "until git fetch; do sleep 1; done", "if true; then cat .git/config; fi",
                "if git status --short; then echo ok; fi"):
    expect(command, "ALLOW")

for command in ('cd "$(dirname "$(git rev-parse --git-path hooks/pre-push)")" && rm -f pre-push',
                'cd "$(dirname "$(git rev-parse --git-path hooks/x)")" && echo x > pre-push',
                'cd "$(dirname "$(git rev-parse --git-path config)")" && rm -f hooks/pre-push',
                'cd "$(git rev-parse --git-path hooks)/.." && rm -f hooks/pre-push',
                'h=$(git rev-parse --git-path hooks); cd "$h/.." && rm -f hooks/pre-push',
                'h=$(dirname "$(git rev-parse --git-path hooks/pre-push)"); rm -rf "$h"',
                'root=$(dirname "$(git rev-parse --git-common-dir)"); rm -rf "$root"',
                'for d in $(git rev-parse --git-dir); do rm -rf "$d"; done',
                'for h in $(git rev-parse --git-path hooks); do rm -f "$h/pre-push"; done'):
    expect(command, "DENY")
for command in ("Set-Location (Split-Path (git rev-parse --git-path hooks/pre-push)); Remove-Item pre-push",
                "$h = (Split-Path (git rev-parse --git-path hooks/pre-push)); Remove-Item -Recurse $h",
                "$h = Split-Path (git rev-parse --git-path hooks/pre-push); Remove-Item -Recurse $h",
                "$global:d = git rev-parse --git-dir; Remove-Item -Recurse $global:d",
                "$script:d = (git rev-parse --git-dir); Remove-Item -Recurse $script:d",
                "$local:d = '.git/hooks'; Remove-Item -Recurse $local:d",
                "$global:d = git rev-parse --git-dir; Remove-Item -Recurse $d"):
    expect(command, "DENY", tool="PowerShell")

for command in ('cd "$(dirname "$(git rev-parse --git-dir)")" && rm -rf dist',
                'root=$(dirname "$(git rev-parse --git-common-dir)"); cd "$root" && rm -rf dist',
                'd=$(git rev-parse --git-dir); cd "$d/.." && rm -rf dist',
                'for f in *.bak; do rm -f "$f"; done', 'for f in a b; do echo "$f" > out.log; done'):
    expect(command, "ALLOW")
for command in ("Set-Location (Split-Path (git rev-parse --git-common-dir)); Remove-Item dist -Recurse",
                "$root = Split-Path (git rev-parse --git-common-dir); Set-Location $root; Remove-Item dist -Recurse",
                "$root = (Split-Path (git rev-parse --git-common-dir)); Set-Location $root; "
                "Remove-Item dist -Recurse",
                "$global:f = 'dist'; Remove-Item -Recurse $global:f"):
    expect(command, "ALLOW", tool="PowerShell")

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
