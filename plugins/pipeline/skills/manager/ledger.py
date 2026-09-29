#!/usr/bin/env python3
import argparse
import contextlib
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from findings import LINE_SUFFIX, fix_scope_reason

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
MIN_REASON_CHARS = 40
LESSON_TEXT_MAX = 280
LESSONS_DEFAULT = ".superpowers/lessons.jsonl"
PLUGIN_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
LESSONS_DIR_DEFAULT = os.path.join(PLUGIN_ROOT, "lessons")
COUNTERS = ("injected", "held", "recurred")
ROLES = {"implementer": "implement", "reviewer": "review"}
NAME_PATTERN = re.compile(r"^[\w.-]+$")
LEDGER_LINE = re.compile(r"^[\s`>*-]*LEDGER\s*\{", re.MULTILINE)
SHA_TOKEN = re.compile(r"\b[0-9a-f]{7,40}\b")
SHA_LINE = re.compile(r"^[\s>*_`-]*(?:commit(?:\s+sha)?|sha|head)[\s*_`]*[:=][\s*_`]*(.*)$", re.IGNORECASE)
PLACEHOLDER_SHA = re.compile(r"<[^<>]*\b(?:sha|commit|hash)\b[^<>]*>|\bsee\s+`?git\b|`git rev-parse[^`]*`",
                             re.IGNORECASE)
BACKTICKED = re.compile(r"`([^`\s]+)`")
PARENTHETICAL = r"(?:\s*\((?:[^()]|\([^()]*\))*\))?"
FILES_LABEL = re.compile(r"^\s*(?:#+\s*)?\**\s*(?:changed\s+|modified\s+)?files"
                         r"(?:\s+(?:changed|touched|modified))?\s*\**" + PARENTHETICAL +
                         r"\s*\**\s*:\s*\**\s*(.*)$", re.IGNORECASE)
FILES_HEADING = re.compile(r"^\s*#+\s*(?:changed\s+)?files(?:\s+changed)?" + PARENTHETICAL + r"\s*$",
                           re.IGNORECASE)
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
LIST_GAP = re.compile(r"^\s*(?:\([^()]*\)\s*)?(?:,\s*(?:and\s+)?|and\s+|&\s*)$", re.IGNORECASE)
SCOPES = ("fix", "full")
LAYOUTS = ("task", "per-file")
FULL_SCOPE_AGENTS = ("security", "db")
ANCHOR_MARK = '<a id="{}"></a>'
SECTION_RANGE = re.compile(r"^## .* ([0-9a-f]{7,40})\.\.([0-9a-f]{7,40})\s*$", re.MULTILINE)
LOCK_WAIT_SECONDS = 10.0
LOCK_STALE_SECONDS = 30.0
ITEM_LABELS = {"add", "added", "change", "changed", "create", "created", "delete", "deleted", "modify",
               "modified", "new", "remove", "removed", "rename", "renamed", "update", "updated", "test", "tests"}


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
    return verdict_problem(entry) or spec_problem(entry) or scope_problem(entry)


def scope_problem(entry):
    if "scope" not in entry:
        return None
    if entry["scope"] not in SCOPES:
        return f"'scope' must be one of: {', '.join(SCOPES)}"
    if role(entry) != "review":
        return "'scope' is only valid on reviewer entries"
    if entry["scope"] == "fix" and entry.get("agent") in FULL_SCOPE_AGENTS:
        return f"{entry['agent']} always re-reviews the task's full range; 'scope' fix is not valid for it"
    if entry["scope"] == "fix" and not entry.get("covers_from"):
        return "a fix-scoped entry lacks 'covers_from'"
    return None


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


def split_ref(ref):
    path, _, anchor = str(ref).partition("#")
    return path, anchor or None


def sums_path(path):
    return path + ".sums"


def read_sums(path):
    sidecar = sums_path(path)
    if not os.path.isfile(sidecar):
        return None
    try:
        with open(sidecar, encoding="utf-8") as handle:
            data = json.load(handle)
    except ValueError:
        return None
    sections = data.get("sections") if isinstance(data, dict) else None
    if not isinstance(sections, list) or not all(isinstance(s, dict) and isinstance(s.get("start"), int)
                                                 and isinstance(s.get("end"), int) for s in sections):
        return None
    return sections


def write_sums(path, sections, pending=None):
    temporary = sums_path(path) + ".tmp"
    data = {"version": 1, "sections": sections}
    if pending:
        data["pending"] = pending
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=1)
    os.replace(temporary, sums_path(path))


def read_pending(path):
    try:
        with open(sums_path(path), encoding="utf-8") as handle:
            pending = json.load(handle).get("pending")
    except (OSError, ValueError, AttributeError):
        return None
    return pending if isinstance(pending, dict) else None


def repair_hint(path):
    task = os.path.splitext(os.path.basename(path))[0]
    return (f"; if a save-report was interrupted, run `ledger.py repair-reports --task {task}` to see them and "
            "drop them")


def report_file_problems(path):
    if not os.path.isfile(path):
        return [f"{path} does not exist"]
    sections = read_sums(path)
    if sections is None:
        return [f"{sums_path(path)} is missing or unreadable, so {path} cannot be verified"]
    with open(path, "rb") as handle:
        raw = handle.read()
    for section in sections:
        end = section["end"]
        if end > len(raw) or hashlib.sha256(raw[:end]).hexdigest() != section.get("sha256"):
            return [f"{path}: section #{section.get('anchor')} or an earlier one changed after it was saved "
                    "(prefix hash mismatch)"]
    recorded = sections[-1]["end"] if sections else 0
    if len(raw) != recorded:
        return [f"{path}: {len(raw) - recorded} bytes after the last saved section were not recorded by save-report"
                + repair_hint(path)]
    return []


def section_bounds(path, anchor):
    for section in read_sums(path) or []:
        if section.get("anchor") == anchor:
            return section["start"], section["end"]
    return None


def report_bytes(ref):
    path, anchor = split_ref(ref)
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as handle:
        raw = handle.read()
    if anchor:
        bounds = section_bounds(path, anchor)
        if bounds is None:
            return None
        raw = raw[bounds[0]:bounds[1]]
    return raw


def read_report(ref):
    raw = report_bytes(ref)
    return None if raw is None else raw.decode("utf-8", errors="replace")


def section_problem(ref, agent, kind, from_sha, head):
    anchor = split_ref(ref)[1]
    if not anchor:
        return None
    stem = anchor_stem(agent, kind)
    if not re.fullmatch(re.escape(stem) + r"\d+", anchor):
        return f"--report anchor #{anchor} is not a section of this {agent} {kind} line (expected #{stem}<N>)"
    found = SECTION_RANGE.search(read_report(ref) or "")
    if not found or not from_sha.startswith(found.group(1)) or not head.startswith(found.group(2)):
        saved = f"{found.group(1)}..{found.group(2)}" if found else "no range"
        return f"section #{anchor} was saved for {saved}, not for --from {from_sha[:7]} --head {head[:7]}"
    return None


def report_ref_problem(ref):
    path, anchor = split_ref(ref)
    if not anchor:
        return None if os.path.isfile(path) else f"--report does not exist: {path} (save the agent's report first)"
    problems = report_file_problems(path)
    if problems:
        return problems[0]
    if section_bounds(path, anchor) is None:
        return f"--report anchor #{anchor} is not a saved section of {path}"
    return None


def coverage_start(group, index):
    entry = group[index]
    while entry.get("scope") == "fix":
        if index == 0 or group[index - 1].get("head") != entry.get("from"):
            return None
        index -= 1
        entry = group[index]
    return entry.get("from")


def item_paths(body):
    ticked = list(BACKTICKED.finditer(body))
    if ticked:
        paths = [ticked[0].group(1)]
        for previous, current in zip(ticked, ticked[1:]):
            if not LIST_GAP.match(body[previous.end():current.start()]):
                break
            if "/" in current.group(1) or "." in current.group(1):
                paths.append(current.group(1))
        return paths
    before, colon, after = body.partition(":")
    if colon and before.strip(" *").lower() in ITEM_LABELS and after.split():
        body = after
    return unticked_paths(re.sub(r",(?=\S)", ", ", body).split())


def unticked_paths(words):
    paths, index = [], 0
    while index < len(words):
        word = words[index]
        path = word.rstrip(",;:")
        if paths and ("/" not in path and "." not in path or path.endswith(".")):
            break
        if path:
            paths.append(path)
        joined = word.endswith(",") or (not word.endswith((":", ";")) and index + 1 < len(words)
                                         and words[index + 1].lower() in ("and", "&"))
        if not joined:
            break
        index += 1
        if index < len(words) and words[index].lower() in ("and", "&"):
            index += 1
    return paths


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
            found.update(item_paths(item.group(1)))
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


def sha_placeholder(body):
    for line in body.splitlines():
        labelled = SHA_LINE.match(line)
        value = labelled.group(1).strip() if labelled else ""
        if labelled and value and not SHA_TOKEN.search(value.lower()):
            return line.strip()[:80]
        if PLACEHOLDER_SHA.search(line) and not SHA_TOKEN.search(line.lower()):
            return line.strip()[:80]
    return None


def implementer_problems(entry, text, from_sha, head, allow_unlisted):
    problems = []
    if not LEDGER_LINE.search(text):
        problems.append("the report has no 'LEDGER {...}' line")
    body = "\n".join(line for line in text.splitlines() if not LEDGER_LINE.match(line))
    words = set(re.findall(r"[a-z]+", body.lower()))
    minimum = MIN_REPORT_CHARS if entry["verdict"] in COMMITTED_VERDICTS else MIN_REASON_CHARS
    if len(re.sub(r"\s", "", body)) < minimum or not words or words <= {"placeholder", "todo"}:
        problems.append(f"the report looks like a placeholder (a {entry['verdict']} report needs at least "
                        f"{minimum} non-space characters besides the LEDGER line, not just 'placeholder'/'TODO')")
    if entry["agent"] in COMMITTING_IMPLEMENTERS and entry["verdict"] in COMMITTED_VERDICTS:
        placeholder = sha_placeholder(body)
        if placeholder:
            problems.append(f"the report's SHA line is a placeholder ('{placeholder}'): paste the real short SHA "
                            "from `git rev-parse --short HEAD`")
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
    write_line(args.ledger, {"event": "start", "ts": now(), "slug": args.slug, "base": base,
                             "report_layout": args.layout})


def fix_coverage(earlier, from_sha, task):
    if not earlier:
        sys.exit(f"--scope fix needs an earlier entry of this agent on task {task}; record a first review "
                 "with --scope full")
    if earlier[-1].get("head") != from_sha:
        sys.exit(f"--scope fix needs --from = the head of this agent's previous entry on task {task} "
                 f"({str(earlier[-1].get('head'))[:8]}), so the fix range continues it")
    covers = coverage_start(earlier, len(earlier) - 1)
    if covers is None:
        sys.exit("the previous entry's fix chain is broken; re-review the task's full range with --scope full")
    return covers


def open_findings_reports(entries, task, agent, fix_base):
    latest, ancestry = {}, {}
    for entry in entries:
        if not entry.get("agent") or entry.get("task") != task or role(entry) != "review":
            continue
        if entry["head"] not in ancestry:
            ancestry[entry["head"]] = git("merge-base", "--is-ancestor", entry["head"], fix_base)[0] == 0
        if ancestry[entry["head"]]:
            latest[entry["agent"]] = entry
    order = [agent] + sorted(name for name in latest if name != agent)
    return [(latest[name]["report"], read_report(latest[name]["report"])) for name in order if name in latest]


def fix_scope_problem(entries, earlier, covers, head, task):
    if task == SPEC_TASK:
        return None
    previous = earlier[-1]
    plain = ("-c", "core.quotepath=off")
    fixed = git(*plain, "diff", "--name-only", f"{previous['head']}..{head}")[1].splitlines()
    universe = git(*plain, "diff", "--name-only", f"{covers}..{head}")[1].splitlines()
    reason = fix_scope_reason(open_findings_reports(entries, task, previous["agent"], previous["head"]), fixed, universe)
    return f"--scope fix does not fit: {reason}; record it with --scope full" if reason else None


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
    problem = report_ref_problem(args.report)
    if problem:
        sys.exit(problem)
    for field in ("spec", "scope", "covers_from", "report_sha256"):
        entry.pop(field, None)
    if args.scope and role(entry) != "review":
        sys.exit("--scope is only for reviewer lines")
    if args.scope == "fix" and entry["agent"] in FULL_SCOPE_AGENTS:
        sys.exit(f"{entry['agent']} always re-reviews the task's full range; record it with --scope full")
    problem = section_problem(args.report, entry["agent"], role(entry), from_sha, head)
    if problem:
        sys.exit(problem)
    if args.spec:
        spec = os.path.normpath(args.spec).replace("\\", "/")
        if git("cat-file", "-e", f"{head}:./{spec}")[0] != 0:
            sys.exit(f"--spec {args.spec} is not in --head {args.head} (commit the spec first)")
        entry["spec"] = spec
    entry["task"] = args.task
    problem = spec_problem(entry)
    if problem:
        sys.exit(f"agent line rejected: {problem}")
    if args.allow_unlisted is not None and not args.allow_unlisted.strip():
        sys.exit("--allow-unlisted needs a non-empty reason (it goes into the ruling note)")
    unlisted = []
    if entry["agent"] in VALIDATED_IMPLEMENTERS and role(entry) == "implement":
        problems, unlisted = implementer_problems(entry, read_report(args.report), from_sha, head,
                                                  args.allow_unlisted)
        if problems:
            sys.exit("report rejected:\n- " + "\n- ".join(problems))
    entries, invalid = read_ledger(args.ledger)
    warn_invalid(args.ledger, invalid)
    earlier = [e for e in entries if e.get("agent") == entry["agent"] and e.get("task") == args.task
               and role(e) == role(entry)]
    entry.update({"ts": now(), "from": from_sha, "head": head,
                  "round": len(earlier) + 1, "report": args.report,
                  "report_sha256": hashlib.sha256(report_bytes(args.report) or b"").hexdigest()})
    if role(entry) == "review":
        scope = args.scope or "full"
        entry["scope"] = scope
        entry["covers_from"] = fix_coverage(earlier, from_sha, args.task) if scope == "fix" else from_sha
        problem = (fix_scope_problem(entries, earlier, entry["covers_from"], head, args.task)
                   if scope == "fix" else None)
        if problem:
            sys.exit(problem)
    if unlisted:
        entry["unlisted"] = unlisted
    write_line(args.ledger, entry)
    print(f"{entry['agent']} {entry['verdict']} task={args.task} round={entry['round']}")
    if unlisted:
        reason = f" ({args.allow_unlisted.strip()})"
        write_line(args.ledger, {"event": "note", "ts": now(), "kind": "ruling", "task": args.task,
                                 "text": f"{entry['agent']} r{entry['round']} report cites files outside "
                                         f"its diff, accepted with --allow-unlisted: "
                                         f"{', '.join(unlisted)}{reason}"})
        print(f"unlisted files accepted, ruling note recorded: {', '.join(unlisted)}")


def agent_roles(agent):
    verdicts = AGENT_VERDICTS[agent]
    return [kind for kind, sample in (("implement", IMPLEMENTER_VERDICTS[0]), ("review", REVIEWER_VERDICTS[0]))
            if sample in verdicts]


def report_role(args):
    roles = agent_roles(args.agent)
    if args.role:
        kind = ROLES[args.role]
        if kind not in roles:
            sys.exit(f"--role {args.role} does not fit {args.agent}")
        return kind
    if len(roles) == 1:
        return roles[0]
    if args.task == SPEC_TASK:
        return "review"
    sys.exit(f"{args.agent} is both implementer and reviewer: pass --role implementer|reviewer")


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
    kind = report_role(args)
    if args.round != "auto" and not (args.round.isdigit() and int(args.round) > 0):
        sys.exit(f"--round must be 'auto' or a positive integer: {args.round}")
    entries = read_ledger(args.ledger)[0] if os.path.exists(args.ledger) else []
    directory = args.reports_dir or os.path.join(os.path.dirname(args.ledger) or ".", "reports")
    suffix = anchor_stem(args.agent, kind)[len(args.agent):-len("-r")]
    first = 1 + sum(1 for e in entries if e.get("agent") == args.agent and e.get("task") == args.task
                    and role(e) == kind)
    text = text if text.endswith("\n") else text + "\n"
    if (args.layout or ledger_layout(entries)) == "task":
        save_task_section(args, text, directory, suffix, first)
    else:
        save_report_file(args, text, directory, suffix, first)


def anchor_stem(agent, kind):
    return f"{agent}{'-review' if len(agent_roles(agent)) == 2 and kind == 'review' else ''}-r"


def process_alive(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            code = ctypes.c_ulong()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_lock(lock):
    try:
        with open(lock, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return None


def lock_is_stale(lock, holder):
    parts = holder.split()
    try:
        pid, since = int(parts[0]), float(parts[1])
    except (IndexError, ValueError):
        try:
            return time.time() - os.path.getmtime(lock) > LOCK_STALE_SECONDS
        except OSError:
            return False
    return time.time() - since > LOCK_STALE_SECONDS or not process_alive(pid)


def remove_quietly(path, attempts=50):
    for _ in range(attempts):
        try:
            os.remove(path)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            time.sleep(0.02)


def take_over(lock, holder):
    grave = f"{lock}.{os.getpid()}-{os.urandom(4).hex()}.stale"
    try:
        os.rename(lock, grave)
    except OSError:
        return False
    moved = read_lock(grave)
    if moved == holder:
        remove_quietly(grave)
        return True
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        remove_quietly(grave)
        return False
    try:
        os.write(descriptor, (moved or "").encode("ascii", errors="replace"))
    finally:
        os.close(descriptor)
    remove_quietly(grave)
    return False


@contextlib.contextmanager
def exclusive(path):
    lock = path + ".lock"
    deadline, delay = time.monotonic() + LOCK_WAIT_SECONDS, 0.005
    while True:
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            holder = read_lock(lock)
            if holder and lock_is_stale(lock, holder) and take_over(lock, holder):
                continue
        except PermissionError:
            pass
        if time.monotonic() > deadline:
            sys.exit(f"{path} is locked by another save-report ({lock}); retry, or delete the lock file if no "
                     "save-report is running")
        time.sleep(delay * (1 + int.from_bytes(os.urandom(1), "big") / 255))
        delay = min(delay * 2, 0.25)
    token = f"{os.getpid()} {time.time():.3f} {os.urandom(8).hex()}\n"
    try:
        os.write(descriptor, token.encode("ascii"))
        os.close(descriptor)
        yield
    finally:
        if read_lock(lock) == token:
            remove_quietly(lock)


def ledger_layout(entries):
    for entry in entries:
        if entry.get("event") == "start":
            return entry.get("report_layout") if entry.get("report_layout") in LAYOUTS else "per-file"
    return "task"


def save_report_file(args, text, directory, suffix, first):
    stem = os.path.join(directory, f"{args.task}-{args.agent}{suffix}-r")
    number = first if args.round == "auto" else int(args.round)
    while args.round == "auto" and os.path.exists(f"{stem}{number}.md"):
        number += 1
    path = f"{stem}{number}.md"
    os.makedirs(directory, exist_ok=True)
    try:
        with open(path, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except FileExistsError:
        sys.exit(f"report already exists, not overwriting: {path}")
    print(path.replace("\\", "/"))


def save_task_section(args, text, directory, suffix, first):
    if not args.from_sha:
        sys.exit("--from is required with the per-task report layout (the section heading names the range)")
    from_sha, head = resolve_commit(args.from_sha), resolve_commit(args.head)
    if not from_sha or not head:
        sys.exit(f"--from/--head must be commits: {args.from_sha}, {args.head}")
    path = os.path.join(directory, f"{args.task}.md")
    os.makedirs(directory, exist_ok=True)
    with exclusive(path):
        anchor = append_section(args, text, path, suffix, first, from_sha, head)
    print(f"{path.replace(chr(92), '/')}#{anchor}")


def append_section(args, text, path, suffix, first, from_sha, head):
    sections = []
    if os.path.exists(path):
        problems = report_file_problems(path)
        if problems:
            sys.exit(f"refusing to append: {problems[0]}")
        sections = read_sums(path)
    anchors = {section.get("anchor") for section in sections}
    stem = f"{args.agent}{suffix}-r"
    number = first if args.round == "auto" else int(args.round)
    while args.round == "auto" and f"{stem}{number}" in anchors:
        number += 1
    anchor = f"{stem}{number}"
    if anchor in anchors:
        sys.exit(f"section #{anchor} already exists in {path}, not overwriting")
    title = f"{args.agent}{' review' if suffix else ''} r{number} — {from_sha[:7]}..{head[:7]}"
    start = os.path.getsize(path) if os.path.exists(path) else 0
    block = (("\n" if start else "") + ANCHOR_MARK.format(anchor) + f"\n## {title}\n\n{text}").encode("utf-8")
    write_sums(path, sections, pending={"anchor": anchor, "start": start, "end": start + len(block),
                                        "block_sha256": hashlib.sha256(block).hexdigest()})
    with open(path, "ab") as handle:
        handle.write(block)
        handle.flush()
        os.fsync(handle.fileno())
    with open(path, "rb") as handle:
        prefix = handle.read(start + len(block))
    sections.append({"anchor": anchor, "title": title, "start": start, "end": start + len(block),
                     "sha256": hashlib.sha256(prefix).hexdigest()})
    write_sums(path, sections)
    return anchor


def repair_reports(args):
    if not NAME_PATTERN.match(args.task):
        sys.exit(f"--task must match {NAME_PATTERN.pattern}: {args.task}")
    directory = args.reports_dir or os.path.join(os.path.dirname(args.ledger) or ".", "reports")
    path = os.path.join(directory, f"{args.task}.md")
    if not os.path.isfile(path):
        sys.exit(f"{path} does not exist")
    with exclusive(path):
        sections = read_sums(path)
        if sections is None:
            sys.exit(f"{sums_path(path)} is missing or unreadable; repair-reports only drops unrecorded trailing bytes")
        with open(path, "rb") as handle:
            raw = handle.read()
        recorded = sections[-1]["end"] if sections else 0
        if recorded > len(raw) or any(hashlib.sha256(raw[:s["end"]]).hexdigest() != s.get("sha256")
                                      for s in sections):
            sys.exit(f"{path}: a saved section changed (prefix hash mismatch); that is not an interrupted save, "
                     "repair-reports will not touch it")
        trailing = raw[recorded:]
        if not trailing:
            write_sums(path, sections)
            print(f"{path}: nothing to repair")
            return
        pending = read_pending(path)
        interrupted = bool(pending and pending.get("start") == recorded and pending.get("end") == len(raw)
                           and hashlib.sha256(trailing).hexdigest() == pending.get("block_sha256"))
        origin = (f"the interrupted save of section #{pending['anchor']}" if interrupted
                  else "no interrupted save-report (written by something else)")
        preview = trailing[:400].decode("utf-8", errors="replace")
        sys.stdout.flush()
        sys.stdout.buffer.write((f"{path}: {len(trailing)} unrecorded bytes after byte {recorded}, from {origin}:"
                                 f"\n---\n{preview}" + ("\n[...]" if len(trailing) > 400 else "")
                                 + "\n---\n").encode("utf-8"))
        sys.stdout.flush()
        if not args.yes:
            sys.exit("nothing changed; re-run with --yes to truncate them, then save the report again")
        with open(path, "r+b") as handle:
            handle.truncate(recorded)
        write_sums(path, sections)
        print(f"truncated {path} to {recorded} bytes; save the report again with save-report")


def read_lessons(path):
    return [lesson for _, lesson in read_rows(path)]


def read_rows(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                rows.append([line.rstrip("\r\n"), json.loads(line)])
            except ValueError:
                sys.exit(f"{path}:{number} is not valid JSON; fix it before writing lessons")
    return rows


def write_rows(path, rows):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        for raw, _ in rows:
            handle.write(raw + "\n")
    os.replace(temporary, path)


def write_lessons(path, lessons):
    write_rows(path, [[json.dumps(lesson, ensure_ascii=False, separators=(",", ":")), lesson] for lesson in lessons])


def global_line(lesson):
    return json.dumps(lesson, ensure_ascii=False)


def is_override(lesson):
    return lesson.get("override") is True


def global_files(directory):
    return sorted(glob.glob(os.path.join(directory, "*.jsonl")))


def find_global(directory, lesson_id):
    for path in global_files(directory):
        for lesson in read_lessons(path):
            if lesson.get("id") == lesson_id:
                return lesson
    return None


def find_lesson(lessons, lesson_id, path):
    for lesson in lessons:
        if lesson.get("id") == lesson_id and not is_override(lesson):
            return lesson
    if any(lesson.get("id") == lesson_id for lesson in lessons):
        sys.exit(f"'{lesson_id}' in {path} only carries counters of a global lesson; use 'lesson sync'")
    sys.exit(f"lesson '{lesson_id}' not found in {path}")


def lesson_add(args):
    for flag, value in (("--id", args.id), ("--stack", args.stack)):
        if not NAME_PATTERN.match(value):
            sys.exit(f"{flag} must match {NAME_PATTERN.pattern}: {value}")
    stacks = [os.path.splitext(os.path.basename(path))[0] for path in global_files(args.lessons_dir)]
    if args.stack not in stacks:
        sys.exit(f"--stack must be one of the lesson files in {args.lessons_dir}: "
                 f"{', '.join(stacks) or '(none found)'}")
    text = " ".join(args.text.split())
    if not text:
        sys.exit("--text is empty")
    if len(text) > LESSON_TEXT_MAX:
        sys.exit(f"--text has {len(text)} characters; a lesson is one rule of at most {LESSON_TEXT_MAX}")
    lessons = read_lessons(args.lessons)
    if any(lesson.get("id") == args.id for lesson in lessons):
        sys.exit(f"lesson '{args.id}' already exists in {args.lessons}")
    if find_global(args.lessons_dir, args.id):
        sys.exit(f"lesson '{args.id}' already exists in {args.lessons_dir}")
    code, root = git("rev-parse", "--show-toplevel")
    project = args.project or os.path.basename(root if code == 0 and root else os.getcwd())
    lesson = {"id": args.id, "stack": args.stack,
              "paths": [pattern.strip() for pattern in args.paths.split(",") if pattern.strip()],
              "text": text,
              "source": {"project": project, "task": args.task, "agent": args.agent,
                         "finding": args.finding},
              "counters": {counter: 0 for counter in COUNTERS},
              "status": "active", "created": time.strftime("%Y-%m-%d")}
    write_lessons(args.lessons, lessons + [lesson])
    print(f"lesson {args.id} added to {args.lessons}")


def lesson_mark(args):
    lessons = read_lessons(args.lessons)
    lesson = next((item for item in lessons if item.get("id") == args.id), None)
    if lesson is None:
        source = find_global(args.lessons_dir, args.id)
        if source is None:
            sys.exit(f"lesson '{args.id}' not found in {args.lessons} nor in {args.lessons_dir}")
        lesson = {"id": args.id, "stack": source.get("stack"), "override": True,
                  "counters": {counter: 0 for counter in COUNTERS}}
        lessons.append(lesson)
    counter = "held" if args.held else "recurred"
    counters = lesson.setdefault("counters", {})
    counters[counter] = int(counters.get(counter, 0)) + 1
    write_lessons(args.lessons, lessons)
    scope = " (global lesson; counted in this delivery until 'lesson sync')" if is_override(lesson) else ""
    print(f"lesson {args.id} {counter}={counters[counter]}{scope}")


def lesson_list(args):
    lessons = read_lessons(args.lessons)
    if args.json:
        print(json.dumps(lessons, indent=2, ensure_ascii=False))
        return
    for lesson in lessons:
        counters = lesson.get("counters", {})
        tally = ", ".join(f"{counter} {counters.get(counter, 0)}" for counter in COUNTERS)
        if is_override(lesson):
            print(f"{lesson.get('id')}  [{lesson.get('stack')}, global lesson, counters of this delivery]  {tally}")
            continue
        print(f"{lesson.get('id')}  [{lesson.get('stack')}, {lesson.get('status')}]  {tally}  "
              f"paths: {', '.join(lesson.get('paths') or ['(all)'])}")
        print(f"    {lesson.get('text')}")


def lesson_promote(args):
    lesson = find_lesson(read_lessons(args.lessons), args.id, args.lessons)
    stack = lesson.get("stack")
    if os.path.splitext(os.path.basename(args.to))[0] != stack:
        sys.exit(f"--to {args.to} is not the file of stack '{stack}' (expected lessons/{stack}.jsonl)")
    rows = read_rows(args.to)
    if any(existing.get("id") == args.id for _, existing in rows):
        sys.exit(f"lesson '{args.id}' already exists in {args.to}")
    write_rows(args.to, rows + [[global_line(lesson), lesson]])
    print(f"lesson {args.id} promoted to {args.to}")


def file_digest(path):
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def rows_digest(rows):
    return hashlib.sha256("".join(raw + "\n" for raw, _ in rows).encode("utf-8")).hexdigest()


def sync_journal_path(lessons_path):
    return os.path.splitext(lessons_path)[0] + ".sync.json"


def read_sync_journal(path):
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            journal = json.load(handle)
    except ValueError:
        sys.exit(f"{path} is not valid JSON; check the global lesson counters by hand, then delete it")
    return journal if isinstance(journal, dict) else None


def write_sync_journal(path, journal):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(journal, handle, indent=2)
    os.replace(temporary, path)


def target_key(path):
    return os.path.normcase(os.path.abspath(path))


def sync_round(args, lessons, group, journal_path):
    sync_id = group[0]["sync_pending"]["id"]
    files = {}
    for lesson in group:
        path = os.path.join(args.to_dir, f"{lesson.get('stack')}.jsonl")
        if path not in files:
            rows = read_rows(path)
            files[path] = (rows, {row[1].get("id"): row for row in rows})
        if lesson["id"] not in files[path][1]:
            sys.exit(f"lesson '{lesson['id']}' not found in {path}; nothing synced")
    current = {path: file_digest(path) for path in files}
    for lesson in group:
        path = os.path.join(args.to_dir, f"{lesson.get('stack')}.jsonl")
        row = files[path][1][lesson["id"]]
        counters = row[1].setdefault("counters", {})
        for counter in COUNTERS:
            counters[counter] = int(counters.get(counter, 0)) + int(lesson["sync_pending"]["counters"].get(counter, 0))
        row[0] = global_line(row[1])
    journal = read_sync_journal(journal_path)
    if not journal or journal.get("id") != sync_id:
        journal = {"id": sync_id, "files": {target_key(path): {"before": current[path], "after": rows_digest(rows)}
                                            for path, (rows, _) in files.items()}}
        write_sync_journal(journal_path, journal)
    for path in sorted(files):
        planned = (journal.get("files") or {}).get(target_key(path))
        if planned and current[path] == planned.get("after"):
            continue
        if not planned or current[path] != planned.get("before"):
            sys.exit(f"{path} changed since the interrupted sync {sync_id}; check its counters by hand, "
                     f"then delete {journal_path}")
        write_rows(path, files[path][0])
    for lesson in group:
        journal_counters = lesson.pop("sync_pending")["counters"]
        lesson["counters"] = {counter: max(0, int(lesson["counters"].get(counter, 0))
                                           - int(journal_counters.get(counter, 0))) for counter in COUNTERS}
        lesson["synced"] = time.strftime("%Y-%m-%d")
        print(f"lesson {lesson['id']} counters added to {args.to_dir}")
    write_lessons(args.lessons, lessons)
    os.remove(journal_path)


def lesson_sync(args):
    lessons = read_lessons(args.lessons)
    journal_path = sync_journal_path(args.lessons)
    journaled = [lesson for lesson in lessons if is_override(lesson) and lesson.get("sync_pending")]
    fresh = [lesson for lesson in lessons if is_override(lesson) and not lesson.get("sync_pending")
             and (not args.id or lesson.get("id") in args.id)
             and any(int(lesson.get("counters", {}).get(counter, 0)) for counter in COUNTERS)]
    missing = sorted(set(args.id or ()) - {lesson.get("id") for lesson in journaled + fresh})
    if missing:
        sys.exit(f"no global-lesson counters to sync for: {', '.join(missing)}")
    if not journaled and os.path.isfile(journal_path):
        os.remove(journal_path)
    if not journaled and not fresh:
        print("no global-lesson counters to sync")
        return
    for sync_id in dict.fromkeys(lesson["sync_pending"]["id"] for lesson in journaled):
        sync_round(args, lessons, [lesson for lesson in journaled if lesson["sync_pending"]["id"] == sync_id],
                   journal_path)
    if fresh:
        for lesson in fresh:
            path = os.path.join(args.to_dir, f"{lesson.get('stack')}.jsonl")
            if lesson["id"] not in {row.get("id") for _, row in read_rows(path)}:
                sys.exit(f"lesson '{lesson['id']}' not found in {path}; nothing synced")
        sync_id = f"{time.strftime('%Y%m%dT%H%M%S')}-{os.urandom(4).hex()}"
        for lesson in fresh:
            lesson["sync_pending"] = {"id": sync_id, "counters": {counter: int(lesson["counters"].get(counter, 0))
                                                                  for counter in COUNTERS}}
        write_lessons(args.lessons, lessons)
        sync_round(args, lessons, fresh, journal_path)


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


def groups_of(entries):
    groups = {}
    for entry in entries:
        if entry.get("agent"):
            groups.setdefault((entry["task"], entry["agent"], role(entry)), []).append(entry)
    return groups


def review_starts(entries, latest):
    groups, starts = groups_of(entries), {}
    for entry in latest:
        if entry.get("verdict") in REVIEWER_VERDICTS:
            group = groups[(entry["task"], entry["agent"], "review")]
            starts[id(entry)] = coverage_start(group, len(group) - 1)
    return starts


def names(*args):
    code, out = git("-c", "core.quotepath=off", *args)
    return out.splitlines() if code == 0 else []


class History:
    def __init__(self):
        self.ranges, self.files = {}, {}

    def commits(self, start, end):
        if (start, end) not in self.ranges:
            code, out = git("rev-list", f"{start}..{end}")
            self.ranges[(start, end)] = set(out.split()) if code == 0 else set()
        return self.ranges[(start, end)]

    def touched(self, sha):
        if sha not in self.files:
            self.files[sha] = set(names("diff-tree", "--no-commit-id", "--name-only", "-r", "-m", "--first-parent",
                                        "--root", sha))
        return self.files[sha]


def spec_stale(entry, start, head):
    behind = commits_after(entry.get("head"), head, entry["spec"])
    item = {"task": entry["task"], "agent": entry["agent"], "head": entry.get("head"), "covers_from": start,
            "commits_after": behind, "spec": entry["spec"]}
    if start is None:
        return {**item, "chain_broken": True}
    return None if behind == 0 else item


def code_stale(entry, start, head, history, reviewed):
    item = {"task": entry["task"], "agent": entry["agent"], "head": entry.get("head"), "covers_from": start}
    code, out = git("rev-list", "--reverse", f"{entry.get('head')}..{head}")
    if code != 0:
        return {**item, "commits_after": None}
    after = out.split()
    if start is None:
        return {**item, "commits_after": len(after), "chain_broken": True}
    if not after:
        return None
    files = set(names("diff", "--name-only", f"{start}..{entry['head']}"))
    touched, uncovered = [], []
    for sha in after:
        hit = sorted(files & history.touched(sha))
        if hit:
            touched.append({"commit": sha, "files": hit})
        elif not any(task != entry["task"] and sha in commits for task, commits in reviewed):
            uncovered.append(sha)
    if not touched and not uncovered:
        return None
    return {**item, "commits_after": len(after), "touched": touched, "uncovered": uncovered}


def stale_entries(entries, latest, head):
    history, starts = History(), review_starts(entries, latest)
    reviewed = [(entry["task"], history.commits(starts[id(entry)], entry["head"])) for entry in latest
                if starts.get(id(entry)) and entry["task"] != SPEC_TASK]
    stale = []
    for entry in latest:
        if id(entry) not in starts:
            continue
        if entry["task"] == SPEC_TASK and entry.get("spec"):
            item = spec_stale(entry, starts[id(entry)], head)
        else:
            item = code_stale(entry, starts[id(entry)], head, history, reviewed)
        if item:
            stale.append(item)
    return stale


def short_list(items, limit=3):
    return ", ".join(items[:limit]) + (f" +{len(items) - limit} more" if len(items) > limit else "")


def stale_lines(item):
    if item.get("chain_broken"):
        return "  STALE (fix-scoped chain broken: re-review the full range)", []
    if item.get("commits_after") is None:
        return "  STALE (unknown range)", []
    details = [f"{touch['commit'][:8]} touches {short_list(touch['files'])}" for touch in item.get("touched", [])]
    details += [f"{sha[:8]} is reviewed by no other task" for sha in item.get("uncovered", [])]
    return f"  STALE (+{item['commits_after']} commits)", details


def status(args):
    entries, invalid = read_ledger(args.ledger)
    latest, totals, spec_totals = summarize(entries)
    notes = [{k: e[k] for k in ("kind", "task", "text", "ts")} for e in entries
             if e.get("event") == "note"]
    starts = review_starts(entries, latest)
    stale = stale_entries(entries, latest, args.head) if args.head else []
    flagged = {(s["task"], s["agent"]): s for s in stale}
    if args.json:
        shown = [{**e, "covers_from": starts[id(e)]} if id(e) in starts else e for e in latest]
        report = {"latest": shown, "totals": totals, "spec_totals": spec_totals,
                  "notes": notes, "invalid": invalid}
        if args.head:
            report["stale"] = stale
        print(json.dumps(report, indent=2))
        return
    for item in invalid:
        print(f"INVALID line {item['line']}: {item['reason']} (ignored)")
    for entry in latest:
        key = (entry["task"], entry["agent"])
        flag, details = "", []
        if role(entry) == "review" and key in flagged:
            flag, details = stale_lines(flagged[key])
        start = starts.get(id(entry), entry.get("from"))
        chain = f"  (fix-scoped from {str(entry.get('from'))[:8]})" if entry.get("scope") == "fix" else ""
        span = "chain broken" if start is None else f"{str(start)[:8]}..{str(entry.get('head'))[:8]}"
        print(f"{entry['task']:<10} {label(entry):<16} {entry['verdict']:<20} "
              f"{span}  round {entry.get('round')}{chain}{flag}")
        for detail in details:
            print(f"{'':<12}{detail}")
    for scope, buckets in (("total", totals), ("spec ", spec_totals)):
        for agent, bucket in buckets.items():
            raised = ", ".join(f"{bucket[s]} {s}" for s in SEVERITIES)
            print(f"{scope} {agent:<12} raised: {raised}; rounds: {bucket['rounds']}")
    for item in notes:
        print(f"note {item['kind']:<10} {item['task']:<10} {item['text']}")


def verify_reports(args):
    entries, invalid = read_ledger(args.ledger)
    warn_invalid(args.ledger, invalid)
    problems, checked, count = [], {}, 0
    for entry in entries:
        if not entry.get("agent"):
            continue
        count += 1
        who = f"task {entry['task']} {label(entry)} r{entry.get('round')}"
        path, anchor = split_ref(entry["report"])
        if not anchor and not os.path.isfile(path):
            problems.append(f"{who}: report {path} does not exist")
            continue
        if anchor:
            if path not in checked:
                checked[path] = report_file_problems(path)
                problems.extend(checked[path])
            if not checked[path] and section_bounds(path, anchor) is None:
                problems.append(f"{who}: section #{anchor} is not in {path}")
                continue
        recorded, raw = entry.get("report_sha256"), report_bytes(entry["report"])
        if recorded and raw is not None and hashlib.sha256(raw).hexdigest() != recorded:
            problems.append(f"{who}: {entry['report']} differs from the bytes recorded at append (sha256 mismatch)")
    if args.json:
        print(json.dumps({"entries": count, "files": sorted(checked), "problems": problems}, indent=2))
    else:
        for problem in problems:
            print(f"PROBLEM {problem}")
        verdict = "OK" if not problems else f"{len(problems)} problem(s)"
        print(f"{count} report reference(s), {len(checked)} per-task file(s): {verdict}")
    if problems:
        sys.exit(1)


def show_report(args):
    path, anchor = split_ref(args.ref)
    if anchor:
        for problem in report_file_problems(path):
            sys.stderr.write(f"warning: {problem}\n")
    text = read_report(args.ref)
    if text is None:
        sys.exit(f"no saved report at {args.ref}")
    sys.stdout.flush()
    sys.stdout.buffer.write(text.encode("utf-8"))


def main():
    parser = argparse.ArgumentParser(prog="ledger.py")
    parser.add_argument("--ledger", default=".superpowers/ledger.jsonl")
    commands = parser.add_subparsers(dest="command", required=True)

    start_cmd = commands.add_parser("start")
    start_cmd.add_argument("--slug", required=True)
    start_cmd.add_argument("--base", required=True)
    start_cmd.add_argument("--layout", choices=LAYOUTS, default="task",
                           help="reports: one append-only file per task (default) or one file per report (1.4.0)")
    start_cmd.set_defaults(run=start)

    append_cmd = commands.add_parser("append")
    append_cmd.add_argument("--task", required=True)
    append_cmd.add_argument("--from", dest="from_sha", required=True)
    append_cmd.add_argument("--head", required=True)
    append_cmd.add_argument("--report", required=True)
    append_cmd.add_argument("--line", required=True)
    append_cmd.add_argument("--spec", help="the reviewed spec document; required with --task spec")
    append_cmd.add_argument("--allow-unlisted", metavar="REASON",
                            help="accept an implementer report citing files outside FROM..HEAD; "
                                 "the reason goes into the ruling note it records")
    append_cmd.add_argument("--scope", choices=SCOPES,
                            help="reviewer lines: 'fix' when --from is this agent's previous head on the task "
                                 "(a fix-only re-review), 'full' otherwise (default)")
    append_cmd.set_defaults(run=append)

    save_cmd = commands.add_parser("save-report", help="append an agent report to reports/<task>.md "
                                                        "(or <task>-<agent>-r<round>.md in the per-file layout)")
    save_cmd.add_argument("--task", required=True)
    save_cmd.add_argument("--agent", required=True)
    save_cmd.add_argument("--round", default="auto", help="'auto' (next free round) or a number")
    save_cmd.add_argument("--role", choices=sorted(ROLES),
                          help="required for db outside the spec task; inferred for the other agents")
    save_cmd.add_argument("--reports-dir", help="default: 'reports' next to the ledger")
    save_cmd.add_argument("--from", dest="from_sha", help="the range start; required in the per-task layout")
    save_cmd.add_argument("--head", default="HEAD")
    save_cmd.add_argument("--layout", choices=LAYOUTS, help="default: the ledger's (per-file for ledgers "
                                                            "started before 1.5.0)")
    source = save_cmd.add_mutually_exclusive_group(required=True)
    source.add_argument("--stdin", action="store_true")
    source.add_argument("--file")
    save_cmd.set_defaults(run=save_report)

    repair_cmd = commands.add_parser("repair-reports", help="show, and with --yes drop, the unrecorded bytes an "
                                                            "interrupted save-report left at the end of reports/<task>.md")
    repair_cmd.add_argument("--task", required=True)
    repair_cmd.add_argument("--reports-dir", help="default: 'reports' next to the ledger")
    repair_cmd.add_argument("--yes", action="store_true", help="confirm the truncation")
    repair_cmd.set_defaults(run=repair_reports)

    lesson_cmd = commands.add_parser("lesson", help="manage this delivery's lessons")
    lesson_cmd.add_argument("--lessons", default=LESSONS_DEFAULT)
    lesson_cmd.add_argument("--lessons-dir", default=LESSONS_DIR_DEFAULT,
                            help="the global lessons (default: the plugin's lessons/)")
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
    sync_cmd = actions.add_parser("sync", help="add this delivery's counters of global lessons to the global files")
    sync_cmd.add_argument("--to-dir", required=True, help="the plugin's lessons/ folder")
    sync_cmd.add_argument("--id", action="append", help="sync only this lesson (repeatable)")
    sync_cmd.set_defaults(run=lesson_sync)

    note_cmd = commands.add_parser("note")
    note_cmd.add_argument("--kind", required=True, choices=NOTE_KINDS)
    note_cmd.add_argument("--task", required=True)
    note_cmd.add_argument("--text", required=True)
    note_cmd.set_defaults(run=note)

    status_cmd = commands.add_parser("status")
    status_cmd.add_argument("--json", action="store_true")
    status_cmd.add_argument("--head", help="mark reviewer entries whose range ends before this commit")
    status_cmd.set_defaults(run=status)

    verify_cmd = commands.add_parser("verify-reports", help="check every report the ledger cites: per-task files "
                                                            "only grew and every anchor exists")
    verify_cmd.add_argument("--json", action="store_true")
    verify_cmd.set_defaults(run=verify_reports)

    show_cmd = commands.add_parser("show-report", help="print one saved report (path or path#anchor)")
    show_cmd.add_argument("ref")
    show_cmd.set_defaults(run=show_report)

    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
