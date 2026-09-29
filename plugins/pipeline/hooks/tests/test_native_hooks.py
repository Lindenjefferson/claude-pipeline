import importlib.util, io, json, os, subprocess, sys, tempfile, time

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pre-commit-secret-scan.py")
os.environ["CLAUDE_PIPELINE_HOME"] = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
base = os.path.join(tempfile.gettempdir(), f"hooknative_{int(time.time() * 1000)}")
repo = os.path.join(base, "repo")
remote = os.path.join(base, "remote.git")
os.makedirs(repo)
SECRET_LINE = "AWS_" + "KEY=AK" + "IAABCDEFGHIJKLMNOP\n"
SECRET_LINE2 = "AWS_" + "KEY=AK" + "IAQRSTUVWXYZABCDEF\n"
results = []


def sh(cwd, *a, check=True, env=None, stdin=None):
    return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          check=check, env=env, input=stdin)


def hook(command, cwd=repo, tool="Bash", file_path=None):
    tool_input = {"file_path": file_path} if file_path else {"command": command}
    payload = json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": cwd})
    r = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True, encoding="utf-8")
    if not r.stdout.strip():
        return "ALLOW", "", r.stderr
    return "DENY", json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"], r.stderr


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("PASS" if ok else "FAIL", name, "" if ok else f"| {detail[-300:]}")


def expect(name, command, expected, cwd=repo, tool="Bash", reason_has=None, file_path=None):
    got, reason, _ = hook(command, cwd, tool, file_path)
    ok = got == expected and (reason_has is None or reason_has in reason)
    check(f"[{tool}] {name} -> {got}", ok, reason)


def write(folder, name, text):
    path = os.path.join(folder, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def configure(path):
    for k, v in (("user.email", "t@t.com"), ("user.name", "t"), ("core.autocrlf", "false")):
        sh(path, "git", "config", k, v)


sh(base, "git", "init", "-q", "--bare", remote)
sh(repo, "git", "init", "-q", "-b", "main")
configure(repo)
sh(repo, "git", "remote", "add", "origin", remote)
hooks_dir = os.path.join(repo, ".git", "hooks")
write(hooks_dir, "pre-commit", "#!/bin/sh\necho chained-ran >> \"$(git rev-parse --git-dir)/chained.log\"\n"
                               "[ ! -f block-me ] || { echo chained-blocked >&2; exit 3; }\n")
os.chmod(os.path.join(hooks_dir, "pre-commit"), 0o755)

r = sh(repo, sys.executable, HOOK, "--install-pre-commit", "--install-pre-push", "--enable-gate", check=False)
check("install both hooks and enable the gate", r.returncode == 0 and "pre-commit" in r.stdout
      and "pre-push" in r.stdout and "pipeline.gate" in r.stdout, r.stdout + r.stderr)
check("foreign pre-commit kept as pre-commit.pipeline-chained",
      "chained-ran" in open(os.path.join(hooks_dir, "pre-commit.pipeline-chained")).read())
check("pre-commit shim carries the marker", "secretscan-managed" in open(os.path.join(hooks_dir, "pre-commit")).read())
check("pipeline.gate is set", sh(repo, "git", "config", "--get", "pipeline.gate").stdout.strip() == "true")
r = sh(repo, sys.executable, HOOK, "--install-pre-commit", check=False)
check("reinstall is idempotent and keeps the chained hook", r.returncode == 0
      and os.path.exists(os.path.join(hooks_dir, "pre-commit.pipeline-chained")), r.stderr)
other = os.path.join(base, "other")
os.makedirs(other)
sh(other, "git", "init", "-q")
write(os.path.join(other, ".git", "hooks"), "pre-commit", "#!/bin/sh\nexit 0\n")
write(os.path.join(other, ".git", "hooks"), "pre-commit.pipeline-chained", "#!/bin/sh\nexit 0\n")
r = sh(other, sys.executable, HOOK, "--install-pre-commit", check=False)
check("foreign hook plus an existing chained file: refuses, overwrites nothing",
      r.returncode == 2 and "secretscan" not in open(os.path.join(other, ".git", "hooks", "pre-commit")).read(), r.stderr)

write(repo, "cfg.txt", SECRET_LINE)
sh(repo, "git", "add", "cfg.txt")
r = sh(repo, "git", "commit", "-q", "-m", "initial with secret", check=False)
check("native pre-commit blocks a secret in the first commit (no HEAD yet)",
      r.returncode != 0 and "Secret scan blocked this commit" in r.stderr, r.stderr)
check("the chained hook ran first", "chained-ran" in open(os.path.join(repo, ".git", "chained.log")).read())
sh(repo, "git", "rm", "-q", "--cached", "cfg.txt")
os.remove(os.path.join(repo, "cfg.txt"))
write(repo, "a.txt", "base\n")
write(repo, ".pipeline-secrets-allow", "# user entries\n")
sh(repo, "git", "add", "-A")
r = sh(repo, "git", "commit", "-q", "-m", "base", check=False)
check("clean commit passes both hooks", r.returncode == 0, r.stderr)
write(repo, "block-me", "x\n")
r = sh(repo, "git", "commit", "-q", "--allow-empty", "-m", "chained blocks", check=False)
check("a failing chained hook blocks the commit", r.returncode != 0 and "chained-blocked" in r.stderr, r.stderr)
os.remove(os.path.join(repo, "block-me"))
sh(repo, "git", "push", "-q", "origin", "main")

alt_index = os.path.join(base, "alt-index")
env = dict(os.environ, GIT_INDEX_FILE=alt_index)
sh(repo, "git", "read-tree", "HEAD", env=env)
write(repo, "cfg.txt", SECRET_LINE)
sh(repo, "git", "add", "cfg.txt", env=env)
r = sh(repo, "git", "commit", "-q", "-m", "relocated index", env=env, check=False)
check("native pre-commit scans a relocated GIT_INDEX_FILE", r.returncode != 0 and "Secret scan blocked" in r.stderr,
      r.stderr)
blob = sh(repo, "git", "hash-object", "-w", "cfg.txt").stdout.strip()
sh(repo, "git", "update-index", "--add", "--cacheinfo", f"100644,{blob},plumb.txt")
r = sh(repo, "git", "commit", "-q", "-m", "plumbing", check=False)
check("native pre-commit scans what update-index staged", r.returncode != 0 and "plumb.txt" in r.stderr, r.stderr)
r = sh(repo, "git", "commit", "-q", "-m", "commit -a", "-a", check=False)
check("native pre-commit scans commit -a", r.returncode != 0, r.stderr)
sh(repo, "git", "reset", "-q")
os.remove(os.path.join(repo, "cfg.txt"))
fp = sh(repo, sys.executable, HOOK, "--fingerprint", "--path", "cfg.txt", stdin=SECRET_LINE).stdout.split()[0]
write(repo, "cfg.txt", SECRET_LINE)
write(repo, ".pipeline-secrets-allow", f"# user entries\n{fp}  # test fixture\n")
sh(repo, "git", "add", "cfg.txt")
r = sh(repo, "git", "commit", "-q", "-m", "allowlist only in the working tree", check=False)
check("native pre-commit ignores an allowlist entry that is not staged", r.returncode != 0, r.stderr)
sh(repo, "git", "add", ".pipeline-secrets-allow")
r = sh(repo, "git", "commit", "-q", "-m", "allowlisted", check=False)
check("native pre-commit honours the allowlist read from the index", r.returncode == 0, r.stderr)
sh(repo, "git", "reset", "-q", "--hard", "HEAD~1")

expect("commit --no-verify", "git commit --no-verify -m x", "DENY", reason_has="hooks")
expect("commit -n", "git commit -n -m x", "DENY", reason_has="hooks")
expect("commit -anm (bundled)", "git commit -anm x", "DENY", reason_has="hooks")
expect("commit --no-veri (abbreviated)", "git commit --no-veri -m x", "DENY", reason_has="hooks")
expect("alias to commit -n", "git -c alias.c='commit -n' c -m x", "DENY", reason_has="hooks")
expect("push --no-verify", "git push --no-verify origin main", "DENY", reason_has="hooks")
expect("commit -m with a message starting with -n", 'git commit --allow-empty -m "-n is fine here"', "ALLOW")
expect("-c core.hooksPath on commit", "git -c core.hooksPath=/dev/null commit -m x", "DENY",
       reason_has="settings")
expect("GIT_CONFIG_* core.hooksPath", "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/x "
       "git commit -m x", "DENY")
expect("GIT_CONFIG_GLOBAL on commit", "GIT_CONFIG_GLOBAL=/tmp/evil git commit -m x", "DENY", reason_has="hooks")
expect("git config core.hooksPath", "git config core.hooksPath /dev/null", "DENY", reason_has="settings")
expect("git config --local core.hookspath (any case)", "git config --local core.hookspath x", "DENY")
expect("git config pipeline.gate false", "git config pipeline.gate false", "DENY", reason_has="settings")
expect("git config --unset pipeline.gate", "git config --unset pipeline.gate", "DENY")
expect("git config --remove-section pipeline", "git config --remove-section pipeline", "DENY")
expect("git config set (new syntax)", "git config set pipeline.gate false", "DENY")
expect("git config --edit", "git config --edit", "DENY")
expect("git config url insteadOf", "git config url./x.insteadOf https://github.com/", "DENY")
expect("git config remote pushurl", "git config remote.origin.pushurl /tmp/x.git", "DENY")
expect("git config --global pipeline.home", "git config --global pipeline.home /x", "DENY")
expect("reading pipeline.gate", "git config --get pipeline.gate", "ALLOW")
expect("listing config", "git config --list", "ALLOW")
expect("setting user.name", "git config user.name someone", "ALLOW")
expect("rm of the native hook", "rm .git/hooks/pre-commit", "DENY", reason_has="hooks")
expect("redirect into the native hook", "echo 'exit 0' > .git/hooks/pre-push", "DENY", reason_has="hooks")
expect("PowerShell Remove-Item of the hooks folder", "Remove-Item -Recurse .git\\hooks", "DENY", tool="PowerShell")
expect("reading the hook with grep", "grep secretscan-managed .git/hooks/pre-commit", "ALLOW")
expect("reading .git/config with cat", "cat .git/config", "ALLOW")
expect("Write to a native hook", None, "DENY", tool="Write", file_path=os.path.join(repo, ".git", "hooks", "pre-commit"),
       reason_has="hooks")
expect("Edit of .git/config", None, "DENY", tool="Edit", file_path=repo + "/.git/config", reason_has="hooks")
expect("Write to an ordinary .gitconfig-like name", None, "ALLOW", tool="Write",
       file_path=os.path.join(repo, "docs", "git-config.md"))

approvals = os.path.join(repo, ".git", "gate-approved")
write(repo, "b.txt", "clean\n")
sh(repo, "git", "add", "b.txt")
sh(repo, "git", "commit", "-q", "-m", "clean b")
expect("gate on through pipeline.gate alone (no docs/quality-reports)", "git push origin main", "DENY",
       reason_has="gate agent's approval")
tree = sh(repo, "git", "rev-parse", "HEAD^{tree}").stdout.strip()
write(repo, os.path.join(".git", "gate-approved"), f"{tree} test\n")
got, reason, stderr = hook("git push origin main")
check("approved tree pushes, and no warning while the native hooks are installed",
      got == "ALLOW" and "not installed" not in stderr, reason + stderr)
os.rename(os.path.join(hooks_dir, "pre-push"), os.path.join(base, "pre-push.saved"))
got, reason, stderr = hook("git push origin main")
check("PreToolUse warns on stderr when a native hook is missing in a gated repo",
      got == "ALLOW" and "pre-push hook(s) are not installed" in stderr, stderr)
os.rename(os.path.join(base, "pre-push.saved"), os.path.join(hooks_dir, "pre-push"))
sh(repo, "git", "push", "-q", "origin", "main")

write(repo, "cfg.txt", SECRET_LINE)
sh(repo, "git", "add", "cfg.txt")
sh(repo, "git", "commit", "-q", "--no-verify", "-m", "secret made in a terminal")
secret_head = sh(repo, "git", "rev-parse", "HEAD").stdout.strip()
write(repo, os.path.join(".git", "gate-approved"),
      sh(repo, "git", "rev-parse", "HEAD^{tree}").stdout.strip() + " test\n")
forgeries = [
    ("fetch . main:refs/remotes/origin/main", [["git", "fetch", "-q", ".", "main:refs/remotes/origin/main"]]),
    ("remote add loop . && fetch loop", [["git", "remote", "add", "loop", "."], ["git", "fetch", "-q", "loop"]]),
    ("copy of refs/heads/main into refs/remotes/origin/main", "copy"),
]
for name, steps in forgeries:
    if steps == "copy":
        ref_file = os.path.join(repo, ".git", "refs", "remotes", "origin", "main")
        os.makedirs(os.path.dirname(ref_file), exist_ok=True)
        with open(ref_file, "w", newline="\n") as handle:
            handle.write(secret_head + "\n")
    else:
        for step in steps:
            sh(repo, *step)
    forged = sh(repo, "git", "rev-parse", "refs/remotes/origin/main").stdout.strip() == secret_head \
        or sh(repo, "git", "rev-parse", "--verify", "-q", "refs/remotes/loop/main", check=False).stdout.strip() == secret_head
    got, reason, _ = hook("git push origin main")
    check(f"forged tracking ref ({name}) does not hide the secret from the PreToolUse push check",
          forged and got == "DENY" and "Secret scan blocked this push" in reason, reason)
    r = sh(repo, "git", "push", "origin", "main", check=False)
    check(f"forged tracking ref ({name}) does not hide the secret from the native pre-push",
          r.returncode != 0 and "Secret scan blocked this push" in r.stderr, r.stderr)
    sh(repo, "git", "update-ref", "refs/remotes/origin/main", sh(remote, "git", "rev-parse", "main").stdout.strip())
    sh(repo, "git", "remote", "remove", "loop", check=False)

sh(repo, "git", "checkout", "-q", "-b", "feat")
sh(repo, "git", "fetch", "-q", ".", "feat:refs/remotes/origin/feat")
r = sh(repo, "git", "push", "origin", "feat", check=False)
check("native pre-push: new branch with a forged tracking ref is still scanned",
      r.returncode != 0 and "Secret scan blocked this push" in r.stderr, r.stderr)
sh(repo, "git", "update-ref", "-d", "refs/remotes/origin/feat")
sh(repo, "git", "checkout", "-q", "main")

sh(repo, "git", "config", "remote.origin.url", ".")
sh(repo, "git", "config", "remote.origin.pushurl", remote)
got, reason, _ = hook("git push origin main")
check("remote state comes from the push URL, not a fetch URL pointing at the local repo",
      got == "DENY" and "Secret scan blocked this push" in reason, reason)
sh(repo, "git", "config", "remote.origin.url", remote)
sh(repo, "git", "config", "--unset", "remote.origin.pushurl")

expect("fetch into refs/remotes with an explicit refspec", "git fetch . main:refs/remotes/origin/main", "DENY",
       reason_has="remote-tracking ref")
expect("forced fetch refspec into refs/remotes", "git fetch origin +main:refs/remotes/origin/x", "DENY")
expect("pull with a refspec into refs/remotes", "git pull . main:refs/remotes/origin/main", "DENY")
expect("remote add with . as the URL", "git remote add loop .", "DENY", reason_has="remote-tracking ref")
expect("remote add with a relative path", "git remote add loop ../elsewhere", "DENY")
expect("remote add with a file:// URL", "git remote add loop file:///tmp/x", "DENY")
expect("remote set-url to a local path", "git remote set-url origin /tmp/x.git", "DENY")
expect("cp into .git/refs/remotes", "cp .git/refs/heads/main .git/refs/remotes/origin/main", "DENY",
       reason_has="remote-tracking ref")
expect("remote add with an https URL", "git remote add gh https://github.com/a/b.git", "ALLOW")
expect("remote add with an scp-like URL", "git remote add gh git@github.com:a/b.git", "ALLOW")
expect("plain fetch", "git fetch origin", "ALLOW")
expect("fetch into a local branch", "git fetch origin main:refs/heads/tmp", "ALLOW")
expect("symbolic-ref read of origin/HEAD", "git symbolic-ref refs/remotes/origin/HEAD", "ALLOW")
expect("symbolic-ref --short read", "git symbolic-ref --short refs/remotes/origin/HEAD", "ALLOW")
expect("symbolic-ref -q read", "git symbolic-ref -q refs/remotes/origin/HEAD", "ALLOW")
expect("symbolic-ref write", "git symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/main", "DENY")
expect("symbolic-ref -m write", "git symbolic-ref -m why refs/remotes/origin/HEAD refs/remotes/origin/x", "DENY")
expect("symbolic-ref --delete", "git symbolic-ref --delete refs/remotes/origin/HEAD", "DENY")
expect("update-ref of a remote-tracking ref", "git update-ref refs/remotes/origin/x HEAD",
       "DENY")

spec = importlib.util.spec_from_file_location("scan", HOOK)
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)
sh(repo, "git", "remote", "add", "gone", os.path.join(base, "missing.git"))
sh(repo, "git", "update-ref", "refs/remotes/gone/main", "HEAD~1")
saved_cap = scanner.FALLBACK_CAP
check("unreachable remote: falls back to that remote's tracking refs (secret still found)",
      "Secret scan blocked" in (scanner.push_reason(repo, repo, [("gone", False), ("main", False)]) or ""))
sh(repo, "git", "update-ref", "-d", "refs/remotes/gone/main")
scanner.FALLBACK_CAP = 1
reason = scanner.push_reason(repo, repo, [("gone", False), ("main", False)]) or ""
check("unreachable remote with more outgoing commits than the cap: denied with a clear message",
      "Cannot tell which commits gone already has" in reason, reason)
scanner.FALLBACK_CAP = saved_cap
sh(repo, "git", "update-ref", "refs/remotes/origin/main", "HEAD")
check("fallback only trusts the tracking refs of the remote being pushed to",
      "Secret scan blocked" in (scanner.push_reason(repo, repo, [("gone", False), ("main", False)]) or ""))
sh(repo, "git", "update-ref", "refs/remotes/origin/main", sh(remote, "git", "rev-parse", "main").stdout.strip())

expect("g\\it push", "g\\it push origin main", "DENY", reason_has="Secret scan blocked this push")
sh(repo, "git", "reset", "-q", "--hard", sh(remote, "git", "rev-parse", "main").stdout.strip())
write(repo, "cfg.txt", SECRET_LINE2)
sh(repo, "git", "add", "cfg.txt")
expect("g''it commit", "g''it commit -m x", "DENY", reason_has="Secret scan blocked this commit")
sh(repo, "git", "reset", "-q")
expect('"g"it add -A then commit', '"g"it add -A && git commit -m x', "DENY", reason_has="Secret scan blocked")
expect("g\\it commit --no-verify", "g\\it commit --no-verify -m x", "DENY", reason_has="hooks")
sh(repo, "git", "add", "cfg.txt")
expect("PowerShell g`it commit", "g`it commit -m x", "DENY", tool="PowerShell", reason_has="Secret scan blocked")
os.remove(os.path.join(repo, "cfg.txt"))


def crash_verdict(command, tool="Bash"):
    saved = (sys.stdin, sys.stdout, scanner.main)
    scanner.main = lambda raw: 1 / 0
    sys.stdin = io.TextIOWrapper(io.BytesIO(json.dumps({"tool_name": tool, "tool_input": {"command": command},
                                                        "cwd": repo}).encode("utf-8")), encoding="utf-8")
    sys.stdout = io.StringIO()
    try:
        scanner.run()
    except SystemExit:
        pass
    finally:
        output = sys.stdout.getvalue()
        sys.stdin, sys.stdout, scanner.main = saved
    return "DENY" if output.strip() else "ALLOW"


for command in ("g\\it push", "g''it commit -m x", '"g"it add -A', "git config core.hooksPath x",
                "git fetch . main:refs/remotes/origin/main", "rm .git/hooks/pre-commit"):
    check(f"hook crash still denies {command}", crash_verdict(command) == "DENY")
check("hook crash still allows g\\it status", crash_verdict("g\\it status") == "ALLOW")

relocations = [
    ("export with a quote-split name", 'export GIT_INDEX""_FILE=/tmp/i; git commit -m x', "Bash"),
    ("export with an escape-split name", "export GIT_\\DIR=/tmp/x; git add a.txt", "Bash"),
    ("declare -x with a quoted, split name", 'declare -x "GIT_INDEX""_FILE=/tmp/i"; git commit -m x', "Bash"),
    ("export of a dynamic name", 'export "$N=/tmp/x"; git add a.txt', "Bash"),
    ("export GIT_CONFIG_GLOBAL", "export GIT_CONFIG_GLOBAL=/tmp/evil; git commit -m x", "Bash"),
    ("source a file", "source ./e.sh && git add a.txt", "Bash"),
    ("dot a file", ". ./e.sh; git commit -m x", "Bash"),
    ("eval", 'eval "$SETUP"; git push origin main', "Bash"),
    ("set -a", "set -a; git add a.txt", "Bash"),
    ("set -o allexport", "set -o allexport; git add a.txt", "Bash"),
    ("PowerShell env: path with a variable name", "$n = 'GIT_DIR'; Set-Item \"env:$n\" C:/x; git add a.txt",
     "PowerShell"),
    ("PowerShell SetEnvironmentVariable with a variable name",
     "[Environment]::SetEnvironmentVariable($n, 'C:/x'); git add a.txt", "PowerShell"),
    ("PowerShell ${env:} assignment", "${env:GIT_WORK_TREE} = 'C:/x'; git add a.txt", "PowerShell"),
    ("PowerShell dot-source", ". .\\env.ps1; git commit -m x", "PowerShell"),
    ("PowerShell Invoke-Expression", "Invoke-Expression $s; git add a.txt", "PowerShell"),
]
for name, command, tool in relocations:
    expect(f"relocation: {name}", command, "DENY", tool=tool, reason_has="--git-dir/--work-tree")
not_relocations = [
    ("python reading GIT_DIR", "python -c \"import os; print(os.environ.get('GIT_DIR'))\" && git add a.txt", "Bash"),
    ("node mentioning GIT_WORK_TREE", "node -e \"console.log(process.env.GIT_WORK_TREE)\"; git add a.txt", "Bash"),
    ("source before a read-only git command", "source ./e.sh && git status", "Bash"),
    ("set -e before git add", "set -euo pipefail; git add a.txt", "Bash"),
    ("PowerShell reading $env:GIT_DIR", "Write-Output $env:GIT_DIR; git add a.txt", "PowerShell"),
    ("PowerShell comparing $env:GIT_DIR", "if ($env:GIT_DIR -eq $null) { git add a.txt }", "PowerShell"),
]
for name, command, tool in not_relocations:
    expect(f"no relocation: {name}", command, "ALLOW", tool=tool)

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
