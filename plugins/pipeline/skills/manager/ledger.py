#!/usr/bin/env python3
"""Delivery ledger: one JSON line per agent run, so the manager and the gate see what ran and what is pending.

  start  --slug <slug> [--base <rev>]                       once per delivery
  add    --task <id> --agent <agent> --verdict <v> [--open N] [--summary <text>]
  note   --task <id> --text <text>                          a decision taken on the user's behalf
  status [--json] [--check]                                 per task: latest verdict per agent, what is pending

A task is done when its latest dev run is followed by a reviewer PASS and then a qa PASS. --check exits 1
while any task is not done, so the gate can rely on it."""
import argparse
import datetime
import json
import os
import subprocess
import sys

VERDICTS = {
    "discovery": {"DONE", "NEEDS_CONTEXT", "BLOCKED"},
    "dev": {"DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "BLOCKED"},
    "reviewer": {"PASS", "FAIL"},
    "qa": {"PASS", "FAIL"},
    "gate": {"APPROVED", "BLOCKED"},
}
ROUND_LIMIT = 3


def git_head(rev="HEAD"):
    result = subprocess.run(["git", "rev-parse", "--verify", "--quiet", rev + "^{commit}"], capture_output=True,
                            text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def read(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write(path, entry):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    entry["at"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def start(args):
    if read(args.ledger):
        sys.exit(f"{args.ledger} already has a delivery; use a new ledger file per delivery")
    base = git_head(args.base)
    if base is None:
        sys.exit(f"not a commit: {args.base}")
    write(args.ledger, {"type": "start", "slug": args.slug, "base": base})
    print(f"started {args.slug} at {base[:12]}")


def add(args):
    entries = read(args.ledger)
    if not entries:
        sys.exit("no delivery started: run start first")
    if args.verdict not in VERDICTS[args.agent]:
        sys.exit(f"{args.agent} verdict must be one of {', '.join(sorted(VERDICTS[args.agent]))}")
    if args.agent in ("reviewer", "qa") and (args.verdict == "FAIL") != (args.open > 0):
        sys.exit("FAIL needs --open > 0 (open Critical/Important findings) and PASS needs --open 0")
    runs = [e for e in entries if e["type"] == "run" and e["task"] == args.task and e["agent"] == args.agent]
    entry = {"type": "run", "task": args.task, "agent": args.agent, "verdict": args.verdict, "open": args.open,
             "round": len(runs) + 1, "head": git_head() or "", "summary": args.summary}
    write(args.ledger, entry)
    print(f"{args.task} {args.agent} round {entry['round']}: {args.verdict}")


def note(args):
    if not read(args.ledger):
        sys.exit("no delivery started: run start first")
    write(args.ledger, {"type": "note", "task": args.task, "text": args.text})
    print("noted")


def task_state(runs):
    latest = {}
    for index, entry in enumerate(runs):
        latest[entry["agent"]] = (index, entry)
    pending = []
    dev = latest.get("dev")
    review = latest.get("reviewer")
    qa = latest.get("qa")
    if dev and dev[1]["verdict"] not in ("DONE", "DONE_WITH_CONCERNS"):
        pending.append(f"dev {dev[1]['verdict']}")
    elif not review or (dev and review[0] < dev[0]):
        pending.append("reviewer has not reviewed the latest dev run")
    elif review[1]["verdict"] != "PASS":
        pending.append(f"reviewer FAIL ({review[1]['open']} open): back to dev")
    elif not qa or qa[0] < review[0]:
        pending.append("qa has not run after the latest review")
    elif qa[1]["verdict"] != "PASS":
        pending.append(f"qa FAIL ({qa[1]['open']} open): back to dev")
    for agent in ("reviewer", "qa"):
        if agent in latest and latest[agent][1]["verdict"] == "FAIL" and latest[agent][1]["round"] >= ROUND_LIMIT:
            pending.append(f"{agent} failed {ROUND_LIMIT} rounds: ask the user")
    return {agent: entry for agent, (_, entry) in latest.items()}, pending


def status(args):
    entries = read(args.ledger)
    if not entries:
        sys.exit("no delivery started")
    header = entries[0]
    tasks = {}
    for entry in entries:
        if entry["type"] == "run" and entry["agent"] not in ("discovery", "gate"):
            tasks.setdefault(entry["task"], []).append(entry)
    report = {"slug": header.get("slug"), "base": header.get("base"), "tasks": {},
              "notes": [e for e in entries if e["type"] == "note"],
              "gate": [e for e in entries if e["type"] == "run" and e["agent"] == "gate"][-1:]}
    for task, runs in tasks.items():
        latest, pending = task_state(runs)
        report["tasks"][task] = {"latest": latest, "pending": pending}
    report["ready_for_gate"] = bool(tasks) and not any(t["pending"] for t in report["tasks"].values())
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"delivery {report['slug']} (base {str(report['base'])[:12]})")
        for task, state in report["tasks"].items():
            runs = ", ".join(f"{agent} r{e['round']} {e['verdict']}" for agent, e in state["latest"].items())
            print(f"- {task}: {runs}")
            for item in state["pending"]:
                print(f"    pending: {item}")
        for entry in report["notes"]:
            print(f"note [{entry['task']}]: {entry['text']}")
        print("ready for gate" if report["ready_for_gate"] else "not ready for gate")
    if args.check and not report["ready_for_gate"]:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ledger", default=".superpowers/ledger.jsonl")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("start")
    command.add_argument("--slug", required=True)
    command.add_argument("--base", default="HEAD")
    command.set_defaults(run=start)
    command = commands.add_parser("add")
    command.add_argument("--task", required=True)
    command.add_argument("--agent", required=True, choices=sorted(VERDICTS))
    command.add_argument("--verdict", required=True)
    command.add_argument("--open", type=int, default=0)
    command.add_argument("--summary", default="")
    command.set_defaults(run=add)
    command = commands.add_parser("note")
    command.add_argument("--task", required=True)
    command.add_argument("--text", required=True)
    command.set_defaults(run=note)
    command = commands.add_parser("status")
    command.add_argument("--json", action="store_true")
    command.add_argument("--check", action="store_true")
    command.set_defaults(run=status)
    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
