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


def bash(command, cwd=None):
    if cwd is None:
        return run_hook("Bash", {"command": command})
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd})
    r = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True, encoding="utf-8")
    return "ALLOW" if not r.stdout.strip() else "DENY"


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
os.makedirs(os.path.join(repo, "sub"))
write(os.path.join("sub", "b.txt"), "base\n")
FP = "ab" * 32
FP2 = "cd" * 32
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
denied += ['echo abc | git -c "alias.r=!tee -a .pipeline-secrets-allow" r',
           "git -c alias.r='!cp /tmp/x .pipeline-secrets-allow' r",
           "git -c 'alias.c=!git add .pipeline-secrets-allow && git commit -m x' c",
           "git --config-env=alias.r=X r .pipeline-secrets-allow",
           "git -c diff.external=x diff -- .pipeline-secrets-allow",
           "GIT_EXTERNAL_DIFF=x git diff -- .pipeline-secrets-allow",
           "GIT_CONFIG_PARAMETERS=x git log -- .pipeline-secrets-allow",
           "git grep -Ocat x -- .pipeline-secrets-allow",
           "git grep --open-files-in-pager=vi x -- .pipeline-secrets-allow",
           "git r .pipeline-secrets-allow"]
for command in denied:
    check(f"denied: {command}", bash(command) == "DENY")

allowed = ['git commit -m "mention .pipeline-secrets-allow"', "git commit -m 'update *secrets* docs'",
           "git log -p -- .pipeline-secrets-allow", "git diff -- '.pipeline-*'", "cat .pipeline-*",
           "ls *", "rm *.tmp", "git add src/*.py", "git log --output=out.txt", "git -c core.pager=cat log",
           "git diff --ext-diff", "git show HEAD:.pipeline-secrets-allow",
           "git grep x -- .pipeline-secrets-allow", "git -C sub log -- ../.pipeline-secrets-allow"]
for command in allowed:
    check(f"allowed: {command}", bash(command) == "ALLOW")

write(ALLOW, f"# user entries\n{FP}  # pending\n")
for command in ("git commit -a -m x", "git commit -am x", "git commit --all -m x", "git add -A", "git add .",
                "git add -u", "git add -A && git commit -m x", "powershell -Command \"git add --all\"",
                "git add '*.*'", 'git add "?*"', 'git add ":/**"', "git add ./.", "git add -f '*'",
                'git commit -m x -- "*.*"', "git commit -m x -- .", "cd sub && git add ..", "git -C sub add ..",
                "git -C sub add :/", "git add --pathspec-from-file=list.txt", 'git add "$X"'):
    check(f"unstaged allowlist edit: {command} denied", bash(command) == "DENY")
for command in ("cd sub && git add .", "git -C sub add .", "git -C sub add -A .", "git add sub",
                "git add '*.txt'", "cd sub && git add -u ."):
    check(f"unstaged allowlist edit: {command} allowed (the pathspec cannot reach the root file)",
          bash(command) == "ALLOW")
check("unstaged allowlist edit: git add . from a subdirectory (tool cwd) allowed",
      bash("git add .", cwd=os.path.join(repo, "sub")) == "ALLOW")
check("unstaged allowlist edit: git add .. from a subdirectory (tool cwd) denied",
      bash("git add ..", cwd=os.path.join(repo, "sub")) == "DENY")
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
      r.returncode == 0 and "Warning" in r.stderr and f"{FP}  # pending" in r.stderr
      and "# user entries" not in r.stderr.split("Warning", 1)[1], r.stderr)
write("a.txt", "again\n")
sh(repo, "git", "commit", "-q", "-am", "no allowlist change")
r = sh(repo, "git", "push", "origin", "HEAD:refs/heads/main", check=False)
check("pre-push is silent when the allowlist did not change", r.returncode == 0 and "Warning" not in r.stderr, r.stderr)
write(".gitattributes", "/.pipeline-secrets-allow binary\n")
write(ALLOW, f"# user entries\n{FP}  # pending\n{FP2}  # hidden from diffs\n")
sh(repo, "git", "add", ".gitattributes", ALLOW)
sh(repo, "git", "commit", "-q", "-m", "binary allowlist")
r = sh(repo, "git", "push", "origin", "HEAD:refs/heads/main", check=False)
check("pre-push lists a new entry even when the allowlist is marked binary",
      r.returncode == 0 and f"{FP2}  # hidden from diffs" in r.stderr and f"{FP}  # pending" not in r.stderr, r.stderr)
head = sh(repo, "git", "rev-parse", "HEAD").stdout.strip()
r = subprocess.run([sys.executable, HOOK, "--pre-push"], cwd=repo, capture_output=True, text=True, encoding="utf-8",
                   input=f"refs/heads/main {head} refs/heads/main {'1' * 40}\n")
check("pre-push says so when the remote state is unknown, and lists every entry",
      r.returncode == 0 and "remote state unknown" in r.stderr and FP in r.stderr and FP2 in r.stderr, r.stderr)
r = subprocess.run([sys.executable, HOOK, "--pre-push"], cwd=repo, capture_output=True, text=True, encoding="utf-8",
                   input=f"refs/heads/new {head} refs/heads/new {'0' * 40}\n")
check("pre-push to a new remote branch compares with the remote-tracking branches",
      r.returncode == 0 and "Warning" not in r.stderr, r.stderr)

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
