import atexit, json, os, shutil, stat, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "pre-commit-secret-scan.py")
base = tempfile.mkdtemp(prefix="hook151_")


def cleanup():
    def retry(func, path, _):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except OSError:
            pass
    shutil.rmtree(base, onerror=retry)


atexit.register(cleanup)
repo = os.path.join(base, "repo")
husky = os.path.join(base, "husky")
remote = os.path.join(base, "remote.git")
os.makedirs(repo)
os.makedirs(husky)
GLOBAL = os.path.join(base, "global.gitconfig")
open(GLOBAL, "w").close()
os.environ["GIT_CONFIG_GLOBAL"] = GLOBAL
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
os.environ["XDG_CONFIG_HOME"] = os.path.join(base, "xdg")
for name in ("X", "GIT_WORK_TREE", "GIT_DIR", "UNSET_KEY", "k"):
    os.environ.pop(name, None)
results = []


def sh(cwd, *a):
    return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=True).stdout.strip()


def hook_run(command, tool, cwd):
    payload = json.dumps({"tool_name": tool, "tool_input": {"command": command}, "cwd": cwd})
    r = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True, encoding="utf-8",
                       cwd=cwd, env=dict(os.environ, PWD=cwd))
    reason = json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"] if r.stdout.strip() else ""
    return ("DENY" if r.stdout.strip() else "ALLOW"), reason, r.stderr


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("PASS" if ok else "FAIL", name, "" if ok else f"| {str(detail)[-400:]}")


def expect(command, expected, reason_has=None, tool="Bash", cwd=repo):
    got, reason, stderr = hook_run(command, tool, cwd)
    ok = got == expected and (reason_has is None or reason_has in reason)
    where = "husky" if cwd == husky else "repo"
    check(f"[{tool}@{where}] {command} -> {expected}", ok, f"got {got}: {reason} {stderr}")


for folder in (repo, husky):
    sh(folder, "git", "init", "-q", "-b", "main")
    for k, v in (("user.email", "t@t.com"), ("user.name", "t"), ("core.autocrlf", "false")):
        sh(folder, "git", "config", k, v)
sh(husky, "git", "config", "core.hooksPath", ".husky")

for command in ("git config remote.origin.prune true", "git config remote.origin.pruneTags true",
                "git config remote.origin.tagOpt --no-tags", "git config remote.origin.skipDefaultUpdate true",
                "git config remote.origin.skipFetchAll true", "git config remote.origin.mirror true",
                "git config remote.pushDefault origin", "git config set remote.origin.prune true",
                "git config --unset remote.origin.prune", "git config --local remote.upstream.tagopt --tags",
                "git -c remote.origin.prune=true fetch --dry-run"):
    expect(command, "ALLOW")
for command in ("git config remote.origin.url /tmp/x", "git config remote.origin.pushurl x",
                "git config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'",
                "git config remote.origin.push refs/heads/main", "git config remote.origin.uploadpack x",
                "git config remote.origin.receivepack x", "git config remote.origin.proxy http://p",
                "git config remote.origin.vcs x", "git config --add remote.origin.fetch x",
                "git config set remote.origin.url x", "git config --unset remote.origin.url",
                "git config --rename-section remote.origin remote.other", "git config --remove-section remote.origin",
                "git config rename-section remote.origin remote.other", "git config remove-section remote.origin",
                "git config --rename-section evil core", "git config --remove-section url.x"):
    expect(command, "DENY", reason_has="git settings")

for command in ("git config user.name core", "git config --global alias.r remote", "git config user.name pipeline",
                "git config user.name remote.origin.url", "git config set user.name include",
                "git config alias.hp 'config --get core.hooksPath'"):
    expect(command, "ALLOW")
for command in ("git config core.hooksPath /evil", "git config --global core.hooksPath x",
                "git config pipeline.gate false", "git config url.x.insteadOf y", "git config include.path x",
                "git config --type bool pipeline.gate false", "git config --weird user.name core",
                "git config core.hooksPath --show-origin", "git config -zt bool pipeline.gate false"):
    expect(command, "DENY", reason_has="git settings")

for command in ("git config get --show-names --all remote.origin.url", "git config get --show-origin remote.origin.url",
                "git config --get remote.origin.url", "git config --get-regexp remote",
                "git config list --show-names"):
    expect(command, "ALLOW")
expect("git config set --show-names remote.origin.url x", "DENY")

FIND = "Exclude .git"
for command in ("find . \\( -name '*.bak' -o -name '*.orig' \\) -delete",
                "find . \\( -name '*.bak' -o -name '*.orig' \\) -type f -delete",
                "find . -type f \\( -name '*.bak' -o \\( -name '*.orig' -size +1k \\) \\) -delete",
                "find . -type d -empty -name build -delete",
                "find . -empty -type d -not -path './.git/*' -delete",
                "find . -mtime +3 -name '*.log' -delete"):
    expect(command, "ALLOW")
for command in ("find . -empty -delete", "find . \\( -name '*.bak' -o -name 'pre-*' \\) -delete",
                "find . \\( -name '*.bak' -o -type f \\) -delete", "find . -type f -delete",
                "find . -mtime +3 -delete", "find . -newer x -size +1k -delete",
                "find . \\( -name '*.bak' -o -name '*.orig' \\) -o -delete",
                "find . ! \\( -name '*.bak' -o -name '*.orig' \\) -delete"):
    expect(command, "DENY", reason_has=FIND)

for command in ('node -e "console.log(process.argv[1])" --no-verify',
                'python -c "import sys; print(sys.argv)" --no-verify',
                "perl -e 'print 1' --no-verify", "bash -c 'echo hi' _ --no-verify"):
    expect(command, "ALLOW")
for command in ("node -e \"require('child_process').execSync('git commit --no-verify')\"",
                "bash -c 'git commit \"$@\"' _ --no-verify -m x", "sh -c 'git push $1' _ --no-verify",
                "perl -e 'print 1' -e 'system(\"git commit --no-verify\")'",
                "cmd /c git commit --no-verify -m x"):
    expect(command, "DENY")
expect("pwsh -Command git commit --no-verify -m x", "DENY", tool="PowerShell")

for command in ('cp "$(git rev-parse --git-dir)/COMMIT_EDITMSG" msg.txt',
                'cp -r "$(git rev-parse --git-dir)/hooks" backup/',
                'rsync -a "$(git rev-parse --git-dir)/info/" backup/',
                'rm -f "$(git rev-parse --git-dir)/index.lock"',
                'rm -f "$(git rev-parse --absolute-git-dir)/HEAD.lock"',
                'rm -f "$(git rev-parse --git-common-dir)/packed-refs.lock"',
                'd=$(git rev-parse --git-dir); rm -f "$d/index.lock"'):
    expect(command, "ALLOW")
for command in ('Copy-Item "$(git rev-parse --git-dir)/COMMIT_EDITMSG" msg.txt',
                'Copy-Item -Path "$(git rev-parse --git-dir)/COMMIT_EDITMSG" -Destination msg.txt',
                'Remove-Item "$(git rev-parse --git-dir)/index.lock"'):
    expect(command, "ALLOW", tool="PowerShell")
GIT_DERIVED = "git worktree list"
for command in ('cp msg.txt "$(git rev-parse --git-dir)/COMMIT_EDITMSG"',
                'mv "$(git rev-parse --git-dir)/COMMIT_EDITMSG" msg.txt',
                'rm -f "$(git rev-parse --git-dir)/hooks/x.lock"',
                'rm -f "$(git rev-parse --git-dir)/*.lock"',
                'rm -f "$(git rev-parse --git-dir)/config"',
                'rm -f "$(git rev-parse --git-path hooks)/index.lock"',
                'rm -f "$(dirname "$(git rev-parse --git-dir)")/index.lock"',
                'rm -f "$(git rev-parse --git-dir)/../index.lock"',
                'echo x > "$(git rev-parse --git-dir)/index.lock"',
                'touch "$(git rev-parse --git-dir)/index.lock"'):
    expect(command, "DENY", reason_has=GIT_DERIVED)
expect('Copy-Item msg.txt "$(git rev-parse --git-dir)/COMMIT_EDITMSG"', "DENY", reason_has=GIT_DERIVED,
       tool="PowerShell")

expect('y=$(echo "$x"); x=$(git rev-parse --git-dir); rm -rf "$y"/dist', "ALLOW")
expect('y=$x; x=$(git rev-parse --git-dir); rm -rf "$y"/dist', "ALLOW")
for command in ('x=$(git rev-parse --git-dir); y=$(echo "$x"); rm -rf "$y"/dist',
                'x=$(git rev-parse --git-dir); y=$x; rm -rf "$y"',
                'x=$(git rev-parse --git-dir); y=$x; x=build; rm -rf "$y"/hooks',
                'x=$(git rev-parse --git-dir) y=$(echo "$x"); rm -rf "$y"/dist',
                'x=$(git rev-parse --git-dir); echo $(rm -rf "$x"/dist)'):
    expect(command, "DENY", reason_has=GIT_DERIVED)
expect("$y = \"$x\"; $x = git rev-parse --git-dir; Remove-Item \"$y/dist\" -Recurse", "ALLOW", tool="PowerShell")
expect("$x = git rev-parse --git-dir; $y = \"$x\"; Remove-Item \"$y/dist\" -Recurse", "DENY",
       reason_has=GIT_DERIVED, tool="PowerShell")

UNKNOWN_CWD = "cannot resolve"
for command in ('cd "$GIT_WORK_TREE/.." && rm -rf .git/modules/sub/hooks',
                'cd "$X" && echo x > .git/modules/s/config', 'cd "$X" && rm -rf sub/.git',
                'cd "$(pwd)/x" && rm -rf .git/modules/s/hooks'):
    expect(command, "DENY", reason_has=UNKNOWN_CWD)
expect('cd "$X" && rm -rf .husky', "DENY", reason_has=UNKNOWN_CWD, cwd=husky)
expect('cd "$X" && rm -f .husky/pre-commit', "DENY", reason_has=UNKNOWN_CWD, cwd=husky)
expect("Set-Location $env:X; Remove-Item .git/modules/s/hooks -Recurse", "DENY", reason_has=UNKNOWN_CWD,
       tool="PowerShell")
for command in ('cd "$X" && rm -rf dist', 'cd "$X" && rm -f .gitignore', 'cd "$X" && rm -rf .github/x',
                'cd "$X" && rm -rf .husky', 'cd "$X" && cat .git/config'):
    expect(command, "ALLOW")
expect('cd "$X" && rm -rf dist', "ALLOW", cwd=husky)
expect('cd "$X" && rm -rf src/.husky', "ALLOW", cwd=husky)
expect("rm -rf .husky", "DENY", cwd=husky)

for command in ("k=core.hooksPath; git config $k /evil", "git config $(echo core.hooksPath) /evil",
                "git config `echo core.hooksPath` /evil", "git config core.$(echo hooksPath) /evil",
                "git config set $(echo core.hooksPath) /evil", 'git config "$UNSET_KEY" x',
                "k=pipeline.gate; git config --unset $k", "k=core.hooksPath; git config set ${k} /evil",
                "k=remote.origin.url; git config $k /tmp/x"):
    expect(command, "DENY", reason_has="git settings")
for command in ('k=user.name; git config $k "X"', "git config --get $UNSET_KEY", "k=user.name; git config set $k X",
                "k=remote.origin.prune; git config $k true"):
    expect(command, "ALLOW")
expect("$k = 'user.name'; git config $k X", "ALLOW", tool="PowerShell")
expect("$k = 'core.hooksPath'; git config $k /evil", "DENY", reason_has="git settings", tool="PowerShell")
expect("git config $env:UNSET_KEY /evil", "DENY", reason_has="git settings", tool="PowerShell")

for command in ("Get-ChildItem .git/hooks | Remove-Item", "gci .git | Remove-Item -Recurse -Force",
                "Get-ChildItem -Path .git/hooks -Filter pre-* | Remove-Item",
                "Get-Item .git/config | Set-Content -Value x", "ls .git/hooks | Move-Item -Destination x",
                "dir .git\\hooks | Out-File x", "Get-ChildItem .git/hooks | ForEach-Object { Remove-Item $_ }"):
    expect(command, "DENY", tool="PowerShell")
expect("Get-ChildItem .husky | Remove-Item", "DENY", tool="PowerShell", cwd=husky)
for command in ("$d = git rev-parse --git-path hooks; Get-ChildItem $d | Remove-Item",
                "$d = git rev-parse --git-dir; Get-ChildItem $d | Remove-Item -Recurse",
                "1 | ForEach-Object { $d = git rev-parse --git-path hooks }; Remove-Item $d -Recurse",
                "Get-ChildItem x | ForEach-Object { $d = git rev-parse --git-path hooks; Remove-Item $d/pre-push }"):
    expect(command, "DENY", reason_has=GIT_DERIVED, tool="PowerShell")
for command in ("Get-ChildItem src/hooks | Remove-Item", "Get-ChildItem *.bak | Remove-Item",
                "Get-ChildItem .git/hooks | Select-Object Name", "Get-ChildItem -Recurse -Filter *.log | Remove-Item",
                "Get-ChildItem dist | Remove-Item -Recurse",
                "1 | ForEach-Object { $d = 'build' }; Remove-Item $d -Recurse"):
    expect(command, "ALLOW", tool="PowerShell")

sh(base, "git", "init", "-q", "--bare", remote)
os.makedirs(os.path.join(repo, "docs", "quality-reports"))
with open(os.path.join(repo, "docs", "quality-reports", "r.txt"), "w") as handle:
    handle.write("report\n")
sh(repo, "git", "add", "-A")
sh(repo, "git", "commit", "-q", "-m", "gated")
sh(repo, "git", "remote", "add", "origin", remote)
sh(repo, "git", "branch", "side")
sh(repo, "git", "switch", "-q", "side")
with open(os.path.join(repo, "side.txt"), "w") as handle:
    handle.write("side\n")
sh(repo, "git", "add", "side.txt")
sh(repo, "git", "commit", "-q", "-m", "side")
sh(repo, "git", "switch", "-q", "main")
common = os.path.join(repo, sh(repo, "git", "rev-parse", "--git-common-dir"))
with open(os.path.join(common, "gate-approved"), "w") as handle:
    handle.write(sh(repo, "git", "rev-parse", "HEAD^{tree}") + "\n")
expect("git push origin main", "ALLOW")
expect("git push", "ALLOW")
sh(repo, "git", "config", "remote.origin.mirror", "true")
expect("git push", "DENY", reason_has="gate agent")
expect("git -c remote.origin.mirror=false push", "ALLOW")
sh(repo, "git", "config", "--unset", "remote.origin.mirror")
expect("git -c remote.origin.mirror=true push", "DENY", reason_has="gate agent")

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
