#!/usr/bin/env python3
"""SessionStart hook (matcher compact|resume, see hooks.json): hands the manager its place back.

After a compaction or a resumed session the manager has lost the thread of the delivery. When the project has
.superpowers/ledger.jsonl, this prints `ledger.py status` (plain stdout from SessionStart goes into Claude's
context). Without a ledger it prints nothing and exits 0; any failure also exits 0, so a session never breaks."""
import json
import os
import subprocess
import sys

LEDGER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "manager", "ledger.py")


def main():
    try:
        payload = json.load(sys.stdin)
        project = payload.get("cwd") if isinstance(payload, dict) else None
    except ValueError:
        project = None
    project = project or os.getcwd()
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
