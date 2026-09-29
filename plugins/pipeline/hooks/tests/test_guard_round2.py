import json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "pre-commit-secret-scan.py")
base = tempfile.mkdtemp(prefix="guardround2_")
repo = os.path.join(base, "repo")
real = os.path.join(base, "real.git")
fake = os.path.join(base, "fake.git")
xdg = os.path.join(base, "xdg")
os.makedirs(repo)
os.makedirs(os.path.join(xdg, "git"))
GLOBAL = os.path.join(base, "global.gitconfig")
open(GLOBAL, "w").close()
os.environ["GIT_CONFIG_GLOBAL"] = GLOBAL
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
os.environ["XDG_CONFIG_HOME"] = xdg
os.environ["CLAUDE_PIPELINE_HOME"] = os.path.abspath(os.path.join(HERE, "..", ".."))
SECRET = "k = AKIA" + "ABCDEFGHIJKLMNOP\n"
TOKEN = "tok" + "9f8e7d6c5b4a"
results = []


def sh(cwd, *a, check=True, data=None):
    return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=check, input=data)


def hook_run(command, tool="Bash", cwd=None, script=HOOK):
    key = "file_path" if tool == "Write" else "command"
    payload = json.dumps({"tool_name": tool, "tool_input": {key: command}, "cwd": cwd or repo})
    r = subprocess.run([sys.executable, script], input=payload, capture_output=True, text=True, encoding="utf-8")
    reason = json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"] if r.stdout.strip() else ""
    return ("DENY" if r.stdout.strip() else "ALLOW"), reason, r.stderr


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("PASS" if ok else "FAIL", name, "" if ok else f"| {str(detail)[-400:]}")


def expect(name, command, expected, tool="Bash", reason_has=None):
    got, reason, stderr = hook_run(command, tool)
    ok = got == expected and (reason_has is None or reason_has in reason)
    check(f"{name} -> {expected}", ok, f"got {got}: {reason} {stderr}")


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def configure(path):
    for k, v in (("user.email", "t@t.com"), ("user.name", "t"), ("core.autocrlf", "false")):
        sh(path, "git", "config", k, v)


sh(base, "git", "init", "-q", "--bare", real)
sh(base, "git", "init", "-q", "--bare", fake)
sh(repo, "git", "init", "-q", "-b", "main")
configure(repo)
os.makedirs(os.path.join(repo, "src"))
write(os.path.join(repo, "src", "a.txt"), "base\n")
sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-q", "-m", "base")

# hook removal: forms beyond the literal .git/hooks
for command in ("rm .gi?/hooks/pre-push", "rm .git/hook*/pre-push", "rm ./.git/./hooks/pre-push",
                "rm .git//hooks/pre-push", "rm .git/x/../hooks/pre-push", "rm -f .git/*",
                "cd .git; rm hooks/pre-push", "cd .git && rm -f hooks/*", "cd .gi? && mv hooks h",
                "pushd .git && echo > hooks/pre-push", "d=.git; rm $d/hooks/pre-push",
                "rm $SOME_UNSET_DIR_X/hooks/pre-push", "find . -name pre-push -delete",
                "find . -name pre-push -exec rm {} +", "find .git -name pre-push -delete",
                "bash -c 'cd .git && rm hooks/pre-push'", "cp /dev/null .git/config*",
                "find . -name 'pre-*' -delete -not -path './.git/*'",
                "find . -not -path './.git/*' -o -name pre-push -delete",
                "find . -path ./src -prune -o -name pre-push -delete",
                "find . -not -path './src/*' -name pre-push -delete",
                "find src -name a.txt -exec cp {} .git/hooks/pre-push \\;"):
    expect(command, command, "DENY", reason_has="hooks")
expect("[PowerShell] Set-Location .git; Remove-Item hooks\\pre-push",
       "Set-Location .git; Remove-Item hooks\\pre-push", "DENY", tool="PowerShell")
expect("[PowerShell] Remove-Item .\\.git\\.\\hooks\\pre-push", "Remove-Item .\\.git\\.\\hooks\\pre-push",
       "DENY", tool="PowerShell")
for command in ("rm src/a.txt.bak", "rm -rf node_modules", "find src -name '*.pyc' -delete",
                "cd .git && cat config", "ls .git/hooks", "rm .git/x.orig", "cd src && rm a.txt.bak",
                "find . -name '*.log'", "find . -name '*.tmp' -not -path './.git/*' -delete",
                "find . -path ./.git -prune -o -name '*.tmp' -delete",
                "find . -name .git -prune -o -name '*.tmp' -exec rm {} +",
                "find . ! -path '*/.git/*' -name '*.tmp' -delete"):
    expect(command, command, "ALLOW")

sh(repo, "git", "config", "core.hooksPath", ".husky")
os.makedirs(os.path.join(repo, ".husky"))
for command in ("rm .husky/pre-push", "rm -rf .husky", "rm ./.husky/../.husky/pre-push",
                "cd .husky && rm pre-push", "find .husky -delete", "echo exit 0 > .husky/pre-commit"):
    expect(f"core.hooksPath: {command}", command, "DENY", reason_has="hooks")
expect("core.hooksPath: rm src/a.txt.bak still allowed", "rm src/a.txt.bak", "ALLOW")
sh(repo, "git", "config", "--unset", "core.hooksPath")

# no-verify inside interpreter and exec strings
for command in ("python -c \"import subprocess; subprocess.run(['git', 'commit', '--no-verify'])\"",
                "bash -c 'git commit --NO-VERIFY -m x'", "node -e \"run('git push --no-veri')\"",
                "pwsh -Command \"git commit --no-verify -m x\"", "echo x | xargs git commit --no-verify -m",
                "find . -name x -exec git commit --no-verify -m x \\;", "eval \"git commit --no-verify -m x\"",
                "python - <<'EOF'\nimport os\nos.system('git commit --no-verify -m x')\nEOF"):
    expect(command, command, "DENY", reason_has="no-verify")
expect("[PowerShell] Invoke-Expression 'git commit --no-verify -m x'",
       "Invoke-Expression 'git commit --no-verify -m x'", "DENY", tool="PowerShell", reason_has="no-verify")
for command in ("grep no-verify README.md", "rg -n no-verify docs", "cat no-verify-notes.txt",
                "git commit -m \"docs: explain no-verify\"", "git log --grep=no-verify"):
    expect(command, command, "ALLOW")

# global git config files
home = os.path.expanduser("~")
for target in ("~/.gitconfig", os.path.join(home, ".gitconfig"), os.path.join(xdg, "git", "config"),
               os.path.join(home, ".config", "git", "config"), GLOBAL):
    expect(f"Write {target}", target, "DENY", tool="Write", reason_has="global git config")
for command in ("echo x >> ~/.gitconfig", "cp a ~/.gitconfig", "mv a $HOME/.gitconfig",
                "cat a | tee -a ~/.gitconfig", "printf x >$XDG_CONFIG_HOME/git/config",
                "cp a ~/.config/git/config",
                "cp a " + os.path.join(home, ".gitconfig").replace("\\", "/")):
    expect(command, command, "DENY", reason_has="global git config")
expect("[PowerShell] Set-Content $env:USERPROFILE\\.gitconfig x",
       "Set-Content $env:USERPROFILE\\.gitconfig x", "DENY", tool="PowerShell", reason_has="global git config")
expect("[PowerShell] cmd /c copy a %USERPROFILE%\\.gitconfig", "cmd /c copy a %USERPROFILE%\\.gitconfig",
       "DENY", tool="PowerShell", reason_has="global git config")
for command in ("cat ~/.gitconfig", "git config --global --get user.name", "grep url ~/.gitconfig"):
    expect(command, command, "ALLOW")
expect("Write a repo file", os.path.join(repo, "notes.txt"), "ALLOW", tool="Write")

# missing native hooks: warned even with the gate off
got, _, stderr = hook_run("git commit -m x")
check("missing native hooks are warned without the gate", "hook(s) are not installed" in stderr, stderr)

# split URL rewrite: ls-remote asks a fake remote that already has the secret commit
sh(repo, "git", "push", "-q", real, "main")
sh(repo, "git", "push", "-q", fake, "main")
write(os.path.join(repo, "src", "s.txt"), SECRET)
sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-q", "-m", "leak")
leak = sh(repo, "git", "rev-parse", "HEAD").stdout.strip()
sh(repo, "git", "push", "-q", fake, "main")
alias = "https://example.invalid/team/repo.git"
sh(repo, "git", "remote", "add", "origin", alias)
sh(base, "git", "config", "--file", GLOBAL, f"url.{real}.pushInsteadOf", alias)
sh(base, "git", "config", "--file", GLOBAL, f"url.{fake}.insteadOf", real)
check("setup: ls-remote of the push URL answers from the fake remote",
      leak in sh(repo, "git", "ls-remote", real).stdout)
old_hook = os.path.join(base, "old-hook.py")
previous = sh(os.path.join(HERE, ".."), "git", "show", "d0d3e91:./pre-commit-secret-scan.py", check=False)
if previous.returncode == 0:
    write(old_hook, previous.stdout)
    got, reason, _ = hook_run("git push origin main", script=old_hook)
    check("reproduction: the hook before this fix trusted the spoofed ls-remote", got == "ALLOW", reason)
got, reason, stderr = hook_run("git push origin main")
check("PreToolUse falls back to tracking refs and finds the secret",
      got == "DENY" and "Secret scan blocked this push" in reason, reason)
check("PreToolUse warns naming the rewrite",
      "URL rewrite" in stderr and ".insteadof" in stderr.lower(), stderr)
sh(repo, sys.executable, HOOK, "--install-pre-push")
r = sh(repo, "git", "push", "origin", "main", check=False)
check("native pre-push falls back to tracking refs under a split rewrite and finds the secret",
      r.returncode != 0 and "Secret scan blocked this push" in r.stderr and "URL rewrite" in r.stderr
      and "from a terminal" not in r.stderr, r.stderr)
sh(repo, "git", "branch", "clean0", "HEAD~1")
r = sh(repo, "git", "push", "origin", "clean0", check=False)
check("native pre-push lets a clean push through a split rewrite, with a warning",
      r.returncode == 0 and "URL rewrite" in r.stderr, r.stderr)
check("the real remote did not receive the secret commit",
      leak not in sh(base, "git", "--git-dir", real, "rev-parse", "main").stdout)

write(GLOBAL, "")
sh(base, "git", "config", "--file", GLOBAL, "url.https://mirror.invalid/.insteadOf", "https://other.invalid/")
sh(repo, "git", "branch", "clean", "HEAD~1")
r = sh(repo, "git", "push", real, "clean", check=False)
check("an unrelated rewrite does not block a clean push", r.returncode == 0, r.stderr)
gh = os.path.join(base, "gh")
sh(base, "git", "init", "-q", "--bare", os.path.join(gh, "repo.git"))
gh_base = gh.replace(os.sep, "/")
sh(base, "git", "config", "--file", GLOBAL, f"url.{gh_base}/.insteadOf", "https://github.invalid/team/")
sh(repo, "git", "remote", "add", "gh", "https://github.invalid/team/repo.git")
got, reason, stderr = hook_run("git push gh clean")
check("ordinary https->other insteadOf: PreToolUse allows without a rewrite warning",
      got == "ALLOW" and "URL rewrite" not in stderr, reason + stderr)
r = sh(repo, "git", "push", "gh", "clean", check=False)
check("ordinary https->other insteadOf: native pre-push lets the push through", r.returncode == 0, r.stderr)

# userinfo is stripped from printed URLs
many = os.path.join(base, "many")
os.makedirs(many)
sh(many, "git", "init", "-q", "-b", "main")
configure(many)
stream = []
for n in range(1, 1003):
    parent = f"from :{n - 1}\n" if n > 1 else ""
    stream.append(f"commit refs/heads/main\nmark :{n}\ncommitter t <t@t.com> {1700000000 + n} +0000\n"
                  f"data 2\nc\n{parent}M 644 inline f.txt\ndata {len(str(n)) + 1}\n{n}\n\n")
subprocess.run(["git", "fast-import", "--quiet"], cwd=many, input="".join(stream).encode(), check=True,
               capture_output=True)
sh(many, "git", "reset", "-q", "--hard", "main")
cred_url = "https://user:" + TOKEN + "@127.0.0.1:9/x.git"
got, reason, _ = hook_run(f"git push {cred_url} main", cwd=many)
check("PreToolUse UNKNOWN_REMOTE drops the userinfo",
      got == "DENY" and TOKEN not in reason and "https://127.0.0.1:9/x.git" in reason, reason)
head = sh(many, "git", "rev-parse", "HEAD").stdout.strip()
r = sh(many, sys.executable, HOOK, "--pre-push", "cred", cred_url, check=False,
       data=f"refs/heads/main {head} refs/heads/main {'0' * 40}\n")
check("native UNKNOWN_REMOTE drops the userinfo",
      r.returncode != 0 and TOKEN not in r.stderr and "https://127.0.0.1:9/x.git" in r.stderr, r.stderr)

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
