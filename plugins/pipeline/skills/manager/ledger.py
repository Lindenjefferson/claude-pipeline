#!/usr/bin/env python3
"""Delivery ledger: one JSON line per agent run, grouped in cycles, so the manager sees what is pending.

  start  --slug <slug> [--base <rev>] [--archive]           once per delivery
  add    --agent dev --task <id> --verdict <v> [--summary <text>]   (task fix-N for a fix round)
  add    --agent reviewer|qa --verdict PASS|FAIL [--critical N --important N | --open N] [--minor N]
  note   --text <text>                                      a decision taken on the user's behalf
  lesson --text <rule> [--check <test or lint rule>]        a lesson, automated when --check names the check
  status [--json] [--check]                                 the current cycle, what it still needs, and metrics

A cycle is a few dev tasks followed by one reviewer pass over their diff and one qa pass. It closes when the latest
reviewer PASS came after the latest dev run and qa PASSed after the cycle's latest regular task; the next regular
dev run opens the next cycle. A fix round (task fix-N) always stays in the current cycle, even a closed one: it needs
a reviewer pass on the fix, and qa again only when the cycle's latest qa was a FAIL. start --archive moves an
existing delivery to ledger-<old-slug>.jsonl next to the ledger first. --check exits 1 while the current cycle is
open, so the gate can rely on it."""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

VERDICTS = {
    "discovery": {"DONE", "NEEDS_CONTEXT", "BLOCKED"},
    "dev": {"DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "BLOCKED"},
    "reviewer": {"PASS", "FAIL"},
    "qa": {"PASS", "FAIL"},
}
FIX_ROUNDS = 2
FIX_TASK = re.compile(r"fix-\d+", re.IGNORECASE)


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


def runs(entries):
    return [entry for entry in entries if entry["type"] == "run"]


def is_fix(entry):
    return entry["agent"] == "dev" and bool(FIX_TASK.fullmatch(entry.get("task") or ""))


def cycles(entries):
    groups, current, closed = [], [], False
    for entry in runs(entries):
        if closed and entry["agent"] == "dev" and not is_fix(entry):
            groups.append(current)
            current, closed = [], False
        current.append(entry)
        closed = cycle_state(current)[1] == []
    groups.append(current)
    return groups


def cycle_state(cycle):
    tasks, reviews, checks, last, work = {}, [], [], {}, -1
    for index, entry in enumerate(cycle):
        last[entry["agent"]] = index
        if entry["agent"] == "dev":
            tasks[entry["task"]] = entry
            if not is_fix(entry):
                work = index
        elif entry["agent"] == "reviewer":
            reviews.append(entry)
        elif entry["agent"] == "qa":
            checks.append(entry)
    pending = [f"dev {task}: {entry['verdict']}" for task, entry in tasks.items()
               if entry["verdict"] not in ("DONE", "DONE_WITH_CONCERNS")]
    if not tasks:
        pending.append("no dev task yet")
    if pending:
        return {"tasks": tasks, "reviewer": reviews[-1:], "qa": checks[-1:]}, pending
    if last.get("reviewer", -1) < last["dev"]:
        pending.append("reviewer has not reviewed the latest changes")
    elif reviews[-1]["verdict"] == "FAIL":
        pending.append(f"reviewer FAIL ({reviews[-1]['open']} open): dev fixes every finding in one batch")
    elif last.get("qa", -1) < work or not checks:
        pending.append("qa has not run after the latest review")
    elif checks[-1]["verdict"] == "FAIL" and last["qa"] < last["dev"]:
        pending.append("qa has not re-run the scenarios that failed")
    elif checks[-1]["verdict"] == "FAIL":
        pending.append(f"qa FAIL ({checks[-1]['open']} open): dev fixes every finding in one batch")
    for agent, done in (("reviewer", reviews), ("qa", checks)):
        failed = sum(1 for entry in done if entry["verdict"] == "FAIL")
        if done and done[-1]["verdict"] == "FAIL" and failed >= FIX_ROUNDS:
            pending.append(f"{agent} still fails after a fix round: ask the user")
    return {"tasks": tasks, "reviewer": reviews[-1:], "qa": checks[-1:]}, pending


def archive_path(ledger, slug):
    name = "ledger-" + re.sub(r"[^\w.-]+", "-", slug or "delivery")
    stem = os.path.join(os.path.dirname(os.path.abspath(ledger)), name)
    path, number = stem + ".jsonl", 1
    while os.path.exists(path):
        number += 1
        path = f"{stem}-{number}.jsonl"
    return path


def start(args):
    entries = read(args.ledger)
    if entries and not args.archive:
        sys.exit(f"{args.ledger} already has a delivery ({entries[0].get('slug')}); "
                 "run start --archive to move it to ledger-<slug>.jsonl and start fresh")
    base = git_head(args.base)
    if base is None:
        sys.exit(f"not a commit: {args.base}")
    if entries:
        target = archive_path(args.ledger, entries[0].get("slug"))
        os.replace(args.ledger, target)
        print(f"archived {entries[0].get('slug')} to {target}")
    write(args.ledger, {"type": "start", "slug": args.slug, "base": base})
    print(f"started {args.slug} at {base[:12]}")


def add(args):
    entries = read(args.ledger)
    if not entries:
        sys.exit("no delivery started: run start first")
    if args.verdict not in VERDICTS[args.agent]:
        sys.exit(f"{args.agent} verdict must be one of {', '.join(sorted(VERDICTS[args.agent]))}")
    if args.agent == "dev" and not args.task:
        sys.exit("dev runs need --task")
    blocking = args.critical + args.important
    if args.open is not None and blocking and args.open != blocking:
        sys.exit("--open must equal --critical + --important")
    open_count = blocking if args.open is None else args.open
    if args.agent in ("reviewer", "qa") and (args.verdict == "FAIL") != (open_count > 0):
        sys.exit("FAIL needs open Critical/Important findings (--critical, --important or --open > 0) and PASS none")
    write(args.ledger, {"type": "run", "agent": args.agent, "task": args.task, "verdict": args.verdict,
                        "open": open_count, "critical": args.critical, "important": args.important,
                        "minor": args.minor, "head": git_head() or "", "summary": args.summary})
    print(f"{args.agent}{' ' + args.task if args.task else ''}: {args.verdict} (cycle {len(cycles(read(args.ledger)))})")


def note(args):
    if not read(args.ledger):
        sys.exit("no delivery started: run start first")
    write(args.ledger, {"type": "note", "text": args.text})
    print("noted")


def lesson(args):
    if not read(args.ledger):
        sys.exit("no delivery started: run start first")
    write(args.ledger, {"type": "lesson", "text": args.text, "check": args.check})
    print("lesson recorded" + (f" (automated: {args.check})" if args.check else ""))


def metrics(entries):
    per_cycle = []
    for number, cycle in enumerate(cycles(entries), 1):
        passes = [entry for entry in cycle if entry["agent"] in ("reviewer", "qa")]
        counts = {key: sum(entry.get(key, 0) for entry in passes)
                  for key in ("critical", "important", "minor", "open")}
        fixes = {entry["task"] for entry in cycle if is_fix(entry)}
        per_cycle.append({"cycle": number, **counts, "fix_rounds": len(fixes)})
    lessons = [{"text": entry["text"], "check": entry.get("check", "")} for entry in entries
               if entry["type"] == "lesson"]
    return {"cycles": per_cycle, "lessons": lessons}


def status(args):
    entries = read(args.ledger)
    if not entries:
        sys.exit("no delivery started")
    groups = cycles(entries)
    state, pending = cycle_state(groups[-1])
    report = {"slug": entries[0].get("slug"), "base": entries[0].get("base"), "cycle": len(groups),
              "tasks": {task: entry["verdict"] for task, entry in state["tasks"].items()},
              "reviewer": state["reviewer"], "qa": state["qa"], "pending": pending,
              "notes": [entry["text"] for entry in entries if entry["type"] == "note"],
              "metrics": metrics(entries), "ready_for_gate": not pending}
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"delivery {report['slug']} (base {str(report['base'])[:12]}), cycle {report['cycle']}")
        for task, verdict in report["tasks"].items():
            print(f"- {task}: {verdict}")
        for agent in ("reviewer", "qa"):
            if report[agent]:
                print(f"- {agent}: {report[agent][0]['verdict']}")
        for item in pending:
            print(f"pending: {item}")
        for text in report["notes"]:
            print(f"note: {text}")
        print("ready for gate" if report["ready_for_gate"] else "not ready for gate")
    if args.check and pending:
        sys.exit(1)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ledger", default=".superpowers/ledger.jsonl")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("start")
    command.add_argument("--slug", required=True)
    command.add_argument("--base", default="HEAD")
    command.add_argument("--archive", action="store_true", help="move an existing delivery aside first")
    command.set_defaults(run=start)
    command = commands.add_parser("add")
    command.add_argument("--agent", required=True, choices=sorted(VERDICTS))
    command.add_argument("--task", default="")
    command.add_argument("--verdict", required=True)
    command.add_argument("--open", type=int)
    command.add_argument("--critical", type=int, default=0)
    command.add_argument("--important", type=int, default=0)
    command.add_argument("--minor", type=int, default=0)
    command.add_argument("--summary", default="")
    command.set_defaults(run=add)
    command = commands.add_parser("note")
    command.add_argument("--text", required=True)
    command.set_defaults(run=note)
    command = commands.add_parser("lesson")
    command.add_argument("--text", required=True)
    command.add_argument("--check", default="")
    command.set_defaults(run=lesson)
    command = commands.add_parser("status")
    command.add_argument("--json", action="store_true")
    command.add_argument("--check", action="store_true")
    command.set_defaults(run=status)
    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
