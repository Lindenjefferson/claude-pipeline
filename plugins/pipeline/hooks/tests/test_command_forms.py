import json, os, subprocess, sys, tempfile, time

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pre-commit-secret-scan.py")
base = os.path.join(tempfile.gettempdir(), f"hookforms_{int(time.time())}")
repo = os.path.join(base, "repo")
elsewhere = os.path.join(base, "elsewhere")
os.makedirs(repo)
os.makedirs(elsewhere)
results = []


def sh(*args):
    return subprocess.run(args, cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def run_hook(command, tool="Bash", cwd=repo):
    payload = json.dumps({"tool_name": tool, "tool_input": {"command": command}, "cwd": cwd})
    r = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True)
    return "DENY" if r.stdout.strip() else "ALLOW"


def check(name, command, expected, tool="Bash", cwd=repo):
    got = run_hook(command, tool, cwd)
    results.append(got == expected)
    print(("PASS" if got == expected else "FAIL"), f"[{tool}] {name} -> {got}")


sh("git", "init", "-q")
sh("git", "config", "user.email", "t@t.com")
sh("git", "config", "user.name", "t")
sh("git", "config", "core.autocrlf", "false")
sh("git", "commit", "-q", "--allow-empty", "-m", "base")
open(os.path.join(repo, "cfg.txt"), "w").write("AWS_KEY=AKIAABCDEFGHIJKLMNOP\n")
sh("git", "add", "cfg.txt")

bash_denied = [
    ("plain", "git commit -m x"),
    ("-c config before the subcommand", "git -c user.name=x commit -m x"),
    ("--no-pager", "git --no-pager commit -m x"),
    ("command wrapper", "command git commit -m x"),
    ("full path", "/usr/bin/git commit -m x"),
    ("git.exe", "git.exe commit -m x"),
    ("Windows path to git.exe", '"C:/Program Files/Git/cmd/git.exe" commit -m x'),
    ("bash -c", "bash -c 'git commit -m x'"),
    ("sh -c with double quotes", 'sh -c "git commit -m x"'),
    ("subshell", "(git commit -m x)"),
    ("brace group", "{ git commit -m x; }"),
    ("env assignment prefix", "GIT_AUTHOR_NAME=x git commit -m x"),
    ("env wrapper", "env GIT_AUTHOR_NAME=x git commit -m x"),
    ("inside command substitution", "echo $(git commit -m x)"),
    ("after ||", "false || git commit -m x"),
    ("after a pipe", "true | git commit -m x"),
    ("line continuation", "git \\\ncommit -m x"),
    ("second line", "echo ok\ngit commit -m x"),
    ("amend", "git commit --amend --no-edit"),
    ("quoted message with separators", 'git commit -m "a; b && c | d"'),
    ("cd to the repo from elsewhere", f'cd "{repo}" && git commit -m x', ),
]
for name, command in bash_denied:
    check(name, command, "DENY", cwd=elsewhere if name.startswith("cd to") else repo)

bash_allowed = [
    ("commit-tree is not commit", "git commit-tree HEAD^{tree} -m x"),
    ("git log", "git log --oneline"),
    ("word commit in an argument", "git log --grep commit"),
    ("echo of a git command", 'echo "git commit -m x"'),
    ("grep for a git command", "grep -rn 'git commit' ."),
    ("git status", "git status"),
    ("not a repo: git status", "git status"),
    ("not a repo: git log", "git log --oneline"),
    ("not a repo: git init", "git init -q x"),
    ("not a repo: non-git command", "ls"),
]
for name, command in bash_allowed:
    check(name, command, "ALLOW", cwd=elsewhere if name.startswith("not a repo") else repo)

check("not a repo: git commit denied (the hook cannot see which repository it lands in)",
      "git commit -m x", "DENY", cwd=elsewhere)
check("not a repo: git push denied", "git push", "DENY", cwd=elsewhere)
check("not a repo: git add denied", "git add -A", "DENY", cwd=elsewhere)
check("a cd the parser does not follow (eval) cannot skip the scan", f'eval "cd {repo}" && git commit -m x',
      "DENY", cwd=elsewhere)

check("${VAR} path is resolved, not split", 'cd "${HOOKFORMS_REPO}" && git commit -m x', "DENY", cwd=elsewhere) \
    if os.environ.setdefault("HOOKFORMS_REPO", repo) else None
check("unset variable in a cd path", 'cd "$HOOKFORMS_UNSET" && git commit -m x', "DENY", cwd=elsewhere)

ps_denied = [
    ("plain", "git commit -m x", repo),
    ("call operator", "& git commit -m x", repo),
    ("call operator with a quoted path", '& "C:\\Program Files\\Git\\cmd\\git.exe" commit -m x', repo),
    ("git.exe", "git.exe commit -m x", repo),
    ("after ;", "Write-Output ok; git commit -m x", repo),
    ("script block", "if ($true) { git commit -m x }", repo),
    ("powershell -Command", "powershell -Command \"git commit -m x\"", repo),
    ("-C with a Windows path", f'git -C "{repo}" commit -m x', elsewhere),
    ("Set-Location", f'Set-Location "{repo}"; git commit -m x', elsewhere),
    ("Set-Location -Path", f"Set-Location -Path '{repo}'; git commit -m x", elsewhere),
    ("cd", f'cd "{repo}"; git commit -m x', elsewhere),
    ("$env: path", 'cd "$env:HOOKFORMS_REPO"; git commit -m x', elsewhere),
]
for name, command, cwd in ps_denied:
    check(name, command, "DENY", tool="PowerShell", cwd=cwd)

check("unset $env: variable", 'cd "$env:HOOKFORMS_UNSET"; git commit -m x', "DENY", tool="PowerShell", cwd=elsewhere)
check("git status", "git status", "ALLOW", tool="PowerShell")
check("Select-String for a git command", "Select-String -Pattern 'git commit' -Path x", "ALLOW", tool="PowerShell")

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
