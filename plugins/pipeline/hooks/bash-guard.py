#!/usr/bin/env python3
"""PreToolUse hook (matcher Bash|PowerShell, see hooks.json): denies skipping the secret-scan pre-commit hook,
anything that reaches the default branch while the delivery is in autonomous mode, and the project's dev server
outside background mode; asks the user before a delivery starts
outside Claude Code's auto permission mode (not the delivery's autonomous mode).

A ledger.py start (also start --next), run in a session whose permission_mode is neither auto nor
bypassPermissions, asks the user first, naming the mode: the delivery would stop at each permission prompt while the
user is away. A payload with no permission_mode passes.

In autonomous mode (the latest mode entry of the ledger ledger.py finds from the session's directory), denied in the
foreground or background: a git push of the default branch (named by origin/HEAD, else init.defaultBranch, main or
master: as a refspec's target, with --all or --mirror, or with no refspec while it is checked out; --tags alone
passes), a git merge while it is checked out (--abort and --quit pass), and a pull request merge (gh pr merge or glab
mr merge or accept, also behind the tool's own options, and its api on pulls/<n>/merge or merge_requests/<n>/merge). A
git checkout or switch earlier in the same command counts as what is checked out for the rest of it (a checkout with
-- or of a word that is no branch here restores files and changes nothing); a cd does not, so the check reads the
session's directory. Pushing and merging the work branch pass; in supervised mode, or with no ledger, nothing here is
denied, and a push of the default branch (the same reading) asks the user: approval 2 is theirs, and a push of a work
branch passes, since a permission rule cannot tell them apart inside a compound command. With the user's standing
approval (ledger.py approve, read from approval.json beside the ledger), a publish passes when what it publishes is a
gated delivery: the commit (the ref a git merge names, HEAD for a pull request merge, the source of a push, or the
default branch a merge earlier in the same command already approved) has the tree of the commit that last added the
delivery's quality report (docs/quality-reports/*-<slug>.md, which the gate writes on READY only), the report's head
differs from that commit only in docs/quality-reports/, and the report's version is at most the approval's --until. A
push with --all, --mirror or --delete is still denied.

Skipping the hook is denied in any project, in the foreground or background: a git commit with --no-verify (or an
unambiguous prefix such as --no-veri) or -n (also inside a cluster such as -nm or -an), a git -c or --config-env that
sets core.hooksPath, a GIT_CONFIG_* assignment naming it (also through env or export), and a git config that writes or
unsets it. The command is read word by word as the shell splits it, after the heredoc bodies the shell only passes
along are removed, so a flag quoted inside a commit message is a message, not a flag. Wrappers such as env, command,
time, nohup, xargs, `!`, `{` and if/then are looked through; a command given to a shell's -c (also -lc, and after
options that take a value, such as -o pipefail) or to eval is read the same way (a script the shell runs is a command
of its own), and so is a command substitution outside quotes; one inside double quotes is not read. Permission rules
match the command as plain text and cannot tell a flag from a message, which is why this check lives here. A command
that does not parse (an unbalanced quote) passes, since the shell refuses it too.

A PowerShell call goes through the same checks, read with PowerShell's own rules. Text the command only passes
along: single quotes literal ('' an escaped quote), double quotes with a backtick escape, the typographic quotes as
the straight pair they stand for, a here-string body (@'...'@), a `<# ... #>` block and a `#` that opens a word, to
the end of its line. Separators: `;` `|` a newline and `&&` `||`, and `{` `}` too, since a script block is a
command of its own whether or not a space follows the brace; a backtick before a line break is a space, and what
stands between parentheses is read also as an argument of the command around them, which is what PowerShell makes
of it. Looked through: the call operator `&`, alone or glued to the name; `$name = <command>`, the variable gone
and the command kept; -Command (any unambiguous prefix), cmd's /c, the first positional argument of powershell.exe
and a decoded -EncodedCommand, read like a shell's -c; Invoke-Expression or iex, like eval; and Start-Process with
its -ArgumentList. `$env:NAME = value` is read as the assignment it is, in any spacing, as `${env:NAME}` and as a
Set-Item or New-Item on env:NAME. Not read, so still passing: a flag held in a variable, an alias, splatting, a
`%VAR%` expanded after `--%` (a flag written out after it still counts) and a command inside double quotes.

A dev server run in the foreground never returns: the call hangs, and the process is orphaned when it times out.
The command comes from the project's CLAUDE.md, the line `- Rodar em desenvolvimento: `<command>`` under
"Comandos" (the same lines gate.py reads); the plugin knows no stack. Without a CLAUDE.md found from the session's
directory upwards, or without that line holding a command in backticks, it does nothing.

Denied: a call without run_in_background whose command contains the dev command at the start of a shell
segment (after &&, ||, ;, |, a newline, an opening parenthesis or env assignments), alone or followed by arguments;
`npm run dev &` counts too, because the shell leaves the same orphan. Text the shell only passes along is not
read: quoted strings (a commit message) and heredoc bodies (a file being written), unless a shell reads the
heredoc (`bash <<EOF`). The reason names the right form. Any failure of the hook itself lets the call through."""
import base64
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


def program_name(word):
    """The command's name without its path, its case or a Windows executable suffix."""
    return re.sub(r"\.(exe|cmd|bat|ps1)$", "", re.split(r"[\\/]", word)[-1].lower())


def runs_it(command, dev, powershell=False):
    """True when the command runs the dev command: in PowerShell, as a simple command of its own, since its
    quoting is resolved word by word; in Bash, at the start of a shell segment of the text the shell executes."""
    words = dev.split()
    if powershell:
        return any(program == program_name(words[0]) and list(arguments[:len(words) - 1]) == words[1:]
                   for program, arguments, _ in simple_commands(command, powershell=True))
    pattern = r"\s+".join(re.escape(word) for word in words)
    return re.search(r"(?:^|&&|\|\||[;|\n(])\s*(?:[A-Za-z_]\w*=\S*\s+)*" + pattern + r"(?=\s|$|[;&|)])",
                     executed(command)) is not None


SHELLS = {"sh", "bash", "zsh", "dash"}
SHELL_VALUE = {"--rcfile", "--init-file"}  # with -o, -O, +o, +O (also ending a cluster): an option and its value
PS_SHELLS = {"powershell", "pwsh", "cmd"}
PS_LAUNCHERS = {"start-process", "saps", "start"}
PS_SET_ENV = {"set-item", "si", "new-item", "ni", "set-variable", "sv"}
EVALS = {"eval"}
PS_EVALS = {"invoke-expression", "iex"}
WRAPPERS = {"env", "command", "time", "nohup", "exec", "xargs", "!", "{", "&", "if", "then", "else", "elif", "do",
            "while", "until"}
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


PS_HERESTRING = re.compile(r"@(['\"])[ \t]*\r?\n.*?\n\1@", re.S)
PS_SEPARATORS = ";\n|(){}"
PS_QUOTES = {"'": "'", '"': '"', "\u2018": "\u2019", "\u2019": "\u2019", "\u201c": "\u201d", "\u201d": "\u201d"}
PS_LITERAL = {"'", "\u2018", "\u2019"}


def ps_quoted(text, index, quote):
    """The text of the quoted string that opens at index, and the index after it. Inside single quotes '' is an
    escaped quote and nothing else is special; inside double quotes a backtick escapes the next character. The
    typographic quotes PowerShell also accepts are read as the straight pair they stand for."""
    closing, word, index = PS_QUOTES[quote], "", index + 1
    while index < len(text):
        char = text[index]
        if char == closing:
            if text[index + 1:index + 2] != closing:
                return word, index + 1
            index += 1
        elif char == "`" and quote not in PS_LITERAL:
            index += 1
            if index >= len(text):
                break
        word += text[index]
        index += 1
    raise ValueError(f"unbalanced {closing} in the PowerShell command")


def ps_glued(words):
    """An assignment written with the `=` apart put back together: `$x = v`, `$x =v` and `$x= v` all become `$x=v`,
    so one rule reads every spacing PowerShell accepts."""
    found, index = [], 0
    while index < len(words):
        word = words[index]
        if word.startswith("$") and "=" not in word and words[index + 1:index + 2] \
                and words[index + 1].startswith("="):
            word, index = word + words[index + 1], index + 1
        if word.startswith("$") and word.endswith("=") and words[index + 1:index + 2]:
            word, index = word + words[index + 1], index + 1
        found.append(word)
        index += 1
    return found


def ps_assignments(words):
    """A PowerShell assignment read as the shape the checks already know. `$env:NAME=value` becomes
    `export NAME=value` (also `${env:NAME}=`, the `=` spaced either way, and a Set-Item or New-Item on env:NAME):
    it does change the process environment of what follows. `$name = <command>` keeps the command, which runs
    either way, and drops the variable. A `$env:NAME` read as a value is left as it is, so it stays one argument."""
    words = ps_glued(words)
    if words and program_name(words[0]) in PS_SET_ENV:
        names = [word[len("env:"):] for word in words[1:] if re.fullmatch(r"env:\w+", word, re.I)]
        values = [word for word in words[1:]
                  if not word.startswith("-") and not re.fullmatch(r"env:\w+", word, re.I)]
        if names and values:
            return ["export", names[0] + "=" + values[-1]]
    found = []
    for word in words:
        name, sep, value = word.partition("=")
        plain = name.replace("${", "$").replace("}", "")
        if plain.lower().startswith("$env:") and sep:
            found += ["export", plain[len("$env:"):] + "=" + value]
        elif plain.startswith("$") and sep:
            found += [value] if value else []
        else:
            found.append(word)
    return found


def ps_segments(command):
    """Each simple command of a PowerShell command line as its words, quotes resolved, with the here-string bodies
    the command only passes along removed. Raises ValueError on an unbalanced quote, which PowerShell refuses too."""
    text = PS_HERESTRING.sub("''", command)
    found, words, word, open_word, index = [], [], "", False, 0
    while index < len(text):
        char, pair = text[index], text[index:index + 2]
        if char in PS_QUOTES:
            quoted, index = ps_quoted(text, index, char)
            word, open_word = word + quoted, True
            continue
        if pair == "${" and text.find("}", index + 2) >= 0:
            end = text.find("}", index + 2)
            word, open_word, index = word + text[index:end + 1], True, end + 1
            continue
        if pair == "${" and text.find("}", index + 2) >= 0:
            end = text.find("}", index + 2)
            word, open_word, index = word + text[index:end + 1], True, end + 1
            continue
        if open_word and (char in " \t\r" or char in PS_SEPARATORS or pair in ("&&", "||")):
            words.append(word)
            word, open_word = "", False
        if pair == "<#" and not open_word:
            end = text.find("#>", index + 2)
            index = len(text) if end < 0 else end + 2
            continue
        if char == "`" and text[index + 1:index + 2] in ("\n", "\r"):
            index += 1
            while index < len(text) and text[index] in "\r\n":
                index += 1
            continue
        if char == "#" and not open_word:
            index = text.find("\n", index)
            if index < 0:
                break
            continue
        if char in PS_SEPARATORS or pair in ("&&", "||"):
            if words:
                found.append(words)
                words = []
            index += 2 if pair in ("&&", "||") else 1
        elif char in " \t\r":
            index += 1
        else:
            if char == "`":
                index += 1
                if index >= len(text):
                    break
            word, open_word = word + text[index], True
            index += 1
    if open_word:
        words.append(word)
    return [ps_assignments(segment) for segment in (found + [words] if words else found)]


def hooks_path(key):
    return key.split("=", 1)[0].lower() == "core.hookspath"


PS_COMMAND_FLAGS = ("/c", "/k", "/r")


def ps_inner(words):
    """The command a PowerShell or cmd call runs: behind -Command (any unambiguous prefix) or cmd's /c, decoded
    from -EncodedCommand, or the first word that is not an option, which powershell.exe reads as -Command too."""
    for index, word in enumerate(words[1:], 1):
        lower = word.lower()
        if lower.startswith("-") and len(lower) > 2 and "-encodedcommand".startswith(lower):
            try:
                return base64.b64decode(words[index + 1]).decode("utf-16-le", "ignore")
            except Exception:
                return None
        if (lower.startswith("-") and len(lower) > 1 and "-command".startswith(lower)) \
                or lower in PS_COMMAND_FLAGS:
            return " ".join(words[index + 1:])
        if not lower.startswith(("-", "/")):
            return " ".join(words[index:])
    return None


def simple_commands(command, powershell=False):
    """Each simple command the shell runs, as (program, its arguments, the segment's words), looking through
    wrappers and into a shell's -c (PowerShell's -Command) and eval (Invoke-Expression). In Bash a '#' is read as
    text first (it starts a comment only at the start of a word, which shlex cannot tell); a command that does not
    parse that way is read again with '#' as a comment, and one that parses neither way yields nothing."""
    try:
        parsed = ps_segments(command) if powershell else segments(command)
    except ValueError:
        if powershell:
            return
        try:
            parsed = segments(command, "#")
        except ValueError:
            return
    if powershell and "(" in command:
        try:
            parsed = parsed + ps_segments(command.replace("(", " ").replace(")", " "))
        except ValueError:
            pass
    for segment in parsed:
        words = segment
        while words:
            if words[0] in WRAPPERS or re.fullmatch(r"[A-Za-z_]\w*=.*", words[0]) \
                    or (words[0].startswith("-") and len(words) > 1):
                words = words[1:]
            elif powershell and words[0].startswith("&") and len(words[0]) > 1:
                words = [words[0][1:]] + words[1:]
            else:
                break
        if not words:
            continue
        program = program_name(words[0])
        if powershell and program in PS_SHELLS:
            inner = ps_inner(words)
            if inner:
                yield from simple_commands(inner, True)
        elif powershell and program in PS_LAUNCHERS:
            parts = [part for word in words[1:] if not word.startswith("-")
                     for part in word.split(",") if part]
            if parts:
                yield program_name(parts[0]), parts[1:], parts
        elif not powershell and program in SHELLS:
            position = 1
            while position < len(words) - 1:
                word = words[position]
                if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", word):
                    yield from simple_commands(words[position + 1], powershell)
                    break
                if not word.startswith(("-", "+")):
                    yield program, words[1:], segment  # a script the shell runs
                    break
                position += 2 if word in SHELL_VALUE or re.fullmatch(r"[-+][A-Za-z]*[oO]", word) else 1
        elif program in (PS_EVALS if powershell else EVALS):
            yield from simple_commands(" ".join(words[1:]), powershell)
        else:
            yield program, words[1:], segment


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


def skips_hook(command, powershell=False):
    """True when the command skips the pre-commit hook."""
    for program, arguments, segment in simple_commands(command, powershell):
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


def ledger_state(cwd):
    """(ledger module, ledger path, entries) for the session's directory, or None with no ledger."""
    spec = importlib.util.spec_from_file_location("pipeline_ledger", LEDGER)
    ledger = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ledger)
    os.chdir(cwd)
    try:
        path = ledger.default_ledger("status")
        return ledger, path, ledger.read(path)
    except SystemExit:
        return None


def gated(cwd, ref, state):
    """True when the standing approval covers publishing ref: see the docstring."""
    ledger, path, entries = state
    approval, slug = ledger.standing(path), entries and entries[0].get("slug")
    commit = ref and git_out(cwd, "rev-parse", "--verify", "--quiet", ref + "^{commit}")
    if not approval or not slug or not commit:
        return False
    reports = sorted(name for name in git_out(cwd, "ls-tree", "--name-only", commit, "docs/quality-reports/").splitlines()
                     if name.endswith(f"-{slug}.md"))
    added = reports and git_out(cwd, "log", "-1", "--format=%H", commit, "--", reports[-1])
    match = added and re.search(r"\b[0-9a-f]{7,40}\.\.([0-9a-f]{7,40})\b.*?\bv(\d+\.\d+\.\d+)\b",
                                git_out(cwd, "show", f"{added}:{reports[-1]}"))
    if not match or (ledger.version_key(match.group(2)) or ()) > ledger.version_key(approval["until"]):
        return False
    head = git_out(cwd, "rev-parse", "--verify", "--quiet", match.group(1) + "^{commit}")
    if not head or subprocess.run(["git", "diff", "--quiet", added, commit], cwd=cwd, capture_output=True).returncode:
        return False
    changed = subprocess.run(["git", "diff", "--name-only", head, added], cwd=cwd, capture_output=True, text=True)
    return changed.returncode == 0 and all(line.startswith("docs/quality-reports/")
                                           for line in changed.stdout.splitlines())


def main_branch(cwd):
    remote = git_out(cwd, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if remote:
        return remote.split("/", 1)[-1]
    names = [git_out(cwd, "config", "--get", "init.defaultBranch"), "main", "master"]
    return next((name for name in names
                 if name and git_out(cwd, "rev-parse", "--verify", "--quiet", "refs/heads/" + name)), None)


def push_sources(arguments, main, current):
    """What a push that reaches the default branch publishes there: the source of each refspec whose target it is
    (the branch checked out with no refspec), or None when it is no single commit (--all, --mirror, --delete)."""
    if {"--all", "--mirror", "--delete", "-d"} & set(arguments):
        return None
    positional = [word for position, word in enumerate(arguments) if not word.startswith("-")
                  and not (position and arguments[position - 1] in PUSH_VALUE)]
    if len(positional) < 2:
        return [current]
    sources = []
    for spec in positional[1:]:
        source, _, target = spec.lstrip("+").rpartition(":") if ":" in spec else ("", "", spec.lstrip("+"))
        if target.removeprefix("refs/heads/") == main or (target in ("HEAD", "@") and current == main):
            sources.append(source if ":" in spec else target)
    return sources if all(sources) else None


def merged_ref(arguments):
    value_next = False
    for word in arguments:
        if value_next:
            value_next = False
        elif word in ("-m", "-s", "-X", "-F", "--strategy", "--strategy-option", "--file"):
            value_next = True
        elif not word.startswith("-"):
            return word
    return None


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
        return current == main and "--tags" not in arguments
    for spec in positional[1:]:
        target = spec.lstrip("+").split(":")[-1].removeprefix("refs/heads/")
        if target == main or (target in ("HEAD", "@") and current == main):
            return True
    return False


def switched_to(name, arguments, cwd):
    """The branch a git checkout or git switch leaves checked out, or None when it is not a branch change: a git
    checkout with -- or of a word that is no local or remote branch here (a path, ., HEAD) restores files."""
    if name == "checkout" and "--" in arguments:
        return None
    for position, word in enumerate(arguments):
        if word in ("-b", "-B", "-c", "-C", "--orphan"):
            return arguments[position + 1] if position + 1 < len(arguments) else None
        if not word.startswith("-"):
            if name == "switch" or git_out(cwd, "rev-parse", "--verify", "--quiet", f"refs/heads/{word}") \
                    or git_out(cwd, "for-each-ref", "--count=1", f"refs/remotes/*/{word}"):
                return word
            return None
    return None


def merges_pull_request(arguments):
    pairs = zip(arguments, arguments[1:])
    return any(pair in (("pr", "merge"), ("mr", "merge"), ("mr", "accept")) for pair in pairs) or (
        arguments[:1] == ["api"]
        and any(re.search(r"(pulls|merge_requests)/\d+/merge\b", word) for word in arguments))


def reaches_main(command, cwd, powershell=False):
    """Returns "deny" in autonomous mode when the command merges into or pushes the default branch, or merges a pull
    request; "ask" otherwise (supervised, or no ledger) when it pushes the default branch; None when neither. A git
    checkout or switch earlier in the same command counts as the branch checked out for what follows it."""
    calls = []
    for program, arguments, _ in simple_commands(command, powershell):
        if program == "git":
            name, rest, _ = git_command(arguments)
            if name in ("push", "merge", "checkout", "switch"):
                calls.append((program, name, rest))
        elif program in ("gh", "glab"):
            calls.append((program, "", arguments))
    if not any(name in ("push", "merge") or (program != "git" and merges_pull_request(rest))
               for program, name, rest in calls):
        return None
    state = ledger_state(cwd)
    autonomous = bool(state) and state[0].autonomous(state[2])
    main, current = main_branch(cwd), git_out(cwd, "branch", "--show-current")
    published = set()
    for program, name, rest in calls:
        if program != "git":
            if autonomous and merges_pull_request(rest) and not gated(cwd, "HEAD", state):
                return "deny"
        elif name in ("checkout", "switch"):
            current = switched_to(name, rest, cwd) or current
        elif main and name == "push" and push_reaches(rest, main, current):
            if not autonomous:
                return "ask"
            sources = push_sources(rest, main, current)
            if sources is None or not all(source in published or gated(cwd, source, state) for source in sources):
                return "deny"
        elif autonomous and main and name == "merge" and current == main and not {"--abort", "--quit"} & set(rest):
            if not gated(cwd, merged_ref(rest), state):
                return "deny"
            published.add(main)
    return None


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


UNATTENDED = {"auto", "bypassPermissions"}


def starts_delivery(command, powershell=False):
    """True when the command runs ledger.py start (also start --next): the delivery begins there."""
    for _, arguments, segment in simple_commands(command, powershell):
        words = [word for word in segment if word]
        found = [i for i, word in enumerate(words) if os.path.basename(word.replace("\\", "/")) == "ledger.py"]
        if not found:
            continue
        rest = words[found[0] + 1:]
        while rest and rest[0].startswith("--ledger"):
            rest = rest[1:] if "=" in rest[0] else rest[2:]
        if rest[:1] == ["start"]:
            return True
    return False


def main():
    payload = json.load(sys.stdin)
    if payload.get("tool_name") not in ("Bash", "PowerShell"):
        return
    powershell = payload["tool_name"] == "PowerShell"
    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command") or ""
    cwd = payload.get("cwd") or os.getcwd()
    mode = payload.get("permission_mode")
    if mode and mode not in UNATTENDED and starts_delivery(command, powershell):
        json.dump({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                          "permissionDecisionReason": (
                                              f"This session is in {mode} mode, not auto: the delivery would stop at "
                                              "each permission prompt while the user is away. Start it anyway, or "
                                              "restart the session in auto mode first?")}}, sys.stdout)
        return
    skips = skips_hook(command, powershell)
    publishes = None if skips else reaches_main(command, cwd, powershell)
    if publishes == "ask":
        json.dump({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                          "permissionDecisionReason": "This pushes the main branch: approval 2 is "
                                          "the user's."}}, sys.stdout)
        return
    if skips:
        reason = ("This skips the secret-scan pre-commit hook (--no-verify, -n or a core.hooksPath override), and a "
                  "secret committed stays in the history. Commit without it; if the hook blocks, fix what it reports "
                  "(a false positive is allowlisted by the user, as its message explains).")
    elif publishes == "deny":
        reason = ("The delivery is in autonomous mode (the ledger says so), and nothing reaches the default branch "
                  "without the user: no push to it, no merge into it, no pull request merge. Leave the merge and the "
                  "push for approval 2, when the user returns.")
    elif tool_input.get("run_in_background"):
        return
    else:
        dev = dev_command(cwd)
        if not dev or not runs_it(command, dev, powershell):
            return
        reason = (f"`{dev}` is this project's dev server and never returns, so in the foreground it hangs the call and "
                  "leaves an orphan process. Run the same command with the tool's run_in_background set to true "
                  "(and stop it before you finish), or reuse a server already running for this directory.")
    json.dump({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                      "permissionDecisionReason": reason}}, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
