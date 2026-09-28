#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
import time

SEVERITIES = ("critical", "important", "minor")


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def read_entries(path):
    if not os.path.exists(path):
        sys.exit(f"ledger not found: {path} (run 'start' first)")
    entries = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except ValueError:
                sys.exit(f"{path}:{number}: invalid JSON")
    return entries


def write_line(path, entry):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, separators=(",", ":")) + "\n")


def start(args):
    if os.path.exists(args.ledger):
        sys.exit(f"ledger already exists: {args.ledger}")
    write_line(args.ledger, {"event": "start", "ts": now(), "slug": args.slug, "base": args.base})


def append(args):
    raw = args.line.strip()
    if raw.startswith("LEDGER"):
        raw = raw[len("LEDGER"):].strip()
    try:
        entry = json.loads(raw)
    except ValueError:
        sys.exit("agent line is not valid JSON")
    for field in ("agent", "verdict"):
        if not entry.get(field):
            sys.exit(f"agent line lacks '{field}'")
    earlier = [e for e in read_entries(args.ledger)
               if e.get("agent") == entry["agent"] and e.get("task") == args.task]
    entry.update({"ts": now(), "task": args.task, "from": args.from_sha, "head": args.head,
                  "round": len(earlier) + 1, "report": args.report})
    write_line(args.ledger, entry)
    print(f"{entry['agent']} {entry['verdict']} task={args.task} round={entry['round']}")


NOTE_KINDS = ("ruling", "deferred", "parked", "condition")


def note(args):
    read_entries(args.ledger)
    write_line(args.ledger, {"event": "note", "ts": now(), "kind": args.kind,
                             "task": args.task, "text": args.text})
    print(f"note {args.kind} task={args.task}")


def summarize(entries):
    latest = {}
    totals = {}
    for entry in entries:
        agent = entry.get("agent")
        if not agent:
            continue
        latest[(entry["task"], agent)] = entry
        bucket = totals.setdefault(agent, {**{s: 0 for s in SEVERITIES}, "rounds": 0})
        for severity in SEVERITIES:
            bucket[severity] += (entry.get("new") or {}).get(severity, 0)
        bucket["rounds"] = max(bucket["rounds"], entry.get("round", 1))
    return list(latest.values()), totals


def commits_after(entry_head, head):
    result = subprocess.run(["git", "rev-list", "--count", f"{entry_head}..{head}"],
                            capture_output=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        return None
    return int(result.stdout.strip() or 0)


def stale_entries(latest, head):
    stale = []
    for entry in latest:
        if "new" not in entry:
            continue
        behind = commits_after(entry.get("head"), head)
        if behind != 0:
            stale.append({"task": entry["task"], "agent": entry["agent"],
                          "head": entry.get("head"), "commits_after": behind})
    return stale


def status(args):
    entries = read_entries(args.ledger)
    latest, totals = summarize(entries)
    notes = [{k: e[k] for k in ("kind", "task", "text", "ts")} for e in entries
             if e.get("event") == "note"]
    stale = stale_entries(latest, args.head) if args.head else []
    behind = {(s["task"], s["agent"]): s["commits_after"] for s in stale}
    if args.json:
        report = {"latest": latest, "totals": totals, "notes": notes}
        if args.head:
            report["stale"] = stale
        print(json.dumps(report, indent=2))
        return
    for entry in latest:
        key = (entry["task"], entry["agent"])
        flag = ""
        if key in behind:
            count = behind[key]
            flag = "  STALE (unknown range)" if count is None else f"  STALE (+{count} commits)"
        print(f"{entry['task']:<10} {entry['agent']:<12} {entry['verdict']:<20} "
              f"{str(entry.get('from'))[:8]}..{str(entry.get('head'))[:8]}  round {entry.get('round')}"
              f"{flag}")
    for agent, bucket in totals.items():
        raised = ", ".join(f"{bucket[s]} {s}" for s in SEVERITIES)
        print(f"total {agent:<12} raised: {raised}; rounds: {bucket['rounds']}")
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
