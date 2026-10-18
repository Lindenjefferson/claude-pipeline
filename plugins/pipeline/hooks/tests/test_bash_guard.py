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


def run(folder, command, background=False, tool="Bash", cwd=None):
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "cwd": cwd or folder,
               "tool_input": {"command": command, "run_in_background": background}}
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
check("supervised: a push to the main branch is left to the ask rule", not reaches_main("git push origin main"))
sh(sys.executable, LEDGER_PY, "mode", "autonomous")
for command in main_pushes + ("git push", "git merge feat/x", "git merge --no-ff feat/x"):
    check(f"autonomous, on the main branch: denied {command!r}", reaches_main(command))
check("autonomous, on the main branch: denied 'git push origin @'", reaches_main("git push origin @"))
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
for command in ("git push", "git push -u origin feat/x", "git push origin HEAD", "git merge main",
                "git merge --no-ff task-1", "gh pr view 20", "git switch main && git switch feat/x && git push",
                "git switch -c main2 && git push", "gh api repos/o/r/pulls/3", "glab mr view 3",
                "glab api projects/1/merge_requests/3"):
    check(f"autonomous, on a work branch: passes {command!r}", run(repo, command)[1] is None, str(run(repo, command)))
sub = os.path.join(repo, "src")
os.makedirs(sub)
check("autonomous: the ledger is found from a subfolder", run(repo, "git push origin main", cwd=sub)[1] is not None)
check("no ledger: a push to the main branch is left to the ask rule", run(bare, "git push origin main")[1] is None)

config = json.load(open(os.path.join(HOOKS, "hooks.json"), encoding="utf-8"))
pre = config["hooks"]["PreToolUse"]
check("hooks.json registers bash-guard.py for Bash", len(pre) == 1 and pre[0]["matcher"] == "Bash"
      and "${CLAUDE_PLUGIN_ROOT}/hooks/bash-guard.py" in pre[0]["hooks"][0]["command"], json.dumps(config))

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
