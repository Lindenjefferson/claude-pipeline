import importlib.util, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "pre-commit-secret-scan.py")
base = tempfile.mkdtemp(prefix="guardround4_")
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


def expect(command, expected, reason_has=None):
    got, reason, stderr = hook_run(command)
    ok = got == expected and (reason_has is None or reason_has in reason)
    check(f"{command} -> {expected}", ok, f"got {got}: {reason} {stderr}")


sh(repo, "git", "init", "-q", "-b", "main")
for k, v in (("user.email", "t@t.com"), ("user.name", "t"), ("core.autocrlf", "false")):
    sh(repo, "git", "config", k, v)
with open(os.path.join(repo, "a.txt"), "w") as handle:
    handle.write("a\n")
sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-q", "-m", "base")

for command in ("git config core.hooksPath --show-origin", "git config core.hooksPath --show-scope",
                "git config core.hooksPath --type=path", "git config core.hooksPath -x",
                "git config core.hooksPath --", "git config -- core.hooksPath -y",
                "git config pipeline.gate --bool", "git config pipeline.gate -false",
                "git config remote.origin.url --", "git config url.-x.insteadOf --",
                "git config core.hooksPath --get", "git config core.hooksPath -l"):
    expect(command, "DENY", reason_has="settings")
for command in ("git config core.hooksPath", "git config --get core.hooksPath",
                "git config --show-origin --get core.hooksPath", "git config --bool --get pipeline.gate",
                "git config -l", "git config --list --show-origin", "git config get core.hooksPath",
                "git config --type path --get core.hooksPath", "git config user.name --someone"):
    expect(command, "ALLOW")

for command in (r"find . -name '*.log' -exec gzip {} \; -o -mtime +30 -delete",
                "find . -name '*.log' -exec rm {} + -o -name 'pre-*' -delete",
                r"find . -name '*.log' -exec rm -f {} \; -o -type f -exec rm {} \;",
                r"find . -name '*.log' -exec grep -q x {} \; -o -exec rm -rf {} +",
                r"find . -name info -type d -exec rm -rf {}/../hooks \;",
                r"find . -name info -type d -execdir rm -rf hooks \;"):
    expect(command, "DENY", reason_has="find")
for command in ("find . -type d -name __pycache__ -exec rm -rf {} +",
                "find . -name node_modules -prune -o -name '*.log' -delete",
                r"find . -name '*.log' -exec gzip {} \;", "find . -type f -exec sha256sum {} +",
                r"find . -name '*.bak' -exec mv {} {}.old \;",
                r"find . -not -path './.git/*' -name info -execdir rm -rf hooks \;"):
    expect(command, "ALLOW")

for command in ("rm -rf $(git rev-parse --git-path hooks)", "rm $(git rev-parse --git-path hooks)/pre-push",
                'd=$(git rev-parse --git-path hooks); rm -rf "$d"', "rm -f $GIT_DIR/hooks/pre-commit"):
    expect(command, "DENY", reason_has="hooks")
for command in ("rm -rf $(mktemp -d)/build", "cat $(git rev-parse --git-path hooks)/pre-push",
                "rm -f $HOOKDIR_UNSET/pre-commit",
                "echo $(date) done"):
    expect(command, "ALLOW")

spec = importlib.util.spec_from_file_location("scan", HOOK)
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)
check("gate off without pipeline.gate or docs/quality-reports", not scan.gate_enabled(repo, repo, []))
for value, expected in (("false", False), ("off", False), ("true", True), ("maybe", True), ("2", True)):
    sh(repo, "git", "config", "pipeline.gate", value)
    check(f"pipeline.gate={value} -> gate {'on' if expected else 'off'}",
          scan.gate_enabled(repo, repo, []) is expected)
sh(repo, "git", "config", "--add", "pipeline.gate", "false")
sh(repo, "git", "config", "--replace-all", "pipeline.gate", "junk", "^2$")
check("any non-false pipeline.gate value keeps the gate on", scan.gate_enabled(repo, repo, []))

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
