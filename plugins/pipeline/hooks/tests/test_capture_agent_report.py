import glob, json, os, shutil, subprocess, sys, tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "capture-agent-report.py")
HOOKS_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hooks.json")
root = tempfile.mkdtemp(prefix="capture_")
repo = os.path.join(root, "repo")
os.makedirs(os.path.join(repo, ".git"))
os.makedirs(os.path.join(repo, ".superpowers"))
os.makedirs(os.path.join(repo, "src", "deep"))
bare = os.path.join(root, "bare")
os.makedirs(os.path.join(bare, ".git"))
INBOX = os.path.join(repo, ".superpowers", "reports", "inbox")
REPORT = ("## Findings\n\nNone.\r\n\n**Checked:** src/a.ts:12 — ok\n\n"
          'LEDGER {"agent":"security","verdict":"PASS","new":{"critical":0,"important":0,"minor":0},'
          '"open":{"critical":0,"important":0,"minor":0}}\n')
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS" if ok else "FAIL"), name, "" if ok else f"| {str(detail)[:300]}")


def run(payload, raw=None):
    data = raw if raw is not None else json.dumps(payload).encode("utf-8")
    return subprocess.run([sys.executable, HOOK], input=data, capture_output=True)


def payload(agent_type="plugin:pipeline:security", message=REPORT, cwd=repo, **extra):
    base = {"session_id": "s1", "transcript_path": "/nowhere.jsonl", "cwd": cwd, "hook_event_name": "SubagentStop",
            "agent_id": "subagent-4f2a9c71e0", "agent_type": agent_type, "stop_hook_active": False}
    if message is not None:
        base["last_assistant_message"] = message
    base.update(extra)
    return base


def inbox():
    return sorted(glob.glob(os.path.join(INBOX, "*.md")))


def clear():
    shutil.rmtree(INBOX, ignore_errors=True)


result = run(payload())
files = inbox()
check("a pipeline reviewer's final message lands in the inbox", result.returncode == 0 and len(files) == 1,
      (result.returncode, result.stderr, files))
check("the file holds the message byte for byte", files and open(files[0], "rb").read() == REPORT.encode("utf-8"),
      files and open(files[0], "rb").read())
name = os.path.basename(files[0]) if files else ""
check("the name is <timestamp>-<agent>-<short id>.md", name.endswith("-security-a9c71e0.md") or
      name.endswith("-security-2a9c71e0.md"), name)
context = json.loads(result.stdout or b"{}").get("hookSpecificOutput", {}).get("additionalContext", "")
check("the hook tells the manager where the report is", "--from-inbox .superpowers/reports/inbox/" in context
      and name in context, result.stdout)

result = run(payload())
check("a second capture in the same second never overwrites the first", len(inbox()) == 2, inbox())
clear()

for agent_type in ("pipeline:code-review", "code-review"):
    text = REPORT.replace('"security"', '"code-review"')
    result = run(payload(agent_type=agent_type, message=text))
    check(f"agent_type {agent_type} is recognized", len(inbox()) == 1 and "-code-review-" in inbox()[0], inbox())
    clear()

run(payload(agent_type="plugin:other:security"))
check("another plugin's agent of the same name is ignored", inbox() == [], inbox())
run(payload(agent_type="Explore"))
check("a non-pipeline agent is ignored", inbox() == [], inbox())
run(payload(message="All done, nothing to report here."))
check("a final message without a LEDGER line is ignored", inbox() == [], inbox())
run(payload(agent_type="plugin:pipeline:qa"))
check("a LEDGER line naming another agent is ignored", inbox() == [], inbox())

run(payload(cwd=os.path.join(repo, "src", "deep")))
check("a subagent running in a subfolder writes to the repo's .superpowers", len(inbox()) == 1, inbox())
clear()

result = run(payload(cwd=bare))
check("a repo without .superpowers gets nothing", result.returncode == 0 and not os.path.exists(
    os.path.join(bare, ".superpowers")) and result.stdout == b"", result.stdout)

transcript = os.path.join(root, "agent-subagent-4f2a9c71e0.jsonl")
with open(transcript, "w", encoding="utf-8") as handle:
    handle.write(json.dumps({"type": "user", "message": {"role": "user", "content": "review T1"}}) + "\n")
    handle.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": "Reading the diff."}, {"type": "tool_use", "id": "t1", "name": "Read", "input": {}}]}})
                 + "\n")
    handle.write("not json\n")
    handle.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": REPORT}]}}) + "\n")
run(payload(message=None, agent_transcript_path=transcript))
files = inbox()
check("without last_assistant_message the last assistant text of the transcript JSONL is used",
      len(files) == 1 and open(files[0], "rb").read() == REPORT.encode("utf-8"),
      files and open(files[0], "rb").read())
clear()

for label, raw in (("invalid JSON", b"{nope"), ("an empty payload", b""), ("a JSON list", b"[1, 2]")):
    result = run(None, raw=raw)
    check(f"{label} exits 0 silently", result.returncode == 0 and result.stdout == b"", (result.returncode, result.stdout))
result = run(payload(message=None, agent_transcript_path=os.path.join(root, "missing.jsonl")))
check("a missing transcript exits 0 and writes nothing", result.returncode == 0 and inbox() == [], inbox())
os.makedirs(os.path.dirname(INBOX), exist_ok=True)
open(INBOX, "w").write("a file where the folder should be")
result = run(payload())
check("an unwritable inbox exits 0 (never blocks the subagent)", result.returncode == 0, result.stderr)
os.remove(INBOX)

hooks = json.load(open(HOOKS_JSON, encoding="utf-8"))["hooks"]
entry = hooks.get("SubagentStop", [{}])[0]
command = entry.get("hooks", [{}])[0].get("command", "")
check("hooks.json registers the capture on SubagentStop", "capture-agent-report.py" in command, hooks.get("SubagentStop"))
check("the registration exits 0 when no Python is found", command.rstrip().endswith("exit 0"), command)

shutil.rmtree(root, ignore_errors=True)
print(f"ALL PASS ({sum(results)}/{len(results)})" if all(results) else f"FAILED ({sum(results)}/{len(results)})")
sys.exit(0 if all(results) else 1)
