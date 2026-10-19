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

r = run(project, payload={"hook_event_name": "SessionStart", "source": "startup", "cwd": project})
check("a new session does not print the ledger status", r.returncode == 0 and r.stdout == "", r.stdout + r.stderr)
r = run(project, payload={"hook_event_name": "SessionStart", "source": "compact", "cwd": project})
check("after a compaction it prints the ledger status", status in r.stdout, r.stdout + r.stderr)

# The native pre-commit hook finds the scanner through pipeline.home: each session points it at the running plugin.
ROOT = os.path.abspath(os.path.join(HOOKS, "..")).replace("\\", "/")
SCANNER = os.path.join(HOOKS, "pre-commit-secret-scan.py")


def home(repo):
    return subprocess.run(["git", "config", "--local", "--get", "pipeline.home"], cwd=repo, capture_output=True,
                          text=True).stdout.strip()


subprocess.run([sys.executable, SCANNER, "--install-pre-commit"], cwd=project, check=True, capture_output=True)
subprocess.run(["git", "config", "--local", "pipeline.home", "/no/such/older/version"], cwd=project, check=True)
r = run(project, payload={"hook_event_name": "SessionStart", "source": "startup", "cwd": project})
check("with the secret-scan hook, a session points pipeline.home at the running plugin", home(project) == ROOT
      and r.returncode == 0 and r.stdout == "", home(project) + r.stdout + r.stderr)
sub = os.path.join(project, "src")
os.makedirs(sub)
subprocess.run(["git", "config", "--local", "pipeline.home", "/no/such/older/version"], cwd=project, check=True)
run(sub, payload={"hook_event_name": "SessionStart", "source": "resume", "cwd": sub})
check("from a subfolder too", home(project) == ROOT, home(project))
plain = tempfile.mkdtemp(prefix="sessionstart_plain_")
subprocess.run(["git", "init", "-q"], cwd=plain, check=True)
run(plain, payload={"hook_event_name": "SessionStart", "source": "startup", "cwd": plain})
check("without the secret-scan hook, pipeline.home is left alone", home(plain) == "", home(plain))
outside = tempfile.mkdtemp(prefix="sessionstart_nogit_")
r = run(outside, payload={"hook_event_name": "SessionStart", "source": "startup", "cwd": outside})
check("outside a git repo: nothing and exit 0", r.returncode == 0 and r.stdout == "", r.stdout + r.stderr)

# An update started by the atualizar skill leaves .superpowers/atualizar.json; the new session is reminded to finish it.
VERSION = json.load(open(os.path.join(HOOKS, "..", ".claude-plugin", "plugin.json"), encoding="utf-8"))["version"]
upd_dir = tempfile.mkdtemp(prefix="sessionstart_upd_")
subprocess.run(["git", "init", "-q"], cwd=upd_dir, check=True)
os.makedirs(os.path.join(upd_dir, ".superpowers"))
UPD = os.path.join(upd_dir, ".superpowers", "atualizar.json")


def write_upd(text):
    with open(UPD, "w", encoding="utf-8") as handle:
        handle.write(text)


def start(cwd, source="startup"):
    return run(cwd, payload={"hook_event_name": "SessionStart", "source": source, "cwd": cwd})


r = start(upd_dir)
check("atualizar: no file prints nothing", r.returncode == 0 and r.stdout == "", r.stdout + r.stderr)
write_upd(json.dumps({"from": "0.0.1", "to": VERSION}))
want = (f"pipeline: the plugin was updated from 0.0.1 to {VERSION}; finish the update with the atualizar skill "
        "(kickoff and the upgrade notes).")
for source in ("startup", "resume", "clear", "compact"):
    r = start(upd_dir, source)
    check(f"atualizar: `to` is the running version, on {source}", r.returncode == 0 and r.stdout.strip() == want,
          r.stdout + r.stderr)
sub_upd = os.path.join(upd_dir, "src")
os.makedirs(sub_upd)
r = start(sub_upd)
check("atualizar: from a subfolder too", r.stdout.strip() == want, r.stdout + r.stderr)
write_upd(json.dumps({"from": "0.0.1", "to": "99.0.0"}))
r = start(upd_dir)
check("atualizar: `to` differs from the running version", r.returncode == 0 and r.stdout.strip() == (
    f"pipeline: an update to 99.0.0 was started but this session runs {VERSION}; run /reload-plugins or restart, "
    "then the atualizar skill."), r.stdout + r.stderr)
for bad in ("{not json", "[]", json.dumps({"from": "1"}), json.dumps({"to": VERSION}), json.dumps({"from": 1, "to": 2}),
            ""):
    write_upd(bad)
    r = start(upd_dir)
    check(f"atualizar: unusable file {bad!r} says nothing and never fails", r.returncode == 0 and r.stdout == ""
          and r.stderr == "", r.stdout + r.stderr)
write_upd(json.dumps({"from": "0.0.1", "to": VERSION}))
subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "base"],
               cwd=upd_dir, check=True)
subprocess.run([sys.executable, LEDGER, "start", "--slug", "retomada"], cwd=upd_dir, check=True, capture_output=True)
upd_status = subprocess.run([sys.executable, LEDGER, "status"], cwd=upd_dir, capture_output=True, text=True,
                            encoding="utf-8").stdout
r = start(upd_dir, "compact")
check("atualizar: with a ledger, the ledger output comes first and unchanged, then the notice",
      r.stdout == "Delivery ledger (resumed session), `ledger.py status`:\n" + upd_status + want + "\n",
      r.stdout + r.stderr)

config = json.load(open(os.path.join(HOOKS, "hooks.json"), encoding="utf-8"))
groups = config["hooks"]["SessionStart"]
check("hooks.json registers session-start.py for every session start", len(groups) == 1
      and set(groups[0]["matcher"].split("|")) == {"startup", "resume", "clear", "compact"}
      and "${CLAUDE_PLUGIN_ROOT}/hooks/session-start.py" in groups[0]["hooks"][0]["command"]
      and groups[0]["hooks"][0]["type"] == "command", json.dumps(config))

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
sys.exit(0 if all(results) else 1)
