#!/usr/bin/env python3
"""SessionStart hook (every session start, see hooks.json): hands the manager its place back, and keeps the native
secret-scan hook pointed at the running plugin.

After a compaction or a resumed session the manager has lost the thread of the delivery. When the project has
.superpowers/ledger.jsonl, this prints `ledger.py status` (plain stdout from SessionStart goes into Claude's
context); a new or cleared session prints nothing.

The native pre-commit hook finds the scanner through `git config pipeline.home`, and an installed plugin lives in a
folder per version: in a repository whose pre-commit hook is the plugin's, each session start sets the repository's
pipeline.home to the running plugin's folder when it names another one, so no clone of the plugin is needed and an
update never leaves every commit blocked. Without a ledger or a git repository it does nothing; any failure exits 0,
so a session never breaks."""
import json
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
LEDGER = os.path.join(ROOT, "skills", "manager", "ledger.py")
MARKER = "secretscan-managed"


def git(project, *args):
    done = subprocess.run(["git", *args], cwd=project, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    return done.stdout.strip() if done.returncode == 0 else ""


def point_home(project):
    hook = git(project, "rev-parse", "--path-format=absolute", "--git-path", "hooks/pre-commit")
    try:
        with open(hook, encoding="utf-8", errors="replace") as handle:
            if MARKER not in handle.read():
                return
    except OSError:
        return
    root = ROOT.replace("\\", "/")
    current = git(project, "config", "--get", "pipeline.home").replace("\\", "/").rstrip("/")
    if os.path.normcase(current) != os.path.normcase(root):
        git(project, "config", "--local", "pipeline.home", root)


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}
    payload = payload if isinstance(payload, dict) else {}
    project = payload.get("cwd") or os.getcwd()
    point_home(project)
    if payload.get("source") in ("startup", "clear"):
        return
    if not os.path.isfile(os.path.join(project, ".superpowers", "ledger.jsonl")):
        return
    done = subprocess.run([sys.executable, LEDGER, "status"], cwd=project, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if done.returncode == 0 and done.stdout.strip():
        sys.stdout.reconfigure(encoding="utf-8")
        print("Delivery ledger (resumed session), `ledger.py status`:\n" + done.stdout, end="")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
