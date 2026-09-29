#!/usr/bin/env python3
import argparse
import glob
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ledger import (FULL_SCOPE_AGENTS, LINE_SUFFIX, SPEC_TASK, cited_paths, coverage_start, read_ledger,
                    read_report, role)

PLUGIN_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
LOCKFILES = ("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb", "Cargo.lock", "poetry.lock")
TASK_HEADING = re.compile(r"^(#+)[ \t]+Task[ \t]+([\w.-]+)[ \t]*:?")
ANY_HEADING = re.compile(r"^(#+)[ \t]")
LESSONS_HEADER = "## Lessons (from past deliveries)\n"
LESSONS_MAX = 6
LESSONS_CHARS = 8000
TRUNCATION_RESERVE = 40
LESSON_ID = re.compile(r"^- .* \[([\w.-]+)\]$", re.MULTILINE)
DEPENDENCY_FIELD = re.compile(r"\b(?:name|version|resolved|resolution|integrity|checksum)\b|node_modules/", re.IGNORECASE)
DEPENDENCY_HEADER = re.compile(r"^(?:\S.*@.*|\s+/?\S+@\S+):\s*$")
DEPENDENCY_LINES_MAX = 80
FINDINGS_MARK = re.compile(r"^\s*(#*)\s*\**\s*(?:open\s+|new\s+|remaining\s+)?findings\b", re.IGNORECASE)
SECTION_END = re.compile(r"^\s*(?:#+\s|LEDGER\s*\{|\*\*[^*]+\*\*\s*:?\s*$)")
FILE_LINE = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)*[\w.-]+\.\w+):\d+")


def git(*args):
    result = subprocess.run(["git", "-c", "core.quotepath=off", *args], capture_output=True,
                            encoding="utf-8", errors="replace")
    return result.returncode, result.stdout or "", (result.stderr or "").strip()


def write(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def replace_file(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(temporary, path)


def glob_regex(pattern):
    parts, index = [], 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            parts.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            parts.append(".*")
            index += 2
        elif pattern[index] == "*":
            parts.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            parts.append("[^/]")
            index += 1
        else:
            parts.append(re.escape(pattern[index]))
            index += 1
    return re.compile("".join(parts) + r"\Z")


def matches_any(globs, paths):
    regexes = [glob_regex(pattern.strip().lstrip("/")) for pattern in globs if pattern.strip()]
    return any(regex.match(path) for regex in regexes for path in paths)


def specificity(pattern):
    literal = len(re.sub(r"[*?/]", "", pattern))
    prefix = len(re.split(r"[*?]", pattern, maxsplit=1)[0])
    return literal, -len(re.findall(r"\*\*|\*|\?", pattern)), prefix


def relevance(globs, paths):
    patterns = [pattern.strip().lstrip("/") for pattern in globs if pattern.strip()]
    ranked = [(glob_regex(pattern), specificity(pattern)) for pattern in patterns]
    matched, best = 0, (-1, 0, -1)
    for path in paths:
        hits = [rank for regex, rank in ranked if regex.match(path)]
        if hits:
            matched += 1
            best = max(best, *hits)
    return matched, best


def frontmatter_value(raw):
    raw = raw.strip()
    if raw.startswith("["):
        try:
            value = json.loads(raw)
            return [str(item) for item in value] if isinstance(value, list) else [str(value)]
        except ValueError:
            return [item.strip().strip("'\"") for item in raw.strip("[]").split(",") if item.strip()]
    return raw.strip("'\"")


def read_frontmatter(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        lines = handle.read().splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields, key = {}, None
    for line in lines[1:]:
        if line.strip() == "---":
            return fields
        item = re.match(r"^\s+-\s+(.*)$", line)
        if item and key and isinstance(fields.get(key), list):
            fields[key].append(item.group(1).strip().strip("'\""))
            continue
        pair = re.match(r"^([\w-]+):\s*(.*)$", line)
        if pair:
            key = pair.group(1)
            fields[key] = frontmatter_value(pair.group(2)) if pair.group(2).strip() else []
    return {}


def checklists_section(directory, changed):
    lines = []
    for path in sorted(glob.glob(os.path.join(directory, "*.md"))):
        fields = read_frontmatter(path)
        paths = fields.get("paths") or []
        if isinstance(paths, str):
            paths = [paths]
        if paths and matches_any(paths, changed):
            agents = fields.get("agents") or []
            agents = ", ".join(agents) if isinstance(agents, list) else agents
            lines.append(f"- {os.path.abspath(path)} (stack: {fields.get('stack', '?')}; agents: {agents})\n")
    body = "".join(lines) or "- none matched the changed files\n"
    return ("## Checklists\nOpen the ones whose agents include your role and run each item "
            "against this diff.\n" + body)


def dependency_section(span, locks):
    parts = ["## Dependency changes\nChanged package lines (name, version, resolved, integrity) of each lockfile left "
             "out of the diff; ask for --include-lockfiles to read a lockfile in full.\n"]
    for path in locks:
        _, text, _ = git("diff", "-U0", span, "--", f":(top,literal){path}")
        if "Binary files" in text or "GIT binary patch" in text:
            lines = ["(binary lockfile; only the stat above)"]
        else:
            lines = [line for line in text.splitlines()
                     if line[:1] in "+-" and not line.startswith(("+++", "---"))
                     and (DEPENDENCY_FIELD.search(line[1:]) or DEPENDENCY_HEADER.match(line[1:]))]
            if len(lines) > DEPENDENCY_LINES_MAX:
                lines = lines[:DEPENDENCY_LINES_MAX] + [f"[truncated: {len(lines) - DEPENDENCY_LINES_MAX} more lines]"]
        body = "\n".join(lines) or "(no package line changed)"
        parts.append(f"### {path}\n```\n{body}\n```\n")
    return "\n".join(parts)


def is_section_end(line, level):
    heading = re.match(r"^\s*(#+)\s+(.*)$", line)
    if heading:
        if level:
            return len(heading.group(1)) <= level
        return not re.match(r"\W*(?:critical|important|minor)\b", heading.group(2), re.IGNORECASE)
    if level or not SECTION_END.match(line):
        return False
    return line.lstrip().startswith("LEDGER") or not re.search(r"critical|important|minor", line, re.IGNORECASE)


def findings_sections(text):
    sections, current, level = [], None, 0
    for line in text.splitlines():
        if current is not None and is_section_end(line, level):
            sections.append("\n".join(current))
            current = None
        if current is None:
            mark = FINDINGS_MARK.match(line)
            if mark and len(line.strip()) <= 80:
                current, level = [line[mark.end():]], len(mark.group(1))
            continue
        current.append(line)
    if current is not None:
        sections.append("\n".join(current))
    return sections


def finding_paths(text):
    sections = findings_sections(text)
    if not sections:
        return None
    body = "\n".join(sections)
    paths = set()
    for candidate in cited_paths(body) | set(FILE_LINE.findall(body)):
        path = LINE_SUFFIX.sub("", candidate.strip(" `*,;")).replace("\\", "/")
        while path.startswith("./"):
            path = path[2:]
        if "/" in path or "." in path:
            paths.add(path)
    return paths


def scope_reason(args, last, fixed, spec):
    if args.agent in FULL_SCOPE_AGENTS:
        return f"{args.agent} always re-reviews the task's full range"
    if spec:
        return None
    text = read_report(last["report"])
    if text is None:
        return f"the previous report {last['report']} cannot be read"
    cited = finding_paths(text)
    if not cited:
        return "the previous report's findings cite no file"
    outside = [path for path in fixed if path not in cited]
    if outside:
        more = f" +{len(outside) - 5} more" if len(outside) > 5 else ""
        return f"the fix touches files outside the open findings: {', '.join(outside[:5])}{more}"
    return None


def fix_package(args):
    entries = read_ledger(args.ledger)[0]
    group = [e for e in entries if e.get("agent") == args.agent and e.get("task") == args.fix_of
             and role(e) == "review"]
    if not group:
        sys.exit(f"no {args.agent} review of task {args.fix_of} in {args.ledger}; build a full package with --base")
    last = group[-1]
    start = coverage_start(group, len(group) - 1)
    if start is None:
        sys.exit(f"the fix-scoped chain of {args.agent} on task {args.fix_of} is broken; "
                 "build a full package with --base <task start>")
    code, head, _ = git("rev-parse", "--verify", "--quiet", f"{args.head}^{{commit}}")
    if code != 0:
        sys.exit(f"bad head: {args.head}")
    head = head.strip()
    spec = last.get("spec") if args.fix_of == SPEC_TASK else None
    only = ["--", f":(top,literal){spec}"] if spec else []
    fixed = git("diff", "--name-only", f"{last['head']}..{head}", *only)[1].splitlines()
    if not fixed:
        sys.exit(f"nothing changed{f' in {spec}' if spec else ''} since {last['head'][:8]}, "
                 f"the head of the last {args.agent} review of task {args.fix_of}")
    reason = scope_reason(args, last, fixed, spec)
    return {"base": last["head"] if reason is None else start, "head": head,
            "scope": "fix-only" if reason is None else f"full ({reason})",
            "flag": "fix" if reason is None else "full", "previous": last["report"], "spec": spec,
            "name": f"{args.fix_of}-{args.agent}-fix-r{len(group) + 1}"}


def review(args):
    fix = None
    if args.fix_of:
        if not args.agent:
            sys.exit("--fix-of needs --agent (the reviewer to re-run)")
        fix = fix_package(args)
        args.base, args.head = fix["base"], fix["head"]
        args.name = args.name or fix["name"]
    elif not args.base:
        sys.exit("--base is required (or --fix-of <task> --agent <agent>)")
    for name, rev in (("base", args.base), ("head", args.head)):
        if git("rev-parse", "--verify", "--quiet", rev)[0] != 0:
            sys.exit(f"bad {name}: {rev}")
    if git("merge-base", "--is-ancestor", args.base, args.head)[0] != 0:
        sys.exit(f"{args.head} is not a descendant of {args.base}")
    _, count, _ = git("rev-list", "--count", f"{args.base}..{args.head}")
    if int(count.strip() or 0) == 0:
        sys.exit(f"empty commit range: {args.base}..{args.head}")
    span = f"{args.base}..{args.head}"
    only = ["--", f":(top,literal){fix['spec']}"] if fix and fix["spec"] else []
    changed = git("diff", "--name-only", span, *only)[1].splitlines()
    locks = [] if args.include_lockfiles or only else [p for p in changed if os.path.basename(p) in LOCKFILES]
    excludes = ["--", ":/", *(f":(top,exclude,literal){p}" for p in locks)] if locks else only
    _, commits, _ = git("log", "--oneline", span, *only)
    _, stat, _ = git("diff", "--stat", span, *only)
    _, diff, _ = git("diff", "-U10", span, *excludes)
    _, history, _ = git("log", "-p", "-m", "--format=commit %h %s", span, *only)
    short = lambda rev: git("rev-parse", "--short", rev)[1].strip()
    name = args.name or f"{short(args.base)}..{short(args.head)}"
    package = os.path.join(args.out_dir, f"review-{name}.diff")
    patches = os.path.join(args.out_dir, f"review-{name}.history.patch")
    skipped = (f"\nLockfiles left out of the diff below (still in the stat; --include-lockfiles keeps them): "
               f"{', '.join(locks)}\n") if locks else ""
    checklists = checklists_section(args.checklists_dir, changed)
    dependencies = f"\n{dependency_section(span, locks)}" if locks else ""
    header = ""
    if fix:
        header = (f"Scope: {fix['scope']}\nPrevious report: {fix['previous']}\n"
                  + (f"Spec: {fix['spec']}\n" if fix["spec"] else "")
                  + f"Record with: append --task {args.fix_of} --from {args.base} --head {args.head} "
                    f"--scope {fix['flag']}\n")
    write(package, f"# Review package: {span}\n{header}\n{checklists}\n## Commits\n{commits}\n"
                   f"## Files changed\n{stat}{skipped}{dependencies}\n## Diff\n{diff}")
    write(patches, f"# Commit-by-commit patches: {span}\n\n{history}")
    print(f"package: {package}")
    print(f"history: {patches}")
    print(f"{count.strip()} commit(s)")
    if fix:
        print(f"scope: {fix['scope']}")
        print(f"record with: --from {args.base} --head {args.head} --scope {fix['flag']}")


def extract_task(plan, task_id):
    fenced, keep, level, lines = False, False, 0, []
    with open(plan, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("```"):
                fenced = not fenced
            task = None if fenced else TASK_HEADING.match(line)
            other = None if fenced or task else ANY_HEADING.match(line)
            if task:
                keep = task.group(2).rstrip(".") == task_id
                level = len(task.group(1))
            elif keep and other and len(other.group(1)) <= level:
                keep = False
            if keep:
                lines.append(line)
    return lines


def addenda(directory, task_id):
    found = []
    for folder in (f"{task_id}.addenda", "all.addenda"):
        found.extend(sorted(glob.glob(os.path.join(directory, folder, "*.md"))))
    return found


def load_jsonl(path):
    rows = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except ValueError:
                value = None
            if not isinstance(value, dict):
                sys.stderr.write(f"warning: {path}:{number} is not a lesson object; ignored\n")
                value = None
            rows.append((line, value))
    return rows


def is_override(lesson):
    return lesson.get("override") is True


def counter(lesson, name):
    return int((lesson.get("counters") or {}).get(name, 0))


def lesson_score(lesson, from_delivery, overrides):
    extra = overrides.get(lesson["id"], {}) if not from_delivery else {}
    held = counter(lesson, "held") + counter(extra, "held")
    recurred = counter(lesson, "recurred") + counter(extra, "recurred")
    return held - 2 * recurred + (0.25 if from_delivery else 0)


def lesson_priority(lesson):
    priority = lesson.get("priority", 0)
    return priority if isinstance(priority, int) and not isinstance(priority, bool) else 0


def lesson_rank(lesson, from_delivery, overrides, task_paths):
    matched, (literal, wildcards, prefix) = relevance(lesson.get("paths") or [], task_paths)
    return (-lesson_priority(lesson), -literal, -wildcards, -prefix, -matched,
            -lesson_score(lesson, from_delivery, overrides), lesson["id"])


def fair_order(candidates, overrides, task_paths):
    rank = lambda item: lesson_rank(item[0], item[1], overrides, task_paths)
    fallback = sorted((item for item in candidates if not item[0].get("paths")), key=rank)
    queues = {}
    for item in sorted((item for item in candidates if item[0].get("paths")), key=rank):
        queues.setdefault(str(item[0].get("stack") or ""), []).append(item)
    taken = {stack: 0 for stack in queues}
    order = []

    def fill(eligible, has_room):
        while True:
            heads = [stack for stack, queue in queues.items() if queue and eligible(queue[0])]
            if not heads:
                return
            stack = min(heads, key=lambda stack: (taken[stack], rank(queues[stack][0])))
            if not has_room(stack):
                return
            order.append(queues[stack].pop(0))
            taken[stack] += 1

    unserved = lambda stack: sum(1 for other, count in taken.items() if count == 0 and other != stack)
    fill(lambda item: lesson_priority(item[0]) > 0, lambda stack: len(order) + 1 + unserved(stack) <= LESSONS_MAX)
    fill(lambda item: True, lambda stack: True)
    return order + fallback


def injected_before(out):
    sidecar = out + ".lessons"
    if os.path.isfile(sidecar):
        with open(sidecar, encoding="utf-8", errors="replace") as handle:
            return {line.strip() for line in handle if line.strip()}
    if not os.path.isfile(out):
        return set()
    with open(out, encoding="utf-8", errors="replace") as handle:
        text = handle.read()
    start = text.find(LESSONS_HEADER)
    return set(LESSON_ID.findall(text[start:])) if start >= 0 else set()


def count_injections(path, rows, chosen, already):
    pending = {lesson["id"]: lesson for lesson, _, _ in chosen if lesson["id"] not in already}
    if not pending:
        return
    lines = []
    for raw, lesson in rows:
        if lesson and lesson.get("id") in pending:
            del pending[lesson["id"]]
            counters = lesson.setdefault("counters", {})
            counters["injected"] = int(counters.get("injected", 0)) + 1
            raw = json.dumps(lesson, ensure_ascii=False, separators=(",", ":"))
        lines.append(raw.rstrip("\r\n") + "\n")
    for lesson_id, lesson in pending.items():
        row = {"id": lesson_id, "stack": lesson.get("stack"), "override": True,
               "counters": {"injected": 1, "held": 0, "recurred": 0}}
        lines.append(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    replace_file(path, "".join(lines))


def lessons_section(args, task_paths):
    delivery_rows = load_jsonl(args.delivery_lessons) if os.path.isfile(args.delivery_lessons) else []
    overrides = {lesson["id"]: lesson for _, lesson in delivery_rows
                 if lesson and is_override(lesson) and lesson.get("id")}
    sources = [(lesson, True) for _, lesson in delivery_rows if lesson and not is_override(lesson)]
    for path in sorted(glob.glob(os.path.join(args.lessons_dir, "*.jsonl"))):
        sources.extend((lesson, False) for _, lesson in load_jsonl(path) if lesson)
    candidates, seen = [], set()
    for lesson, from_delivery in sources:
        lesson_id = lesson.get("id")
        if not lesson_id or lesson_id in seen or lesson.get("status") != "active" or not lesson.get("text"):
            continue
        globs = lesson.get("paths") or []
        if (globs and matches_any(globs, task_paths)) or (not globs and lesson.get("stack") == "general"):
            seen.add(lesson_id)
            candidates.append((lesson, from_delivery))
    candidates = fair_order(candidates, overrides, task_paths)
    chosen, size = [], len(LESSONS_HEADER)
    for lesson, from_delivery in candidates:
        if len(chosen) == LESSONS_MAX:
            break
        line = f"- {' '.join(str(lesson['text']).split())} [{lesson['id']}]\n"
        if size + len(line) > LESSONS_CHARS - TRUNCATION_RESERVE:
            continue
        chosen.append((lesson, from_delivery, line))
        size += len(line)
    if not chosen:
        return "", 0
    already = injected_before(args.out)
    count_injections(args.delivery_lessons, delivery_rows, chosen, already)
    injected = sorted(already | {lesson["id"] for lesson, _, _ in chosen})
    write(args.out + ".lessons", "".join(f"{lesson_id}\n" for lesson_id in injected))
    section = LESSONS_HEADER + "".join(line for _, _, line in chosen)
    left = len(candidates) - len(chosen)
    if left:
        section += f"[lessons truncated: {left} more]\n"
    return section, len(chosen)


def brief(args):
    lines = extract_task(args.plan, args.task)
    if not lines:
        sys.exit(f"task {args.task} not found in {args.plan}")
    task_text = "".join(lines)
    text = task_text.rstrip("\n") + "\n"
    extra = addenda(args.addenda_dir, args.task)
    for path in extra:
        with open(path, encoding="utf-8", errors="replace") as handle:
            text += "\n---\n\n" + handle.read().replace("\r\n", "\n").rstrip("\n") + "\n"
    injected = 0
    if not args.no_lessons:
        section, injected = lessons_section(args, cited_paths(task_text))
        if section:
            text += "\n" + section
    write(args.out, text)
    print(f"brief: {args.out} ({len(lines)} lines, {len(extra)} addenda, {injected} lessons)")


def main():
    parser = argparse.ArgumentParser(prog="package.py")
    commands = parser.add_subparsers(dest="command", required=True)

    review_cmd = commands.add_parser("review", help="write a review package and history patches for BASE..HEAD")
    review_cmd.add_argument("--base", help="required unless --fix-of")
    review_cmd.add_argument("--head", default="HEAD")
    review_cmd.add_argument("--fix-of", metavar="TASK",
                            help="re-review after a fix: range, scope and previous report come from the ledger")
    review_cmd.add_argument("--agent", help="the reviewer to re-run, with --fix-of")
    review_cmd.add_argument("--ledger", default=".superpowers/ledger.jsonl")
    review_cmd.add_argument("--name", help="file name stem; default BASE..HEAD short SHAs, "
                                           "or <task>-<agent>-fix-r<round> with --fix-of")
    review_cmd.add_argument("--out-dir", default=".superpowers/reviews")
    review_cmd.add_argument("--include-lockfiles", action="store_true")
    review_cmd.add_argument("--checklists-dir", default=os.path.join(PLUGIN_ROOT, "checklists"))
    review_cmd.set_defaults(run=review)

    brief_cmd = commands.add_parser("brief", help="extract one task's text from a plan file")
    brief_cmd.add_argument("--plan", required=True)
    brief_cmd.add_argument("--task", required=True)
    brief_cmd.add_argument("--out", required=True)
    brief_cmd.add_argument("--addenda-dir", default=".superpowers/briefs")
    brief_cmd.add_argument("--lessons-dir", default=os.path.join(PLUGIN_ROOT, "lessons"))
    brief_cmd.add_argument("--delivery-lessons", default=".superpowers/lessons.jsonl")
    brief_cmd.add_argument("--no-lessons", action="store_true")
    brief_cmd.set_defaults(run=brief)

    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
