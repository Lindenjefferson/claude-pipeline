#!/usr/bin/env python3
import json
import os
import re
import sys
import time

PIPELINE_AGENTS = ("dev", "db", "docs", "qa", "security", "audit", "design", "code-review", "gate", "discovery")
AGENT_PREFIXES = ("plugin:pipeline:", "pipeline:")
LEDGER_LINE = re.compile(r"^[\s`>*-]*LEDGER\s*(\{.*\})", re.MULTILINE)
INBOX = os.path.join(".superpowers", "reports", "inbox")


def pipeline_agent(agent_type):
    for prefix in AGENT_PREFIXES:
        if agent_type.startswith(prefix):
            name = agent_type[len(prefix):]
            return name if name in PIPELINE_AGENTS else None
    return agent_type if agent_type in PIPELINE_AGENTS else None


def transcript_text(path):
    text = None
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            message = entry.get("message") if isinstance(entry, dict) else None
            if not isinstance(message, dict) or message.get("role", entry.get("type")) != "assistant":
                continue
            content = message.get("content")
            if isinstance(content, str):
                parts = [content]
            else:
                parts = [block.get("text", "") for block in content or ()
                         if isinstance(block, dict) and block.get("type") == "text"]
            joined = "\n".join(part for part in parts if part)
            if joined.strip():
                text = joined
    return text


def final_message(payload):
    text = payload.get("last_assistant_message")
    if isinstance(text, str) and text.strip():
        return text
    path = payload.get("agent_transcript_path")
    return transcript_text(path) if isinstance(path, str) and os.path.isfile(path) else None


def ledger_matches(text, agent):
    lines = LEDGER_LINE.findall(text)
    if not lines:
        return False
    try:
        declared = json.loads(lines[-1]).get("agent")
    except (ValueError, AttributeError):
        return True
    return declared in (None, agent)


def project_root(cwd):
    current = os.path.abspath(cwd)
    while True:
        if os.path.isdir(os.path.join(current, ".superpowers")):
            return current
        parent = os.path.dirname(current)
        if os.path.exists(os.path.join(current, ".git")) or parent == current:
            return None
        current = parent


def write_new(directory, stem, text):
    os.makedirs(directory, exist_ok=True)
    for attempt in range(1, 100):
        path = os.path.join(directory, f"{stem}{'' if attempt == 1 else f'.{attempt}'}.md")
        try:
            with open(path, "x", encoding="utf-8", newline="") as handle:
                handle.write(text)
            return path
        except FileExistsError:
            continue
    return None


def capture(payload):
    agent = pipeline_agent(str(payload.get("agent_type") or ""))
    cwd = payload.get("cwd") or os.getcwd()
    if not agent or not isinstance(cwd, str):
        return None
    text = final_message(payload)
    if not text or not ledger_matches(text, agent):
        return None
    root = project_root(cwd)
    if not root:
        return None
    short_id = re.sub(r"[^A-Za-z0-9]", "", str(payload.get("agent_id") or ""))[-8:] or "noid"
    stem = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{agent}-{short_id}"
    path = write_new(os.path.join(root, INBOX), stem, text)
    return (agent, os.path.relpath(path, root).replace("\\", "/")) if path else None


def main():
    try:
        saved = capture(json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace")))
    except Exception:
        saved = None
    if saved:
        agent, path = saved
        context = (f"pipeline: the final report of {agent} was saved verbatim to {path}. Record it with "
                   f"ledger.py save-report --from-inbox {path} --task <id> [--from <sha>] instead of "
                   f"transcribing it.")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SubagentStop", "additionalContext": context}}))
    sys.exit(0)


if __name__ == "__main__":
    main()
