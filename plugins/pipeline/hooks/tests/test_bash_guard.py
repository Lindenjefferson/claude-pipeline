import json, os, subprocess, sys, tempfile, time

HOOKS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SCRIPT = os.path.join(HOOKS, "bash-guard.py")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("PASS" if ok else "FAIL", name, "" if ok else f"| {detail[-300:]}")


def project(commands):
    folder = tempfile.mkdtemp(prefix="devserver_")
    with open(os.path.join(folder, "CLAUDE.md"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write("# Projeto\n\n## Comandos\n\n" + commands + "\n## Outra seção\n\n- Rodar em desenvolvimento: `ignored run`\n")
    return folder


def run(folder, command, background=False, tool="Bash", cwd=None, mode=None):
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "cwd": cwd or folder,
               "tool_input": {"command": command, "run_in_background": background}}
    if mode:
        payload["permission_mode"] = mode
    done = subprocess.run([sys.executable, SCRIPT], cwd=tempfile.gettempdir(), input=json.dumps(payload),
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    reason = None
    if done.stdout.strip():
        out = json.loads(done.stdout)["hookSpecificOutput"]
        assert out["hookEventName"] == "PreToolUse"
        reason = (out["permissionDecision"], out["permissionDecisionReason"])
    return done.returncode, reason, done.stderr


configured = project("- Rodar em desenvolvimento: `npm run dev`\n- Testes: `npm test`\n")

code, reason, err = run(configured, "npm run dev")
check("the configured dev server in the foreground is denied", code == 0 and reason and reason[0] == "deny", err)
check("the message shows the right form", reason and "run_in_background" in reason[1] and "npm run dev" in reason[1],
      str(reason))
check("the same command in background passes", run(configured, "npm run dev", background=True) == (0, None, ""))
check("extra arguments are still the dev server", run(configured, "npm  run dev -- --port 3001")[1] is not None)
check("after cd and &&", run(configured, "cd app && npm run dev")[1] is not None)
check("after an env assignment", run(configured, "PORT=3001 npm run dev")[1] is not None)
check("piped", run(configured, "npm run dev | tee log.txt")[1] is not None)
check("shell backgrounding with & is still denied (orphan process)", run(configured, "npm run dev &")[1] is not None)
check("another command passes", run(configured, "npm test")[1] is None)
check("a longer script name is not the dev server", run(configured, "npm run dev:docs")[1] is None)
check("the command quoted in other text passes", run(configured, "grep 'npm run dev' README.md")[1] is None)
check("not a Bash call passes", run(configured, "npm run dev", tool="Read")[1] is None)
check("a heredoc body that only mentions the command passes",
      run(configured, "cat > README.md <<'EOF'\n## Como rodar\nnpm run dev\nEOF\ngit add README.md")[1] is None)
check("a quoted message that mentions the command passes",
      run(configured, 'git commit -m "docs: explain the dev server (npm run dev)"')[1] is None)
check("after a quoted argument, the command itself is still denied",
      run(configured, 'echo "starting; really" && npm run dev')[1] is not None)
check("a heredoc fed to a shell is still denied", run(configured, "bash <<'EOF'\nnpm run dev\nEOF")[1] is not None)
start = time.monotonic()
run(configured, "echo " + "x" * 80000)
check("a long one-line command is read quickly (well under the hook's 10s timeout)", time.monotonic() - start < 3)
check("a here-string is not a heredoc: the next line is still read",
      run(configured, 'cat <<< "x"\nnpm run dev')[1] is not None)
sub = os.path.join(configured, "app")
os.makedirs(sub)
check("cwd in a subfolder still finds the project's CLAUDE.md", run(configured, "npm run dev", cwd=sub)[1] is not None)

placeholder = project("- Rodar em desenvolvimento: _(comando)_\n")
check("a placeholder line does nothing", run(placeholder, "npm run dev") == (0, None, ""))
check("a command declared outside the Comandos section does nothing",
      run(placeholder, "ignored run") == (0, None, ""))
nolines = project("- Testes: `npm test`\n")
check("without the line the hook does nothing", run(nolines, "npm run dev") == (0, None, ""))
bare = tempfile.mkdtemp(prefix="devserver_")
check("without a CLAUDE.md the hook does nothing", run(bare, "npm run dev") == (0, None, ""))

garbage = subprocess.run([sys.executable, SCRIPT], input="not json", capture_output=True, text=True)
check("garbage on stdin never blocks", garbage.returncode == 0 and garbage.stdout == "", garbage.stderr)

def skips(command, background=False, folder=None):
    reason = run(folder or bare, command, background=background)[1]
    return reason is not None and reason[0] == "deny" and "pre-commit" in reason[1]


for command in ('git commit --no-verify -m "x"', 'git commit -m "x" --no-verify', 'git commit -nm "x"',
                "git commit -am wip -n", "git commit -an -m ''", "git commit --no-veri -m x",
                'git commit "--no-verify" -m x', "cd sub && git commit -n -m x", "git -C repo commit -n -m x",
                "git -c core.hooksPath=/dev/null commit -m x", "git -c CORE.HOOKSPATH=x commit -m x",
                "git --config-env=core.hooksPath=EMPTY commit -m x", "GIT_CONFIG_KEY_0=core.hooksPath git commit -m x",
                "git config core.hooksPath /tmp/none", "git config set --local core.hooksPath x",
                "echo ok; git commit -n -m x", "echo $(git commit -n -m x)", "bash -c 'git commit -n -m x'",
                "/usr/bin/git commit -n -m x", "git.exe commit --no-verify -m x",
                "git commit -n -m \"$(cat <<'EOF'\nmsg\nEOF\n)\"", "echo a#b; git commit -n -m x",
                'git commit -m "#12 fix" -n', "git commit -m x 2>&1 -n", "git commit -m x &>log -n",
                "env git commit -n -m x", "env -i PATH=/bin nohup git commit -n -m x",
                "env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/x git commit -m x",
                "export GIT_CONFIG_KEY_0=core.hooksPath; git commit -m x", "time git commit -n -m x",
                "command git commit -n -m x", "if true; then git commit -n -m x; fi", "{ git commit -n -m x; }",
                "! git commit -n -m x", "bash -lc 'git commit -n -m x'", "sh -ec 'git commit -n -m x'",
                "bash -o pipefail -c 'git commit -n -m x'", "bash -O extglob -c 'git commit -n -m x'",
                "bash --rcfile f -c 'git commit -n -m x'", "bash --init-file f -c 'git commit -n -m x'",
                "bash -euo pipefail -c 'git commit -n -m x'", "bash +o history -c 'git commit -n -m x'",
                "git config --unset core.hooksPath", "git commit -n -m x # don't",
                "git commit --no-verify -F - <<'MSG-END'\nit's done\nMSG-END"):
    check(f"skipping the pre-commit hook is denied: {command!r}", skips(command))
check("skipping the hook is denied in background too", skips("git commit -n -m x", background=True))
check("skipping the hook is denied where the dev server is configured", skips("git commit -n -m x", folder=configured))
for command in ('git commit -m "docs: never use --no-verify"', 'git commit -m "fix: grep -n finds it"',
                "git commit -m \"$(cat <<'EOF'\nfix: explain --no-verify and git commit -n\nEOF\n)\"",
                "git commit -F - <<'EOF'\nchore: -n --no-verify\nEOF", "git commit -uno -m x",
                "git commit --no-verbose -m x", "git commit --amend --no-edit", "git commit -m x -- -n",
                "git log -n 3", "echo git commit -n", "git config --get core.hooksPath", "git config core.hooksPath",
                "grep -n x file && git commit -m y", 'git commit --message "-n items"',
                "git commit --author 'A <a@x>' --date -n -m x", "cat > notes.md <<'MD-EOF'\ngit commit -n -m x\nMD-EOF",
                "cat > notes.md <<\\EOF\ngit commit -n -m x\nEOF", "env | grep GIT",
                'git commit -m "unbalanced'):
    check(f"a commit that keeps the hook passes: {command!r}", run(bare, command)[1] is None, str(run(bare, command)))

LEDGER_PY = os.path.join(HOOKS, "..", "skills", "manager", "ledger.py")
repo = tempfile.mkdtemp(prefix="guard_")


def sh(*args):
    subprocess.run(args, cwd=repo, check=True, capture_output=True)


for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@t.com"), ("config", "user.name", "t"),
             ("commit", "-q", "--allow-empty", "-m", "base")):
    sh("git", *args)
sh(sys.executable, LEDGER_PY, "start", "--slug", "x")


def reaches_main(command):
    reason = run(repo, command)[1]
    return reason is not None and reason[0] == "deny" and "autonomous" in reason[1]


main_pushes = ("git push origin main", "git push origin HEAD:main", "git push origin feat/x:main",
               "git push -u origin +main", "git push --all", "git push --mirror origin",
               "git push origin refs/heads/main", "gh pr merge 20 --merge", "cd . && git push origin main",
               "git push origin --delete main", "git -C . push origin main")


def asks(command, cwd=None):
    reason = run(cwd or repo, command)[1]
    return reason is not None and reason[0] == "ask" and "main" in reason[1]


for command in ("git push origin main", "git push", "git push origin HEAD:main", "git push --all",
                "git switch -q main && git push"):
    check(f"supervised: a push to the main branch asks the user {command!r}", asks(command), str(run(repo, command)))
for command in ("git push origin feat/x", "git push -u origin feat/x:feat/x", "git push --tags", "gh pr merge 20",
                "git merge feat/x"):
    check(f"supervised: passes {command!r}", run(repo, command)[1] is None, str(run(repo, command)))
loose = tempfile.mkdtemp(prefix="noledger_")
for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@t.com"), ("config", "user.name", "t"),
             ("commit", "-q", "--allow-empty", "-m", "base")):
    subprocess.run(["git", *args], cwd=loose, check=True, capture_output=True)
check("with no ledger, a push to the main branch asks too", asks("git push origin main", loose))
check("with no ledger, a push of a work branch passes", run(loose, "git push origin feat/y")[1] is None)
sh(sys.executable, LEDGER_PY, "mode", "autonomous")
for command in main_pushes + ("git push", "git merge feat/x", "git merge --no-ff feat/x"):
    check(f"autonomous, on the main branch: denied {command!r}", reaches_main(command))
check("autonomous, on the main branch: denied 'git push origin @'", reaches_main("git push origin @"))
with open(os.path.join(repo, "README.md"), "w", encoding="utf-8") as handle:
    handle.write("x\n")
for command in ("git checkout README.md && git push origin", "git checkout . && git push origin",
                "git checkout -- README.md && git push", "git checkout main -- README.md && git push origin",
                "git checkout HEAD README.md; git push"):
    check(f"autonomous, on the main branch: a checkout of a path is no branch change, denied {command!r}",
          reaches_main(command))
for command in ("git merge --abort", "git status", "git log -n 3", 'git commit -m "push to main later"',
                "git push --tags", "git push origin --tags"):
    check(f"autonomous, on the main branch: passes {command!r}", run(repo, command)[1] is None, str(run(repo, command)))
sh("git", "checkout", "-q", "-b", "feat/x")
for command in main_pushes:
    check(f"autonomous, on a work branch: denied {command!r}", reaches_main(command))
for command in ("git checkout main && git merge feat/x", "git switch main && git merge feat/x && git push",
                "git switch -q main; git push", "gh -R o/r pr merge 3", "gh api -X PUT repos/o/r/pulls/3/merge",
                "glab mr merge 3", "glab mr accept 3", "glab -R o/r mr merge 3", "glab api -X PUT projects/1/merge_requests/3/merge"):
    check(f"autonomous, on a work branch: denied {command!r}", reaches_main(command))
check("autonomous, on a work branch: a checkout of a file from main is no branch change, passes",
      run(repo, "git checkout main -- README.md && git push origin")[1] is None)
for command in ("git push", "git push -u origin feat/x", "git push origin HEAD", "git merge main",
                "git merge --no-ff task-1", "gh pr view 20", "git switch main && git switch feat/x && git push",
                "git switch -c main2 && git push", "gh api repos/o/r/pulls/3", "glab mr view 3",
                "glab api projects/1/merge_requests/3"):
    check(f"autonomous, on a work branch: passes {command!r}", run(repo, command)[1] is None, str(run(repo, command)))
sub = os.path.join(repo, "src")
os.makedirs(sub)
check("autonomous: the ledger is found from a subfolder", run(repo, "git push origin main", cwd=sub)[1] is not None)
check("outside a git repository, a push asks nothing (no main branch to read)",
      run(bare, "git push origin main")[1] is None)

def ps(folder, command, background=False):
    return run(folder, command, background=background, tool="PowerShell")[1]


check("PowerShell: the dev server in the foreground is denied", ps(configured, "npm run dev") is not None)
check("PowerShell: the same command in background passes", ps(configured, "npm run dev", background=True) is None)
for command in ("cd app; npm run dev", "& npm run dev", "npm run dev | Tee-Object log.txt",
                "$env:PORT = 3001; npm run dev", "npm run dev -- --port 3001", "npm run dev\nnpm test",
                "powershell -Command 'npm run dev'", "Invoke-Expression 'npm run dev'"):
    check(f"PowerShell: the dev server is denied: {command!r}", ps(configured, command) is not None)
for command in ("npm test", "npm run dev:docs", "Write-Output 'npm run dev'", 'Write-Output "npm run dev"',
                "git commit -m @'\nnpm run dev no texto\n'@"):
    check(f"PowerShell: not a run of the dev server, passes: {command!r}", ps(configured, command) is None)


def ps_skips(command):
    reason = run(bare, command, tool="PowerShell")[1]
    return reason is not None and reason[0] == "deny" and "pre-commit" in reason[1]


for command in ('git commit --no-verify -m "x"', "git commit -nm 'x'", "Write-Output ok; git commit -n -m x",
                "git config core.hooksPath C:/none", "$env:GIT_CONFIG_KEY_0 = 'core.hooksPath'; git commit -m x",
                "$env:GIT_CONFIG_KEY_0='core.hooksPath'; git commit -m x", "powershell -Command 'git commit -n -m x'",
                "iex 'git commit -n -m x'", "& git commit --no-verify -m x", "git commit --% --no-verify -m x",
                "git -C $env:TEMP commit -n -m x",
                "git -c core.hooksPath=C:/none commit -m x"):
    check(f"PowerShell: skipping the pre-commit hook is denied: {command!r}", ps_skips(command), command)
for command in ('git commit -m "docs: never use --no-verify"', "git commit -m 'fix: -n nao entra'",
                "git commit -m @'\nfix: explica --no-verify e git commit -n\n'@",
                'git commit -m @"\nfix: --no-verify no here-string\n"@', "git commit -m 'it''s -n'",
                'git commit -m "fix: `"-n`" no texto"', "git log -n 3", "Write-Output 'git commit -n'",
                "git commit -m x # -n", "Write-Output ok" + chr(10) + "# git commit -n -m x", "git commit -m 'x#y'",
                "git commit --no-verbose -m x", "git config --get core.hooksPath", "git commit -m 'unbalanced"):
    check(f"PowerShell: a commit that keeps the hook passes: {command!r}",
          run(bare, command, tool="PowerShell")[1] is None, command)
# Expressao e bloco: o que o PowerShell trata como argumento ou bloco nao e um comando novo sem o git
for command in ("$out = git commit -n -m x", "$null = git commit -n -m x 2>&1", "$out=git commit -n -m x",
                "if ($true) {git commit -n -m x}", "try {git commit -n -m x} catch {}",
                "1 | % { git commit -n -m x }", "Invoke-Command -ScriptBlock {git commit -n -m x}",
                "if ($true) { git commit -m x --no-verify}", "git commit ('-n') -m x", "git commit @('-n') -m x",
                "cmd /c git commit -n -m x", 'cmd /c "git commit -n -m x"',
                "Start-Process -Wait -NoNewWindow git -ArgumentList 'commit','-n','-m','x'",
                'powershell "git commit -n -m x"', 'powershell -NoProfile "git commit -n -m x"',
                "powershell -EncodedCommand ZwBpAHQAIABjAG8AbQBtAGkAdAAgAC0AbgAgAC0AbQAgAHgA",
                "${env:GIT_CONFIG_KEY_0}='core.hooksPath'; git commit -m x",
                "$env:GIT_CONFIG_KEY_0 ='core.hooksPath'; git commit -m x",
                "$env:GIT_CONFIG_KEY_0= 'core.hooksPath'; git commit -m x",
                "Set-Item env:GIT_CONFIG_KEY_0 core.hooksPath; git commit -m x",
                "New-Item -Path env:GIT_CONFIG_KEY_0 -Value core.hooksPath; git commit -m x",
                "&git commit -n -m x", "git commit `" + chr(10) + "-n -m x",
                "<# don" + chr(39) + "t #> git commit -n -m x",
                "git commit " + chr(8216) + "-n" + chr(8217) + " -m x"):
    check(f"PowerShell: skipping the hook behind an expression is denied: {command!r}", ps_skips(command), command)
for command in ("git commit -m " + chr(8220) + "docs: use -n never" + chr(8221),
                "git commit -m x <# never use -n #>",
                "git commit -m @'" + chr(13) + chr(10) + "it" + chr(39) + "s -n" + chr(13) + chr(10) + "'@"):
    check(f"PowerShell: text that only mentions a flag still passes: {command!r}",
          run(bare, command, tool="PowerShell")[1] is None, command)
for command in ("npm.cmd run dev", "npm run ('dev')", "if ($true) {npm run dev}", "$job = npm run dev"):
    check(f"PowerShell: the dev server behind an expression is denied: {command!r}",
          ps(configured, command) is not None, command)
for command in ("cmd /c git push origin main", "if ($?) {git push origin main}", "git push origin ('main')",
                "Start-Process git -ArgumentList 'push','origin','main'"):
    check(f"PowerShell: autonomous, the main branch behind an expression is denied: {command!r}",
          run(repo, command, tool="PowerShell")[1] is not None, command)
check("PowerShell: the autonomous-mode guard reads it too",
      run(repo, "git switch main; git merge feat/x", tool="PowerShell")[1] is not None)

# A standing approval lets the publish of a READY delivery through, and nothing else
repo = tempfile.mkdtemp(prefix="guard_standing_")
for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@t.com"), ("config", "user.name", "t"),
             ("commit", "-q", "--allow-empty", "-m", "base")):
    sh("git", *args)
sh(sys.executable, LEDGER_PY, "start", "--slug", "x")
sh(sys.executable, LEDGER_PY, "mode", "autonomous")
sh("git", "checkout", "-q", "-b", "feat/x")


def commit_file(name, text):
    os.makedirs(os.path.dirname(os.path.join(repo, name)) or repo, exist_ok=True)
    with open(os.path.join(repo, name), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    sh("git", "add", name)
    sh("git", "commit", "-q", "-m", name)


def git_head():
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()


commit_file("a.txt", "a\n")
gated = git_head()
REPORT = "docs/quality-reports/2026-10-31-x.md"
commit_file(REPORT, f"# x\n\n2026-10-31 · 0000000..{gated[:7]} · v1.2.0\n\n## Checks\n")
PUBLISH = ("gh pr merge 3 --merge", "git checkout main && git merge --no-ff feat/x && git push origin main")
for command in PUBLISH:
    check(f"autonomous, READY report but no standing approval: denied {command!r}", reaches_main(command))
r = subprocess.run([sys.executable, LEDGER_PY, "approve", "--until", "1.5.0", "--conditions", "gate READY"], cwd=repo,
                   capture_output=True, text=True)
check("approve records a standing approval", r.returncode == 0, r.stderr)
for command in PUBLISH:
    check(f"standing approval and a READY report at this tree: passes {command!r}",
          run(repo, command)[1] is None, str(run(repo, command)))
check("standing approval: a push of every branch is still denied", reaches_main("git push --all"))
commit_file("b.txt", "after the gate\n")
check("standing approval: a commit after the READY report is denied", reaches_main("gh pr merge 3 --merge"))
sh("git", "reset", "-q", "--hard", "HEAD~1")
commit_file(REPORT, f"# x\n\n2026-10-31 · 0000000..{gated[:7]} · v1.6.0\n\n## Checks\n")
check("standing approval: a version past --until is denied", reaches_main("gh pr merge 3 --merge"))
sh("git", "reset", "-q", "--hard", "HEAD~1")
r = subprocess.run([sys.executable, LEDGER_PY, "approve", "--revoke"], cwd=repo, capture_output=True, text=True)
check("approve --revoke ends it: denied again", r.returncode == 0 and reaches_main("gh pr merge 3 --merge"), r.stderr)

# A delivery starts only in auto mode unless the user says so: ledger.py start outside it asks first
START = 'sh "${CLAUDE_PLUGIN_ROOT}/hooks/python.sh" "${CLAUDE_PLUGIN_ROOT}/skills/manager/ledger.py" start --slug x'
bare_start = tempfile.mkdtemp(prefix="start_")
reason = run(bare_start, START, mode="default")[1]
check("ledger.py start outside auto mode asks the user, naming the mode",
      reason and reason[0] == "ask" and "default" in reason[1] and "auto" in reason[1], str(reason))
check("start --next of the next delivery asks too", (run(bare_start, START.replace("start", "--ledger "
      ".superpowers/next-x.jsonl start --next"), mode="acceptEdits")[1] or ("",))[0] == "ask")
check("in PowerShell too", (run(bare_start, "& python C:\p\skills\manager\ledger.py start --slug x",
                                tool="PowerShell", mode="default")[1] or ("",))[0] == "ask")
check("in auto mode it passes", run(bare_start, START, mode="auto")[1] is None)
check("with permissions bypassed it passes", run(bare_start, START, mode="bypassPermissions")[1] is None)
check("another ledger command passes in any mode", run(bare_start, START.replace("start --slug x", "status"),
                                                       mode="default")[1] is None)
check("with no permission_mode in the payload it passes", run(bare_start, START)[1] is None)

config = json.load(open(os.path.join(HOOKS, "hooks.json"), encoding="utf-8"))
pre = config["hooks"]["PreToolUse"]
check("hooks.json registers bash-guard.py for Bash and PowerShell",
      len(pre) == 1 and pre[0]["matcher"] == "Bash|PowerShell"
      and "${CLAUDE_PLUGIN_ROOT}/hooks/bash-guard.py" in pre[0]["hooks"][0]["command"], json.dumps(config))

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
sys.exit(0 if all(results) else 1)
