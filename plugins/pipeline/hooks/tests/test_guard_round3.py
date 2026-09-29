import importlib.util, json, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "pre-commit-secret-scan.py")
base = os.path.join(tempfile.gettempdir(), f"guardround3_{int(time.time() * 1000)}")
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
os.environ.setdefault("HOME", os.path.expanduser("~"))
os.environ.setdefault("TEMP", tempfile.gettempdir())
os.environ["OUT"] = "build"
os.environ["SRC"] = "vendor"
os.environ["PWD"] = repo
for name in ("UNSET_X", "GIT_SSH", "GIT_SSH_COMMAND"):
    os.environ.pop(name, None)
results = []


def sh(cwd, *a, check=True):
    return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=check)


def hook_run(command, tool="Bash", cwd=None):
    key = "file_path" if tool == "Write" else "command"
    payload = json.dumps({"tool_name": tool, "tool_input": {key: command}, "cwd": cwd or repo})
    r = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True, encoding="utf-8")
    reason = json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"] if r.stdout.strip() else ""
    return ("DENY" if r.stdout.strip() else "ALLOW"), reason, r.stderr


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("PASS" if ok else "FAIL", name, "" if ok else f"| {str(detail)[-400:]}")


def expect(command, expected, tool="Bash", reason_has=None, reason_lacks=None, cwd=None):
    got, reason, stderr = hook_run(command, tool, cwd)
    ok = (got == expected and (reason_has is None or reason_has in reason)
          and (reason_lacks is None or reason_lacks not in reason))
    label = f"[{tool}] {command}" if tool != "Bash" else command
    check(f"{label} -> {expected}", ok, f"got {got}: {reason} {stderr}")


sh(repo, "git", "init", "-q", "-b", "main")
for k, v in (("user.email", "t@t.com"), ("user.name", "t"), ("core.autocrlf", "false")):
    sh(repo, "git", "config", k, v)
os.makedirs(os.path.join(repo, "src", "hooks"))
with open(os.path.join(repo, "src", "hooks", "useAuth.ts"), "w") as handle:
    handle.write("export {}\n")
sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-q", "-m", "base")

FIND_HINT = "-not -path './.git/*'"
for command in ('find . -name "*.ts" -exec grep -l useX {} +', 'find . -name "*.log" -delete',
                "find . -type d -name __pycache__ -exec rm -rf {} +", "find . -name '*.pyc' -delete",
                "find . -name node_modules -prune -o -name '*.log' -delete",
                "find . -path ./node_modules -prune -o -name '*.log' -delete",
                "find . -type f -exec sha256sum {} +", "find . -exec wc -l {} +",
                "find . -name '*.ts' -exec sed -i s/a/b/ {} +"):
    expect(command, "ALLOW")
for command in ("find . -name hooks -exec rm -rf {} +", "find . -name 'pre-*' -delete",
                "find . -path '*/.git/*' -delete", "find . -name .git -exec rm -rf {} +",
                "find . -name config -delete", "find . -iname PRE-PUSH -delete",
                "find . -name '*.pipeline-chained' -delete", "find . -delete",
                "find . -type f -exec sed -i s/a/b/ {} +", "find . -name node_modules -prune -o -delete",
                "find . -name '*.ts' -o -name 'pre-*' -delete"):
    expect(command, "DENY", reason_has=FIND_HINT, reason_lacks="--no-verify")

sh(repo, "git", "config", "core.hooksPath", ".husky")
os.makedirs(os.path.join(repo, ".husky"))
expect("find . -name '*.log' -delete", "ALLOW")
for command in ("find . -name .husky -exec rm -rf {} +", "find . -name 'pre-*' -delete"):
    expect(f"{command}", "DENY", reason_has=FIND_HINT)
expect("rm -rf src/hooks", "ALLOW")
sh(repo, "git", "config", "--unset", "core.hooksPath")

for command in ("cp $HOME/templates/hooks/useAuth.ts src/hooks/", 'mv "$SRC/hooks/useAuth.ts" src/',
                "rm -rf $OUT/hooks", "echo x > $PWD/src/hooks/a.ts", "rm -rf src/hooks",
                "cp src/hooks/useAuth.ts $UNSET_X/src/hooks/"):
    expect(command, "ALLOW")
expect("Copy-Item $env:TEMP\\hooks\\a.ts src\\hooks\\", "ALLOW", tool="PowerShell")
for command in ("rm -rf $UNSET_X/hooks", "rm $UNSET_X/.git/hooks/pre-push",
                "echo x > ${UNSET_X}/hooks/pre-push", "OUT=.git; rm -rf $OUT/hooks",
                "rm -rf $PWD/.git/hooks", "cp a $UNSET_X/hooks/pre-push"):
    expect(command, "DENY", reason_has="hooks")
expect("Remove-Item $env:UNSET_X\\hooks\\pre-push", "DENY", tool="PowerShell", reason_has="hooks")

home = os.path.expanduser("~")
fixture = os.path.join(repo, "tests", "fixtures", ".gitconfig")
for command in ("cp ~/.gitconfig backup.gitconfig", "cp $HOME/.gitconfig /tmp/backup",
                "echo '[user]' > tests/fixtures/.gitconfig", "cp a tests/fixtures/.gitconfig",
                "mv old.gitconfig tests/fixtures/.gitconfig", "rsync -a ~/.gitconfig backup/"):
    expect(command, "ALLOW")
expect("Copy-Item ~/.gitconfig backup.gitconfig", "ALLOW", tool="PowerShell")
expect("tests/fixtures/.gitconfig", "ALLOW", tool="Write")
expect(fixture, "ALLOW", tool="Write")
for command in ("cp x ~/.gitconfig", "cp -t ~ .gitconfig", "cp .gitconfig ~/", "mv ~/.gitconfig old",
                "cp config $XDG_CONFIG_HOME/git/", "rsync -a x ~/.gitconfig"):
    expect(command, "DENY", reason_has="global git config")
expect("Copy-Item -Destination ~/.gitconfig -Path a", "DENY", tool="PowerShell", reason_has="global git config")
expect("Copy-Item a $env:USERPROFILE\\.gitconfig", "DENY", tool="PowerShell", reason_has="global git config")
expect("~/.gitconfig", "DENY", tool="Write", reason_has="global git config")

for command in ("git config core.hooksPath", "git config --global core.hooksPath",
                "git config --show-origin core.hooksPath", "git config --get core.hooksPath",
                "git config --list --show-origin", "git config get core.hooksPath"):
    expect(command, "ALLOW")
for command in ("git config core.hooksPath x", "git config --unset core.hooksPath",
                "git config set core.hooksPath x", "git config --add core.hooksPath x",
                "git config --global core.hooksPath /tmp/x", "git config unset core.hooksPath",
                "git config pipeline.gate off"):
    expect(command, "DENY", reason_has="git settings")

sh(repo, "git", "worktree", "add", "-q", os.path.join(base, "wt"), "-b", "wt")
worktree_config = sh(os.path.join(base, "wt"), "git", "rev-parse", "--path-format=absolute", "--git-path",
                     "config.worktree").stdout.strip()
for command in ("echo x > .git/config.worktree", "rm .git/worktrees/wt/config.worktree",
                "cp a .git/config.worktree"):
    expect(command, "DENY", reason_has="hooks")
expect(".git/config.worktree", "DENY", tool="Write", reason_has="hooks")
expect(".git/worktrees/wt/config.worktree", "DENY", tool="Write", reason_has="hooks")
expect(f"echo x > '{worktree_config}'", "DENY", reason_has="hooks", cwd=os.path.join(base, "wt"))
expect("cat .git/config.worktree", "ALLOW")

for command in ("python scripts/x.py --no-verify-ssl", "node build.js --no-verify",
                "xargs python x.py --no-verify-ssl", "pwsh -NoProfile -File build.ps1 --no-verify"):
    expect(command, "ALLOW")
for command in ("python -c \"import os; os.system('git commit --no-verify')\"", "bash -lc 'git push --no-verify'",
                "cmd /c git commit --no-verify -m x", "echo x | xargs git commit --no-verify -m",
                "perl -e 'system(\"git push --no-verify\")'"):
    expect(command, "DENY", reason_has="no-verify")

spec = importlib.util.spec_from_file_location("scan", HOOK)
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)
check("ssh command defaults to ssh in batch mode",
      scan.batch_ssh_command(repo) == "ssh -o BatchMode=yes -o ConnectTimeout=10", scan.batch_ssh_command(repo))
sh(repo, "git", "config", "core.sshCommand", "ssh -i key")
check("core.sshCommand is kept and batch options appended",
      scan.batch_ssh_command(repo) == "ssh -i key -o BatchMode=yes -o ConnectTimeout=10", scan.batch_ssh_command(repo))
sh(repo, "git", "config", "--unset", "core.sshCommand")
os.environ["GIT_SSH"] = "plink"
check("a GIT_SSH program is left alone", scan.batch_ssh_command(repo) is None, scan.batch_ssh_command(repo))
os.environ.pop("GIT_SSH")

sleeper = os.path.join(base, "sleeper.py")
marker = os.path.join(base, "sleeper.json")
with open(sleeper, "w") as handle:
    handle.write("import json, os, sys, time\n"
                 f"json.dump({{'pid': os.getpid(), 'argv': sys.argv}}, open({marker!r}, 'w'))\n"
                 "time.sleep(60)\n")
os.environ["GIT_SSH_COMMAND"] = f'"{sys.executable}" "{sleeper}"'.replace("\\", "/")
scan.LS_REMOTE_TIMEOUT = 3
started = time.time()
answer = scan.ls_remote(repo, "ssh://git@example.invalid/team/repo.git")
elapsed = time.time() - started
check("ls-remote through a hanging ssh returns None within the timeout", answer is None and elapsed < 3 + 7,
      f"{answer} after {elapsed:.1f}s")
info = json.load(open(marker)) if os.path.exists(marker) else {}
check("the ssh command got BatchMode and ConnectTimeout",
      "BatchMode=yes" in info.get("argv", []) and "ConnectTimeout=10" in info.get("argv", []), info)
time.sleep(1)
if os.name == "nt":
    alive = str(info.get("pid")) in sh(base, "tasklist", "/FI", f"PID eq {info.get('pid')}", check=False).stdout
else:
    try:
        os.kill(info.get("pid"), 0)
        alive = True
    except OSError:
        alive = False
check("the hanging ssh process tree was killed", info.get("pid") and not alive, info)
os.environ.pop("GIT_SSH_COMMAND")

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
