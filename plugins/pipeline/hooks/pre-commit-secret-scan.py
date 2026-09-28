#!/usr/bin/env python3
"""PreToolUse hook for Claude Code Bash and PowerShell calls that run `git commit` or `git push`.

commit: blocks when the staged diff (plus tracked changes for `commit -a`) adds a
        secret-looking string or an .env-style file.
push:   blocks when the commits about to leave the machine add such content, and,
        in repos that opted in (a docs/quality-reports/ directory exists at the repo
        root), blocks unless the gate agent recorded approval of the current tree
        in <git-common-dir>/gate-approved (legacy name: manager-approved).

Run as a Claude hook it guards Claude's own git calls against accidents. It parses
the command text (chained and nested commands, subshells, `bash -c` / `powershell
-Command`, env prefixes, wrappers, full paths to git, git's global options), so a
script file that calls git inside is not seen, and commands typed in a user terminal
are not affected. `--install-pre-push` writes a real
git pre-push hook that runs `--pre-push`: the same secret scan on the outgoing
commits, enforced by git however push is invoked (approval gate not included).
Fails open on any internal error or outside a git repo. As a Claude hook it is wired
by the `pipeline` plugin, so it runs only in sessions of repos that enable the plugin."""
import base64
import json
import os
import re
import subprocess
import sys

EXCLUDES = [":(exclude)*.lock", ":(exclude)package-lock.json"]
PATTERNS = [
    ("AWS access key", r"AKIA[0-9A-Z]{16}"),
    ("GitHub token", r"gh[pousr]_[A-Za-z0-9]{20,}"),
    ("Slack token", r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    ("private key header", r"-----BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    ("Stripe live key", r"[rs]k_live_[0-9A-Za-z]{16,}"),
    ("Supabase secret key", r"sb_secret_[A-Za-z0-9_\-]{20,}"),
    ("Anthropic API key", r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    ("credentials in a connection URL",
     r"\b[a-z][a-z0-9+.\-]*://[^\s:/@'\"]+:[^\s:/@'\"]{4,}@(?!localhost|127\.0\.0\.1)[^\s/'\"]+"),
    ("generic API key/secret/token assignment",
     r"(?i)(api[_-]?key|secret|token|passw(?:or)?d|private[_-]?key|service[_-]?role\w*"
     r"|access[_-]?key)[\"' ]*[:=][\"' ]*[A-Za-z0-9/+_=.\-]{16,}"),
]
JWT = re.compile(r"eyJ[\w-]{8,}\.(eyJ[\w-]{8,})\.[\w-]{10,}")


def jwt_role(payload):
    try:
        padded = payload + "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(padded)).get("role")
    except Exception:
        return None


def allow():
    sys.exit(0)


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def git(args, cwd):
    try:
        result = subprocess.run(["git"] + args, cwd=cwd, capture_output=True,
                                encoding="utf-8", errors="replace", timeout=30)
        return result.returncode, result.stdout or ""
    except Exception:
        return 1, ""


def resolve_path(path, literal, base, powershell):
    if "`" in path and not powershell or "$(" in path:
        return None
    if not literal:
        if powershell:
            path = re.sub(r"\$env:([A-Za-z_][A-Za-z0-9_]*)",
                          lambda m: os.environ.get(m.group(1), m.group(0)), path)
        else:
            path = os.path.expandvars(path)
    if "$" in path:
        return None
    msys = re.match(r"^/([a-zA-Z])/(.*)", path)
    if msys:
        path = msys.group(1) + ":/" + msys.group(2)
    path = os.path.expanduser(path)
    return path if os.path.isabs(path) else os.path.join(base or os.getcwd(), path)


def added_lines(diff):
    return "\n".join(line[1:] for line in diff.splitlines()
                     if line.startswith("+") and not line.startswith("+++"))


def scan(diff, names):
    findings = []
    env_files = sorted({n for n in names
                        if re.search(r"(^|/)\.env(\..+)?$", n)
                        and not n.endswith((".example", ".sample"))})
    if env_files:
        findings.append(".env-style file(s): " + ", ".join(env_files))
    text = added_lines(diff)
    for label, pattern in PATTERNS:
        if re.search(pattern, text):
            findings.append(f"possible {label} in added lines")
    for token in JWT.finditer(text):
        role = jwt_role(token.group(1))
        if role != "anon":
            findings.append("possible JWT" + (f" with role {role}" if role else "")
                            + " in added lines (only the public anon key may be committed)")
            break
    return findings


HOOK_MARKER = "secretscan-managed"
ZERO_SHA = "0" * 40


def pre_push():
    cwd = os.getcwd()
    for line in sys.stdin:
        parts = line.split()
        if len(parts) < 4 or parts[1] == ZERO_SHA:
            continue
        local_sha, remote_sha = parts[1], parts[3]
        if remote_sha == ZERO_SHA:
            revs = [local_sha, "--not", "--remotes"]
        else:
            revs = [f"{remote_sha}..{local_sha}"]
        code, diff = git(["log", "-p", "-m", "--format="] + revs + ["--"] + EXCLUDES, cwd)
        if code != 0:
            code, diff = git(["log", "-p", "-m", "--format=", local_sha, "--not", "--remotes",
                              "--"] + EXCLUDES, cwd)
        _, names = git(["log", "--name-only", "--format="] + revs, cwd)
        findings = scan(diff, names.splitlines())
        if findings:
            sys.stderr.write("Secret scan blocked this push. The commits leaving this machine "
                             "contain:\n- " + "\n- ".join(findings)
                             + "\nRewrite the affected local commits and rotate the secret.\n")
            sys.exit(1)
    sys.exit(0)


def install_pre_push():
    code, hooks_dir = git(["rev-parse", "--git-path", "hooks"], None)
    if code != 0:
        sys.stderr.write("Not inside a git repository.\n")
        sys.exit(2)
    hooks_dir = os.path.abspath(hooks_dir.strip())
    target = os.path.join(hooks_dir, "pre-push")
    if os.path.exists(target) and HOOK_MARKER not in open(target, encoding="utf-8").read():
        sys.stderr.write(f"A pre-push hook already exists at {target}; not overwriting it.\n")
        sys.exit(2)
    script = os.path.abspath(__file__).replace("\\", "/")
    os.makedirs(hooks_dir, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(f'#!/bin/sh\n# {HOOK_MARKER}\n[ -f "{script}" ] || exit 0\n'
                     f'exec python "{script}" --pre-push "$@"\n')
    os.chmod(target, 0o755)
    print(f"installed {target}")
    sys.exit(0)


SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
POWERSHELLS = {"powershell", "pwsh"}
WRAPPERS = {"command", "builtin", "exec", "nohup", "time", "env", "sudo", "noglob", "&", "."}
CD_BASH = {"cd", "pushd"}
CD_POWERSHELL = {"cd", "chdir", "set-location", "sl", "pushd", "push-location"}
GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path",
                     "--super-prefix", "--config-env", "--list-cmds"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
BASH_ESCAPABLE_IN_QUOTES = '$`"\\\n'
BASH_ESCAPABLE = BASH_ESCAPABLE_IN_QUOTES + " \t'&|;()<>{}*?[]#~!"


def is_escape(text, index, powershell, quoted):
    if index + 1 >= len(text):
        return False
    if powershell:
        return text[index] == "`"
    if text[index] != "\\":
        return False
    return text[index + 1] in (BASH_ESCAPABLE_IN_QUOTES if quoted else BASH_ESCAPABLE)


def split_segments(command, powershell):
    segments, current, quote, index = [], [], None, 0
    while index < len(command):
        char = command[index]
        if quote:
            current.append(char)
            if quote == '"' and is_escape(command, index, powershell, True):
                current.append(command[index + 1])
                index += 1
            elif char == quote:
                quote = None
        elif is_escape(command, index, powershell, False):
            if command[index + 1] != "\n":
                current.extend(command[index:index + 2])
            index += 1
        elif char in "'\"":
            quote = char
            current.append(char)
        elif char == "{" and current and current[-1] == "$":
            current.append(char)
        elif char in ";&|\n(){}":
            segments.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    segments.append("".join(current))
    return [s.strip() for s in segments if s.strip()]


def tokenize(segment, powershell):
    tokens, text, literal, started, quote, index = [], [], False, False, None, 0
    while index < len(segment):
        char = segment[index]
        if quote:
            if char == quote:
                quote = None
            elif quote == '"' and is_escape(segment, index, powershell, True):
                text.append(segment[index + 1])
                index += 1
            else:
                text.append(char)
        elif char in "'\"":
            quote, started = char, True
            literal = literal or char == "'"
        elif not powershell and is_escape(segment, index, powershell, False):
            text.append(segment[index + 1])
            started = True
            index += 1
        elif char.isspace():
            if started:
                tokens.append(("".join(text), literal))
            text, literal, started = [], False, False
        else:
            text.append(char)
            started = True
        index += 1
    if started:
        tokens.append(("".join(text), literal))
    return tokens


def program(token):
    name = re.split(r"[\\/]", token)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def inline_script(tokens, flags):
    for position, (text, _) in enumerate(tokens[:-1]):
        if text.lower() in flags:
            return tokens[position + 1][0]
    return None


def find_git_ops(command, powershell, steps=None, ops=None):
    steps = [] if steps is None else steps
    ops = [] if ops is None else ops
    for segment in split_segments(command, powershell):
        tokens = tokenize(segment, powershell)
        while tokens and (tokens[0][0].lower() in WRAPPERS
                          or (not powershell and ASSIGNMENT.match(tokens[0][0]))):
            tokens = tokens[1:]
        if not tokens:
            continue
        name = program(tokens[0][0])
        if name in SHELLS:
            script = inline_script(tokens[1:], {"-c"})
            if script:
                find_git_ops(script, False, list(steps), ops)
            continue
        if name in POWERSHELLS:
            script = inline_script(tokens[1:], {"-c", "-command"})
            if script:
                find_git_ops(script, True, list(steps), ops)
            continue
        if name in (CD_POWERSHELL if powershell else CD_BASH):
            paths = [t for t in tokens[1:] if not t[0].startswith("-")]
            if paths:
                steps.append(paths[0])
            continue
        if name != "git":
            continue
        local, rest = [], tokens[1:]
        while rest and rest[0][0].startswith("-"):
            option = rest[0][0]
            if option in GIT_VALUE_OPTIONS and len(rest) > 1:
                if option == "-C":
                    local.append(rest[1])
                rest = rest[2:]
            else:
                rest = rest[1:]
        if rest and rest[0][0] in ("commit", "push"):
            ops.append({"op": rest[0][0], "steps": steps + local,
                        "args": [t[0] for t in rest[1:]]})
    return ops


def resolve_cwd(steps, base, powershell):
    cwd = base
    for text, literal in steps:
        cwd = resolve_path(text, literal, cwd, powershell)
        if cwd is None:
            return None
    return cwd


def commit_reason(cwd, args):
    _, names = git(["diff", "--cached", "--name-only"], cwd)
    _, diff = git(["diff", "--cached", "--"] + EXCLUDES, cwd)
    if any(a == "--all" or re.match(r"^-[a-zA-Z]*a[a-zA-Z]*$", a) for a in args):
        _, unstaged = git(["diff", "--"] + EXCLUDES, cwd)
        diff += "\n" + unstaged
    findings = scan(diff, names.splitlines())
    if findings:
        return ("Secret scan blocked this commit. Findings:\n- " + "\n- ".join(findings)
                + "\n\nRemove the secret from the staged changes and try again. "
                  "For a false positive, unstage that file/line and commit the rest.")
    return None


def push_reason(cwd, top, args):
    if any(a == "--dry-run" or re.match(r"^-[a-zA-Z]*n[a-zA-Z]*$", a) for a in args):
        return None
    _, unpushed = git(["rev-list", "HEAD", "--not", "--remotes"], cwd)
    if unpushed.strip():
        _, diff = git(["log", "-p", "-m", "--format=", "HEAD", "--not", "--remotes", "--"]
                      + EXCLUDES, cwd)
        _, names = git(["log", "--name-only", "--format=", "HEAD", "--not", "--remotes"], cwd)
        findings = scan(diff, names.splitlines())
        if findings:
            return ("Secret scan blocked this push: the commits about to leave this machine "
                    "contain:\n- " + "\n- ".join(findings)
                    + "\n\nRemoving it in a later commit is not enough because it stays in "
                      "the history being pushed. Rewrite the affected local commits first.")
    if os.path.isdir(os.path.join(top, "docs", "quality-reports")):
        _, tree = git(["rev-parse", "HEAD^{tree}"], cwd)
        _, common = git(["rev-parse", "--git-common-dir"], cwd)
        git_dir = os.path.abspath(os.path.join(cwd or os.getcwd(), common.strip()))
        approvals = os.path.join(git_dir, "gate-approved")
        approved = set()
        # manager-approved is the pre-rename file name; keep honoring approvals already recorded there
        for name in ("gate-approved", "manager-approved"):
            path = os.path.join(git_dir, name)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as handle:
                    approved |= {line.split()[0] for line in handle if line.split()}
        if tree.strip() not in approved:
            return ("Push blocked: this project requires the gate agent's approval before "
                    "anything leaves the machine, and the current tree (" + tree.strip()[:12]
                    + ") has none recorded. Run the gate (manager skill, step 4); on "
                      "APPROVED it records the tree in " + approvals + ". Commits made after "
                      "the approval need a new one. To push without this flow, run git push "
                      "yourself in a terminal.")
    return None


def main():
    if "--pre-push" in sys.argv:
        pre_push()
    if "--install-pre-push" in sys.argv:
        install_pre_push()
    try:
        payload = json.load(sys.stdin)
    except Exception:
        allow()

    command = (payload.get("tool_input") or {}).get("command", "") or ""
    powershell = payload.get("tool_name") == "PowerShell"
    base = payload.get("cwd") or None
    for item in find_git_ops(command, powershell):
        cwd = resolve_cwd(item["steps"], base, powershell)
        if cwd is None:
            deny("Cannot verify which repository this git " + item["op"] + " targets: the path "
                 "in the command uses a command substitution or a variable not set in the "
                 "environment. Use a literal path (or cd to it in a separate command) and run "
                 "it again.")
        code, top = git(["rev-parse", "--show-toplevel"], cwd)
        if code != 0:
            continue
        if item["op"] == "commit":
            reason = commit_reason(cwd, item["args"])
        else:
            reason = push_reason(cwd, top.strip(), item["args"])
        if reason:
            deny(reason)
    allow()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        if "--pre-push" in sys.argv:
            sys.stderr.write(f"Secret scan failed ({error!r}); blocking the push. "
                             "Fix the scanner or push with --no-verify after checking by hand.\n")
            sys.exit(1)
        allow()
