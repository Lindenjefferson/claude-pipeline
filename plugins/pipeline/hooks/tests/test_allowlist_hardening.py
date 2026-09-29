import importlib.util, json, os, subprocess, sys, tempfile, time

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pre-commit-secret-scan.py")
os.environ["CLAUDE_PIPELINE_HOME"] = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
base = os.path.join(tempfile.gettempdir(), f"allowhard_{int(time.time() * 1000)}")
repo = os.path.join(base, "repo")
remote = os.path.join(base, "remote.git")
os.makedirs(repo)
ALLOW = ".pipeline-secrets-allow"
results = []


def sh(cwd, *a, check=True):
    return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=check)


def run_hook(name, tool_input):
    payload = json.dumps({"tool_name": name, "tool_input": tool_input, "cwd": repo})
    r = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True, encoding="utf-8")
    if not r.stdout.strip():
        return "ALLOW"
    return "DENY" if ALLOW in json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"] else "OTHER"


def bash(command):
    return run_hook("Bash", {"command": command})


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("PASS" if ok else "FAIL", name, "" if ok else detail)


def write(name, text):
    with open(os.path.join(repo, name), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


sh(base, "git", "init", "-q", "--bare", remote)
sh(repo, "git", "init", "-q")
for k, v in (("user.email", "t@t.com"), ("user.name", "t"), ("core.autocrlf", "false")):
    sh(repo, "git", "config", k, v)
sh(repo, "git", "remote", "add", "origin", remote)
write("a.txt", "base\n")
write(ALLOW, "# user entries\n")
sh(repo, "git", "add", "-A")
sh(repo, "git", "commit", "-q", "-m", "base")
sh(repo, "git", "push", "-q", "origin", "HEAD:refs/heads/main")
write("a.txt", "changed\n")

for command in ("git commit -a -m x", "git commit -am x", "git commit --all -m x", "git add -A", "git add --all",
                "git add .", "git add -u", "git add -u && git commit -m x", "git stage -A"):
    check(f"clean allowlist: {command} allowed", bash(command) == "ALLOW")

denied = ["git commit -m x .pipeline-secrets-allow", "git commit -o .pipeline-secrets-allow -m x",
          "git commit --only -m x -- .pipeline-secrets-allow", "git commit -i .pipeline-secrets-allow -m x",
          "git commit --include .pipeline-secrets-allow -m x",
          "git diff --output=.pipeline-secrets-allow", "git log --output .pipeline-secrets-allow",
          "git -c core.pager='tee .pipeline-secrets-allow' log", "git -c pager.log=cat log -- .pipeline-secrets-allow",
          "GIT_PAGER=cat git log -p -- .pipeline-secrets-allow", "git diff --ext-diff -- .pipeline-secrets-allow",
          "git diff --ext-diff -- '.pipeline-*'",
          "cp /tmp/x .pipeline-secrets-*", "rm .pipeline-*", "mv x '*secrets*'", "cp x .pipeline-secrets-a?low",
          "cp x .pipeline-secrets-[a]llow", "rm .*", "git add '.pipeline-secrets-*'", "git commit -m x -- '*secrets*'",
          "git checkout -- '.pipeline-*'", "bash -c 'cp x .pipeline-s*'"]
for command in denied:
    check(f"denied: {command}", bash(command) == "DENY")

allowed = ['git commit -m "mention .pipeline-secrets-allow"', "git commit -m 'update *secrets* docs'",
           "git log -p -- .pipeline-secrets-allow", "git diff -- '.pipeline-*'", "cat .pipeline-*",
           "ls *", "rm *.tmp", "git add src/*.py", "git log --output=out.txt", "git -c core.pager=cat log",
           "git diff --ext-diff", "git show HEAD:.pipeline-secrets-allow"]
for command in allowed:
    check(f"allowed: {command}", bash(command) == "ALLOW")

write(ALLOW, "# user entries\nabc  # pending\n")
for command in ("git commit -a -m x", "git commit -am x", "git commit --all -m x", "git add -A", "git add .",
                "git add -u", "git add -A && git commit -m x", "powershell -Command \"git add --all\""):
    check(f"unstaged allowlist edit: {command} denied", bash(command) == "DENY")
check("unstaged allowlist edit: git add of another file allowed", bash("git add a.txt") == "ALLOW")
check("unstaged allowlist edit: plain git commit allowed", bash("git commit -m x") != "DENY")
sh(repo, "git", "add", ALLOW)
check("staged by the user: git commit -a allowed", bash("git commit -a -m x") == "ALLOW")
sh(repo, "git", "commit", "-q", "-m", "user adds entry")

sh(repo, "git", "rm", "-q", "--cached", ALLOW)
sh(repo, "git", "commit", "-q", "-m", "untrack")
check("untracked allowlist: git add -A denied", bash("git add -A") == "DENY")
check("untracked allowlist: git add . denied", bash("git add .") == "DENY")
check("untracked allowlist: git add -u allowed (it skips untracked files)", bash("git add -u") == "ALLOW")
check("untracked allowlist: git commit -a allowed (it skips untracked files)", bash("git commit -a -m x") == "ALLOW")
sh(repo, "git", "add", ALLOW)
sh(repo, "git", "commit", "-q", "-m", "track again")

allow_path = os.path.join(repo, ALLOW)
for target in (allow_path + ".", allow_path + " ", allow_path + " . ", allow_path + "::$DATA",
               allow_path + ":stream", "C:" + ALLOW, allow_path.upper() + "::$data"):
    check(f"Write denied: {target[-30:]!r}", run_hook("Write", {"file_path": target, "content": "x"}) == "DENY")
for target in (os.path.join(repo, ALLOW + ".md"), os.path.join(repo, "x" + ALLOW), os.path.join(repo, "notes.txt")):
    check(f"Write allowed: {os.path.basename(target)}", run_hook("Write", {"file_path": target, "content": "x"}) == "ALLOW")

spec = importlib.util.spec_from_file_location("scan", HOOK)
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)
for token, expected in ((".pipeline-secrets-*", True), (".pipeline-*", True), ("*secrets*", True),
                        (".pipeline-secrets-a?low", True), ("*", False), ("*.*", False), ("*.py", False),
                        ("src/*", False), (".env*", False)):
    check(f"glob token {token!r} names the allowlist: {expected}", scanner.names_allowlist(token) == expected)

sh(repo, sys.executable, HOOK, "--install-pre-push")
r = sh(repo, "git", "push", "origin", "HEAD:refs/heads/main", check=False)
check("pre-push warns about allowlist lines the remote lacks, without blocking",
      r.returncode == 0 and "Warning" in r.stderr and "abc  # pending" in r.stderr
      and "# user entries" not in r.stderr.split("Warning", 1)[1], r.stderr)
write("a.txt", "again\n")
sh(repo, "git", "commit", "-q", "-am", "no allowlist change")
r = sh(repo, "git", "push", "origin", "HEAD:refs/heads/main", check=False)
check("pre-push is silent when the allowlist did not change", r.returncode == 0 and "Warning" not in r.stderr, r.stderr)

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
