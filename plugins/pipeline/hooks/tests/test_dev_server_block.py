import json, os, subprocess, sys, tempfile, time

HOOKS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SCRIPT = os.path.join(HOOKS, "block-dev-server.py")
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

config = json.load(open(os.path.join(HOOKS, "hooks.json"), encoding="utf-8"))
pre = config["hooks"]["PreToolUse"]
check("hooks.json registers block-dev-server.py for Bash", len(pre) == 1 and pre[0]["matcher"] == "Bash"
      and "${CLAUDE_PLUGIN_ROOT}/hooks/block-dev-server.py" in pre[0]["hooks"][0]["command"], json.dumps(config))

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
