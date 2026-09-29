import json, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "pre-commit-secret-scan.py")
base = os.path.join(tempfile.gettempdir(), f"unresolved_{int(time.time() * 1000)}")
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

for command in ("rm -rf $(git rev-parse --git-path hooks)", "rm $(git rev-parse --git-path hooks)/pre-push",
                'd=$(git rev-parse --git-path hooks); rm -rf "$d"', 'rm -rf "$(git rev-parse --git-dir)"/hooks',
                "rm -rf `git rev-parse --git-path hooks`", "rm `git rev-parse --git-path hooks`/pre-push",
                'd=`git rev-parse --git-path hooks`; rm -rf "$d"', 'rm -rf "`git rev-parse --git-dir`"/hooks',
                "rm -rf ${GITDIR:-.git}/hooks", 'rm -rf "$1"/../hooks', "d=.git; rm $d/hooks/pre-push",
                'rm -rf "$GIT_DIR"', "rm -f $GIT_COMMON_DIR/pre-commit", 'echo x > "$(git config core.hooksPath)"',
                r"find . -execdir rm -rf hooks \;", r"find . -name '*.log' -okdir sh -c 'rm -rf hooks' \;"):
    expect(command, "DENY")
for command in ('$d = git rev-parse --git-path hooks; Remove-Item -Recurse $d', "Remove-Item $env:GIT_DIR -Recurse"):
    expect(command, "DENY", tool="PowerShell")

for command in ('echo hi > "$LOG"', 'cmd 2> "$ERRFILE"', 'cp a.txt "$DEST"', 'mv a.txt "$DEST"', 'rm -f "$f"',
                "rm -rf $(mktemp -d)", "touch $(date +%s).log", 'tmp=$(mktemp); echo x > "$tmp"; rm -f "$tmp"',
                'for f in *.bak; do rm -f "$f"; done', "echo `date` > out.txt",
                r"""find . -name '*.tmp' -exec sh -c 'rm -f "$1"' _ {} \;""",
                r"""find . -name '*.bak' -exec sh -c 'mv "$1" "${1%.bak}"' _ {} \;""",
                r"find . -name '*.log' -execdir gzip {} \;", r"find . -name '*.log' -execdir gzip -9 {} +"):
    expect(command, "ALLOW")
for command in ('$f = New-TemporaryFile; "x" | Out-File $f; Remove-Item $f', '"a" > $out',
                "Copy-Item a.txt $dest", "Remove-Item $tmp"):
    expect(command, "ALLOW", tool="PowerShell")

got, reason, _ = hook_run("rm -rf $(git rev-parse --git-path hooks)")
check("the unresolved deny names the hooks dir, not --no-verify",
      got == "DENY" and "--no-verify" not in reason and "rewire" not in reason
      and "hooks" in reason and "literal path" in reason, reason)
got, reason, _ = hook_run('rm -rf "$1"/../hooks')
check("the .. deny uses the unresolved-path wording", reason.startswith("This command writes to a path built"), reason)

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
