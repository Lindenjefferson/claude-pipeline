import glob, json, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER_PY = os.path.join(HERE, "..", "ledger.py")
HOOK = os.path.join(HERE, "..", "..", "..", "hooks", "capture-agent-report.py")
repo = tempfile.mkdtemp(prefix="ledgerinbox_")
os.makedirs(os.path.join(repo, "src"))
LEDGER = os.path.join(repo, ".superpowers", "ledger.jsonl")
REPORTS = os.path.join(repo, ".superpowers", "reports")
INBOX = os.path.join(REPORTS, "inbox")
ZERO = {"critical": 0, "important": 0, "minor": 0}
results = []


def sh(*args):
    return subprocess.run(args, cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def ledger(*args, stdin=None):
    return subprocess.run([sys.executable, LEDGER_PY, "--ledger", LEDGER, *args], cwd=repo,
                          capture_output=True, input=stdin, encoding="utf-8")


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS" if ok else "FAIL"), name, "" if ok else f"| {str(detail)[:300]}")


def reviewer_line(agent, verdict="PASS"):
    return "LEDGER " + json.dumps({"agent": agent, "verdict": verdict, "new": ZERO, "open": ZERO})


def review_text(agent, marker, verdict="PASS"):
    return f"## Findings\n\nNone ({marker}).\r\n\n**Checked:** src/a.py:1 — fine\n\n{reviewer_line(agent, verdict)}\n"


def transcript(agent, text, agent_id):
    path = os.path.join(repo, "..", f"{os.path.basename(repo)}-{agent_id}.jsonl")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"type": "user", "message": {"role": "user", "content": "go"}}) + "\n")
        handle.write(json.dumps({"type": "assistant", "message": {"role": "assistant",
                                                                  "content": [{"type": "text", "text": text}]}}) + "\n")
    return path


def capture(agent, text, agent_id):
    payload = {"session_id": "s", "cwd": repo, "hook_event_name": "SubagentStop", "agent_id": agent_id,
               "agent_type": f"plugin:pipeline:{agent}", "stop_hook_active": False,
               "agent_transcript_path": transcript(agent, text, agent_id)}
    result = subprocess.run([sys.executable, HOOK], input=json.dumps(payload).encode("utf-8"), capture_output=True)
    context = json.loads(result.stdout or b"{}").get("hookSpecificOutput", {}).get("additionalContext", "")
    return context.split("--from-inbox ")[1].split(" ")[0] if "--from-inbox " in context else None


def pending():
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(INBOX, "*.md")))


def saved():
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(INBOX, "saved", "*.md")))


sh("git", "init", "-q")
sh("git", "config", "user.email", "t@t.com")
sh("git", "config", "user.name", "t")
open(os.path.join(repo, "src", "a.py"), "w").write("a = 1\n")
sh("git", "add", ".")
sh("git", "commit", "-q", "-m", "base")
base = sh("git", "rev-parse", "HEAD")
open(os.path.join(repo, "src", "a.py"), "w").write("a = 2\n")
sh("git", "commit", "-q", "-am", "task 1")
check("start", ledger("start", "--slug", "inbox", "--base", base).returncode == 0)

security = review_text("security", "security r1")
path = capture("security", security, "agent-aaaa1111")
check("the hook captures the reviewer's report from its transcript", path and os.path.isfile(os.path.join(repo, path)),
      path)
result = ledger("save-report", "--task", "1", "--from", base, "--from-inbox", path)
ref = result.stdout.strip()
check("save-report --from-inbox saves it with no --agent", result.returncode == 0
      and ref.endswith("reports/1.md#security-r1"), result.stderr + result.stdout)
section = ledger("show-report", ref).stdout
check("the saved section is the report verbatim (CRLF normalized like --file)",
      section.endswith(security.replace("\r\n", "\n")), section)
check("the inbox file moves to inbox/saved/", pending() == [] and len(saved()) == 1, (pending(), saved()))
result = ledger("append", "--task", "1", "--from", base, "--head", "HEAD", "--report", ref,
                "--line", reviewer_line("security"))
check("append accepts the section saved from the inbox", result.returncode == 0, result.stderr)

first = capture("code-review", review_text("code-review", "old"), "agent-bbbb0001")
time.sleep(1.1)
newest = capture("code-review", review_text("code-review", "new"), "agent-bbbb0002")
result = ledger("save-report", "--task", "1", "--from", base, "--agent", "code-review", "--latest-inbox")
section = ledger("show-report", result.stdout.strip()).stdout
check("--latest-inbox --agent picks the newest capture of that agent", result.returncode == 0 and "(new)" in section,
      result.stderr + section)
check("--latest-inbox warns about the older capture left behind", "older inbox reports of code-review" in result.stderr
      and os.path.basename(first) in result.stderr, result.stderr)
check("only the saved capture leaves the inbox", pending() == [os.path.basename(first)], pending())

result = ledger("save-report", "--task", "1", "--from", base, "--agent", "design", "--latest-inbox")
check("--latest-inbox with no capture of that agent refuses and points at transcription",
      result.returncode != 0 and "transcribe" in result.stderr, result.stderr)
result = ledger("save-report", "--task", "1", "--from", base, "--latest-inbox")
check("--latest-inbox without --agent refuses", result.returncode != 0 and "--agent" in result.stderr, result.stderr)
result = ledger("save-report", "--task", "1", "--from", base, "--agent", "qa", "--from-inbox", first)
check("--agent that contradicts the report's LEDGER line refuses", result.returncode != 0
      and "does not match" in result.stderr and os.path.isfile(os.path.join(repo, first)), result.stderr)
result = ledger("save-report", "--task", "1", "--from", base, "--stdin", stdin="text")
check("--stdin still needs --agent", result.returncode != 0 and "--agent is required" in result.stderr, result.stderr)

db_review = review_text("db", "db review")
path = capture("db", db_review, "agent-cccc0001")
result = ledger("save-report", "--task", "1", "--from", base, "--from-inbox", path)
check("a db report with a PASS/FAIL verdict is saved as a review without --role",
      result.returncode == 0 and result.stdout.strip().endswith("#db-review-r1"), result.stderr + result.stdout)
db_impl = ("Implemented the migration.\n\nCommit: " + sh("git", "rev-parse", "--short", "HEAD") +
           "\nFiles changed:\n- src/a.py\n\n" + 'LEDGER {"agent":"db","verdict":"DONE"}\n')
path = capture("db", db_impl, "agent-cccc0002")
result = ledger("save-report", "--task", "1", "--from", base, "--from-inbox", path)
check("a db report with an implementer verdict is saved as implementation without --role",
      result.returncode == 0 and result.stdout.strip().endswith("#db-r1"), result.stderr + result.stdout)

stray = os.path.join(INBOX, "notes.md")
open(stray, "w", encoding="utf-8").write("no ledger line here\n")
result = ledger("save-report", "--task", "1", "--from", base, "--from-inbox", stray)
check("an inbox file with no LEDGER line and no agent in its name refuses", result.returncode != 0
      and "cannot tell which agent" in result.stderr, result.stderr)
result = ledger("save-report", "--task", "1", "--from", base, "--from-inbox", os.path.join(INBOX, "gone.md"))
check("a missing inbox file refuses", result.returncode != 0 and "does not exist" in result.stderr, result.stderr)

path = capture("audit", review_text("audit", "per-file"), "agent-dddd0001")
result = ledger("save-report", "--task", "1", "--layout", "per-file", "--from-inbox", path)
check("--from-inbox works in the per-file layout", result.returncode == 0
      and result.stdout.strip().endswith("1-audit-r1.md"), result.stderr + result.stdout)

AGENTS_DIR = os.path.join(HERE, "..", "..", "..", "agents")
for agent in ("dev", "db"):
    template = next(line for line in open(os.path.join(AGENTS_DIR, f"{agent}.md"), encoding="utf-8")
                    if line.startswith("Commit:"))
    check(f"the {agent} report template asks for the output of git rev-parse --short HEAD",
          template.strip() == "Commit: <output of git rev-parse --short HEAD>", template)
    literal = ("Implemented the task as the brief asks and ran the tests. " * 5 + "\n\n" + template +
               "Files changed:\n- src/a.py\n\n" + json.dumps({"agent": agent, "verdict": "DONE"}).join(["LEDGER ", "\n"]))
    path = capture(agent, literal, f"agent-eeee000{len(agent)}")
    role = ("--role", "implementer") if agent == "db" else ()
    ref = ledger("save-report", "--task", "2", "--from", base, "--from-inbox", path, *role).stdout.strip()
    result = ledger("append", "--task", "2", "--from", base, "--head", "HEAD", "--report", ref,
                    "--line", json.dumps({"agent": agent, "verdict": "DONE"}).join(["LEDGER ", ""]))
    check(f"append rejects a {agent} report that pastes the template's Commit line as is",
          result.returncode != 0 and "placeholder" in result.stderr, result.stderr + ref)

print(f"ALL PASS ({sum(results)}/{len(results)})" if all(results) else f"FAILED ({sum(results)}/{len(results)})")
sys.exit(0 if all(results) else 1)
