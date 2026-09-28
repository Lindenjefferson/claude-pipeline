#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
import time

SEVERITIES = ("critical", "important", "minor")
IMPLEMENTER_VERDICTS = ("DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "BLOCKED", "NO_DOC_CHANGE_NEEDED")
REVIEWER_VERDICTS = ("PASS", "FAIL")
AGENT_VERDICTS = {
    "discovery": IMPLEMENTER_VERDICTS,
    "dev": IMPLEMENTER_VERDICTS,
    "docs": IMPLEMENTER_VERDICTS,
    "db": IMPLEMENTER_VERDICTS + REVIEWER_VERDICTS,
    "security": REVIEWER_VERDICTS,
    "audit": REVIEWER_VERDICTS,
    "design": REVIEWER_VERDICTS,
    "code-review": REVIEWER_VERDICTS,
    "qa": REVIEWER_VERDICTS,
}
NOTE_KINDS = ("ruling", "deferred", "parked", "condition")
SPEC_TASK = "spec"
SPEC_REVIEWERS = ("security", "db", "audit", "design", "code-review")


def role(entry):
    return "review" if entry.get("verdict") in REVIEWER_VERDICTS else "implement"


def label(entry):
    verdicts = AGENT_VERDICTS.get(entry["agent"], ())
    both = REVIEWER_VERDICTS[0] in verdicts and IMPLEMENTER_VERDICTS[0] in verdicts
    return f"{entry['agent']} ({role(entry)})" if both else entry["agent"]


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def git(*args):
    result = subprocess.run(["git", *args], capture_output=True, encoding="utf-8", errors="replace")
    return result.returncode, (result.stdout or "").strip()


def resolve_commit(rev):
    code, sha = git("rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    return sha if code == 0 and sha else None


def counts_problem(entry, field):
    value = entry.get(field)
    if not isinstance(value, dict):
        return f"'{field}' must be an object with {', '.join(SEVERITIES)}"
    for severity in SEVERITIES:
        count = value.get(severity)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            return f"'{field}.{severity}' must be a non-negative integer"
    extra = set(value) - set(SEVERITIES)
    if extra:
        return f"'{field}' has unknown keys: {', '.join(sorted(extra))}"
    return None


def verdict_problem(entry):
    agent, verdict = entry.get("agent"), entry.get("verdict")
    if agent not in AGENT_VERDICTS:
        return f"unknown agent '{agent}' (expected one of: {', '.join(AGENT_VERDICTS)})"
    if verdict not in AGENT_VERDICTS[agent]:
        return f"verdict '{verdict}' is not valid for {agent} (expected one of: {', '.join(AGENT_VERDICTS[agent])})"
    if verdict in REVIEWER_VERDICTS:
        for field in ("new", "open"):
            problem = counts_problem(entry, field)
            if problem:
                return problem
        blocking = entry["open"]["critical"] + entry["open"]["important"]
        if verdict == "PASS" and blocking:
            return "PASS with open critical/important findings; the verdict must be FAIL"
        if verdict == "FAIL" and not blocking:
            return "FAIL with no open critical/important finding; the verdict must be PASS"
    return None


def entry_problem(entry):
    if not isinstance(entry, dict):
        return "not a JSON object"
    event = entry.get("event")
    if event == "start":
        return None if entry.get("slug") and entry.get("base") else "start entry lacks slug or base"
    if event == "note":
        if entry.get("kind") not in NOTE_KINDS or not entry.get("task") or not entry.get("text"):
            return "note entry lacks a valid kind, task or text"
        return None
    for field in ("task", "from", "head", "round", "report"):
        if not entry.get(field):
            return f"agent entry lacks '{field}'"
    return verdict_problem(entry) or spec_problem(entry)


def spec_problem(entry):
    if entry.get("task") != SPEC_TASK:
        return "'spec' is only valid on the spec task" if "spec" in entry else None
    if entry.get("agent") not in SPEC_REVIEWERS or entry.get("verdict") not in REVIEWER_VERDICTS:
        return f"the spec task takes reviewer lines from: {', '.join(SPEC_REVIEWERS)}"
    if not entry.get("spec"):
        return "spec review entry lacks 'spec' (the reviewed document)"
    return None


def read_ledger(path):
    if not os.path.exists(path):
        sys.exit(f"ledger not found: {path} (run 'start' first)")
    entries, invalid = [], []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                invalid.append({"line": number, "reason": "invalid JSON"})
                continue
            problem = entry_problem(entry)
            if problem:
                invalid.append({"line": number, "reason": problem})
            else:
                entries.append(entry)
    return entries, invalid


def warn_invalid(path, invalid):
    for item in invalid:
        sys.stderr.write(f"warning: {path}:{item['line']} ignored: {item['reason']}\n")


def write_line(path, entry):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, separators=(",", ":")) + "\n")


def start(args):
    if os.path.exists(args.ledger):
        sys.exit(f"ledger already exists: {args.ledger}")
    base = resolve_commit(args.base)
    if not base:
        sys.exit(f"--base is not a commit: {args.base}")
    write_line(args.ledger, {"event": "start", "ts": now(), "slug": args.slug, "base": base})


def append(args):
    raw = args.line.strip()
    if raw.startswith("LEDGER"):
        raw = raw[len("LEDGER"):].strip()
    try:
        entry = json.loads(raw)
    except ValueError:
        sys.exit("agent line is not valid JSON")
    if not isinstance(entry, dict):
        sys.exit("agent line is not a JSON object")
    problem = verdict_problem(entry)
    if problem:
        sys.exit(f"agent line rejected: {problem}")
    from_sha, head = resolve_commit(args.from_sha), resolve_commit(args.head)
    if not from_sha:
        sys.exit(f"--from is not a commit: {args.from_sha}")
    if not head:
        sys.exit(f"--head is not a commit: {args.head}")
    if git("merge-base", "--is-ancestor", from_sha, head)[0] != 0:
        sys.exit(f"--from {args.from_sha} is not an ancestor of --head {args.head}")
    if not os.path.isfile(args.report):
        sys.exit(f"--report does not exist: {args.report} (save the agent's report first)")
    entry.pop("spec", None)
    if args.spec:
        spec = os.path.normpath(args.spec).replace("\\", "/")
        if git("cat-file", "-e", f"{head}:./{spec}")[0] != 0:
            sys.exit(f"--spec {args.spec} is not in --head {args.head} (commit the spec first)")
        entry["spec"] = spec
    entry["task"] = args.task
    problem = spec_problem(entry)
    if problem:
        sys.exit(f"agent line rejected: {problem}")
    entries, invalid = read_ledger(args.ledger)
    warn_invalid(args.ledger, invalid)
    earlier = [e for e in entries if e.get("agent") == entry["agent"] and e.get("task") == args.task
               and role(e) == role(entry)]
    entry.update({"ts": now(), "from": from_sha, "head": head,
                  "round": len(earlier) + 1, "report": args.report})
    write_line(args.ledger, entry)
    print(f"{entry['agent']} {entry['verdict']} task={args.task} round={entry['round']}")


def note(args):
    _, invalid = read_ledger(args.ledger)
    warn_invalid(args.ledger, invalid)
    write_line(args.ledger, {"event": "note", "ts": now(), "kind": args.kind,
                             "task": args.task, "text": args.text})
    print(f"note {args.kind} task={args.task}")


def summarize(entries):
    latest = {}
    totals = {}
    spec_totals = {}
    for entry in entries:
        agent = entry.get("agent")
        if not agent:
            continue
        latest[(entry["task"], agent, role(entry))] = entry
        scope = spec_totals if entry["task"] == SPEC_TASK else totals
        bucket = scope.setdefault(agent, {**{s: 0 for s in SEVERITIES}, "rounds": 0})
        for severity in SEVERITIES:
            bucket[severity] += (entry.get("new") or {}).get(severity, 0)
        bucket["rounds"] = max(bucket["rounds"], entry.get("round", 1))
    return list(latest.values()), totals, spec_totals


def commits_after(entry_head, head, path=None):
    paths = ["--", path] if path else []
    code, count = git("rev-list", "--count", f"{entry_head}..{head}", *paths)
    return int(count or 0) if code == 0 else None


def stale_entries(latest, head):
    stale = []
    for entry in latest:
        if entry.get("verdict") not in REVIEWER_VERDICTS:
            continue
        spec = entry.get("spec") if entry["task"] == SPEC_TASK else None
        behind = commits_after(entry.get("head"), head, spec)
        if behind != 0:
            item = {"task": entry["task"], "agent": entry["agent"],
                    "head": entry.get("head"), "commits_after": behind}
            if spec:
                item["spec"] = spec
            stale.append(item)
    return stale


def status(args):
    entries, invalid = read_ledger(args.ledger)
    latest, totals, spec_totals = summarize(entries)
    notes = [{k: e[k] for k in ("kind", "task", "text", "ts")} for e in entries
             if e.get("event") == "note"]
    stale = stale_entries(latest, args.head) if args.head else []
    behind = {(s["task"], s["agent"]): s["commits_after"] for s in stale}
    if args.json:
        report = {"latest": latest, "totals": totals, "spec_totals": spec_totals,
                  "notes": notes, "invalid": invalid}
        if args.head:
            report["stale"] = stale
        print(json.dumps(report, indent=2))
        return
    for item in invalid:
        print(f"INVALID line {item['line']}: {item['reason']} (ignored)")
    for entry in latest:
        key = (entry["task"], entry["agent"])
        flag = ""
        if role(entry) == "review" and key in behind:
            count = behind[key]
            flag = "  STALE (unknown range)" if count is None else f"  STALE (+{count} commits)"
        print(f"{entry['task']:<10} {label(entry):<16} {entry['verdict']:<20} "
              f"{str(entry.get('from'))[:8]}..{str(entry.get('head'))[:8]}  round {entry.get('round')}"
              f"{flag}")
    for scope, buckets in (("total", totals), ("spec ", spec_totals)):
        for agent, bucket in buckets.items():
            raised = ", ".join(f"{bucket[s]} {s}" for s in SEVERITIES)
            print(f"{scope} {agent:<12} raised: {raised}; rounds: {bucket['rounds']}")
    for item in notes:
        print(f"note {item['kind']:<10} {item['task']:<10} {item['text']}")


def main():
    parser = argparse.ArgumentParser(prog="ledger.py")
    parser.add_argument("--ledger", default=".superpowers/ledger.jsonl")
    commands = parser.add_subparsers(dest="command", required=True)

    start_cmd = commands.add_parser("start")
    start_cmd.add_argument("--slug", required=True)
    start_cmd.add_argument("--base", required=True)
    start_cmd.set_defaults(run=start)

    append_cmd = commands.add_parser("append")
    append_cmd.add_argument("--task", required=True)
    append_cmd.add_argument("--from", dest="from_sha", required=True)
    append_cmd.add_argument("--head", required=True)
    append_cmd.add_argument("--report", required=True)
    append_cmd.add_argument("--line", required=True)
    append_cmd.add_argument("--spec", help="the reviewed spec document; required with --task spec")
    append_cmd.set_defaults(run=append)

    note_cmd = commands.add_parser("note")
    note_cmd.add_argument("--kind", required=True, choices=NOTE_KINDS)
    note_cmd.add_argument("--task", required=True)
    note_cmd.add_argument("--text", required=True)
    note_cmd.set_defaults(run=note)

    status_cmd = commands.add_parser("status")
    status_cmd.add_argument("--json", action="store_true")
    status_cmd.add_argument("--head", help="mark reviewer entries whose range ends before this commit")
    status_cmd.set_defaults(run=status)

    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
