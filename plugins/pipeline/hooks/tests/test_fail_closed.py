import importlib.util, io, json, os, subprocess, sys, tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pre-commit-secret-scan.py")
base = tempfile.mkdtemp(prefix="hookfailclosed_")
repo = os.path.join(base, "repo")
os.makedirs(repo)
ALLOW = ".pipeline-secrets-allow"
SECRET_LINE = "AWS_" + "KEY=AK" + "IAABCDEFGHIJKLMNOP\n"
results = []


def sh(cwd, *a, check=True):
    return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=check)


def verdict(stdout):
    if not stdout.strip():
        return "ALLOW", ""
    return "DENY", json.loads(stdout)["hookSpecificOutput"]["permissionDecisionReason"]


def hook(command, cwd=repo, tool="Bash"):
    payload = json.dumps({"tool_name": tool, "tool_input": {"command": command}, "cwd": cwd})
    r = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True, encoding="utf-8")
    return verdict(r.stdout)


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("PASS" if ok else "FAIL", name, "" if ok else f"| {detail[-300:]}")


def expect(name, command, expected, cwd=repo, tool="Bash", reason_has=None):
    got, reason = hook(command, cwd, tool)
    ok = got == expected and (reason_has is None or reason_has in reason)
    check(f"[{tool}] {name} -> {got}", ok, reason)


def write(folder, name, text):
    with open(os.path.join(folder, name), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def configure(path):
    for k, v in (("user.email", "t@t.com"), ("user.name", "t"), ("core.autocrlf", "false")):
        sh(path, "git", "config", k, v)


sh(repo, "git", "init", "-q", "-b", "main")
configure(repo)
write(repo, "a.txt", "base\n")
write(repo, ALLOW, "# user entries\n")
sh(repo, "git", "add", "-A")
sh(repo, "git", "commit", "-q", "-m", "base")
write(repo, "b.txt", "clean\n")
sh(repo, "git", "add", "b.txt")

spec = importlib.util.spec_from_file_location("scan", HOOK)
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)


def run_in_process(stdin_text, patch=None):
    saved = (sys.stdin, sys.stdout, scanner.main, scanner.git)
    if patch == "crash":
        def crashing(raw):
            raise RuntimeError("boom")
        scanner.main = crashing
    elif patch is not None:
        scanner.git = patch
    sys.stdin = io.TextIOWrapper(io.BytesIO(stdin_text.encode("utf-8")), encoding="utf-8")
    sys.stdout = io.StringIO()
    try:
        scanner.run()
    except SystemExit:
        pass
    finally:
        output = sys.stdout.getvalue()
        sys.stdin, sys.stdout, scanner.main, scanner.git = saved
    return verdict(output)


def payload(command=None, tool="Bash", file_path=None):
    tool_input = {"file_path": file_path} if file_path else {"command": command}
    return json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": repo})


crash_cases = [
    ("git commit", payload("git commit -m x"), "DENY"),
    ("git push", payload("git push origin main"), "DENY"),
    ("git add", payload("git add -A"), "DENY"),
    ("git stage", payload("git stage b.txt"), "DENY"),
    ("git with options then commit", payload('git -C "x" -c a.b=c commit -m y'), "DENY"),
    ("bash -c git commit", payload("bash -c 'git commit -m x'"), "DENY"),
    ("possible alias (not a builtin)", payload("git ci -m x"), "DENY"),
    ("remote-ref tool", payload("git update-ref refs/heads/x HEAD"), "DENY"),
    ("command naming the allowlist", payload("cp x " + ALLOW), "DENY"),
    ("Write to the allowlist", payload(tool="Write", file_path=os.path.join(repo, ALLOW)), "DENY"),
    ("Write to a remote-tracking ref", payload(tool="Write", file_path=repo + "/.git/refs/remotes/o/main"), "DENY"),
    ("non-JSON input mentioning git commit", "not json git commit -m x", "DENY"),
    ("git status", payload("git status"), "ALLOW"),
    ("git log piped to grep", payload("git log --oneline | grep fix"), "ALLOW"),
    ("unrelated command", payload("npm test && ls -la"), "ALLOW"),
    ("Write to an ordinary file", payload(tool="Write", file_path=os.path.join(repo, "c.txt")), "ALLOW"),
    ("non-JSON input without git", "not json at all", "ALLOW"),
]
for name, stdin_text, expected in crash_cases:
    got, reason = run_in_process(stdin_text, "crash")
    check(f"hook crash: {name} -> {got}", got == expected and (got == "ALLOW" or "hook error" in reason), reason)

real_blocks = scanner.blocks_on_error
scanner.blocks_on_error = lambda raw: 1 / 0
got, reason = run_in_process(payload("git commit -m x"), "crash")
check("hook crash while classifying: a git command is still denied", got == "DENY" and "hook error" in reason, reason)
got, _ = run_in_process(payload("npm test"), "crash")
check("hook crash while classifying: a non-git command is still allowed", got == "ALLOW")
scanner.blocks_on_error = real_blocks

real_git = scanner.git


def failing(verb):
    def fake(args, cwd, env=None, **options):
        if args[0] == verb:
            return 1, ""
        return real_git(args, cwd, env, **options)
    return fake


got, reason = run_in_process(payload("git commit -m x"), failing("diff"))
check("git diff failing during a commit scan denies with hook error", got == "DENY" and "hook error" in reason, reason)
got, reason = run_in_process(payload("git push origin main"), failing("rev-list"))
check("git rev-list failing during a push scan denies with hook error", got == "DENY" and "hook error" in reason,
      reason)

expect("empty -c alias no longer crashes (clean commit allowed)", "git -c alias.x=' ' x; git commit -m y", "ALLOW")
expect("empty -c alias alone is allowed", "git -c alias.x=' ' x", "ALLOW")
check("expand_alias returns [] for a blank alias",
      scanner.expand_alias({"op": "x", "steps": [], "tokens": [], "pairs": [("alias.x", "  ")], "configs": [],
                            "assigns": [], "relocated": False, "chain": ()}, repo, False) == [])

relocating = [
    ("[Environment]::SetEnvironmentVariable",
     "[Environment]::SetEnvironmentVariable('GIT_DIR', 'C:/x/.git', 'Process'); git add b.txt", "PowerShell"),
    ("New-Item Env:", "New-Item -Path Env: -Name GIT_WORK_TREE -Value C:/x; git add b.txt", "PowerShell"),
    ("Set-Content env:", "Set-Content env:GIT_INDEX_FILE C:/x/i; git commit -m y", "PowerShell"),
    ("$env: assignment", "$env:git_dir = 'C:/x/.git'; git add b.txt", "PowerShell"),
    ("printf -v", "printf -v GIT_DIR %s /x/.git; export GIT_DIR; git add b.txt", "Bash"),
    ("printf -v attached", "printf -vGIT_DIR %s /x/.git; git add b.txt", "Bash"),
    ("read", "read GIT_DIR <<< /x/.git; git add b.txt", "Bash"),
    ("declare -x", "declare -x GIT_WORK_TREE=/x; git commit -m y", "Bash"),
    ("${VAR:=default} expansion", "echo ${GIT_DIR:=/x/.git}; git add b.txt", "Bash"),
    ("assignment before a shell", "GIT_DIR=/x/.git bash -c 'git add b.txt'", "Bash"),
    ("-c core.worktree", "git -c core.worktree=/x add b.txt", "Bash"),
    ("GIT_CONFIG_* core.worktree", "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.worktree GIT_CONFIG_VALUE_0=/x "
                                   "git add b.txt", "Bash"),
]
for name, command, tool in relocating:
    expect(f"relocation via {name}", command, "DENY", tool=tool, reason_has="--git-dir/--work-tree")

readers = [
    ("echo of an assignment", 'echo "GIT_DIR=x" && git commit -m y', "Bash"),
    ("grep for an assignment", 'grep -rn "GIT_WORK_TREE=" . ; git add b.txt', "Bash"),
    ("printf without -v", "printf 'GIT_DIR=%s' x; git add b.txt", "Bash"),
    ("cat of a file named after it", "cat GIT_DIR.md; git add b.txt", "Bash"),
    ("unset", "unset GIT_DIR GIT_WORK_TREE; git commit -m y", "Bash"),
    ("Write-Output", 'Write-Output "GIT_DIR=x"; git add b.txt', "PowerShell"),
    ("Remove-Item Env:", "Remove-Item Env:GIT_DIR; git add b.txt", "PowerShell"),
    ("name inside a longer word", "export MY_GIT_DIR_BACKUP=1; git add b.txt", "Bash"),
]
for name, command, tool in readers:
    expect(f"no relocation: {name}", command, "ALLOW", tool=tool)

expect("folder created by the same command", "mkdir newd && cd newd && git add x.txt", "DENY",
       reason_has="create it first in a separate command")
got, reason = hook("mkdir newd && cd newd && git add x.txt")
check("unresolved message names the folder and the bare-repository cases",
      "does not exist yet" in reason and "bare repository" in reason and "mkdir" in reason, reason)

bare_clean = os.path.join(base, "clean.git")
bare_dirty = os.path.join(base, "dirty.git")
bare_gated = os.path.join(base, "gated.git")
target = os.path.join(base, "target.git")
for path in (bare_clean, bare_dirty, bare_gated, target):
    sh(base, "git", "init", "-q", "--bare", path)
sh(repo, "git", "commit", "-q", "-m", "clean b")
sh(repo, "git", "push", "-q", bare_clean, "main")
write(repo, "cfg.txt", SECRET_LINE)
sh(repo, "git", "add", "cfg.txt")
sh(repo, "git", "commit", "-q", "-m", "secret")
sh(repo, "git", "push", "-q", bare_dirty, "main")
sh(repo, "git", "reset", "-q", "--hard", "HEAD~1")
os.makedirs(os.path.join(repo, "docs", "quality-reports"))
write(repo, os.path.join("docs", "quality-reports", "history.jsonl"), "")
sh(repo, "git", "add", "-A")
sh(repo, "git", "commit", "-q", "-m", "opt in")
sh(repo, "git", "push", "-q", bare_gated, "main")
sh(repo, "git", "reset", "-q", "--hard", "HEAD~1")
for path in (bare_clean, bare_dirty, bare_gated):
    sh(path, "git", "remote", "add", "target", target)

expect("push from a clean bare repository", "git push target main", "ALLOW", cwd=bare_clean)
expect("push from a bare repository with a secret in history", "git push target main", "DENY", cwd=bare_dirty,
       reason_has="Secret scan blocked this push")
expect("push from an opted-in bare repository needs the gate", "git push target main", "DENY", cwd=bare_gated,
       reason_has="gate agent's approval")
expect("commit inside a bare repository", "git commit -m x", "DENY", cwd=bare_clean, reason_has="bare repository")
expect("add inside a bare repository", "git add x", "DENY", cwd=bare_clean, reason_has="no working tree")

write(repo, "a.txt", SECRET_LINE)
expect("GIT_CONFIG_* alias to commit -a is resolved and scanned",
       "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.ci GIT_CONFIG_VALUE_0='commit -am y' git ci", "DENY",
       reason_has="Secret scan blocked this commit")
expect("empty -c alias before a commit -a that adds a secret", "git -c alias.x=' ' x; git commit -am y", "DENY",
       reason_has="Secret scan blocked this commit")
sh(repo, "git", "checkout", "--", "a.txt")
r = subprocess.run([sys.executable, HOOK, "--pre-push", "origin"], cwd=repo, capture_output=True, text=True,
                   encoding="utf-8", errors="replace", input=f"refs/heads/x {'f' * 40} refs/heads/x {'0' * 40}\n")
check("pre-push blocks when git cannot list the outgoing commits",
      r.returncode != 0 and "Secret scan failed" in r.stderr, r.stderr)
write(repo, ALLOW, f"# user entries\n{'ab' * 32}  # pending\n")
expect("GIT_CONFIG_* on an external git command is not unverifiable", "GIT_CONFIG_NOSYSTEM=1 git lfs ls-files",
       "ALLOW")
expect("GIT_CONFIG_* on a builtin reader", "GIT_CONFIG_NOSYSTEM=1 git status", "ALLOW")
expect("GIT_CONFIG_* alias to add -A with a dirty allowlist",
       "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.x GIT_CONFIG_VALUE_0='add -A' git x", "DENY")
expect("GIT_CONFIG_* from an unset variable on a possible alias",
       "GIT_CONFIG_GLOBAL=$UNSET_CONFIG_VAR_42 git x", "DENY", reason_has="Cannot verify what the git alias")
sh(repo, "git", "checkout", "--", "a.txt")
write(repo, ALLOW, "# user entries\n")

sh(repo, "git", "update-ref", "refs/remotes/origin/main", "HEAD")
remote_refs = [
    ("update-ref on refs/remotes", "git update-ref refs/remotes/origin/main HEAD~1"),
    ("update-ref -d on refs/remotes", "git update-ref -d refs/remotes/origin/main"),
    ("update-ref --stdin", "echo 'update refs/remotes/origin/main HEAD' | git update-ref --stdin"),
    ("symbolic-ref on refs/remotes", "git symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/main"),
    ("remote set-head", "git remote set-head origin main"),
    ("remote set-head after an option", "git remote -v set-head origin -a"),
    ("alias to update-ref", "git -c alias.ur=update-ref ur refs/remotes/origin/main HEAD"),
    ("redirect into a loose remote ref", "echo 0000 > .git/refs/remotes/origin/main"),
    ("redirect into packed-refs", "echo x >> .git/packed-refs"),
    ("PowerShell update-ref", "git update-ref refs/remotes/origin/main HEAD"),
]
for name, command in remote_refs:
    tool = "PowerShell" if name.startswith("PowerShell") else "Bash"
    expect(name, command, "DENY", tool=tool, reason_has="remote-tracking ref")
for name, file_path in (("Write to a loose remote ref", repo + "/.git/refs/remotes/origin/main"),
                        ("Edit of packed-refs", repo + "\\.git\\packed-refs")):
    got, reason = verdict(subprocess.run([sys.executable, HOOK], input=payload(tool="Write", file_path=file_path),
                                         capture_output=True, text=True, encoding="utf-8").stdout)
    check(f"{name} -> {got}", got == "DENY" and "remote-tracking ref" in reason, reason)
expect("update-ref on a local branch", "git update-ref refs/heads/tmp HEAD", "ALLOW")
expect("symbolic-ref read", "git symbolic-ref HEAD", "ALLOW")
expect("remote -v", "git remote -v", "ALLOW")
expect("reading remote refs", "git for-each-ref refs/remotes/", "ALLOW")
expect("git fetch still allowed", "git fetch --dry-run origin", "ALLOW")

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
