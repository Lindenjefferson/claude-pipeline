#!/usr/bin/env python3
import argparse
import json
import os
import re
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
VALIDATED_IMPLEMENTERS = ("dev", "db", "docs")
COMMITTING_IMPLEMENTERS = ("dev", "db")
COMMITTED_VERDICTS = ("DONE", "DONE_WITH_CONCERNS")
MIN_REPORT_CHARS = 200
LESSON_TEXT_MAX = 280
LESSONS_DEFAULT = ".superpowers/lessons.jsonl"
NAME_PATTERN = re.compile(r"^[\w.-]+$")
LEDGER_LINE = re.compile(r"^[\s`>*-]*LEDGER\s*\{", re.MULTILINE)
SHA_TOKEN = re.compile(r"\b[0-9a-f]{7,40}\b")
BACKTICKED = re.compile(r"`([^`\s]+)`")
FILES_LABEL = re.compile(r"^\s*(?:#+\s*)?\**\s*(?:changed\s+|modified\s+)?files"
                         r"(?:\s+(?:changed|touched|modified))?\s*\**\s*:\s*\**\s*(.*)$", re.IGNORECASE)
FILES_HEADING = re.compile(r"^\s*#+\s*(?:changed\s+)?files(?:\s+changed)?\s*$", re.IGNORECASE)
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
LINE_SUFFIX = re.compile(r":\d+(?:-\d+)?$")


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


def files_section_paths(text):
    found, inside = set(), False
    for line in text.splitlines():
        heading = FILES_HEADING.match(line)
        label = None if heading else FILES_LABEL.match(line)
        if heading or label:
            inside = True
            if label and label.group(1).strip():
                found.update(part.strip(" `*") for part in label.group(1).split(","))
            continue
        if not inside:
            continue
        item = LIST_ITEM.match(line)
        if item:
            ticked = BACKTICKED.findall(item.group(1))
            words = item.group(1).split(":", 1)[-1].split()
            found.update(ticked or words[:1])
        elif line.strip():
            inside = False
    return found


def cited_paths(text, files_section_only=False):
    candidates = files_section_paths(text)
    if not files_section_only:
        candidates |= set(BACKTICKED.findall(text))
    paths = set()
    for candidate in candidates:
        path = LINE_SUFFIX.sub("", candidate.strip(" `*,;")).replace("\\", "/")
        while path.startswith("./"):
            path = path[2:]
        if path:
            paths.add(path)
    return paths


def implementer_problems(entry, text, from_sha, head, allow_unlisted):
    problems = []
    if not LEDGER_LINE.search(text):
        problems.append("the report has no 'LEDGER {...}' line")
    body = "\n".join(line for line in text.splitlines() if not LEDGER_LINE.match(line))
    words = set(re.findall(r"[a-z]+", body.lower()))
    if len(re.sub(r"\s", "", body)) < MIN_REPORT_CHARS or (words and words <= {"placeholder", "todo"}):
        problems.append(f"the report looks like a placeholder (fewer than {MIN_REPORT_CHARS} "
                        "non-space characters besides the LEDGER line)")
    if entry["agent"] in COMMITTING_IMPLEMENTERS and entry["verdict"] in COMMITTED_VERDICTS:
        commits = git("rev-list", f"{from_sha}..{head}")[1].split()
        tokens = set(SHA_TOKEN.findall(text.lower()))
        if not any(sha.startswith(token) for token in tokens for sha in commits):
            problems.append(f"the report names no commit of {from_sha[:8]}..{head[:8]} "
                            "(it must cite the SHA it committed)")
    plain = ("-c", "core.quotepath=off")
    changed = set(git(*plain, "diff", "--name-only", f"{from_sha}..{head}")[1].splitlines())
    tracked = set(git(*plain, "ls-tree", "-r", "--full-tree", "--name-only", head)[1].splitlines())
    unlisted = sorted(p for p in cited_paths(text, files_section_only=True) if p in tracked and p not in changed)
    if unlisted and allow_unlisted is None:
        problems.append(f"the report cites files not changed in {from_sha[:8]}..{head[:8]}: "
                        f"{', '.join(unlisted)} (fix the report, or pass --allow-unlisted with a reason)")
    return problems, unlisted


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
    unlisted = []
    if entry["agent"] in VALIDATED_IMPLEMENTERS and role(entry) == "implement":
        with open(args.report, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        problems, unlisted = implementer_problems(entry, text, from_sha, head, args.allow_unlisted)
        if problems:
            sys.exit("report rejected:\n- " + "\n- ".join(problems))
    entries, invalid = read_ledger(args.ledger)
    warn_invalid(args.ledger, invalid)
    earlier = [e for e in entries if e.get("agent") == entry["agent"] and e.get("task") == args.task
               and role(e) == role(entry)]
    entry.update({"ts": now(), "from": from_sha, "head": head,
                  "round": len(earlier) + 1, "report": args.report})
    if unlisted:
        entry["unlisted"] = unlisted
    write_line(args.ledger, entry)
    print(f"{entry['agent']} {entry['verdict']} task={args.task} round={entry['round']}")
    if unlisted:
        reason = f" ({args.allow_unlisted})" if args.allow_unlisted else ""
        write_line(args.ledger, {"event": "note", "ts": now(), "kind": "ruling", "task": args.task,
                                 "text": f"{entry['agent']} r{entry['round']} report cites files outside "
                                         f"its diff, accepted with --allow-unlisted: "
                                         f"{', '.join(unlisted)}{reason}"})
        print(f"unlisted files accepted, ruling note recorded: {', '.join(unlisted)}")


def save_report(args):
    if not NAME_PATTERN.match(args.task):
        sys.exit(f"--task must match {NAME_PATTERN.pattern}: {args.task}")
    if args.agent not in AGENT_VERDICTS:
        sys.exit(f"unknown agent '{args.agent}' (expected one of: {', '.join(AGENT_VERDICTS)})")
    if args.file:
        if not os.path.isfile(args.file):
            sys.exit(f"--file does not exist: {args.file}")
        with open(args.file, "rb") as handle:
            raw = handle.read()
    else:
        raw = sys.stdin.buffer.read()
    text = re.sub(r"\r+\n", "\n", raw.decode("utf-8", errors="replace"))
    if not text.strip():
        sys.exit("the report is empty; nothing saved")
    directory = args.reports_dir or os.path.join(os.path.dirname(args.ledger) or ".", "reports")
    stem = os.path.join(directory, f"{args.task}-{args.agent}-r")
    if args.round == "auto":
        entries = read_ledger(args.ledger)[0] if os.path.exists(args.ledger) else []
        number = 1 + sum(1 for e in entries if e.get("agent") == args.agent and e.get("task") == args.task)
        while os.path.exists(f"{stem}{number}.md"):
            number += 1
    elif args.round.isdigit() and int(args.round) > 0:
        number = int(args.round)
    else:
        sys.exit(f"--round must be 'auto' or a positive integer: {args.round}")
    path = f"{stem}{number}.md"
    os.makedirs(directory, exist_ok=True)
    try:
        with open(path, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(text if text.endswith("\n") else text + "\n")
    except FileExistsError:
        sys.exit(f"report already exists, not overwriting: {path}")
    print(path.replace("\\", "/"))


def read_lessons(path):
    lessons = []
    if not os.path.exists(path):
        return lessons
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                lessons.append(json.loads(line))
            except ValueError:
                sys.exit(f"{path}:{number} is not valid JSON; fix it before writing lessons")
    return lessons


def write_lessons(path, lessons):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        for lesson in lessons:
            handle.write(json.dumps(lesson, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(temporary, path)


def find_lesson(lessons, lesson_id, path):
    for lesson in lessons:
        if lesson.get("id") == lesson_id:
            return lesson
    sys.exit(f"lesson '{lesson_id}' not found in {path}")


def lesson_add(args):
    for flag, value in (("--id", args.id), ("--stack", args.stack)):
        if not NAME_PATTERN.match(value):
            sys.exit(f"{flag} must match {NAME_PATTERN.pattern}: {value}")
    text = " ".join(args.text.split())
    if not text:
        sys.exit("--text is empty")
    if len(text) > LESSON_TEXT_MAX:
        sys.exit(f"--text has {len(text)} characters; a lesson is one rule of at most {LESSON_TEXT_MAX}")
    lessons = read_lessons(args.lessons)
    if any(lesson.get("id") == args.id for lesson in lessons):
        sys.exit(f"lesson '{args.id}' already exists in {args.lessons}")
    code, root = git("rev-parse", "--show-toplevel")
    project = args.project or os.path.basename(root if code == 0 and root else os.getcwd())
    lesson = {"id": args.id, "stack": args.stack,
              "paths": [glob.strip() for glob in args.paths.split(",") if glob.strip()],
              "text": text,
              "source": {"project": project, "task": args.task, "agent": args.agent,
                         "finding": args.finding},
              "counters": {"injected": 0, "held": 0, "recurred": 0},
              "status": "active", "created": time.strftime("%Y-%m-%d")}
    write_lessons(args.lessons, lessons + [lesson])
    print(f"lesson {args.id} added to {args.lessons}")


def lesson_mark(args):
    lessons = read_lessons(args.lessons)
    lesson = find_lesson(lessons, args.id, args.lessons)
    counter = "held" if args.held else "recurred"
    counters = lesson.setdefault("counters", {})
    counters[counter] = int(counters.get(counter, 0)) + 1
    write_lessons(args.lessons, lessons)
    print(f"lesson {args.id} {counter}={counters[counter]}")


def lesson_list(args):
    lessons = read_lessons(args.lessons)
    if args.json:
        print(json.dumps(lessons, indent=2, ensure_ascii=False))
        return
    for lesson in lessons:
        counters = lesson.get("counters", {})
        print(f"{lesson.get('id')}  [{lesson.get('stack')}, {lesson.get('status')}]  "
              f"injected {counters.get('injected', 0)}, held {counters.get('held', 0)}, "
              f"recurred {counters.get('recurred', 0)}  paths: {', '.join(lesson.get('paths') or ['(all)'])}")
        print(f"    {lesson.get('text')}")


def lesson_promote(args):
    lesson = find_lesson(read_lessons(args.lessons), args.id, args.lessons)
    stack = lesson.get("stack")
    if os.path.splitext(os.path.basename(args.to))[0] != stack:
        sys.exit(f"--to {args.to} is not the file of stack '{stack}' (expected lessons/{stack}.jsonl)")
    target = read_lessons(args.to)
    if any(existing.get("id") == args.id for existing in target):
        sys.exit(f"lesson '{args.id}' already exists in {args.to}")
    write_lessons(args.to, target + [lesson])
    print(f"lesson {args.id} promoted to {args.to}")


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
    append_cmd.add_argument("--allow-unlisted", nargs="?", const="", metavar="REASON",
                            help="accept an implementer report citing files outside FROM..HEAD (records a ruling note)")
    append_cmd.set_defaults(run=append)

    save_cmd = commands.add_parser("save-report", help="save an agent report as <task>-<agent>-r<round>.md")
    save_cmd.add_argument("--task", required=True)
    save_cmd.add_argument("--agent", required=True)
    save_cmd.add_argument("--round", default="auto", help="'auto' (next free round) or a number")
    save_cmd.add_argument("--reports-dir", help="default: 'reports' next to the ledger")
    source = save_cmd.add_mutually_exclusive_group(required=True)
    source.add_argument("--stdin", action="store_true")
    source.add_argument("--file")
    save_cmd.set_defaults(run=save_report)

    lesson_cmd = commands.add_parser("lesson", help="manage this delivery's lessons")
    lesson_cmd.add_argument("--lessons", default=LESSONS_DEFAULT)
    actions = lesson_cmd.add_subparsers(dest="action", required=True)
    add_cmd = actions.add_parser("add")
    for flag in ("--id", "--stack", "--text", "--task", "--agent", "--finding"):
        add_cmd.add_argument(flag, required=True)
    add_cmd.add_argument("--paths", default="", help="comma-separated globs; empty = every task of the stack")
    add_cmd.add_argument("--project", help="default: the repository folder name")
    add_cmd.set_defaults(run=lesson_add)
    mark_cmd = actions.add_parser("mark")
    mark_cmd.add_argument("--id", required=True)
    counter = mark_cmd.add_mutually_exclusive_group(required=True)
    counter.add_argument("--held", action="store_true")
    counter.add_argument("--recurred", action="store_true")
    mark_cmd.set_defaults(run=lesson_mark)
    list_cmd = actions.add_parser("list")
    list_cmd.add_argument("--json", action="store_true")
    list_cmd.set_defaults(run=lesson_list)
    promote_cmd = actions.add_parser("promote")
    promote_cmd.add_argument("--id", required=True)
    promote_cmd.add_argument("--to", required=True, help="the plugin's lessons/<stack>.jsonl")
    promote_cmd.set_defaults(run=lesson_promote)

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
