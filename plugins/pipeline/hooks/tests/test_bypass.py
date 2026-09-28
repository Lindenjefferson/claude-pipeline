import json, os, subprocess, sys, tempfile, time

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pre-commit-secret-scan.py")
base = os.path.join(tempfile.gettempdir(), f"hookbypass_{int(time.time() * 1000)}")
repo = os.path.join(base, "repo")
remote = os.path.join(base, "remote.git")
os.makedirs(repo)
results = []
SECRET = "k = AKIA" + "ABCDEFGHIJKLMNOP\n"


def sh(*a, check=True):
    return subprocess.run(list(a), cwd=repo, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=check).stdout


def hook(command, tool="Bash"):
    payload = json.dumps({"tool_name": tool, "tool_input": {"command": command}, "cwd": repo})
    r = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True, encoding="utf-8")
    return "DENY" if r.stdout.strip() else "ALLOW"


def check(name, got, expected):
    ok = got == expected
    results.append(ok)
    print("PASS" if ok else "FAIL", name, "->", got)


def write(name, text):
    with open(os.path.join(repo, name), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def reset():
    sh("git", "reset", "-q", "--hard")
    sh("git", "clean", "-qfd")


sh("git", "init", "-q", "-b", "master")
for k, v in (("user.email", "t@t.com"), ("user.name", "t"), ("core.autocrlf", "false")):
    sh("git", "config", k, v)
subprocess.run(["git", "init", "-q", "--bare", remote], check=True, capture_output=True)
sh("git", "remote", "add", "origin", remote)
write("a.txt", "base\n")
sh("git", "add", "-A"); sh("git", "commit", "-q", "-m", "base")
sh("git", "push", "-q", "origin", "master")

# commit: changes staged by an earlier `git add` in the same command
write("s.txt", SECRET)
check("git add -A && git commit (untracked secret)", hook("git add -A && git commit -m x"), "DENY")
check("git add s.txt; git commit", hook("git add s.txt; git commit -m x"), "DENY")
check("git add . && git commit", hook("git add . && git commit -m x"), "DENY")
check("git stage s.txt && git commit", hook("git stage s.txt && git commit -m x"), "DENY")
check("bash -c 'git add -A && git commit'", hook("bash -c 'git add -A && git commit -m x'"), "DENY")
check("git add $F is unverifiable -> deny", hook('git add "$F" && git commit -m x'), "DENY")
check("cd $DIR && git add, then commit -> deny", hook('cd "$DIR" && git add . && cd - && git commit -m x'), "DENY")
check("git add $F with no commit after it", hook('git add "$F"'), "ALLOW")
check("cd $DIR && git add with no commit after it", hook('cd "$DIR" && git add .'), "ALLOW")
check("[PowerShell] git add -A; git commit", hook("git add -A; git commit -m x", "PowerShell"), "DENY")
check("[PowerShell] git add s.txt; if ($?) { git commit }",
      hook("git add s.txt; if ($?) { git commit -m x }", "PowerShell"), "DENY")
check("[PowerShell] powershell -Command 'git add -A; git commit'",
      hook("powershell -Command 'git add -A; git commit -m x'", "PowerShell"), "DENY")
check("[PowerShell] git add $env:F is unverifiable -> deny",
      hook("git add $env:NO_SUCH_VAR_X; git commit -m x", "PowerShell"), "DENY")
write("clean.txt", "nothing here\n")
check("[PowerShell] git add clean.txt; git commit", hook("git add clean.txt; git commit -m x", "PowerShell"), "ALLOW")
check("git add clean.txt && git commit (secret left untracked)", hook("git add clean.txt && git commit -m x"), "ALLOW")
check("secret untracked, plain git commit", hook("git commit -m x"), "ALLOW")
check("the real index is left untouched", sh("git", "diff", "--cached", "--name-only").strip(), "")
reset()

# commit: paths and -a pick up unstaged changes
write("a.txt", "base\n" + SECRET)
check("git commit -m x a.txt (pathspec)", hook("git commit -m x a.txt"), "DENY")
check("git commit -m x -- a.txt", hook("git commit -m x -- a.txt"), "DENY")
check("git commit -o a.txt -m x", hook("git commit -o a.txt -m x"), "DENY")
check("git commit -am x", hook("git commit -am x"), "DENY")
check("git commit -a -m x", hook("git commit -a -m x"), "DENY")
check("message naming the file is not a path", hook('git commit -m "a.txt"'), "ALLOW")
check("-F value is not a path", hook("git commit -F a.txt"), "ALLOW")
check("[PowerShell] git commit -m x a.txt", hook("git commit -m x a.txt", "PowerShell"), "DENY")
check("[PowerShell] git commit -am x", hook("git commit -am x", "PowerShell"), "DENY")
check("--author value is not a path", hook('git commit --author "a.txt <a@b>" -m x'), "ALLOW")
reset()

# push: the refs named on the command line, not HEAD
sh("git", "checkout", "-q", "-b", "leak")
write("s.txt", SECRET)
sh("git", "add", "-A"); sh("git", "commit", "-q", "-m", "leak")
sh("git", "tag", "v1")
sh("git", "tag", "-a", "v1a", "-m", "annotated")
sh("git", "checkout", "-q", "master")
check("git push origin leak (HEAD clean)", hook("git push origin leak"), "DENY")
check("git push origin leak:main", hook("git push origin leak:main"), "DENY")
check("git push origin +leak", hook("git push origin +leak"), "DENY")
check("git push origin refs/heads/leak", hook("git push origin refs/heads/leak"), "DENY")
check("git push -u origin leak", hook("git push -u origin leak"), "DENY")
check("git push --all origin", hook("git push --all origin"), "DENY")
check("git push --mirror origin", hook("git push --mirror origin"), "DENY")
check("git push origin v1 (lightweight tag)", hook("git push origin v1"), "DENY")
check("git push origin v1a (annotated tag)", hook("git push origin v1a"), "DENY")
check("git push origin tag v1", hook("git push origin tag v1"), "DENY")
check("git push --tags origin", hook("git push --tags origin"), "DENY")
check("git push origin 'refs/heads/*'", hook("git push origin 'refs/heads/*'"), "DENY")
check("git push origin $BRANCH is unverifiable -> deny", hook('git push origin "$BRANCH"'), "DENY")
check("[PowerShell] git push origin leak", hook("git push origin leak", "PowerShell"), "DENY")
check("[PowerShell] git push --all origin", hook("git push --all origin", "PowerShell"), "DENY")
check("[PowerShell] git push origin $env:BRANCH is unverifiable -> deny",
      hook("git push origin $env:NO_SUCH_VAR_X", "PowerShell"), "DENY")
check("[PowerShell] git push origin HEAD (clean)", hook("git push origin HEAD", "PowerShell"), "ALLOW")
check("git push origin HEAD (clean)", hook("git push origin HEAD"), "ALLOW")
check("git push origin master (clean)", hook("git push origin master"), "ALLOW")
check("git push (clean HEAD, default refspec)", hook("git push"), "ALLOW")
check("git push origin --delete leak", hook("git push origin --delete leak"), "ALLOW")
check("git push origin :leak (delete)", hook("git push origin :leak"), "ALLOW")
check("git push -o ci.skip origin master", hook("git push -o ci.skip origin master"), "ALLOW")
check("git push --dry-run origin leak", hook("git push --dry-run origin leak"), "ALLOW")
sh("git", "tag", "-d", "v1", "v1a")
sh("git", "branch", "-q", "-D", "leak")

# push gate: every ref leaving must be approved, not only HEAD
os.makedirs(os.path.join(repo, "docs", "quality-reports"))
write("docs/quality-reports/.gitkeep", "")
sh("git", "add", "-A"); sh("git", "commit", "-q", "-m", "opt in")
sh("git", "checkout", "-q", "-b", "feature")
write("f.txt", "feature\n")
sh("git", "add", "-A"); sh("git", "commit", "-q", "-m", "feature")
sh("git", "checkout", "-q", "master")
common = sh("git", "rev-parse", "--git-common-dir").strip()
with open(os.path.join(repo, common, "gate-approved"), "w") as handle:
    handle.write(sh("git", "rev-parse", "HEAD^{tree}").strip() + "\n")
check("gate: approved HEAD pushes", hook("git push origin master"), "ALLOW")
check("gate: unapproved other branch is blocked", hook("git push origin feature"), "DENY")
check("gate: --all includes the unapproved branch", hook("git push --all origin"), "DENY")
sh("git", "push", "-q", "--no-verify", "origin", "feature")
check("gate: branch already on the remote sends nothing", hook("git push origin feature"), "ALLOW")

# a cd inside a bash subshell does not outlive it
other = os.path.join(base, "other")
os.makedirs(other)
for args in (("init", "-q"), ("config", "user.email", "t@t.com"), ("config", "user.name", "t")):
    subprocess.run(["git", *args], cwd=other, check=True, capture_output=True)
with open(os.path.join(other, "s.txt"), "w", encoding="utf-8", newline="\n") as handle:
    handle.write(SECRET)
subprocess.run(["git", "add", "s.txt"], cwd=other, check=True, capture_output=True)
check("(cd other) && git commit targets this repo", hook("(cd ../other) && git commit -m x"), "ALLOW")
check("(cd other && git commit) targets the other repo", hook("(cd ../other && git commit -m x)"), "DENY")
check("{ cd other; } && git commit keeps the cd", hook("{ cd ../other; } && git commit -m x"), "DENY")
check("[PowerShell] (Set-Location other); git commit keeps the location",
      hook("(Set-Location ../other); git commit -m x", "PowerShell"), "DENY")

# git aliases resolve to the command they stand for
write("s.txt", SECRET)
sh("git", "config", "alias.ci", "commit")
sh("git", "config", "alias.cam", "commit -am")
sh("git", "config", "alias.save", "!git add -A && git commit")
sh("git", "config", "alias.pub", "push origin")
sh("git", "config", "alias.loop", "loop")
check("alias ci = commit, secret staged", hook("git add s.txt && git ci -m x"), "DENY")
check("alias save = !git add -A && git commit", hook("git save -m x"), "DENY")
check("[PowerShell] git add s.txt; git ci", hook("git add s.txt; git ci -m x", "PowerShell"), "DENY")
check("[PowerShell] alias save", hook("git save -m x", "PowerShell"), "DENY")
reset()
write("a.txt", "base\n" + SECRET)
check("alias cam = commit -am", hook("git cam x"), "DENY")
reset()
sh("git", "checkout", "-q", "-b", "leak2")
write("s.txt", SECRET)
sh("git", "add", "-A"); sh("git", "commit", "-q", "--no-verify", "-m", "leak2")
sh("git", "checkout", "-q", "master")
check("alias pub = push origin", hook("git pub leak2"), "DENY")
check("[PowerShell] alias pub = push origin", hook("git pub leak2", "PowerShell"), "DENY")
check("self-referencing alias does not hang", hook("git loop"), "ALLOW")
check("unaliased read-only command", hook("git status"), "ALLOW")

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
