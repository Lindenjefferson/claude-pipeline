#!/usr/bin/env python3
"""Delivery ledger: one JSON line per agent run, grouped in cycles, so the manager sees what is pending.

  start   --slug <slug> [--base <rev>] [--plan <path>] [--archive]       once per delivery
  add     --agent dev --task <id> --verdict <v> [--seconds <duration>] [--tokens N] [--summary <text>]
  add     --agent reviewer|qa --verdict PASS|FAIL [--critical N --important N --minor N --origin <origin>=N,...]
          [--seconds <duration>] [--tokens N]
  claim   --task <id>                                         a dev run dispatched; refused if the task is in flight or done
  release --task <id>                                         frees a claim whose run was lost
  note    --text <text> [--validar]                           a decision taken on the user's behalf
  validate --id <id> --decision <text>                        the user's decision on a VALIDAR item (V1, V2...)
  waive   --agent reviewer|qa --reason <text>                 accepts the open findings of that agent's latest FAIL
  plan    --path <path>                                       the approved plan, when start ran before it existed
  mode    autonomous|supervised                               the user turned autonomous mode on, or is back
  defer   --text <text>                                       an item left for later; prints its id (D1, D2...)
  resolve --id <id> --decision <text>                         the final decision on a deferred item
  lesson  --text <rule> [--check <test or lint rule>]         a lesson, automated when --check names the check
  status  [--json] [--check]                                  the current cycle, what it still needs, and metrics

A claim is written when the dev is dispatched and freed by the dev's add (or release); status lists the tasks in
flight and the gate waits for them, so a manager resuming after a compaction sees which runs it still owes a report.
claim refuses a task that is in flight or already DONE in the current cycle, so one task never runs twice by mistake.

A cycle is a few dev tasks followed by one reviewer pass over their diff and one qa pass; the two run in parallel.
It closes when the latest reviewer PASS came after the latest dev run, qa PASSed after the cycle's latest regular
task, and qa ran again after every fix of a blocking (FAIL) finding. The next regular dev run opens the next cycle.
A fix round (task fix-N) and the cleanup task (task cleanup) stay in the current cycle, even a closed one: they need
a reviewer pass, and qa again only when a FAIL came before them. Every finding carries its origin (design,
assumption, plan, execution, environment); --seconds takes 90, 12m, 1h5m or 12m30s, and --seconds and --tokens
come from the agent's completion notification, never an estimate (a run without it goes unmeasured). A deferred item
with no decision keeps the delivery from the gate. start --archive moves an existing delivery to
ledger-<old-slug>.jsonl next to the ledger first. --check exits 1 while anything is pending, so the gate can rely on
it. A cycle whose reviewer or qa still fails after a fix round asks the user; in autonomous mode the fix rounds go on
up to three, then the delivery stops. waive is refused when the dev ran after that FAIL (the fix needs its review); it
records the reason as a note and counts as that agent's PASS at the head it reviewed. Notes marked --validar (and
waivers in autonomous mode) are listed apart, numbered V1, V2... in the order written, for the user to confirm on
return; validate records the decision, and status lists the items still waiting apart from the decided ones. A
ledger with no mode entry is supervised.

Without --ledger, the ledger is .superpowers/ledger.jsonl at the root of the current worktree, or of the main
worktree when the current one has none (a task worktree), except for start, which always uses the current one. A
line that is not JSON stops every command with its line number, so a truncated write is never skipped silently."""
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
ORIGINS = ("design", "assumption", "plan", "execution", "environment")
SEVERITIES = ("critical", "important", "minor")
FIX_ROUNDS = {False: 1, True: 3}
FIX_TASK = re.compile(r"fix-\d+", re.IGNORECASE)
FOLLOW_UP = re.compile(r"fix-\d+|cleanup", re.IGNORECASE)
DURATION = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?|(\d+)")
LEDGER = os.path.join(".superpowers", "ledger.jsonl")


def git_head(rev="HEAD", ledger=None):
    where = os.path.dirname(os.path.abspath(ledger)) if ledger else None
    for cwd in ([where] if where and os.path.isdir(where) else []) + [None]:
        result = subprocess.run(["git", "rev-parse", "--verify", "--quiet", rev + "^{commit}"], capture_output=True,
                                text=True, cwd=cwd)
        if result.returncode == 0:
            return result.stdout.strip()
    return None


def git_path(*args):
    result = subprocess.run(["git", "rev-parse", *args], capture_output=True, text=True)
    return os.path.abspath(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else None


def default_ledger(command):
    top = git_path("--show-toplevel")
    here = os.path.join(top, LEDGER) if top else LEDGER
    common = git_path("--git-common-dir")
    main = os.path.join(os.path.dirname(common), LEDGER) if common else here
    return here if os.path.exists(here) or command == "start" or not os.path.exists(main) else main


def read(path):
    if not os.path.exists(path):
        return []
    entries = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except ValueError as error:
                sys.exit(f"{path}:{number}: not a ledger entry ({error}); fix or remove that line by hand")
    return entries


def write(path, entry):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    entry["at"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def runs(entries):
    return [entry for entry in entries if entry["type"] == "run"]


def is_task(entry, pattern):
    return entry["agent"] == "dev" and bool(pattern.fullmatch(entry.get("task") or ""))


def cycles(entries):
    groups, current, closed = [], [], False
    for entry in runs(entries):
        if closed and entry["agent"] == "dev" and not is_task(entry, FOLLOW_UP):
            groups.append(current)
            current, closed = [], False
        current.append(entry)
        closed = cycle_state(current)[1] == []
    groups.append(current)
    return groups


def cycle_state(cycle, autonomous=False):
    tasks, reviews, checks = {}, [], []
    work = last_dev = last_review = last_qa = needs_qa = -1
    for index, entry in enumerate(cycle):
        if entry["agent"] == "dev":
            tasks[entry["task"]] = entry
            if not is_task(entry, FOLLOW_UP):
                work = index
            if any(run["verdict"] == "FAIL" for run in cycle[last_dev + 1:index] if run["agent"] in ("reviewer", "qa")):
                needs_qa = index
            last_dev = index
        elif entry["agent"] == "reviewer":
            reviews.append(entry)
            last_review = index
        elif entry["agent"] == "qa":
            checks.append(entry)
            last_qa = index
    state = {"tasks": tasks, "reviewer": reviews[-1:], "qa": checks[-1:]}
    pending = [f"dev {task}: {entry['verdict']}" for task, entry in tasks.items()
               if entry["verdict"] not in ("DONE", "DONE_WITH_CONCERNS")]
    if not tasks:
        pending.append("no dev task yet")
    if pending:
        return state, pending
    if last_review < last_dev:
        pending.append("reviewer has not reviewed the latest changes")
    elif reviews[-1]["verdict"] == "FAIL":
        pending.append(f"reviewer FAIL ({reviews[-1]['open']} open): dev fixes every finding in one batch")
    if not checks or last_qa < work:
        pending.append("qa has not run on the cycle's tasks")
    elif checks[-1]["verdict"] == "FAIL" and last_qa > last_dev:
        pending.append(f"qa FAIL ({checks[-1]['open']} open): dev fixes every finding in one batch")
    elif last_qa < needs_qa:
        pending.append("qa has not re-run the scenarios the fix touched")
    rounds = FIX_ROUNDS[autonomous]
    for agent, done in (("reviewer", reviews), ("qa", checks)):
        failed = sum(1 for entry in done if entry["verdict"] == "FAIL")
        if done and done[-1]["verdict"] == "FAIL" and failed > rounds:
            pending.append(f"{agent} still fails after {rounds} fix rounds: stop the delivery and record the open "
                           "findings as note --validar" if autonomous else
                           f"{agent} still fails after a fix round: ask the user")
    return state, pending


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
    base = git_head(args.base, args.ledger)
    if base is None:
        sys.exit(f"not a commit: {args.base}")
    if entries:
        target = archive_path(args.ledger, entries[0].get("slug"))
        os.replace(args.ledger, target)
        print(f"archived {entries[0].get('slug')} to {target}")
    write(args.ledger, {"type": "start", "slug": args.slug, "base": base, "plan": args.plan})
    print(f"started {args.slug} at {base[:12]}")


def seconds(text):
    match = DURATION.fullmatch(text.strip()) if text and text.strip() else None
    if not match or not any(match.groups()):
        sys.exit(f"--seconds must look like 90, 12m, 1h5m or 12m30s, not {text!r}")
    hours, minutes, rest, bare = (int(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + rest + bare


def origins(text, total):
    counts = {}
    for item in filter(None, (part.strip() for part in (text or "").split(","))):
        name, _, number = (piece.strip() for piece in item.partition("="))
        if name not in ORIGINS or not number.isdigit():
            sys.exit(f"--origin takes <origin>=N with origin one of {', '.join(ORIGINS)}, not {item!r}")
        counts[name] = counts.get(name, 0) + int(number)
    if sum(counts.values()) != total:
        sys.exit(f"--origin must classify every finding: {sum(counts.values())} classified, {total} counted")
    return counts


def add(args):
    entries = read(args.ledger)
    if not entries:
        sys.exit("no delivery started: run start first")
    if args.verdict not in VERDICTS[args.agent]:
        sys.exit(f"{args.agent} verdict must be one of {', '.join(sorted(VERDICTS[args.agent]))}")
    if args.agent == "dev" and not args.task:
        sys.exit("dev runs need --task")
    blocking = args.critical + args.important
    if args.agent in ("reviewer", "qa") and (args.verdict == "FAIL") != (blocking > 0):
        sys.exit("FAIL needs open Critical/Important findings (--critical or --important > 0) and PASS none")
    entry = {"type": "run", "agent": args.agent, "task": args.task, "verdict": args.verdict, "open": blocking,
             "critical": args.critical, "important": args.important, "minor": args.minor,
             "origin": origins(args.origin, blocking + args.minor), "head": git_head(ledger=args.ledger) or "",
             "summary": args.summary}
    if args.seconds is not None:
        entry["seconds"] = seconds(args.seconds)
    if args.tokens is not None:
        entry["tokens"] = args.tokens
    write(args.ledger, entry)
    print(f"{args.agent}{' ' + args.task if args.task else ''}: {args.verdict} (cycle {len(cycles(read(args.ledger)))})")


def in_flight(entries):
    held = {}
    for entry in entries:
        if entry["type"] == "claim":
            held[entry["task"]] = entry["at"]
        elif entry["type"] == "release" or (entry["type"] == "run" and entry["agent"] == "dev"):
            held.pop(entry.get("task"), None)
    return held


def claim(args):
    entries = read(args.ledger)
    if not entries:
        sys.exit("no delivery started: run start first")
    held = in_flight(entries)
    if args.task in held:
        sys.exit(f"{args.task} is already claimed ({held[args.task]}): its dev run is in flight; "
                 f"if that run was lost, release --task {args.task}")
    groups = cycles(entries)
    done = cycle_state(groups[-1])[0]["tasks"].get(args.task)
    if done and done["verdict"] in ("DONE", "DONE_WITH_CONCERNS"):
        sys.exit(f"{args.task} is already done in cycle {len(groups)}: use a new task id (fix-N for a fix round)")
    write(args.ledger, {"type": "claim", "task": args.task})
    print(f"claimed {args.task}")


def release(args):
    if args.task not in in_flight(read(args.ledger)):
        sys.exit(f"{args.task} has no claim in flight")
    write(args.ledger, {"type": "release", "task": args.task})
    print(f"released {args.task}")


def note(args):
    if not read(args.ledger):
        sys.exit("no delivery started: run start first")
    entry = {"type": "note", "text": args.text}
    if args.validar:
        entry["validar"] = True
    write(args.ledger, entry)
    print("noted (VALIDAR)" if args.validar else "noted")


def validar(entries):
    items, decisions = [], {}
    for entry in entries:
        if entry["type"] == "note" and entry.get("validar"):
            items.append({"id": f"V{len(items) + 1}", "text": entry["text"], "decision": None})
        elif entry["type"] == "validate":
            decisions[entry["id"]] = entry["decision"]
    for item in items:
        item["decision"] = decisions.get(item["id"])
    return items


def validate(args):
    entries = read(args.ledger)
    if args.id not in {item["id"] for item in validar(entries)}:
        sys.exit(f"no VALIDAR item {args.id}")
    if not args.decision.strip():
        sys.exit("--decision needs the user's answer, not an empty text")
    write(args.ledger, {"type": "validate", "id": args.id, "decision": args.decision})
    print(f"{args.id} validated")


def waive(args):
    entries = read(args.ledger)
    if not entries:
        sys.exit("no delivery started: run start first")
    cycle = cycles(entries)[-1]
    done = [index for index, entry in enumerate(cycle) if entry["agent"] == args.agent]
    if not done or cycle[done[-1]]["verdict"] != "FAIL":
        sys.exit(f"the latest {args.agent} run of the cycle is not a FAIL: nothing to waive")
    if any(entry["agent"] == "dev" for entry in cycle[done[-1] + 1:]):
        sys.exit(f"the dev ran after that {args.agent} FAIL: run the {args.agent} on the fix to review it instead")
    text = f"waived {args.agent} FAIL: {args.reason}"
    write(args.ledger, {"type": "note", "text": text, **({"validar": True} if autonomous(entries) else {})})
    write(args.ledger, {"type": "run", "agent": args.agent, "task": "", "verdict": "PASS", "open": 0, "critical": 0,
                        "important": 0, "minor": 0, "origin": {}, "head": cycle[done[-1]].get("head", ""),
                        "summary": "", "waived": args.reason})
    print(text)


def plan(args):
    if not read(args.ledger):
        sys.exit("no delivery started: run start first")
    write(args.ledger, {"type": "plan", "plan": args.path})
    print(f"plan {args.path}")


def autonomous(entries):
    modes = [entry["mode"] for entry in entries if entry["type"] == "mode"]
    return bool(modes) and modes[-1] == "autonomous"


def mode(args):
    if not read(args.ledger):
        sys.exit("no delivery started: run start first")
    write(args.ledger, {"type": "mode", "mode": args.mode})
    print(f"mode {args.mode}")


def deferred(entries):
    items = {}
    for entry in entries:
        if entry["type"] == "defer":
            items[entry["id"]] = {"id": entry["id"], "text": entry["text"], "decision": None}
        elif entry["type"] == "resolve" and entry["id"] in items:
            items[entry["id"]]["decision"] = entry["decision"]
    return list(items.values())


def defer(args):
    entries = read(args.ledger)
    if not entries:
        sys.exit("no delivery started: run start first")
    item = f"D{len(deferred(entries)) + 1}"
    write(args.ledger, {"type": "defer", "id": item, "text": args.text})
    print(f"deferred {item}: needs a final decision before the gate (resolve --id {item})")


def resolve(args):
    entries = read(args.ledger)
    if args.id not in {item["id"] for item in deferred(entries)}:
        sys.exit(f"no deferred item {args.id}")
    write(args.ledger, {"type": "resolve", "id": args.id, "decision": args.decision})
    print(f"{args.id} resolved")


def lesson(args):
    if not read(args.ledger):
        sys.exit("no delivery started: run start first")
    write(args.ledger, {"type": "lesson", "text": args.text, "check": args.check})
    print("lesson recorded" + (f" (automated: {args.check})" if args.check else ""))


def elapsed(cycle):
    measured = [entry for entry in cycle if entry.get("seconds") is not None and entry.get("at")]
    if not measured:
        return None
    ends = [datetime.datetime.fromisoformat(entry["at"]) for entry in measured]
    starts = [end - datetime.timedelta(seconds=entry["seconds"]) for end, entry in zip(ends, measured)]
    return int((max(ends) - min(starts)).total_seconds())


def metrics(entries):
    per_cycle, found = [], {name: 0 for name in ORIGINS + ("unclassified",)}
    for number, cycle in enumerate(cycles(entries), 1):
        passes = [entry for entry in cycle if entry["agent"] in ("reviewer", "qa")]
        counts = {key: sum(entry.get(key, 0) for entry in passes) for key in SEVERITIES + ("open",)}
        for entry in passes:
            classified = entry.get("origin") or {}
            for name, count in classified.items():
                found[name] += count
            total = sum(entry.get(key, 0) for key in SEVERITIES)
            total += max(entry.get("open", 0) - entry.get("critical", 0) - entry.get("important", 0), 0)
            found["unclassified"] += total - sum(classified.values())
        agents = {}
        for entry in cycle:
            if entry.get("seconds") is not None:
                agents[entry["agent"]] = agents.get(entry["agent"], 0) + entry["seconds"]
        fixes = {entry["task"] for entry in cycle if is_task(entry, FIX_TASK)}
        per_cycle.append({"cycle": number, **counts, "fix_rounds": len(fixes), "seconds": sum(agents.values()),
                          "elapsed": elapsed(cycle), "agents": agents,
                          "tokens": sum(entry.get("tokens") or 0 for entry in cycle)})
    measured = [entry for entry in runs(entries) if entry.get("waived") is None]
    lessons = [{"text": entry["text"], "check": entry.get("check", "")} for entry in entries
               if entry["type"] == "lesson"]
    return {"cycles": per_cycle, "origins": found, "time": totals(measured, "seconds"),
            "tokens": totals(measured, "tokens"), "lessons": lessons}


def totals(entries, key):
    sums = {"agents": {}, "tasks": {}, "unmeasured": 0}
    for entry in entries:
        if entry.get(key) is None:
            sums["unmeasured"] += 1
            continue
        sums["agents"][entry["agent"]] = sums["agents"].get(entry["agent"], 0) + entry[key]
        if entry["agent"] == "dev":
            sums["tasks"][entry["task"]] = sums["tasks"].get(entry["task"], 0) + entry[key]
    return sums


def status(args):
    entries = read(args.ledger)
    if not entries:
        sys.exit("no delivery started")
    groups = cycles(entries)
    auto = autonomous(entries)
    state, pending = cycle_state(groups[-1], auto)
    items = deferred(entries)
    held = in_flight(entries)
    pending += [f"dev {task} dispatched at {at}, no report yet (add it when it reports, or release --task {task})"
                for task, at in held.items()]
    pending += [f"deferred {item['id']} has no decision: {item['text']}" for item in items if not item["decision"]]
    plans = [entry["plan"] for entry in entries if entry["type"] == "plan"]
    report = {"slug": entries[0].get("slug"), "base": entries[0].get("base"), "ledger": os.path.abspath(args.ledger),
              "plan": plans[-1] if plans else entries[0].get("plan"),
              "cycle": len(groups), "in_flight": list(held), "dispatched": held,
              "tasks": {task: entry["verdict"] for task, entry in state["tasks"].items()},
              "reviewer": state["reviewer"], "qa": state["qa"], "runs": groups[-1], "pending": pending,
              "autonomous": auto, "deferred": items,
              "notes": [entry["text"] for entry in entries if entry["type"] == "note" and not entry.get("validar")],
              "validar": validar(entries),
              "metrics": metrics(entries), "ready_for_gate": not pending}
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"delivery {report['slug']} (base {str(report['base'])[:12]}), cycle {report['cycle']}")
        if auto:
            print("mode: autonomous (approvals become VALIDAR notes; never merge into or push the default branch)")
        for task, verdict in report["tasks"].items():
            print(f"- {task}: {verdict}")
        for agent in ("reviewer", "qa"):
            if report[agent]:
                print(f"- {agent}: {report[agent][0]['verdict']}")
        for item in pending:
            print(f"pending: {item}")
        for text in report["notes"]:
            print(f"note: {text}")
        for item in report["validar"]:
            print(f"VALIDAR {item['id']}: {item['text']}" if item["decision"] is None
                  else f"validated {item['id']}: {item['text']} -> {item['decision']}")
        for item in items:
            if item["decision"]:
                print(f"deferred {item['id']}: {item['text']} -> {item['decision']}")
        print("ready for gate" if report["ready_for_gate"] else "not ready for gate")
    if args.check and pending:
        sys.exit(1)


def count(text):
    if not text.isdigit():
        raise argparse.ArgumentTypeError(f"a count is a whole number of 0 or more, not {text!r}")
    return int(text)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ledger", help="default: .superpowers/ledger.jsonl at the root of this worktree, or of "
                                         "the main worktree when this one has none")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("start")
    command.add_argument("--slug", required=True)
    command.add_argument("--base", default="HEAD")
    command.add_argument("--plan", help="the approved plan, whose acceptance-criterion ids the gate traces to tests")
    command.add_argument("--archive", action="store_true", help="move an existing delivery aside first")
    command.set_defaults(run=start)
    command = commands.add_parser("add")
    command.add_argument("--agent", required=True, choices=sorted(VERDICTS))
    command.add_argument("--task", default="")
    command.add_argument("--verdict", required=True)
    for severity in SEVERITIES:
        command.add_argument(f"--{severity}", type=count, default=0)
    command.add_argument("--origin", default="", help="design=N,assumption=N,plan=N,execution=N,environment=N")
    command.add_argument("--seconds", help="how long the run took, from its completion notification: 90, 12m, 1h5m or 12m30s")
    command.add_argument("--tokens", type=count, help="the tokens the run used, from its completion notification")
    command.add_argument("--summary", default="")
    command.set_defaults(run=add)
    for name, run in (("claim", claim), ("release", release)):
        command = commands.add_parser(name)
        command.add_argument("--task", required=True)
        command.set_defaults(run=run)
    command = commands.add_parser("note")
    command.add_argument("--text", required=True)
    command.add_argument("--validar", action="store_true", help="the user validates this decision on return")
    command.set_defaults(run=note)
    command = commands.add_parser("validate")
    command.add_argument("--id", required=True)
    command.add_argument("--decision", required=True)
    command.set_defaults(run=validate)
    command = commands.add_parser("waive")
    command.add_argument("--agent", required=True, choices=("reviewer", "qa"))
    command.add_argument("--reason", required=True)
    command.set_defaults(run=waive)
    command = commands.add_parser("plan")
    command.add_argument("--path", required=True)
    command.set_defaults(run=plan)
    command = commands.add_parser("mode")
    command.add_argument("mode", choices=("autonomous", "supervised"))
    command.set_defaults(run=mode)
    command = commands.add_parser("defer")
    command.add_argument("--text", required=True)
    command.set_defaults(run=defer)
    command = commands.add_parser("resolve")
    command.add_argument("--id", required=True)
    command.add_argument("--decision", required=True)
    command.set_defaults(run=resolve)
    command = commands.add_parser("lesson")
    command.add_argument("--text", required=True)
    command.add_argument("--check", default="")
    command.set_defaults(run=lesson)
    command = commands.add_parser("status")
    command.add_argument("--json", action="store_true")
    command.add_argument("--check", action="store_true")
    command.set_defaults(run=status)
    args = parser.parse_args()
    args.ledger = args.ledger or default_ledger(args.command)
    args.run(args)


if __name__ == "__main__":
    main()
