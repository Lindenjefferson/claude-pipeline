#!/usr/bin/env python3
"""Local gate: the last check before anything leaves the machine. Deterministic, no agent.

  gate.py [--base <rev>] [--ledger <path>] [--cmd Name=command ...] [--report <slug>]

Checks, in order: the ledger's current cycle is closed, the tree is clean, every command in the "Comandos"
section of CLAUDE.md passes (lines like "- Testes: `npm test`"; Build, Typecheck, Lint and Testes are run, and
--cmd adds or overrides one), and no secret or .env file is added anywhere in <base>..HEAD, the whole history
that a push would send. Prints READY or NOT READY and exits 0 or 1. With --report and READY, writes
docs/quality-reports/<date>-<slug>.md and stages it."""
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
            "tests": "Testes", "test": "Testes"}
ORDER = ["Build", "Typecheck", "Lint", "Testes"]
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


def project_commands(overrides):
    commands = {}
    if os.path.exists("CLAUDE.md"):
        text = open("CLAUDE.md", encoding="utf-8").read()
        section = re.search(r"(?ms)^##\s+Comandos\s*$(.*?)(?=^##\s|\Z)", text)
        for label, command in re.findall(r"(?m)^\s*[-*]\s*([^:\n]+):\s*`([^`]+)`", section.group(1) if section else ""):
            name = COMMANDS.get(label.strip().lower())
            if name:
                commands[name] = command.strip()
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


def ledger_state(path):
    result = subprocess.run([sys.executable, os.path.join(HERE, "ledger.py"), "--ledger", path, "status", "--json"],
                            capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        return None, result.stderr.strip() or "no ledger"
    return json.loads(result.stdout), None


def write_report(slug, base, head, checks, ledger):
    folder = os.path.join("docs", "quality-reports")
    os.makedirs(folder, exist_ok=True)
    today = datetime.date.today().isoformat()
    path = os.path.join(folder, f"{today}-{slug}.md")
    code, log = git("log", "--format=- %h %s", f"{base}..HEAD")
    lines = [f"# {slug}", "", f"{today} · {base[:7]}..{head[:7]}", "", "## Checks", ""]
    lines += [f"- {name}: {'PASS' if ok else 'FAIL'}" for name, ok, _ in checks]
    lines += ["", "## Commits", "", log.strip() or "-", ""]
    if ledger:
        lines += ["## Ledger", "", f"Cycles: {ledger['cycle']}"]
        lines += [f"- note: {text}" for text in ledger["notes"]]
        lines.append("")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))
    git("add", path)
    return path


def main():
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
        verdict = "SKIP" if ok and detail.startswith("not configured") else "PASS" if ok else "FAIL"
        print(f"{name + ':':12}{verdict}" + ("\n    " + detail.replace("\n", "\n    ") if detail else ""))
    print("Overall:    READY" if ready else "Overall:    NOT READY")
    if ready and args.report:
        print(f"report staged: {write_report(args.report, base, head, checks, ledger)}")
    sys.exit(0 if ready else 1)


if __name__ == "__main__":
    main()
