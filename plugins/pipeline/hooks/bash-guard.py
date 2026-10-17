#!/usr/bin/env python3
"""PreToolUse hook (matcher Bash, see hooks.json): denies skipping the secret-scan pre-commit hook, and the
project's dev server outside background mode.

Skipping the hook is denied in any project, in the foreground or background: a git commit with --no-verify (or an
unambiguous prefix such as --no-veri) or -n (also inside a cluster such as -nm or -an), a git -c or --config-env
that sets core.hooksPath, a GIT_CONFIG_* assignment naming it (also through env or export), and a git config that
writes or unsets it. The command is read word by word as the shell splits it, after the heredoc bodies the shell
only passes along are removed, so a flag quoted inside a commit message is a message, not a flag. Wrappers such as
env, command, time, nohup, xargs, `!`, `{` and if/then are looked through; a command given to a shell's -c (also
-lc) or to eval is read the same way, and so is a command substitution outside quotes; one inside double quotes is
not read. Permission rules match the command as plain text and cannot tell a flag from a message, which is why this
check lives here. A command that does not parse (an unbalanced quote) passes, since the shell refuses it too.

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
import shlex
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


HEREDOC = re.compile(r"^(?P<head>[^\n]*?)(?<!<)<<(?!<)-?\s*\\?(['\"]?)(?P<tag>[\w.-]+)\2[^\n]*\n(?P<body>.*?)"
                     r"(?:\n[ \t]*(?P=tag)[ \t]*(?=\n|$)|\Z)", re.S | re.M)
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


SHELLS = {"sh", "bash", "zsh", "dash"}
WRAPPERS = {"env", "command", "time", "nohup", "exec", "xargs", "!", "{", "if", "then", "else", "elif", "do", "while",
            "until"}
CONFIG_READS = {"--get", "--get-all", "--get-regexp", "--list", "-l", "get", "list"}
CONFIG_UNSETS = {"--unset", "--unset-all", "unset"}
COMMIT_VALUE = set("mFCct")
COMMIT_ATTACHED = set("uS")
COMMIT_LONG_VALUE = {"--message", "--file", "--author", "--date", "--reuse-message", "--reedit-message", "--template",
                     "--fixup", "--squash", "--cleanup", "--trailer", "--pathspec-from-file"}


def segments(command, commenters=""):
    """Each simple command as its words, quotes resolved, with heredoc bodies the shell only passes along removed."""
    text = HEREDOC.sub(lambda match: match.group(0) if SHELL_INPUT.search(match.group("head"))
                       else match.group(0).replace(match.group("body"), "", 1), command)
    lexer = shlex.shlex(re.sub(r"[<>]&|&>", ">", text), posix=True, punctuation_chars=";&|()\n")
    lexer.whitespace, lexer.whitespace_split, lexer.commenters = " \t\r", True, commenters
    found, words = [], []
    for token in lexer:
        if token and set(token) <= set(";&|()\n"):
            if words:
                found.append(words)
            words = []
        else:
            words.append(token)
    return found + [words] if words else found


def hooks_path(key):
    return key.split("=", 1)[0].lower() == "core.hookspath"


def skips_hook(command):
    """True when the command skips the pre-commit hook. A '#' is read as text first (it starts a comment only at
    the start of a word, which shlex cannot tell); a command that does not parse that way is read again with '#'
    as a comment, and one that parses neither way passes."""
    try:
        parsed = segments(command)
    except ValueError:
        try:
            parsed = segments(command, "#")
        except ValueError:
            return False
    for words in parsed:
        if any(re.fullmatch(r"GIT_CONFIG\w*=.*", word) and "core.hookspath" in word.lower() for word in words):
            return True
        while words and (words[0] in WRAPPERS or re.fullmatch(r"[A-Za-z_]\w*=.*", words[0])
                         or (words[0].startswith("-") and len(words) > 1)):
            words = words[1:]
        if not words:
            continue
        program = re.split(r"[\\/]", words[0])[-1].lower()
        if program in SHELLS:
            for position, word in enumerate(words[1:-1], 1):
                if not word.startswith("-"):
                    break
                if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", word):
                    if skips_hook(words[position + 1]):
                        return True
                    break
            continue
        if program == "eval":
            if skips_hook(" ".join(words[1:])):
                return True
            continue
        if program not in ("git", "git.exe"):
            continue
        rest = words[1:]
        while rest and rest[0].startswith("-"):
            option, _, attached = rest[0].partition("=")
            if option in ("-c", "--config-env"):
                if hooks_path(attached or (rest[1] if len(rest) > 1 else "")):
                    return True
                rest = rest[1:] if attached else rest[2:]
            elif option in ("-C", "--git-dir", "--work-tree", "--namespace") and not attached:
                rest = rest[2:]
            else:
                rest = rest[1:]
        if rest[:1] == ["config"]:
            keys = [i for i, word in enumerate(rest) if word.lower() == "core.hookspath"]
            if keys and not CONFIG_READS & set(rest) and (keys[0] + 1 < len(rest) or CONFIG_UNSETS & set(rest)):
                return True
        elif rest[:1] == ["commit"] and commit_skips(rest[1:]):
            return True
    return False


def commit_skips(arguments):
    value_next = False
    for word in arguments:
        if value_next:
            value_next = False
        elif word == "--":
            return False
        elif word.startswith("--"):
            name = word.split("=", 1)[0]
            if name.startswith("--no-v") and "--no-verify".startswith(name):
                return True
            value_next = name in COMMIT_LONG_VALUE and "=" not in word
        elif word.startswith("-") and len(word) > 1:
            for position, flag in enumerate(word[1:], 1):
                if flag == "n":
                    return True
                if flag in COMMIT_VALUE:
                    value_next = position == len(word) - 1
                    break
                if flag in COMMIT_ATTACHED:
                    break
    return False


def main():
    payload = json.load(sys.stdin)
    if payload.get("tool_name") != "Bash":
        return
    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command") or ""
    if skips_hook(command):
        reason = ("This skips the secret-scan pre-commit hook (--no-verify, -n or a core.hooksPath override), and a "
                  "secret committed stays in the history. Commit without it; if the hook blocks, fix what it reports "
                  "(a false positive is allowlisted by the user, as its message explains).")
    elif tool_input.get("run_in_background"):
        return
    else:
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
