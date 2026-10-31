#!/usr/bin/env python3
"""Local gate: the last check before anything leaves the machine. Deterministic, no agent.

  gate.py [--base <rev>] [--ledger <path>] [--cmd Name=command ...] [--report <slug>]
  gate.py --criteria <task> [--ledger <path>]     only the Criteria check, for that task's criteria; exits 0 or 1

A criterion is an id that opens a list item of the plan (- AC-T3-2, * **AC-T3-2**, 1. `AC-T3-2`); an id written
anywhere else is cited, a warning ("cited, never defined") and never traced, and a plan where no id opens a list
item is read as before, every id a criterion (one opening an item of the plan's ## Errata too, as a fix round's
criteria). A task's criteria, for --criteria, are those with a segment that is the
task id or ends with it right after a digit (AC-T3-2, AC-PL-T3-2 and AC-074T3-2 are T3's; AC-T31-2 is not).

Checks, in order: nothing is pending in the ledger (the current cycle is closed, every deferred item has a final
decision, a delivery marked sensitive had its security scan and no copy of an integrated task is left over); the tree is clean; the documentation the kickoff prepared stays whole (with a docs/README.md: docs/arquitetura.md, the patterns every task follows, exists and, once a module doc docs/modulos/NN-*.md is tracked, holds no _(...)_ placeholder; the index names every tracked module doc; every entry of docs/ is in the map (README.md, arquitetura.md, operacao.md
or operacao/, lessons.md, modulos/ with module docs only, discovery/, specs/, plans/, mockups/, quality-reports/, or a
folder or file the index names); and no relative link of README.md, docs/README.md or docs/arquitetura.md points to a missing file); the files of the
"Versão" line of "Comandos" (space-separated) hold one version x.y.z (after a version, versionName or __version__ key,
quoted, bare or an XML element, or alone in the file; a pre-release fails) above the one they held at <base> (none there passes, and so does a delivery that changed only
documentation; with no line, a project with docs/README.md fails and any other skips), named on the GATE line and in the report header; every acceptance-criterion id of the plan recorded in the ledger (tokens like AC-T3-2)
appears in a tracked test file, as written or, for a test named by an identifier, in any case with _ for - and .
(ac_t3_2, test_AC_T3_2; a longer id such as AC-T3-21, AC-T3-2.1 or ac_t3_2_1 is another id); the plan names no path inside .superpowers/, the agent workspace the kickoff
ignores, since no clone would have it (the globs on the
"Arquivos de teste" line of the CLAUDE.md "Comandos" section, space-separated globs where * and ? stay within one
folder, **/ matches zero or more folders and {a,b} is either; an invalid glob, or one that matches no tracked file,
prints a warning; without that line, every tracked file that is not Markdown); no commit after the head of the
ledger's latest reviewer run changes anything but the plan, docs/lessons.md, docs/quality-reports/ or the user's
.pipeline-secrets-allow (first-parent commits only, so a merged front is not counted, and tasks are integrated by
fast-forward or cherry-pick); when "Comandos" has a "Verificação de interface" line and no command the gate runs
is that line's command, a qa run added with --full whose head differs from HEAD in no file but those
same exempt files (Full suite, by tree, so a merged front counts); every command of that section passes (lines like
"- Testes: `<command>`"; Build, Typecheck, Lint, Testes and the optional Auditoria are run, a second line of the same
kind runs too under its own label, such as "Testes (e2e)", a blank command counts as not configured, and --cmd adds
or overrides one, or with no command removes it), each in a POSIX shell, as the Bash tool runs them (Git Bash on
Windows, and cmd.exe with a warning only when there is none; bash, else sh, elsewhere) and within the minutes of the
"Tempo máximo" line of that section (15 by default; a value that is no number of minutes up to a day is a warning;
past the limit the command and, outside Windows, the processes it started are stopped); the commands changed no
tracked file; and no secret or .env file is added anywhere in <base>..HEAD, the whole history that a push would send.
The "Ambiente dos comandos" line of CLAUDE.local.md (the machine's own file; a _(...)_ placeholder is none) runs
before every command, joined with &&, as a PATH to a tool this machine needs. Each run is recorded in the ledger
(ledger.py gate, with the checks that failed), and the quality report counts the runs and why each was NOT READY.
A check that does not apply is SKIP with the reason; only Testes is required. When a check before the commands
fails (Ledger through Full suite), the commands are not run and each fails as "not run", since the run would end NOT
READY anyway; the secret scan still runs. With the test files declared, the gate
also warns when a criterion's test arrived in the same commit as code, naming the criterion and that commit: a test
written first has a commit of its own. Test material is not code arriving (the declared test files and anything
under a folder they name, the plan, the lessons, the allowlist, the quality reports, and a rename with no content).
The warning does not change the verdict, and no warning does not prove the order: code written first and committed
after its test leaves the same history. When the "Comandos" section differs
from the one at <base>, the gate prints the difference as a warning (and the report shows it) and still runs the
branch's commands. A "Comandos" line labeled Testes, Tests or Test plus other words (not "Testes afetados") is no
gate command: it is a warning (and the report lists it) to name it "Testes (<name>)". Prints READY or NOT READY and
exits 0 or 1.

<base> is --base (an error when it is not a commit), or else the base the ledger recorded at start, or else the
merge base with the default branch. With --report, the gate writes and stages docs/quality-reports/<date>-<slug>.md
(checks, commits, ledger mode and notes, the VALIDAR list with the user's decision or pending, deferred decisions, a
changed "Comandos" section and the delivery metrics: findings per cycle and origin, fix rounds, time per cycle, task
and agent, tokens per agent and task, lines changed per dev task with the share of fix and cleanup, lessons added
and automated, the delivery's clock and the gate's warnings) before running the commands, so the project's own tests check it too (the metrics also give each spec
or plan review loop its rounds and findings); READY rewrites
its check lines, NOT READY removes it, and a draft of the same report left staged by a run that was killed is removed
first."""
import argparse
import datetime
import difflib
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCANNER = os.path.join(HERE, "..", "..", "hooks", "pre-commit-secret-scan.py")
COMMANDS = {"build": "Build", "typecheck": "Typecheck", "tipos": "Typecheck", "lint": "Lint", "testes": "Testes",
            "tests": "Testes", "test": "Testes", "auditoria": "Auditoria", "audit": "Auditoria"}
ORDER = ["Build", "Typecheck", "Lint", "Testes", "Auditoria"]
WORKSPACE = re.compile(r"[\w./\-]*\.superpowers/[\w./\-]+")
TEST_FILES = "arquivos de teste"
NOT_COMMANDS = {TEST_FILES, "testes afetados"}
INTERFACE = ("verificação de interface", "verificacao de interface")
CRITERION_ANY = re.compile(r"(?<![\w-])AC-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*")
# The placeholder may sit after a piece of the id (AC-05T<task>-<n>): without \w and - in the lookahead the
# match backtracks to AC-05 and the gate traces a criterion the plan never wrote.
CRITERION = re.compile(CRITERION_ANY.pattern + r"(?![<{\w-])")
# A criterion is defined where its id opens a list item (after ** or a backtick); anywhere else it is only cited.
DEFINED = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+[*_`]*(" + CRITERION.pattern + ")", re.MULTILINE)
MINUTES = 15
DAY = 24 * 60 * 60
REPORTS = "docs/quality-reports"
PATTERNS = "docs/arquitetura.md"
MODULE_NAME = re.compile(r"\d{1,3}-[^/]+\.md")
MODULE_DOC = re.compile(r"docs/modulos/" + MODULE_NAME.pattern)
# What docs/ holds, beside a folder or file the index names: the kickoff's templates and the delivery's slug folders.
DOCS_MAP = {"README.md", "arquitetura.md", "operacao.md", "operacao", "lessons.md", "modulos", "discovery", "specs",
            "plans", "mockups", "quality-reports"}
LINK = re.compile(r"\]\(((?:[^()\s]|\([^()\s]*\))+)\)")
LESSONS = "docs/lessons.md"
SECRETS_ALLOW = ".pipeline-secrets-allow"
VERSION_LABELS = ("versão", "versao", "version")
# Only these keys: a dependency or a tool version (kotlinVersion, "semver": "^7.5.0") is not the product's.
# Quoted (JSON, TOML, Gradle), bare (YAML, properties) or an XML element; a +build after it is the store's number.
VERSION_KEY = re.compile(r"""(?im)^[ \t]*[<"']?(?:version|versionName|__version__)[>"']?[ \t]*[:=]?[ \t]*["']?v?"""
                         r"""(\d+\.\d+\.\d+)(-[\w.]+)?(?![\w.])""")
VERSION_ONLY = re.compile(r"\s*v?(\d+\.\d+\.\d+)(-[\w.]+)?\s*")


WARNINGS = []


def warn(text):
    """Print a warning and keep it for the quality report, where the next feedback-plugin can count it."""
    print("warning: " + text, flush=True)
    WARNINGS.append(text)


def git(*args):
    result = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return result.returncode, result.stdout


def commit_of(rev):
    return rev and git("rev-parse", "--verify", "--quiet", rev + "^{commit}")[1].strip()


def default_base():
    for ref in ("origin/HEAD", "origin/main", "origin/master", "main", "master"):
        code, out = git("merge-base", "HEAD", ref)
        if code == 0 and out.strip():
            return out.strip()
    return None


def comandos_section(text):
    section = re.search(r"(?ms)^##\s+Comandos\s*$(.*?)(?=^##\s|\Z)", text)
    return section.group(1) if section else ""


def claude_md():
    return open("CLAUDE.md", encoding="utf-8").read() if os.path.exists("CLAUDE.md") else ""


def comandos():
    return [(label.strip(), value.strip())
            for label, value in re.findall(r"(?m)^\s*[-*]\s*([^:\n]+):\s*`([^`]+)`", comandos_section(claude_md()))]


def label_key(label):
    return re.sub(r"\s*\(.*\)$", "", label).lower()


def project_commands(overrides):
    commands = {}
    for label, command in comandos():
        kind = COMMANDS.get(label_key(label))
        if not kind or not command:
            continue
        detail = re.search(r"\(([^()]*)\)$", label)
        name, number = kind, 1
        while name in commands:
            number += 1
            name = f"{kind} ({detail.group(1)})" if detail and number == 2 else f"{kind} {number}"
        commands[name] = command
    for item in overrides:
        name, _, command = item.partition("=")
        name = COMMANDS.get(name.strip().lower(), name.strip())
        if command.strip():
            commands[name] = command.strip()
        else:
            commands.pop(name, None)
    return commands


def unrun_tests():
    return [label for label, value in comandos() if value and re.match(r"(?:testes|tests|test)\b", label_key(label))
            and label_key(label) not in COMMANDS and label_key(label) not in NOT_COMMANDS]


def comandos_change(base):
    code, old = git("show", f"{base}:CLAUDE.md")
    before = comandos_section(old if code == 0 else "").strip().splitlines()
    after = comandos_section(claude_md()).strip().splitlines()
    return list(difflib.unified_diff(before, after, f"{base[:7]}:CLAUDE.md", "CLAUDE.md", lineterm=""))


def time_limit():
    line = re.search(r"(?im)^\s*[-*]\s*tempo m[áa]ximo[^:\n]*:(.*)$", comandos_section(claude_md()))
    value = line.group(1).strip() if line else ""
    if not value or re.fullmatch(r"_\(.*\)_", value):
        return MINUTES * 60
    number = re.match(r"`([^`]+)`", value)
    try:
        seconds = round(float(number.group(1).strip().replace(",", ".")) * 60)
    except (AttributeError, ValueError, OverflowError):
        seconds = 0
    if 1 <= seconds <= DAY:
        return seconds
    warn(f"invalid Tempo máximo '{value}' in CLAUDE.md (Comandos); using {MINUTES} minutes")
    return MINUTES * 60


def bash():
    if os.name != "nt":
        return shutil.which("bash") or "/bin/sh"
    # Git Bash, as the Bash tool runs it; the bash.exe on PATH may be WSL's.
    candidates = [os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")]
    code, out = git("--exec-path")
    folder = out.strip() if code == 0 else ""
    for _ in range(4 if folder else 0):
        folder = os.path.dirname(folder)
        candidates += [os.path.join(folder, "bin", "bash.exe"), os.path.join(folder, "usr", "bin", "bash.exe")]
    return next((path for path in candidates if path and os.path.isfile(path)), None)


def run_command(command, shell, seconds):
    # Output goes to a file, not a pipe: on Windows a pipe held by a child would keep the gate waiting past the limit.
    with tempfile.TemporaryFile() as out:
        process = subprocess.Popen([shell, "-c", command] if shell else command, shell=not shell, stdout=out,
                                   stderr=subprocess.STDOUT, start_new_session=os.name != "nt")
        try:
            code = process.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            return False, f"timed out after {seconds}s"
        out.seek(0)
        output = out.read().decode("utf-8", errors="replace").strip().splitlines()
        return code == 0, "\n".join(output[-15:])


def secret_findings(base):
    spec = importlib.util.spec_from_file_location("secretscan", SCANNER)
    scanner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scanner)
    return scanner.range_findings(f"{base}..HEAD", os.getcwd())


def glob_regex(pattern):
    pattern, out, index = pattern.replace("\\", "/").removeprefix("./"), [], 0
    while index < len(pattern):
        char = pattern[index]
        if pattern.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
            continue
        if pattern.startswith("**", index):
            out.append(".*")
            index += 2
            continue
        end = pattern.find("]" if char == "[" else "}", index + 2) if char in "[{" else -1
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "[" and end > 0:
            body = pattern[index + 1:end]
            out.append("[" + ("^" + body[1:] if body.startswith("!") else body) + "]")
            index = end
        elif char == "{" and end > 0 and "," in pattern[index:end]:
            out.append("(?:" + "|".join(re.escape(part) for part in pattern[index + 1:end].split(",")) + ")")
            index = end
        else:
            out.append(re.escape(char))
        index += 1
    return re.compile("".join(out) + r"\Z")


def artifacts(plan, slug=None):
    if not plan:
        return True, "no plan in the ledger (small work has none)"
    if not os.path.exists(plan):
        return False, f"plan not found: {plan}"
    if slug and os.path.isfile("docs/README.md") and repo_path(plan) != f"docs/plans/{slug}.md":
        return False, f"the plan is {repo_path(plan)}, not docs/plans/{slug}.md, where the delivery's slug puts it"
    named = sorted(set(WORKSPACE.findall(open(plan, encoding="utf-8").read())))
    if named:
        return False, (f"{plan} points inside .superpowers/, the agent workspace the kickoff ignores, so no clone has "
                       "these, and an artifact anyone reads (a mock above all) lives in a versioned path: "
                       + ", ".join(named))
    return True, ""


def docs():
    """The documentation the kickoff prepared stays whole: the patterns file, every module doc in the index, and no
    dead relative link in the root README, the index or the patterns."""
    if not os.path.isfile("docs/README.md"):
        return True, "no docs/README.md: the kickoff prepares it"
    problems = []
    tracked = [path for path in git("-c", "core.quotePath=false", "ls-files", "-z", "docs")[1].split("\0") if path]
    modules = [path for path in tracked if MODULE_DOC.fullmatch(path)]
    index = open("docs/README.md", encoding="utf-8").read()
    for top in sorted({path.split("/")[1] for path in tracked if path.count("/") >= 1}):
        if MODULE_NAME.fullmatch(top) or top not in DOCS_MAP and not re.search(
                r"(?<![\w-])" + re.escape(top) + r"(?![\w-])", index):
            where = "a module doc goes in docs/modulos/" if MODULE_NAME.fullmatch(top) else (
                "move it to its place in the map, or name it in the index")
            problems.append(f"docs/{top} is outside the map of docs/README.md: {where}")
    problems += [f"docs/modulos/ holds only module docs (NN-*.md) and their folders: {path}" for path in tracked
                 if path.startswith("docs/modulos/") and path.count("/") == 2 and not MODULE_DOC.fullmatch(path)
                 and not path.endswith("/.gitkeep")]
    problems += [f"docs/README.md does not list {os.path.basename(path)}" for path in modules
                 if os.path.basename(path) not in index]
    if not os.path.isfile(PATTERNS):
        problems.append(f"no {PATTERNS}: the patterns every task follows (the kickoff's template)")
    elif modules and "_(" in open(PATTERNS, encoding="utf-8").read():
        problems.append(f"{PATTERNS} still holds a placeholder _(...)_ while the project has modules")
    for page in ("README.md", "docs/README.md", PATTERNS):
        if not os.path.isfile(page):
            continue
        for target in LINK.findall(open(page, encoding="utf-8").read()):
            path = target.split("#")[0]
            if path and ":" not in path and not os.path.exists(os.path.join(os.path.dirname(page), path)):
                problems.append(f"dead link: {page} -> {path}")
    return not problems, "\n".join(problems)


def version_in(text):
    """The x.y.z of the text, "pre-release" when a suffix such as -rc.1 follows it, or None."""
    match = text is not None and (VERSION_ONLY.fullmatch(text) or VERSION_KEY.search(text))
    return ("pre-release" if match.group(2) else match.group(1)) if match else None


def semver(value):
    return tuple(int(part) for part in value.split("."))


def version(base):
    """The files of the "Versão" line hold one version, above the one they held at the base; returns it too."""
    files = next((value.split() for label, value in comandos() if label_key(label) in VERSION_LABELS), None)
    if files is None:
        if os.path.isfile("docs/README.md"):
            return False, ('no "Versão" line in CLAUDE.md (Comandos): name the file or files that hold the product\'s '
                           "version (the kickoff's template)"), None
        return True, "no Versão line in CLAUDE.md (Comandos)", None
    found = {path: version_in(open(path, encoding="utf-8", errors="replace").read() if os.path.isfile(path) else None)
             for path in files}
    early = [path for path, value in found.items() if value == "pre-release"]
    if early:
        return False, "a pre-release is no delivered version (x.y.z with no suffix): " + ", ".join(early), None
    missing = [path for path, value in found.items() if not value]
    if missing:
        return False, ("no version (x.y.z after a version, versionName or __version__ key, or a file holding only "
                       "it) in: " + ", ".join(missing)), None
    if len(set(found.values())) > 1:
        return False, "the version files disagree: " + ", ".join(f"{path} {value}" for path, value in found.items()), None
    now = found[files[0]]
    before = [version_in(out) for code, out in (git("show", f"{base}:{path}") for path in files) if code == 0]
    old = max((value for value in before if value), key=semver, default=None)
    if old and semver(now) <= semver(old):
        changed = [name for name in git("diff", "--name-only", base, "HEAD")[1].split() if name]
        if changed and all(name.startswith("docs/") or name.endswith(".md") for name in changed):
            return True, f"only documentation changed since the base (version {now})", now
        return False, (f"the version is {now}, not above the base's {old}: the manager raises it before the gate "
                       "(manager step 6)"), now
    return True, "", now


def repo_path(path):
    """A path from the ledger as git names it: relative to the repository root, with forward slashes. Both sides are
    resolved first, so the same file reached by another route (a symbolic link, or a short 8.3 name on Windows, which
    is what a Temp folder gives) is still recognized as the one git names."""
    if os.path.isabs(path):
        root = git("rev-parse", "--show-toplevel")[1].strip()
        path = os.path.relpath(os.path.realpath(path), os.path.realpath(root) if root else root)
    return path.replace("\\", "/").removeprefix("./")


def test_folders(globs):
    """The folder each declared test glob names before its first wildcard (tests/ for tests/**/*.spec.ts), so what
    a test needs to run and lives beside it counts as test material. A glob opening with a wildcard names none."""
    found = []
    for pattern in globs:
        keep = []
        for part in pattern.replace("\\", "/").split("/")[:-1]:
            if set(part) & set("*?["):
                break
            keep.append(part)
        if keep:
            found.append("/".join(keep) + "/")
    return found


def born_with_code(base, plan, ids, patterns, tests, folders):
    """Each criterion whose test arrived in the same commit as code, with that commit. It reads one git log of the
    delivery's own commits (first parent, so a branch a merge brought in is not read): a commit's added lines in a
    test file give the criteria born there, and whatever else it changed says whether code came along. Test
    material is not code arriving, and neither is a rename with no content. Needs the declared test files to tell
    a test from the code it covers.

    It finds test and code arriving together, which a test written first never does; it cannot prove the opposite,
    since code written first and committed after its test leaves the same history."""
    def is_test(name):
        return any(regex.match(name) for regex in tests)

    def material(name):
        return (is_test(name) or (folders and name.startswith(folders))
                or name in (plan, LESSONS, SECRETS_ALLOW) or name.startswith(REPORTS + "/"))

    found, left, sha, where, born, code, header = [], set(ids), "", "", [], False, False
    out = git("-c", "core.quotePath=false", "log", "--reverse", "--first-parent", "--no-merges", "--format=%x00%h",
              "-p", "-U0", "--no-prefix", f"{base}..HEAD")[1]
    for line in out.replace("\r", "").split("\n"):
        if line.startswith("--- "):
            header = True
            continue
        if line.startswith("\0"):
            found += [(item, sha) for item in born] if code else []
            sha, where, born, code = line[1:].strip(), "", [], False
        elif header and line.startswith("+++ "):
            where = line[len("+++ "):].strip()
            code = code or (where != "/dev/null" and not material(where))
        elif line.startswith("+") and where and is_test(where):
            for item in sorted(left):
                if patterns[item].search(line):
                    left.discard(item)
                    born.append(item)
        header = False
    return found + ([(item, sha) for item in born] if code else [])


def of_task(item, task):
    """A segment of the id is the task id, or ends with it right after a digit (AC-T3-2, AC-PL-T3-2, AC-074T3-2), in
    any case and with the task's hyphens left out (fix-2 is FIX2 in AC-DC-FIX2-1)."""
    task = task.replace("-", "").lower()
    return any(part == task or (part.endswith(task) and part[:-len(task)][-1:].isdigit())
               for part in (part.lower() for part in re.split(r"[.-]", item)[1:]))


def environment():
    """The prefix of the "Ambiente dos comandos" line of CLAUDE.local.md, or None."""
    try:
        text = open("CLAUDE.local.md", encoding="utf-8").read()
    except OSError:
        return None
    found = re.search(r"(?mi)^\s*[-*]\s*Ambiente dos comandos[^:\n]*:\s*`([^`]+)`", text)
    return found.group(1).strip() if found and found.group(1).strip() else None


def traceability(plan, base="", task=None):
    if not plan:
        return True, "no plan in the ledger (small work has none; otherwise record it with ledger.py plan --path)"
    if not os.path.exists(plan):
        return False, f"plan not found: {plan}"
    text = open(plan, encoding="utf-8").read()
    ids = sorted(set(CRITERION.findall(text)))
    templates = sorted(set(CRITERION_ANY.findall(text)) - set(ids))
    if templates:
        warn(f"{plan} writes {', '.join(templates)} with a placeholder right after it, so each is an id "
              "template, not a criterion, and the gate traces no test for it")
    defined = sorted(set(DEFINED.findall(text)))
    if defined:
        cited = [item for item in ids if item not in defined]
        if cited:
            warn(f"{plan}: cited, never defined: {', '.join(cited)} (a criterion is the id that opens a "
                  "list item; the gate traces no test for these)")
        ids = defined
    if task:
        ids = [item for item in ids if of_task(item, task)]
        if not ids:
            return True, f"no criterion of {task} in {plan}"
    patterns = {item: re.compile(r"(?<![A-Za-z0-9-])" + "[-_.]".join(map(re.escape, re.split(r"[-.]", item)))
                                 + r"(?![A-Za-z0-9]|[-.][A-Za-z0-9]|_\d)", re.IGNORECASE) for item in ids}
    if not ids:
        return False, f"{plan} lists no acceptance-criterion ids (AC-...)"
    globs = next((value.split() for label, value in comandos() if label_key(label) == TEST_FILES), None)
    folders = tuple(test_folders(globs)) if globs else ()
    names = [name for name in git("ls-files", "-z")[1].split("\0") if name and os.path.isfile(name)]
    tests = []
    if globs:
        tracked, names = names, []
        for pattern in globs:
            try:
                regex = glob_regex(pattern)
            except re.error:
                warn(f"invalid test glob '{pattern}' (Arquivos de teste in CLAUDE.md)")
                continue
            tests.append(regex)
            matched = [name for name in tracked if regex.match(name)]
            if not matched:
                warn(f"test glob '{pattern}' matches no tracked file (Arquivos de teste in CLAUDE.md)")
            names += [name for name in matched if name not in names]
    else:
        names = [name for name in names if not name.lower().endswith(".md")]
    missing = list(ids)
    for name in names:
        if missing and os.path.getsize(name) < 2_000_000:
            text = open(name, encoding="utf-8", errors="ignore").read()
            missing = [item for item in missing if not patterns[item].search(text)]
    if tests and base:
        late = born_with_code(base, repo_path(plan), ids, patterns, tests, folders)
        if late:
            warn("test and code in the same commit for "
                  + ", ".join(f"{item} ({sha})" for item, sha in late)
                  + "; a test written first has a commit of its own, and no warning does not prove that order")
    return not missing, ("criteria with no test: " + ", ".join(missing)) if missing else ""


def changed_after(ledger, head, tree=False):
    """The files changed after <head> that no review or full qa is owed for (by first-parent log, or by tree diff
    when tree), or None when <head> is no ancestor."""
    if git("merge-base", "--is-ancestor", head, "HEAD")[0] != 0:
        return None, []
    plan = repo_path(ledger.get("plan") or "")
    out = (git("diff", "-z", "--name-only", head, "HEAD") if tree else
           git("log", "--first-parent", "--no-merges", "-z", "--name-only", "--format=", f"{head}..HEAD"))[1]
    changed = sorted({name.strip("\n") for name in out.split("\0")} - {"", plan, LESSONS, SECRETS_ALLOW})
    return True, [name for name in changed if not name.startswith(REPORTS + "/")]


def reviewed(ledger):
    reviews = (ledger or {}).get("reviewer") or []
    head = reviews[0].get("head") if reviews else ""
    if not head:
        return True, "no reviewer head in the ledger"
    found, changed = changed_after(ledger, head)
    if not found:
        return False, f"the reviewed head {head[:7]} is not in this history: run the reviewer on the current head"
    return not changed, (f"changed after the reviewed head {head[:7]} with no review: " + ", ".join(changed)
                         if changed else "")


def full_suite(ledger, commands):
    interface = {value for label, value in comandos() if label_key(label) in INTERFACE and value}
    if not interface:
        return True, "no Verificação de interface line"
    other = next((name for name, command in commands.items() if command in interface), None)
    if other:
        return True, f"the gate runs the interface suite ({other})"
    full = ledger.get("full_qa")
    head = full and full.get("head")
    if not head:
        return False, ("the interface suite runs in no gate line and no qa ran the full suite at the final head: "
                       'dispatch qa on the full suite (every test line of Comandos and the entire interface suite) '
                       'and add it with --full, or put the interface command on a "Testes (<name>)" line too')
    found, changed = changed_after(ledger, head, tree=True)
    if not found:
        return False, (f"the full qa head {head[:7]} is not in this history: "
                       "run qa on the full suite at the current head")
    return not changed, (f"changed after the full qa at {head[:7]}: " + ", ".join(changed) if changed else "")


def ledger_state(path):
    result = subprocess.run([sys.executable, os.path.join(HERE, "ledger.py"), *(["--ledger", path] if path else []),
                             "status", "--json"], capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        return None, result.stderr.strip() or "no ledger"
    return json.loads(result.stdout), None


def duration(seconds):
    if seconds < 60:
        return f"{seconds}s"
    hours, minutes = divmod(round(seconds / 60), 60)
    return f"{hours}h{minutes}m" if hours else f"{minutes}m"


def time_lines(metrics):
    time = metrics.get("time")
    if not time or not time["agents"]:
        return []
    unmeasured = time["unmeasured"]
    lines = ["## Time", "", "Agent time adds up every run; elapsed is wall-clock, so parallel runs count once. "
             f"{unmeasured} run{'' if unmeasured == 1 else 's'} unmeasured.", ""]
    clock = time.get("delivery")
    if clock:
        share = f" ({round(clock['share'] * 100)}%)" if clock.get("share") is not None else ""
        lines.append(f"- Delivery: {duration(clock['elapsed'])} elapsed, {duration(clock['paused'])} paused, "
                     f"an agent running {duration(clock['agents'])}{share}")
    for cycle in metrics["cycles"]:
        agents = ", ".join(f"{agent} {duration(seconds)}" for agent, seconds in cycle["agents"].items())
        elapsed = f", {duration(cycle['elapsed'])} elapsed" if cycle.get("elapsed") is not None else ""
        lines.append(f"- Cycle {cycle['cycle']}: {duration(cycle['seconds'])} agent time{elapsed}"
                     + (f" ({agents})" if agents else ""))
    tasks = ", ".join(f"{task} {duration(seconds)}" for task, seconds in time["tasks"].items())
    lines.append(f"- Tasks: {tasks or '-'}")
    lines.append("- Agents: " + ", ".join(f"{agent} {duration(seconds)}" for agent, seconds in time["agents"].items()))
    return lines + [""]


def token_lines(metrics):
    tokens = metrics.get("tokens")
    if not tokens or not tokens["agents"]:
        return []
    unmeasured = tokens["unmeasured"]
    agents = ", ".join(f"{agent} {count}" for agent, count in tokens["agents"].items())
    tasks = ", ".join(f"{task} {count}" for task, count in tokens["tasks"].items())
    return [f"- Tokens: {agents} ({unmeasured} run{'' if unmeasured == 1 else 's'} unmeasured)",
            f"- Task tokens: {tasks or '-'}", ""]


def lines_line(metrics):
    lines = metrics.get("lines")
    if not lines or not lines["tasks"]:
        return []
    tasks = ", ".join(f"{task} {count}" for task, count in lines["tasks"].items())
    unmeasured = lines["unmeasured"]
    detail = f"fix and cleanup {round((lines['share'] or 0) * 100)}%"
    detail += f"; {unmeasured} dev run{'' if unmeasured == 1 else 's'} unmeasured" if unmeasured else ""
    return [f"- Lines changed: {tasks} ({detail})", ""]


def question_line(metrics):
    found = metrics.get("verdicts") or {}
    if not any(found.get(key) for key in ("needs_context", "blocked")):
        return []
    return [f"- Dev questions: {found.get('needs_context', 0)} needs-context, {found.get('blocked', 0)} blocked", ""]


def metrics_lines(metrics):
    if not metrics:
        return []
    lines = ["## Metrics", ""]
    for cycle in metrics["cycles"]:
        unsplit = cycle["open"] - cycle["critical"] - cycle["important"]
        rounds = cycle["fix_rounds"]
        lines.append(f"- Cycle {cycle['cycle']}: {cycle['critical']} Critical, {cycle['important']} Important, "
                     f"{cycle['minor']} Minor" + (f" (+{unsplit} blocking, unsplit)" if unsplit > 0 else "")
                     + f"; {rounds} fix round{'' if rounds == 1 else 's'}")
    for task, loop in (metrics.get("reviews") or {}).items():
        lines.append(f"- {task.capitalize()} review: {loop['rounds']} round{'' if loop['rounds'] == 1 else 's'}, "
                     f"{loop['critical']} Critical, {loop['important']} Important, {loop['minor']} Minor")
    origins = dict(metrics.get("origins") or {})
    if origins:
        unclassified = origins.pop("unclassified", 0)
        lines += ["", "Origins: " + ", ".join(f"{name} {count}" for name, count in origins.items())
                  + (f" (unclassified {unclassified})" if unclassified else "")]
    automated = sum(1 for lesson in metrics["lessons"] if lesson["check"])
    lines += ["", f"Lessons: {len(metrics['lessons'])} ({automated} automated)"]
    lines += [f"- {lesson['text']}" + (f" (check: {lesson['check']})" if lesson["check"] else "")
              for lesson in metrics["lessons"]]
    return lines + [""] + time_lines(metrics) + token_lines(metrics) + lines_line(metrics) + question_line(metrics)


def verdict(ok, detail):
    return "SKIP" if ok and detail else "PASS" if ok else "FAIL"


def tracked_changes():
    return set(git("status", "--porcelain", "--untracked-files=no")[1].splitlines())


def report_path(slug):
    return f"{REPORTS}/{datetime.date.today().isoformat()}-{slug}.md"


def write_report(slug, base, head, checks, ledger, changed, unrun, number=None):
    path = report_path(slug)
    os.makedirs(REPORTS, exist_ok=True)
    today = datetime.date.today().isoformat()
    code, log = git("log", "--format=- %h %s", f"{base}..HEAD")
    lines = [f"# {slug}", "", f"{today} · {base[:7]}..{head[:7]}" + (f" · v{number}" if number else ""), "",
             "## Checks", ""]
    lines += [f"- {name}: {verdict(ok, detail)}" for name, ok, detail in checks]
    lines += ["", "## Commits", "", log.strip() or "-", ""]
    if ledger:
        lines += ["## Ledger", "", f"Cycles: {ledger['cycle']}"]
        lines += ["Mode: autonomous"] if ledger.get("autonomous") else []
        lines += [f"- note: {text}" for text in ledger["notes"]]
        gates = ledger.get("gates") or []
        if gates:
            refused = [item for item in gates if item["verdict"] != "READY"]
            reasons = list(dict.fromkeys(name for item in refused for name in item["failed"]))
            lines += [f"- Gate runs: {len(gates)}" + (f" (NOT READY {len(refused)}: {', '.join(reasons)})" if refused
                                                       else "")]
        if ledger.get("validar"):
            lines += ["", "## VALIDAR", ""] + [f"- {item['id']} {item['text']} -> {item['decision'] or 'pending'}"
                                               for item in ledger["validar"]]
        if ledger.get("deferred"):
            lines += ["", "## Deferred", ""]
            lines += [f"- {item['id']} {item['text']} -> {item['decision']}" for item in ledger["deferred"]]
        lines += [""] + metrics_lines(ledger.get("metrics"))
    if unrun:
        lines += ["## Test lines not run", ""] + [f"- {label}" for label in unrun] + [""]
    if WARNINGS:
        lines += ["## Warnings", ""] + [f"- {text}" for text in dict.fromkeys(WARNINGS)] + [""]
    if changed:
        lines += ["## Comandos changed", "", "```diff"] + changed + ["```", ""]
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))
    git("add", path)
    return path


def drop_report(path, existed):
    if existed:
        git("checkout", "-q", "HEAD", "--", path)
        return
    git("rm", "-q", "--cached", "--force", "--", path)
    if os.path.exists(path):
        os.remove(path)
    try:
        os.rmdir(REPORTS)
    except OSError:
        pass


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base")
    parser.add_argument("--ledger", help="passed to ledger.py; by default it finds the ledger itself")
    parser.add_argument("--cmd", action="append", default=[], help="Name=command, adds or overrides a check")
    parser.add_argument("--report", metavar="SLUG")
    parser.add_argument("--criteria", metavar="TASK", help="trace only that task's criteria to tests, nothing else")
    args = parser.parse_args()

    ledger, problem = ledger_state(args.ledger)
    if args.criteria:
        if not ledger:
            sys.exit(problem or "no ledger")
        ok, detail = traceability(ledger.get("plan"), task=args.criteria)
        print(f"Criteria {args.criteria}: {'PASS' if ok else 'FAIL'}" + (f"\n    {detail}" if detail else ""))
        sys.exit(0 if ok else 1)
    if args.base:
        base = commit_of(args.base)
        if not base:
            sys.exit(f"--base {args.base} is not a commit")
    else:
        base = commit_of(ledger and ledger.get("base")) or default_base()
    head = git("rev-parse", "HEAD")[1].strip()
    if not base:
        sys.exit("cannot find the branch base; pass --base <default-branch>")
    checks = []

    pending = problem or ("; ".join(ledger["pending"]) if ledger["pending"] else "")
    checks.append(("Ledger", not pending, pending))

    if args.report and git("diff", "--cached", "--name-only", "--", report_path(args.report))[1].strip():
        warn(f"removing {report_path(args.report)}, a draft left by a gate run that did not finish")
        drop_report(report_path(args.report), git("cat-file", "-e", f"HEAD:{report_path(args.report)}")[0] == 0)
    dirty = git("status", "--porcelain")[1].strip()
    checks.append(("Clean tree", not dirty, dirty))
    checks.append(("Docs", *docs()))
    ok, detail, number = version(base)
    checks.append(("Version", ok, detail))

    commands = project_commands(args.cmd)
    if ledger:
        checks.append(("Criteria", *traceability(ledger.get("plan"), base)))
        checks.append(("Artifacts", *artifacts(ledger.get("plan"), ledger.get("slug"))))
        checks.append(("Reviewed", *reviewed(ledger)))
        checks.append(("Full suite", *full_suite(ledger, commands)))

    changed = comandos_change(base)
    if changed:
        print(f"warning: the Comandos section of CLAUDE.md changed in {base[:7]}..HEAD; the gate runs the branch's "
              "commands:\n    " + "\n    ".join(changed), flush=True)

    unrun = unrun_tests()
    for label in unrun:
        print(f'warning: the Comandos line "{label}" is not run by the gate: name it "Testes (<name>)" to run it',
              flush=True)

    draft = report_path(args.report) if args.report and not dirty else None
    if draft:
        existed = git("cat-file", "-e", f"HEAD:{draft}")[0] == 0
        write_report(args.report, base, head, checks, ledger, changed, unrun, number)
        git("add", draft)

    ready = False
    failed = [name for name, ok, _ in checks if not ok]
    try:
        before = tracked_changes()
        shell, seconds, prefix = bash(), time_limit(), environment()
        if not shell and not failed:
            warn("no Git Bash found; the commands run in cmd.exe")
        for name in ORDER + [name for name in commands if name not in ORDER]:
            if failed and name in commands:
                checks.append((name, False, f"not run: {', '.join(failed)} failed, and the run would end NOT READY"))
                continue
            if name not in commands:
                checks.append((name, name != "Testes", "not configured in CLAUDE.md (Comandos)"))
                continue
            print(f"running {name}: {commands[name]}", flush=True)
            ok, tail = run_command(f"{prefix} && {commands[name]}" if prefix else commands[name], shell, seconds)
            checks.append((name, ok, "" if ok else tail))
        moved = sorted(line for line in tracked_changes() ^ before if not line.endswith(draft or "\0"))
        checks.append(("Unchanged", not moved, "\n".join(moved)))

        findings = secret_findings(base)
        checks.append(("Secrets", not findings, "\n".join(findings)))

        ready = all(ok for _, ok, _ in checks)
        if ledger:
            failed = [name for name, ok, _ in checks if not ok]
            subprocess.run([sys.executable, os.path.join(HERE, "ledger.py"), *(["--ledger", args.ledger] if args.ledger
                            else []), "gate", "--verdict", "READY" if ready else "NOT_READY", "--failed", ",".join(failed)],
                           capture_output=True)
            ledger.setdefault("gates", []).append({"verdict": "READY" if ready else "NOT_READY", "failed": failed})
        width = max([12] + [len(name) + 2 for name, _, _ in checks])
        print(f"\nGATE {base[:7]}..{head[:7]}" + (f" v{number}" if number else ""))
        for name, ok, detail in checks:
            print(f"{name + ':':{width}}{verdict(ok, detail)}"
                  + ("\n    " + detail.replace("\n", "\n    ") if detail else ""))
        print("Overall:    READY" if ready else "Overall:    NOT READY")
    finally:
        if draft and ready:
            write_report(args.report, base, head, checks, ledger, changed, unrun, number)
            git("add", draft)
            print(f"report staged: {draft}")
        elif draft:
            drop_report(draft, existed)
    sys.exit(0 if ready else 1)


if __name__ == "__main__":
    main()
