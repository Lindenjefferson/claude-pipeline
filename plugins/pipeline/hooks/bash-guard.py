#!/usr/bin/env python3
"""PreToolUse hook (matcher Bash, see hooks.json): denies skipping the secret-scan pre-commit hook, anything that
reaches the default branch while the delivery is in autonomous mode, and the project's dev server outside background
mode.

In autonomous mode (the latest mode entry of the ledger ledger.py finds from the session's directory), denied in the
foreground or background: a git push of the default branch (named by origin/HEAD, else main or master: as a refspec's
target, with --all or --mirror, or with no refspec while it is checked out), a git merge while it is checked out
(--abort and --quit pass), and gh pr merge. Pushing and merging the work branch pass; in supervised mode, or with
no ledger, nothing here is denied and the ask rule on git push applies.

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
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "..", "skills", "manager", "gate.py")
LEDGER = os.path.join(HERE, "..", "skills", "manager", "ledger.py")
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
PUSH_VALUE = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
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


def simple_commands(command):
    """Each simple command the shell runs, as (program, its arguments, the segment's words), looking through
    wrappers and into a shell's -c and eval. A '#' is read as text first (it starts a comment only at the start of a
    word, which shlex cannot tell); a command that does not parse that way is read again with '#' as a comment, and
    one that parses neither way yields nothing."""
    try:
        parsed = segments(command)
    except ValueError:
        try:
            parsed = segments(command, "#")
        except ValueError:
            return
    for segment in parsed:
        words = segment
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
                    yield from simple_commands(words[position + 1])
                    break
        elif program == "eval":
            yield from simple_commands(" ".join(words[1:]))
        else:
            yield program.removesuffix(".exe"), words[1:], segment


def git_command(arguments):
    """The git subcommand and its arguments, past git's own options, and whether those options set core.hooksPath."""
    rest, override = list(arguments), False
    while rest and rest[0].startswith("-"):
        option, _, attached = rest[0].partition("=")
        if option in ("-c", "--config-env"):
            override = override or hooks_path(attached or (rest[1] if len(rest) > 1 else ""))
            rest = rest[1:] if attached else rest[2:]
        elif option in ("-C", "--git-dir", "--work-tree", "--namespace") and not attached:
            rest = rest[2:]
        else:
            rest = rest[1:]
    return (rest[0] if rest else ""), rest[1:], override


def skips_hook(command):
    """True when the command skips the pre-commit hook."""
    for program, arguments, segment in simple_commands(command):
        if any(re.fullmatch(r"GIT_CONFIG\w*=.*", word) and "core.hookspath" in word.lower() for word in segment):
            return True
        if program != "git":
            continue
        name, rest, override = git_command(arguments)
        if override:
            return True
        if name == "config":
            keys = [i for i, word in enumerate(rest) if word.lower() == "core.hookspath"]
            if keys and not CONFIG_READS & set(rest) and (keys[0] + 1 < len(rest) or CONFIG_UNSETS & set(rest)):
                return True
        elif name == "commit" and commit_skips(rest):
            return True
    return False


def git_out(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def autonomous(cwd):
    spec = importlib.util.spec_from_file_location("pipeline_ledger", LEDGER)
    ledger = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ledger)
    os.chdir(cwd)
    try:
        return ledger.autonomous(ledger.read(ledger.default_ledger("status")))
    except SystemExit:
        return False


def main_branch(cwd):
    remote = git_out(cwd, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if remote:
        return remote.split("/", 1)[-1]
    return next((name for name in ("main", "master")
                 if git_out(cwd, "rev-parse", "--verify", "--quiet", "refs/heads/" + name)), None)


def push_reaches(arguments, main, current):
    positional, value_next = [], False
    for word in arguments:
        if value_next:
            value_next = False
        elif word in ("--all", "--mirror"):
            return True
        elif word in PUSH_VALUE:
            value_next = True
        elif not word.startswith("-"):
            positional.append(word)
    if len(positional) < 2:
        return current == main
    for spec in positional[1:]:
        target = spec.lstrip("+").split(":")[-1].removeprefix("refs/heads/")
        if target == main or (target == "HEAD" and current == main):
            return True
    return False


def reaches_main(command, cwd):
    """True in autonomous mode when the command merges into or pushes the default branch, or merges a pull request."""
    calls = [(program, git_command(arguments) if program == "git" else ("", arguments, False))
             for program, arguments, _ in simple_commands(command)]
    calls = [(program, name, rest) for program, (name, rest, _) in calls
             if (program == "git" and name in ("push", "merge")) or (program == "gh" and rest[:2] == ["pr", "merge"])]
    if not calls or not autonomous(cwd):
        return False
    main, current = main_branch(cwd), git_out(cwd, "branch", "--show-current")
    for program, name, rest in calls:
        if program == "gh":
            return True
        if main and name == "push" and push_reaches(rest, main, current):
            return True
        if main and name == "merge" and current == main and not {"--abort", "--quit"} & set(rest):
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
    cwd = payload.get("cwd") or os.getcwd()
    if skips_hook(command):
        reason = ("This skips the secret-scan pre-commit hook (--no-verify, -n or a core.hooksPath override), and a "
                  "secret committed stays in the history. Commit without it; if the hook blocks, fix what it reports "
                  "(a false positive is allowlisted by the user, as its message explains).")
    elif reaches_main(command, cwd):
        reason = ("The delivery is in autonomous mode (the ledger says so), and nothing reaches the default branch "
                  "without the user: no push to it, no merge into it, no pull request merge. Leave the merge and the "
                  "push for approval 2, when the user returns.")
    elif tool_input.get("run_in_background"):
        return
    else:
        dev = dev_command(cwd)
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
