#!/usr/bin/env python3
"""Local gate: the last check before anything leaves the machine. Deterministic, no agent.

  gate.py [--base <rev>] [--ledger <path>] [--cmd Name=command ...] [--report <slug>]

Checks, in order: nothing is pending in the ledger (the current cycle is closed and every deferred item has a final
decision); the tree is clean; every acceptance-criterion id of the plan recorded in the ledger (tokens like AC-T3-2)
appears in a tracked test file (the globs on the "Arquivos de teste" line of the CLAUDE.md "Comandos" section,
space-separated globs where * and ? stay within one folder, **/ matches zero or more folders and {a,b} is either; an
invalid glob, or one that matches no tracked file, prints a warning; without that line, every tracked file that is
not Markdown); no commit after the head of the ledger's latest reviewer run changes anything but the plan,
docs/lessons.md, docs/quality-reports/ or the user's .pipeline-secrets-allow (first-parent commits only, so a merged
front is not counted, and tasks are integrated by fast-forward or cherry-pick);
every command of that section passes (lines like "- Testes: `<command>`"; Build, Typecheck, Lint, Testes and the
optional Auditoria are run, a second line of the same kind runs too under its own label, such as "Testes (e2e)", a
blank command counts as not configured, and --cmd adds or overrides one, or with no command removes it); the
commands changed no tracked file; and no secret or .env file is added anywhere in <base>..HEAD, the whole history
that a push would send. A check that does not apply is SKIP with the reason; only Testes is required. When the
"Comandos" section differs from the one at <base>, the gate prints the difference as a warning (and the report
shows it) and still runs the branch's commands. Prints READY or NOT READY and exits 0 or 1.

<base> is --base (an error when it is not a commit), or else the base the ledger recorded at start, or else the
merge base with the default branch. With --report, the gate writes and stages docs/quality-reports/<date>-<slug>.md
(checks, commits, ledger mode and notes, the VALIDAR list with the user's decision on each, deferred decisions, a
changed "Comandos" section and the delivery metrics: findings per cycle and origin, fix rounds, time per cycle, task
and agent, tokens per agent and task, lessons added and automated) before running the commands, so the project's own tests check it too; READY rewrites its check lines,
NOT READY removes it, and a draft of the same report left staged by a run that was killed is removed first."""
import argparse
import datetime
import difflib
import importlib.util
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCANNER = os.path.join(HERE, "..", "..", "hooks", "pre-commit-secret-scan.py")
COMMANDS = {"build": "Build", "typecheck": "Typecheck", "tipos": "Typecheck", "lint": "Lint", "testes": "Testes",
            "tests": "Testes", "test": "Testes", "auditoria": "Auditoria", "audit": "Auditoria"}
ORDER = ["Build", "Typecheck", "Lint", "Testes", "Auditoria"]
TEST_FILES = "arquivos de teste"
CRITERION = re.compile(r"(?<![\w-])AC-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*")
TIMEOUT = 900
REPORTS = "docs/quality-reports"
LESSONS = "docs/lessons.md"
SECRETS_ALLOW = ".pipeline-secrets-allow"


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


def comandos_change(base):
    code, old = git("show", f"{base}:CLAUDE.md")
    before = comandos_section(old if code == 0 else "").strip().splitlines()
    after = comandos_section(claude_md()).strip().splitlines()
    return list(difflib.unified_diff(before, after, f"{base[:7]}:CLAUDE.md", "CLAUDE.md", lineterm=""))


def run_command(command):
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=TIMEOUT)
        output = (result.stdout + result.stderr).strip().splitlines()
        return result.returncode == 0, "\n".join(output[-15:])
    except subprocess.TimeoutExpired:
        return False, f"timed out after {TIMEOUT}s"


def secret_findings(base):
    spec = importlib.util.spec_from_file_location("secretscan", SCANNER)
    scanner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scanner)
    cwd = os.getcwd()
    diff = scanner.git_checked(["log", "-p", "--diff-merges=separate", "--no-ext-diff", "--no-textconv", "--text",
                                "--format=", f"{base}..HEAD", "--"] + scanner.EXCLUDES, cwd)
    names = scanner.git_checked(["log", "--name-only", "-z", "--diff-merges=separate", "--diff-filter=d", "--format=",
                                 f"{base}..HEAD"], cwd)
    return scanner.scan(diff, scanner.names(names), scanner.load_allowlist(cwd, "HEAD"))


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


def traceability(plan):
    if not plan:
        return True, "no plan in the ledger (small work has none; otherwise record it with ledger.py plan --path)"
    if not os.path.exists(plan):
        return False, f"plan not found: {plan}"
    ids = sorted(set(CRITERION.findall(open(plan, encoding="utf-8").read())))
    if not ids:
        return False, f"{plan} lists no acceptance-criterion ids (AC-...)"
    globs = next((value.split() for label, value in comandos() if label_key(label) == TEST_FILES), None)
    names = [name for name in git("ls-files", "-z")[1].split("\0") if name and os.path.isfile(name)]
    if globs:
        tracked, names = names, []
        for pattern in globs:
            try:
                regex = glob_regex(pattern)
            except re.error:
                print(f"warning: invalid test glob '{pattern}' (Arquivos de teste in CLAUDE.md)", flush=True)
                continue
            matched = [name for name in tracked if regex.match(name)]
            if not matched:
                print(f"warning: test glob '{pattern}' matches no tracked file (Arquivos de teste in CLAUDE.md)",
                      flush=True)
            names += [name for name in matched if name not in names]
    else:
        names = [name for name in names if not name.lower().endswith(".md")]
    found = set()
    for name in names:
        if os.path.getsize(name) < 2_000_000:
            found.update(CRITERION.findall(open(name, encoding="utf-8", errors="ignore").read()))
    missing = [item for item in ids if item not in found]
    return not missing, ("criteria with no test: " + ", ".join(missing)) if missing else ""


def reviewed(ledger):
    reviews = (ledger or {}).get("reviewer") or []
    head = reviews[0].get("head") if reviews else ""
    if not head:
        return True, "no reviewer head in the ledger"
    if git("merge-base", "--is-ancestor", head, "HEAD")[0] != 0:
        return False, f"the reviewed head {head[:7]} is not in this history: run the reviewer on the current head"
    plan = ledger.get("plan") or ""
    if os.path.isabs(plan):
        plan = os.path.relpath(plan, git("rev-parse", "--show-toplevel")[1].strip())
    plan = plan.replace("\\", "/").removeprefix("./")
    out = git("log", "--first-parent", "--no-merges", "-z", "--name-only", "--format=", f"{head}..HEAD")[1]
    changed = sorted({name.strip("\n") for name in out.split("\0")} - {"", plan, LESSONS, SECRETS_ALLOW})
    changed = [name for name in changed if not name.startswith(REPORTS + "/")]
    return not changed, (f"changed after the reviewed head {head[:7]} with no review: " + ", ".join(changed)
                         if changed else "")


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
    origins = dict(metrics.get("origins") or {})
    if origins:
        unclassified = origins.pop("unclassified", 0)
        lines += ["", "Origins: " + ", ".join(f"{name} {count}" for name, count in origins.items())
                  + (f" (unclassified {unclassified})" if unclassified else "")]
    automated = sum(1 for lesson in metrics["lessons"] if lesson["check"])
    lines += ["", f"Lessons: {len(metrics['lessons'])} ({automated} automated)"]
    lines += [f"- {lesson['text']}" + (f" (check: {lesson['check']})" if lesson["check"] else "")
              for lesson in metrics["lessons"]]
    return lines + [""] + time_lines(metrics) + token_lines(metrics)


def verdict(ok, detail):
    return "SKIP" if ok and detail else "PASS" if ok else "FAIL"


def tracked_changes():
    return set(git("status", "--porcelain", "--untracked-files=no")[1].splitlines())


def report_path(slug):
    return f"{REPORTS}/{datetime.date.today().isoformat()}-{slug}.md"


def write_report(slug, base, head, checks, ledger, changed):
    path = report_path(slug)
    os.makedirs(REPORTS, exist_ok=True)
    today = datetime.date.today().isoformat()
    code, log = git("log", "--format=- %h %s", f"{base}..HEAD")
    lines = [f"# {slug}", "", f"{today} · {base[:7]}..{head[:7]}", "", "## Checks", ""]
    lines += [f"- {name}: {verdict(ok, detail)}" for name, ok, detail in checks]
    lines += ["", "## Commits", "", log.strip() or "-", ""]
    if ledger:
        lines += ["## Ledger", "", f"Cycles: {ledger['cycle']}"]
        lines += ["Mode: autonomous"] if ledger.get("autonomous") else []
        lines += [f"- note: {text}" for text in ledger["notes"]]
        if ledger.get("validar"):
            lines += ["", "## VALIDAR", ""] + [f"- {item['id']} {item['text']} -> {item['decision'] or 'pending'}"
                                               for item in ledger["validar"]]
        if ledger.get("deferred"):
            lines += ["", "## Deferred", ""]
            lines += [f"- {item['id']} {item['text']} -> {item['decision']}" for item in ledger["deferred"]]
        lines += [""] + metrics_lines(ledger.get("metrics"))
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
    args = parser.parse_args()

    ledger, problem = ledger_state(args.ledger)
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
        print(f"warning: removing {report_path(args.report)}, a draft left by a gate run that did not finish", flush=True)
        drop_report(report_path(args.report), git("cat-file", "-e", f"HEAD:{report_path(args.report)}")[0] == 0)
    dirty = git("status", "--porcelain")[1].strip()
    checks.append(("Clean tree", not dirty, dirty))

    if ledger:
        checks.append(("Criteria", *traceability(ledger.get("plan"))))
        checks.append(("Reviewed", *reviewed(ledger)))

    changed = comandos_change(base)
    if changed:
        print(f"warning: the Comandos section of CLAUDE.md changed in {base[:7]}..HEAD; the gate runs the branch's "
              "commands:\n    " + "\n    ".join(changed), flush=True)

    draft = report_path(args.report) if args.report and not dirty else None
    if draft:
        existed = git("cat-file", "-e", f"HEAD:{draft}")[0] == 0
        write_report(args.report, base, head, checks, ledger, changed)
        git("add", draft)

    ready = False
    try:
        before = tracked_changes()
        commands = project_commands(args.cmd)
        for name in ORDER + [name for name in commands if name not in ORDER]:
            if name not in commands:
                checks.append((name, name != "Testes", "not configured in CLAUDE.md (Comandos)"))
                continue
            print(f"running {name}: {commands[name]}", flush=True)
            ok, tail = run_command(commands[name])
            checks.append((name, ok, "" if ok else tail))
        moved = sorted(line for line in tracked_changes() ^ before if not line.endswith(draft or "\0"))
        checks.append(("Unchanged", not moved, "\n".join(moved)))

        findings = secret_findings(base)
        checks.append(("Secrets", not findings, "\n".join(findings)))

        ready = all(ok for _, ok, _ in checks)
        width = max([12] + [len(name) + 2 for name, _, _ in checks])
        print(f"\nGATE {base[:7]}..{head[:7]}")
        for name, ok, detail in checks:
            print(f"{name + ':':{width}}{verdict(ok, detail)}"
                  + ("\n    " + detail.replace("\n", "\n    ") if detail else ""))
        print("Overall:    READY" if ready else "Overall:    NOT READY")
    finally:
        if draft and ready:
            write_report(args.report, base, head, checks, ledger, changed)
            git("add", draft)
            print(f"report staged: {draft}")
        elif draft:
            drop_report(draft, existed)
    sys.exit(0 if ready else 1)


if __name__ == "__main__":
    main()
