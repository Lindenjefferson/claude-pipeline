import json, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "pre-commit-secret-scan.py")
base = os.path.join(tempfile.gettempdir(), f"guardround7_{int(time.time() * 1000)}")
repo = os.path.join(base, "repo")
worktree = os.path.join(base, "wt")
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
results = []


def sh(cwd, *a, check=True):
    return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=check)


def hook_run(command, tool, cwd):
    payload = json.dumps({"tool_name": tool, "tool_input": {"command": command}, "cwd": cwd})
    r = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True, encoding="utf-8",
                       cwd=cwd, env=dict(os.environ, PWD=cwd))
    reason = json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"] if r.stdout.strip() else ""
    return ("DENY" if r.stdout.strip() else "ALLOW"), reason, r.stderr


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("PASS" if ok else "FAIL", name, "" if ok else f"| {str(detail)[-400:]}")


def expect(command, expected, reason_has=None, tool="Bash", cwd=worktree):
    got, reason, stderr = hook_run(command, tool, cwd)
    ok = got == expected and (reason_has is None or reason_has in reason)
    where = "wt" if cwd == worktree else "main"
    check(f"[{tool}@{where}] {command} -> {expected}", ok, f"got {got}: {reason} {stderr}")


sh(base, "git", "init", "-q", "--bare", remote)
sh(repo, "git", "init", "-q", "-b", "main")
for k, v in (("user.email", "t@t.com"), ("user.name", "t"), ("core.autocrlf", "false")):
    sh(repo, "git", "config", k, v)
with open(os.path.join(repo, "a.txt"), "w") as handle:
    handle.write("a\n")
os.makedirs(os.path.join(repo, "docs", "quality-reports"))
with open(os.path.join(repo, "docs", "quality-reports", "r.txt"), "w") as handle:
    handle.write("report\n")
sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-q", "-m", "gated")
sh(repo, "git", "remote", "add", "origin", remote)
sh(repo, "git", "worktree", "add", "-q", "-b", "feature", worktree)
git_dir = sh(worktree, "git", "rev-parse", "--absolute-git-dir").stdout.strip().replace("\\", "/")
check("worktree git dir is under the common git dir", "/.git/worktrees/" in git_dir, git_dir)

for command in ('cd "$(git rev-parse --git-dir)/../../hooks" && rm -f pre-push',
                'cd "$(dirname "$(git rev-parse --git-dir)")" && rm -rf ../hooks',
                'cd "$(git rev-parse --git-dir)/.." && rm -f ../hooks/pre-push',
                'cd "$(git rev-parse --git-dir)/.." && echo x > ../hooks/pre-push',
                'cd "$(git rev-parse --git-dir)/.." && rm -rf ../config',
                'd=$(git rev-parse --absolute-git-dir); cd "$d/.." && rm -f ../hooks/pre-push',
                'cd "$(git rev-parse --git-common-dir)/.." && rm -f .git/hooks/pre-push',
                'cd "$(git rev-parse --git-common-dir)/../.." && rm -rf x',
                'cd "$(git rev-parse --git-common-dir)/../x" && rm -rf y',
                'cd "$(git rev-parse --git-common-dir)/../../hooks" && rm -f pre-push',
                'cd "$(git rev-parse --git-common-dir)/.." && rm -rf ../hooks',
                'root=$(dirname "$(git rev-parse --git-common-dir)"); cd "$root" && echo x > ../hooks/pre-push',
                'cd "$GIT_DIR/.." && rm -rf dist',
                'root=$(dirname "$(git rev-parse --git-common-dir)"); rm -rf "$root"',
                'root=$(dirname "$(git rev-parse --git-common-dir)"); rm -f "$root/.git/hooks/pre-push"',
                'r=$(dirname "$(git rev-parse --git-common-dir)"); rm -rf "$r/.git"',
                'r=$(dirname "$(git rev-parse --git-common-dir)"); rm -rf "$r"/.git',
                'r=$(dirname "$(git rev-parse --git-common-dir)"); x="$r/../y"; rm -rf "$x"',
                "coproc git push origin HEAD"):
    expect(command, "DENY")
for command in ("Set-Location (Split-Path (git rev-parse --git-dir)); Remove-Item ../hooks -Recurse",
                "${h} = git rev-parse --git-path hooks; Remove-Item ${h} -Recurse",
                "${global:d} = git rev-parse --git-dir; Remove-Item -Recurse ${global:d}",
                "$root = Split-Path -Path (git rev-parse --git-common-dir) -Parent; Remove-Item $root -Recurse"):
    expect(command, "DENY", tool="PowerShell")

GIT_DERIVED = "git worktree list"
for command in ('cd "$(git rev-parse --git-common-dir)/.." && npm run build > out.log',
                'cd "$(git rev-parse --git-common-dir)/.." && npm run build',
                'root=$(dirname "$(git rev-parse --git-common-dir)"); cd "$root" && rm -rf dist',
                'cd "$(git rev-parse --path-format=absolute --git-common-dir)/.." && rm -rf dist',
                'root=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)"); cd "$root" && rm -rf dist',
                'cd "$(git -C . rev-parse --git-common-dir)/.." && rm -rf dist',
                'root=$(dirname "$(git rev-parse --git-common-dir)"); for f in "$root"/*.log; do rm -f "$f"; done',
                'root=$(dirname "$(git rev-parse --git-common-dir)"); out="$root/dist"; rm -rf "$out"',
                'cd "$(git rev-parse --git-common-dir)/.." && rm -rf sub/hooks',
                'cd "$(git rev-parse --git-common-dir)/.." && rm -f sub/.git',
                'root=$(dirname "$(git rev-parse --git-common-dir)"); rm -rf "$root/sub/hooks"',
                'pushd "$(git rev-parse --git-common-dir)/.." && rm -rf dist',
                'd=$(git rev-parse --git-dir); cd "$(dirname "$d")" && rm -f ../hooks/pre-push',
                'd=$(git rev-parse --git-dir); p=$(dirname "$d"); cd "$p" && rm -f ../hooks/pre-push',
                'd=$(git rev-parse --git-dir); rm -f "$(dirname "$d/hooks/x")/pre-push"',
                'd=.git; rm -f "$(echo $d/hooks)/pre-push"',
                'd=$(git rev-parse --git-dir); rm -f "`dirname $d/hooks/x`/pre-push"',
                'cd "$(dirname "$GIT_DIR")" && rm -rf dist', 'cd "$GIT_COMMON_DIR/.." && rm -rf dist'):
    expect(command, "DENY", reason_has=GIT_DERIVED)
for command in ("$root = Split-Path (git rev-parse --git-common-dir); Set-Location $root; Remove-Item dist -Recurse",
                "$root = Split-Path -Path (git rev-parse --git-common-dir) -Parent; Set-Location $root; "
                "Remove-Item dist -Recurse",
                "$root = Split-Path -Parent -LiteralPath (git rev-parse --git-common-dir); Set-Location $root; "
                "Remove-Item dist -Recurse",
                "$root = Split-Path (git rev-parse --git-common-dir); $out = Join-Path $root dist; "
                "Remove-Item $out -Recurse",
                "$root = Split-Path (git rev-parse --git-common-dir); $out = \"$root\\dist\"; Remove-Item $out -Recurse",
                "$d = git rev-parse --git-dir; Set-Location (Split-Path $d); Remove-Item ../hooks/pre-push",
                "$d = git rev-parse --git-dir; Remove-Item (Join-Path (Split-Path $d) hooks/pre-push)"):
    expect(command, "DENY", reason_has=GIT_DERIVED, tool="PowerShell")

got, reason, _ = hook_run('cd "$(git rev-parse --git-common-dir)/.." && rm -rf dist', "Bash", worktree)
check("the git-derived deny points to --show-toplevel and git worktree list, not the --no-verify text",
      got == "DENY" and "--show-toplevel" in reason and "git worktree list" in reason
      and "--no-verify" not in reason and "rewire" not in reason, reason)

for command in ('cd "$(git rev-parse --git-dir)/.."', 'cd "$(git rev-parse --git-dir)/.." && ls',
                'cd "$(git rev-parse --git-common-dir)/.." && git status',
                "git worktree list", "git worktree list --porcelain",
                'cd "$(git rev-parse --show-toplevel)" && rm -rf dist',
                'root=$(git rev-parse --show-toplevel); rm -rf "$root/dist"',
                "cd ../repo && rm -rf dist", "cd ../repo && npm run build > out.log",
                'cd "$(dirname src/hooks/useX.ts)" && rm -f useOld.ts',
                'tmp=$(mktemp); echo x > "$tmp"; rm -f "$tmp"', 'for f in *.bak; do rm -f "$f"; done',
                "test -f .git/hooks/pre-push && echo yes",
                "if [ -f .git/hooks/pre-push ]; then echo installed; fi",
                "[[ -f .git/hooks/pre-push ]] && echo yes"):
    expect(command, "ALLOW")
for command in ("${f} = 'dist'; Remove-Item -Recurse ${f}",
                "Set-Location (git rev-parse --show-toplevel); Remove-Item dist -Recurse",
                "$root = git rev-parse --show-toplevel; Remove-Item (Join-Path $root dist) -Recurse"):
    expect(command, "ALLOW", tool="PowerShell")

for command in ('cd "$(git rev-parse --show-toplevel)" && rm -rf dist',
                'root=$(git rev-parse --show-toplevel); rm -rf "$root/dist"', "cd ../wt && rm -rf dist"):
    expect(command, "ALLOW", cwd=repo)
for command in ('cd "$(git rev-parse --git-common-dir)/.." && rm -rf dist',
                'cd "$(git rev-parse --git-common-dir)/.." && rm -rf sub/hooks'):
    expect(command, "DENY", reason_has=GIT_DERIVED, cwd=repo)
expect("coproc git push origin HEAD", "DENY", reason_has="gate agent", cwd=repo)

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
