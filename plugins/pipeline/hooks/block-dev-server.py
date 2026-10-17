#!/usr/bin/env python3
"""PreToolUse hook (matcher Bash, see hooks.json): denies the project's dev server outside background mode.

A dev server run in the foreground never returns: the call hangs, and the process is orphaned when it times out.
The command comes from the project's CLAUDE.md, the line `- Rodar em desenvolvimento: `<command>`` under
"Comandos" (the same lines gate.py reads); the plugin knows no stack. Without a CLAUDE.md found from the session's
directory upwards, or without that line holding a command in backticks, it does nothing.

Denied: a Bash call without run_in_background whose command contains the dev command at the start of a shell
segment (after &&, ||, ;, |, a newline, an opening parenthesis or env assignments), alone or followed by arguments;
`npm run dev &` counts too, because the shell leaves the same orphan. Text the shell only passes along is not
read: quoted strings (a commit message) and heredoc bodies (a file being written), unless a shell reads the
heredoc (`bash <<EOF`). The reason names the right form. Any failure of the hook itself lets the call through."""
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "..", "skills", "manager", "gate.py")
LABEL = "rodar em desenvolvimento"


def dev_command(start):
    spec = importlib.util.spec_from_file_location("pipeline_gate", GATE)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    folder = os.path.abspath(start)
    while True:
        if os.path.isfile(os.path.join(folder, "CLAUDE.md")):
            os.chdir(folder)
            for label, command in gate.comandos():
                if gate.label_key(label) == LABEL:
                    return command
        parent = os.path.dirname(folder)
        if parent == folder:
            return None
        folder = parent


HEREDOC = re.compile(r"(?P<head>[^\n]*?)(?<!<)<<(?!<)-?\s*(['\"]?)(?P<tag>\w+)\2[^\n]*\n(?P<body>.*?)"
                     r"(?:\n[ \t]*(?P=tag)[ \t]*(?=\n|$)|\Z)", re.S)
SHELL_INPUT = re.compile(r"(?:^|[\s;&|(])(?:ba|z|da)?sh(?:\s+-\w+)*\s*$")
QUOTED = re.compile(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"")


def executed(command):
    """The command without the text the shell only passes along: heredoc bodies (unless a shell reads them) and
    quoted strings, so a message or a file that mentions the dev command is not taken for running it."""
    def heredoc(match):
        text = match.group(0)
        return text if SHELL_INPUT.search(match.group("head")) else text.replace(match.group("body"), "", 1)
    return QUOTED.sub("''", HEREDOC.sub(heredoc, command))


def runs_it(command, dev):
    words = r"\s+".join(re.escape(word) for word in dev.split())
    return re.search(r"(?:^|&&|\|\||[;|\n(])\s*(?:[A-Za-z_]\w*=\S*\s+)*" + words + r"(?=\s|$|[;&|)])",
                     executed(command)) is not None


def main():
    payload = json.load(sys.stdin)
    if payload.get("tool_name") != "Bash":
        return
    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command") or ""
    if tool_input.get("run_in_background"):
        return
    dev = dev_command(payload.get("cwd") or os.getcwd())
    if not dev or not runs_it(command, dev):
        return
    reason = (f"`{dev}` is this project's dev server and never returns, so in the foreground it hangs the call and "
              "leaves an orphan process. Run the same command with the Bash tool's run_in_background set to true "
              "(and stop it before you finish), or reuse a server already running for this directory.")
    json.dump({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                      "permissionDecisionReason": reason}}, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
