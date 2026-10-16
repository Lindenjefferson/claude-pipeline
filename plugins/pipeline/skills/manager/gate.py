#!/usr/bin/env python3
"""Local gate: the last check before anything leaves the machine. Deterministic, no agent.

  gate.py [--base <rev>] [--ledger <path>] [--cmd Name=command ...] [--report <slug>]

Checks, in order: nothing is pending in the ledger (the current cycle is closed and every deferred item has a final
decision); the tree is clean; every acceptance-criterion id of the plan recorded in the ledger (tokens like AC-T3-2)
appears in a tracked test file (the globs on the "Arquivos de teste" line of the CLAUDE.md "Comandos" section,
space-separated globs where * and ? stay within one folder, **/ matches zero or more folders and {a,b} is either; a
glob that matches no tracked file prints a warning; without that line, every tracked file that is not Markdown);
every command of that
section passes (lines like "- Testes: `<command>`", a parenthetical after the label ignored; Build, Typecheck, Lint,
Testes and the optional Auditoria are run, and --cmd adds or overrides one); and no secret or .env file is added
anywhere in <base>..HEAD, the whole history that a push would send. A check that does not apply is SKIP with the reason; only Testes is required. Prints READY or
NOT READY and exits 0 or 1. With --report and READY, writes docs/quality-reports/<date>-<slug>.md (checks, commits,
ledger notes, deferred decisions and the delivery metrics: findings per cycle and origin, fix rounds, time per cycle,
task and agent, lessons added and automated) and stages it."""
import argparse
import datetime
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


def git(*args):
    result = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return result.returncode, result.stdout


def default_base():
    for ref in ("origin/HEAD", "origin/main", "origin/master", "main", "master"):
        code, out = git("merge-base", "HEAD", ref)
        if code == 0 and out.strip():
            return out.strip()
    return None


def comandos():
    if not os.path.exists("CLAUDE.md"):
        return []
    text = open("CLAUDE.md", encoding="utf-8").read()
    section = re.search(r"(?ms)^##\s+Comandos\s*$(.*?)(?=^##\s|\Z)", text)
    return [(re.sub(r"\s*\(.*\)$", "", label.strip()).lower(), value.strip())
            for label, value in re.findall(r"(?m)^\s*[-*]\s*([^:\n]+):\s*`([^`]+)`", section.group(1) if section else "")]


def project_commands(overrides):
    commands = {}
    for label, command in comandos():
        if label in COMMANDS:
            commands[COMMANDS[label]] = command
    for item in overrides:
        name, _, command = item.partition("=")
        commands[COMMANDS.get(name.strip().lower(), name.strip())] = command.strip()
    return commands


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
    diff = scanner.git_checked(["log", "-p", "-m", "--no-ext-diff", "--no-textconv", "--text", "--format=",
                                f"{base}..HEAD", "--"] + scanner.EXCLUDES, cwd)
    names = scanner.git_checked(["log", "--name-only", "-m", "--format=", f"{base}..HEAD"], cwd)
    return scanner.scan(diff, sorted(set(names.split())), scanner.load_allowlist(cwd, "HEAD"))


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
        return True, "no plan in the ledger (start --plan)"
    if not os.path.exists(plan):
        return False, f"plan not found: {plan}"
    ids = sorted(set(CRITERION.findall(open(plan, encoding="utf-8").read())))
    if not ids:
        return False, f"{plan} lists no acceptance-criterion ids (AC-...)"
    globs = next((value.split() for label, value in comandos() if label == TEST_FILES), None)
    names = [name for name in git("ls-files", "-z")[1].split("\0") if name and os.path.isfile(name)]
    if globs:
        tracked, names = names, []
        for pattern in globs:
            matched = [name for name in tracked if glob_regex(pattern).match(name)]
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


def ledger_state(path):
    result = subprocess.run([sys.executable, os.path.join(HERE, "ledger.py"), "--ledger", path, "status", "--json"],
                            capture_output=True, text=True, encoding="utf-8")
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
    return lines + [""] + time_lines(metrics)


def verdict(ok, detail):
    return "SKIP" if ok and detail else "PASS" if ok else "FAIL"


def write_report(slug, base, head, checks, ledger):
    folder = os.path.join("docs", "quality-reports")
    os.makedirs(folder, exist_ok=True)
    today = datetime.date.today().isoformat()
    path = os.path.join(folder, f"{today}-{slug}.md")
    code, log = git("log", "--format=- %h %s", f"{base}..HEAD")
    lines = [f"# {slug}", "", f"{today} · {base[:7]}..{head[:7]}", "", "## Checks", ""]
    lines += [f"- {name}: {verdict(ok, detail)}" for name, ok, detail in checks]
    lines += ["", "## Commits", "", log.strip() or "-", ""]
    if ledger:
        lines += ["## Ledger", "", f"Cycles: {ledger['cycle']}"]
        lines += [f"- note: {text}" for text in ledger["notes"]]
        if ledger.get("deferred"):
            lines += ["", "## Deferred", ""]
            lines += [f"- {item['id']} {item['text']} -> {item['decision']}" for item in ledger["deferred"]]
        lines += [""] + metrics_lines(ledger.get("metrics"))
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))
    git("add", path)
    return path


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base")
    parser.add_argument("--ledger", default=".superpowers/ledger.jsonl")
    parser.add_argument("--cmd", action="append", default=[], help="Name=command, adds or overrides a check")
    parser.add_argument("--report", metavar="SLUG")
    args = parser.parse_args()

    base = args.base and git("rev-parse", "--verify", "--quiet", args.base + "^{commit}")[1].strip() or default_base()
    head = git("rev-parse", "HEAD")[1].strip()
    if not base:
        sys.exit("cannot find the branch base; pass --base <default-branch>")
    checks = []

    ledger, problem = ledger_state(args.ledger)
    pending = problem or ("; ".join(ledger["pending"]) if ledger["pending"] else "")
    checks.append(("Ledger", not pending, pending))

    dirty = git("status", "--porcelain")[1].strip()
    checks.append(("Clean tree", not dirty, dirty))

    if ledger:
        checks.append(("Criteria", *traceability(ledger.get("plan"))))

    commands = project_commands(args.cmd)
    for name in ORDER + [name for name in commands if name not in ORDER]:
        if name not in commands:
            checks.append((name, name != "Testes", "not configured in CLAUDE.md (Comandos)"))
            continue
        print(f"running {name}: {commands[name]}", flush=True)
        ok, tail = run_command(commands[name])
        checks.append((name, ok, "" if ok else tail))

    findings = secret_findings(base)
    checks.append(("Secrets", not findings, "\n".join(findings)))

    ready = all(ok for _, ok, _ in checks)
    print(f"\nGATE {base[:7]}..{head[:7]}")
    for name, ok, detail in checks:
        print(f"{name + ':':12}{verdict(ok, detail)}" + ("\n    " + detail.replace("\n", "\n    ") if detail else ""))
    print("Overall:    READY" if ready else "Overall:    NOT READY")
    if ready and args.report:
        print(f"report staged: {write_report(args.report, base, head, checks, ledger)}")
    sys.exit(0 if ready else 1)


if __name__ == "__main__":
    main()
