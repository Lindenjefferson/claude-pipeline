import json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "pre-commit-secret-scan.py")
base = tempfile.mkdtemp(prefix="guardround5_")
repo = os.path.join(base, "repo")
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


sh(repo, "git", "init", "-q", "-b", "main")
for k, v in (("user.email", "t@t.com"), ("user.name", "t"), ("core.autocrlf", "false")):
    sh(repo, "git", "config", k, v)
with open(os.path.join(repo, "a.txt"), "w") as handle:
    handle.write("a\n")
sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-q", "-m", "base")

for command in ("git config -t path core.hooksPath /evil", "git config -zt path core.hooksPath /evil",
                "git config --typ path core.hooksPath /evil", "git config --comm x pipeline.gate false",
                "git config --unset-a pipeline.gate", "git config --unset-a core.hooksPath",
                "git config --remove-s pipeline", "git config --remove-sec core",
                "git config --rename-s pipeline foo", "git config --fil .git/config core.hooksPath /evil",
                "git -C . config --unset-a pipeline.gate", "git config --type=path core.hooksPath /evil",
                "git config core.worktree /elsewhere", "git config set core.hooksPath /evil",
                "git config unset pipeline.gate", "git config rename-section pipeline foo",
                "git config --get-urlmatch remote.origin.url x y", "git config core.hooksPath=/evil",
                "git config -- core.hooksPath /evil", "git config -l core.hooksPath /evil",
                "git config --add remote.origin.fetch +refs/heads/*:refs/remotes/x/*",
                "git config url.file:///tmp/x.insteadOf https://github.com/"):
    expect(command, "DENY", reason_has="settings")
expect("'--typ' 'path' 'core.hooksPath' '/evil' | Out-Null; git config '--typ' 'path' 'core.hooksPath' '/evil'",
       "DENY", reason_has="settings", tool="PowerShell")
expect("git config '--typ' 'path' 'core.hooksPath' '/evil'", "DENY", reason_has="settings", tool="PowerShell")
for command in ("git config --edi", "git config --ed", "git config -ze", "GIT_EDITOR=vi git config -ze",
                "git config --edit", "git config -e", "git config --global -e", "git config edit",
                "git config --e"):
    expect(command, "DENY")

for command in ("git config core.hooksPath", "git config --get core.hooksPath",
                "git config --get core.hooksPath somepattern", "git config --show-origin --get core.hooksPath",
                "git config -t bool --get pipeline.gate", "git config --type bool --get pipeline.gate",
                "git config -l", "git config --list --show-scope", "git config get --all core.hooksPath",
                "git config --global --list", "git config -z --get core.hooksPath", 'git config user.name "X"',
                "git config --get-regexp pipeline", "git config --get-all remote.origin.url",
                "git config -tbool --get pipeline.gate", "git config --type=bool --get pipeline.gate",
                "git config --file .gitmodules --get-regexp url", "git config user.email --someone",
                "git config --unset user.signingkey", "git config list --show-origin"):
    expect(command, "ALLOW")
expect("git config '--get' 'core.hooksPath'", "ALLOW", tool="PowerShell")

for command in ('rm -rf "$1"/../hooks', r"""find . -name info -type d -exec sh -c 'rm -rf "$1"/../hooks' _ {} \;""",
                r"find . -name info -type d -exec rm -rf {}\\..\\hooks \;", r'rm -rf "$X\..\hooks"',
                'rm -rf "$D/../../x"'):
    expect(command, "DENY")
expect(r'rm -rf "$X"\..\hooks', "DENY", tool="PowerShell")
got, reason, _ = hook_run('rm -rf "$1"/../hooks')
check("the unresolved-variable deny suggests the literal path", "literal path" in reason, reason)
got, reason, _ = hook_run("rm -rf $(git rev-parse --git-path hooks)")
check("the $(...) deny suggests the literal path", got == "DENY" and "literal path" in reason, reason)
got, reason, _ = hook_run("rm -rf .git/hooks")
check("a literal hooks path deny has no unresolved hint", got == "DENY" and "literal path" not in reason, reason)
for command in ('rm -rf "$TMPDIR"/build', "rm -rf $(mktemp -d)/build", 'cat "$1"/../notes.txt',
                r"""find . -name '*.log' -exec sh -c 'gzip "$1"' _ {} \;"""):
    expect(command, "ALLOW")

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
