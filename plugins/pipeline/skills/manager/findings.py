import os
import re

LINE_SUFFIX = re.compile(r":\d+(?:-\d+)?$")
QUALIFIER = r"(?:new\s+|open\s+|remaining\s+)?"
SEVERITY = QUALIFIER + r"(?:critical|important|minor)s?"
FINDINGS = QUALIFIER + r"findings"
COUNT = r"(?:\s*\([^()]*\))?"
HEADING = re.compile(r"^\s*(#+)\s+(.*)$")
HEADING_OPENER = re.compile(rf"^\W*(?:\d+[.)]\s*)?(?:{SEVERITY}|{FINDINGS})\b", re.IGNORECASE)
LABEL_OPENER = re.compile(rf"^(?:{SEVERITY}(?:\s+(?:findings|issues))?|{FINDINGS}){COUNT}\s*:?$", re.IGNORECASE)
PLAIN_OPENER = re.compile(rf"^\s*(?:{SEVERITY}(?:\s+(?:findings|issues))?{COUNT}\s*(?::|$)|{FINDINGS}\b)",
                          re.IGNORECASE)
BOLD_LINE = re.compile(r"^\s*\*\*([^*]+)\*\*\s*(:?)\s*(.*)$")
PLAIN_LABEL = re.compile(r"^([A-Z][\w'/-]*(?: [\w'/-]+){0,4})" + COUNT + r"\s*:(?:\s|$)")
OTHER_REVIEWER = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)?for\s+[\w-]+(?:\s+[\w-]+)?\s*:", re.IGNORECASE)
CLOSING_HEADING = re.compile(r"^\W*(?:notes?|other domains?|for other reviewers|for [\w-]+|checked\b|open questions?"
                             r"|housekeeping|verdict|summary|out of (?:domain|scope)|not verified|verification)",
                             re.IGNORECASE)
LEDGER_START = re.compile(r"^[\s`>*-]*LEDGER\s*\{")
FINDING_LABELS = {"fix", "fixes", "why", "impact", "evidence", "repro", "reproduction", "scenario", "suggestion",
                  "suggested fix", "recommendation", "location", "where", "cause", "risk", "expected", "actual",
                  "example", "pattern", "exploit"}
BACKTICKED = re.compile(r"`([^`\s]+)`")
SEGMENT = r"[\w.()\[\]@+-]+/"
FILE_NAME = re.compile(rf"(?<![\w/.-])((?:{SEGMENT})*[\w-][\w.-]*\.[A-Za-z]\w{{0,7}})(?::\d+(?:-\d+)?)?(?![\w/(-])")
SHORTHAND = re.compile(r"(?<![\w/.:-])([A-Za-z0-9_][\w-]*):\d+(?:-\d+)?(?![\w.])")
RATIO = re.compile(r"^(?:[1-9]\d*|0)(?:\.\d+)?:\d+(?:\.\d+)?$")
ABBREVIATIONS = ("e.g", "i.e")
EXEMPT_PREFIXES = ("docs/",)


def label_of(line):
    bold = BOLD_LINE.match(line)
    if not bold:
        return None, False
    text = bold.group(1)
    return text.split(":")[0].strip(), bool(bold.group(2)) or ":" in text or not bold.group(3)


def opener(line):
    heading = HEADING.match(line)
    if heading:
        return len(heading.group(1)) if HEADING_OPENER.match(heading.group(2)) else None
    label, _ = label_of(line)
    if label is not None:
        return 0 if LABEL_OPENER.match(label) else None
    if PLAIN_OPENER.match(line) and len(line.strip()) <= 80:
        return 0
    return None


def is_section_end(line, level):
    if LEDGER_START.match(line):
        return True
    heading = HEADING.match(line)
    if heading:
        if HEADING_OPENER.match(heading.group(2)):
            return level == 0 or len(heading.group(1)) <= level
        return level == 0 or len(heading.group(1)) <= level or bool(CLOSING_HEADING.match(heading.group(2)))
    label, closes = label_of(line)
    if label is not None:
        return (closes or bool(CLOSING_HEADING.match(label))) and not LABEL_OPENER.match(label) \
            and label.lower() not in FINDING_LABELS
    plain = PLAIN_LABEL.match(line)
    return bool(plain) and plain.group(1).lower() not in FINDING_LABELS and not PLAIN_OPENER.match(line)


def findings_sections(text):
    sections, current, level = [], None, 0
    for line in text.splitlines():
        if current is not None and is_section_end(line, level):
            sections.append("\n".join(current))
            current = None
        if current is None:
            found = opener(line)
            if found is not None:
                current, level = [line], found
            continue
        if not OTHER_REVIEWER.match(line):
            current.append(line)
    if current is not None:
        sections.append("\n".join(current))
    return sections


def normalized(candidate):
    path = candidate.strip(" `*,;").replace("\\", "/")
    if path.startswith("(") and ")" not in path.split("/", 1)[0]:
        path = path[1:]
    path = LINE_SUFFIX.sub("", path)
    while path.startswith("./"):
        path = path[2:]
    return path.rstrip(".")


def is_prose(candidate):
    token = candidate.strip(" `*,;()")
    return "//" in token or bool(RATIO.match(token)) or token.lower().rstrip(".") in ABBREVIATIONS


def shorthand_names(text):
    return {match.group(1) for match in SHORTHAND.finditer(text) if not RATIO.match(match.group(0))}


def finding_paths(text):
    sections = findings_sections(text)
    if not sections:
        return None
    body = "\n".join(sections)
    paths = set()
    for candidate in BACKTICKED.findall(body) + FILE_NAME.findall(body):
        if is_prose(candidate):
            continue
        path = normalized(candidate)
        if path and ("/" in path or "." in path) and re.search(r"[A-Za-z]", path):
            paths.add(path)
    for token in BACKTICKED.findall(body):
        if "//" not in token:
            paths.update(shorthand_names(token))
    paths.update(shorthand_names(BACKTICKED.sub(" ", body)))
    return paths


def basename_match(cited, path):
    name = os.path.basename(path)
    return name == cited or (name.startswith(cited) and name[len(cited)] in "._-")


def is_cited(path, cited, universe):
    for item in cited:
        if item == path or ("/" in item and path.endswith("/" + item)):
            return True
    for item in cited:
        if "/" not in item and [p for p in universe if basename_match(item, p)] == [path]:
            return True
    return False


def uncited(fixed, cited, universe):
    universe = sorted(set(universe) | set(fixed))
    return [path for path in fixed if not is_cited(path, cited, universe)]


def exempt(path):
    return path.replace("\\", "/").startswith(EXEMPT_PREFIXES)


def fix_scope_reason(reports, fixed, universe):
    cited = set()
    for ref, text in reports:
        if text is None:
            return f"the report {ref} cannot be read"
        cited |= finding_paths(text) or set()
    checked = [path for path in fixed if not exempt(path)]
    if not checked:
        return None
    if not cited:
        return "the open findings of the task's reviewers cite no file"
    outside = uncited(checked, cited, universe)
    if outside:
        more = f" +{len(outside) - 5} more" if len(outside) > 5 else ""
        return f"the fix touches files outside the open findings: {', '.join(outside[:5])}{more}"
    return None
