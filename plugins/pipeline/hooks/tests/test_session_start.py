import json, os, subprocess, sys, tempfile

HOOKS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SCRIPT = os.path.join(HOOKS, "session-start.py")
LEDGER = os.path.join(HOOKS, "..", "skills", "manager", "ledger.py")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("PASS" if ok else "FAIL", name, "" if ok else f"| {detail[-300:]}")


def run(cwd, payload=None):
    stdin = json.dumps(payload if payload is not None else {"hook_event_name": "SessionStart", "cwd": cwd})
    return subprocess.run([sys.executable, SCRIPT], cwd=tempfile.gettempdir(), input=stdin, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


project = tempfile.mkdtemp(prefix="sessionstart_")
r = run(project)
check("no ledger: prints nothing and exits 0", r.returncode == 0 and r.stdout == "" and r.stderr == "",
      r.stdout + r.stderr)

for cmd in (["init", "-q"], ["-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "base"]):
    subprocess.run(["git"] + cmd, cwd=project, check=True)
subprocess.run([sys.executable, LEDGER, "start", "--slug", "retomada"], cwd=project, check=True,
               capture_output=True)
status = subprocess.run([sys.executable, LEDGER, "status"], cwd=project, capture_output=True, text=True,
                        encoding="utf-8").stdout
r = run(project)
check("with a ledger: prints the ledger status", r.returncode == 0 and status.strip() != "" and status in r.stdout,
      r.stdout + r.stderr)
check("with a ledger: says what the output is", "ledger" in r.stdout.lower().splitlines()[0], r.stdout)

r = run(project, payload={})
check("payload without cwd: falls back to the process directory and stays silent", r.returncode == 0
      and r.stdout == "", r.stdout + r.stderr)

r = subprocess.run([sys.executable, SCRIPT], cwd=tempfile.gettempdir(), input="not json", capture_output=True,
                   text=True)
check("garbage on stdin never blocks the session", r.returncode == 0 and r.stdout == "", r.stdout + r.stderr)

config = json.load(open(os.path.join(HOOKS, "hooks.json"), encoding="utf-8"))
groups = config["hooks"]["SessionStart"]
check("hooks.json registers session-start.py for compact|resume only", len(groups) == 1
      and groups[0]["matcher"] == "compact|resume"
      and "${CLAUDE_PLUGIN_ROOT}/hooks/session-start.py" in groups[0]["hooks"][0]["command"]
      and groups[0]["hooks"][0]["type"] == "command", json.dumps(config))

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
sys.exit(0 if all(results) else 1)
