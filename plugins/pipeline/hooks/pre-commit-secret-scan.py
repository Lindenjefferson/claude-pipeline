#!/usr/bin/env python3
"""PreToolUse hook for Claude Code Bash and PowerShell calls that run `git commit` or `git push`.

commit: blocks when what the commit would record adds a secret-looking string or an
        .env-style file. That is the staged diff plus whatever the same command stages
        first (`git add ... && git commit`), the paths given to the commit and, for
        `commit -a`, the tracked changes; they are staged into a throwaway copy of
        the index, never into the real one.
push:   blocks when the commits about to leave the machine add such content. Those
        are the commits of the refs the command pushes (refspecs, tags, --all,
        --mirror; HEAD when none is given) that no remote-tracking ref has yet. In
        repos that opted in (a docs/quality-reports/ directory exists at the repo
        root), it also blocks unless the gate agent recorded approval of the tree
        of every such ref in <git-common-dir>/gate-approved (legacy name:
        manager-approved).

Run as a Claude hook it guards Claude's own git calls against accidents. It parses
the command text (chained and nested commands, subshells, `bash -c` / `powershell
-Command`, env prefixes, wrappers, full paths to git, git's global options), so a
script file that calls git inside is not seen, and commands typed in a user terminal
are not affected. `--install-pre-push` writes a real
git pre-push hook that runs `--pre-push`: the same secret scan on the outgoing
commits, enforced by git however push is invoked (approval gate not included).
A flagged line whose fingerprint (sha256 of its file path and the line with whitespace
collapsed) is listed in .pipeline-secrets-allow at the repo root is not reported. The list
is read from the index for a commit and from each pushed ref's tree for a push, never from
the working tree, and the hook denies Claude's own edits of that file. `--fingerprint`
prints the fingerprints of flagged lines read from stdin (a diff, or plain text with
`--path <file>`).
Fails open on any internal error or outside a git repo. As a Claude hook it is wired
by the `pipeline` plugin, so it runs only in sessions of repos that enable the plugin."""
import base64
import collections
import fnmatch
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

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
     r"\b[a-z][a-z0-9+.\-]*://[^\s:/@'\"]+:[^\s:/@'\"]{4,}@(?!localhost|127\.0\.0\.1)"
     r"[^\s/:'\"]*\.[^\s/'\"]+"),
]
SECRET_ASSIGNMENT = re.compile(
    r"(?i)([\w.$-]*?(?:api[_-]?key|secret|token|passw(?:or)?d|private[_-]?key|service[_-]?role\w*"
    r"|access[_-]?key))[\"' ]*[:=][ \t]*")
SECRET_CHARS = re.compile(r"[A-Za-z0-9/+_=.\-]{16,}")
DOTTED_NAME = re.compile(r"^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)+$")
SNAKE_NAME = re.compile(r"^(?:[a-z][a-z0-9]*(?:_[a-z0-9]+)+|[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)$")
CAMEL_MAX = 40
PASSWORD_KEY = re.compile(r"(?i)(?:passw(?:or)?d|secret)$")
CODE_WORD_PARTS = ("pass", "pwd", "secret", "token", "key", "hash", "crypt", "cred", "salt")
CODE_WORDS = {"value", "input", "new", "old", "plain", "current", "default", "env", "config",
              "user", "field", "param", "arg", "form", "data", "confirm", "stored", "raw", "tmp",
              "temp", "mock", "fake", "test", "dummy", "given", "local", "result"}
ENV_REFERENCE = re.compile(r"^(?:\$|%\w+%|process\.env\b|os\.environ\b|os\.getenv\b"
                           r"|import\.meta\.env\b|Deno\.env\b|env\()")
TEMPLATED = re.compile(r"\$\{|\$\(|\{\{|^\$|^%\w+%$")
PLACEHOLDER = re.compile(r"(?i)^(?:placeholder|example|changeme|x+|\*+)$|^(?:your[_-]|<)")
SQL_KEYWORDS = {"null", "default", "true", "false", "excluded", "current_user", "session_user",
                "current_timestamp", "current_setting", "now"}
JWT = re.compile(r"eyJ[\w-]{8,}\.(eyJ[\w-]{8,})\.[\w-]{10,}")
ALLOWLIST_FILE = ".pipeline-secrets-allow"


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


def git(args, cwd, env=None):
    try:
        result = subprocess.run(["git"] + args, cwd=cwd, capture_output=True,
                                stdin=subprocess.DEVNULL, env=env,
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


def char_classes(value):
    return sum(bool(re.search(pattern, value))
               for pattern in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]"))


def quoted_secret(content):
    words = content.split()
    if not words:
        return False
    word = words[0]
    if TEMPLATED.search(word) or PLACEHOLDER.search(word):
        return False
    return bool(SECRET_CHARS.match(word)) or (len(word) >= 12 and char_classes(word) >= 3)


def random_looking(value):
    counts = collections.Counter(value)
    bits = -sum(n / len(value) * math.log2(n / len(value)) for n in counts.values())
    # why: plain identifiers already reach 3.5 bits/char; random strings also use almost every character once
    return bits >= 3.5 and bits >= 0.95 * math.log2(len(value))


def name_words(value):
    if SNAKE_NAME.match(value):
        return value.lower().split("_")
    if len(value) > CAMEL_MAX or not re.fullmatch(r"[A-Za-z0-9]+", value):
        return None
    words = re.findall(r"[A-Z]?[a-z]+|[A-Z]", re.sub(r"[0-9]", "", value))
    if len(words) < 2 or any(sum(c.islower() for c in word) < 2
                             or not re.search(r"[aeiouy]", word, re.I) for word in words):
        return None
    return [word.lower() for word in words]


def written_identifier(name, value):
    words = name_words(value)
    if words is None or sum(c.isdigit() for c in value) > 3 or random_looking(value):
        return False
    if PASSWORD_KEY.search(name):
        return any(word in CODE_WORDS or any(part in word for part in CODE_WORD_PARTS)
                   for word in words)
    return True


def unquoted_secret(name, rest):
    match = SECRET_CHARS.match(rest)
    if not match:
        return False
    value = match.group(0)
    after = rest[match.end():match.end() + 1]
    if after == "(" or DOTTED_NAME.match(value):
        return False
    if value.lower() == name.rsplit(".", 1)[-1].lower() or value.lower() in SQL_KEYWORDS:
        return False
    return not written_identifier(name, value)


def assigns_secret(text):
    position = 0
    while True:
        match = SECRET_ASSIGNMENT.search(text, position)
        if not match:
            return False
        position = match.end()
        name, rest = match.group(1), text[match.end():]
        quote = rest[:1] if rest[:1] in "\"'`" else ""
        if ENV_REFERENCE.match(rest[len(quote):].lstrip()):
            continue
        if quote:
            closing = rest.find(quote, 1)
            content = rest[1:closing] if closing > 0 else rest[1:]
            if quoted_secret(content):
                return True
        elif unquoted_secret(name, rest):
            return True


def fingerprint(path, line):
    text = (path or "") + "\0" + " ".join(line.split())
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def line_findings(line):
    labels = [label for label, pattern in PATTERNS if re.search(pattern, line)]
    if assigns_secret(line):
        labels.append("generic API key/secret/token assignment")
    for token in JWT.finditer(line):
        role = jwt_role(token.group(1))
        if role != "anon":
            labels.append("JWT" + (f" with role {role}" if role else "")
                          + " (only the public anon key may be committed)")
            break
    return labels


def added_entries(diff):
    path = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[4:].strip()
            path = path[2:] if path.startswith("b/") else None if path == "/dev/null" else path
        elif line.startswith("+"):
            yield path, line[1:]


def allowlist_lines(cwd, rev=""):
    code, text = git(["show", f"{rev}:{ALLOWLIST_FILE}"], cwd)
    if code != 0:
        return {}
    lines = {}
    for line in text.splitlines():
        entry = line.split("#", 1)[0].strip().lower()
        if re.fullmatch(r"[0-9a-f]{64}", entry):
            lines.setdefault(entry, line.strip())
    return lines


def load_allowlist(cwd, rev=""):
    return set(allowlist_lines(cwd, rev))


def scan(diff, names, allowed=frozenset()):
    findings = []
    env_files = sorted({n for n in names
                        if re.search(r"(^|/)\.env(\..+)?$", n)
                        and not n.endswith((".example", ".sample"))})
    if env_files:
        findings.append(".env-style file(s): " + ", ".join(env_files))
    seen = set()
    for path, line in added_entries(diff):
        labels = line_findings(line)
        if not labels:
            continue
        mark = fingerprint(path, line)
        if mark in allowed or (path, mark) in seen:
            continue
        seen.add((path, mark))
        where = f" in {path}" if path else " in added lines"
        findings.append(f"possible {', '.join(labels)}{where} (fingerprint {mark})")
    return findings


ALLOW_HINT = ("\n\nFor a false positive, leave that line out and commit the rest, or ask the user "
              "to allowlist that exact line: they add `<fingerprint>  # reason` to " + ALLOWLIST_FILE
              + " at the repo root and stage it (git add " + ALLOWLIST_FILE + "). Only staged "
              "entries count for a commit and only committed ones for a push; you may not edit "
              "or stage that file yourself. The fingerprint covers the file path and the line, "
              "so any edit to either changes it. To list the fingerprints of flagged lines: git "
              "diff --cached | python \"" + os.path.abspath(__file__).replace("\\", "/")
              + "\" --fingerprint")


def print_fingerprints():
    given = sys.argv[sys.argv.index("--path") + 1] if "--path" in sys.argv[:-1] else None
    text = sys.stdin.buffer.read().decode("utf-8", "replace")
    diff = re.search(r"^(diff --git|@@ )", text, re.M)
    if not diff and given is None:
        sys.stderr.write("Plain text input needs --path <file path relative to the repo root>, "
                         "because the fingerprint covers the path.\n")
        sys.exit(2)
    entries = added_entries(text) if diff else ((given, line) for line in text.splitlines())
    for path, line in entries:
        labels = line_findings(line)
        if labels:
            print(f"{fingerprint(path, line)}  # {path or '-'}: {', '.join(labels)}")
    sys.exit(0)


HOOK_MARKER = "secretscan-managed"
HOME_VAR = "CLAUDE_PIPELINE_HOME"
PRE_PUSH_SHIM = f"""#!/bin/sh
# {HOOK_MARKER}
root="${{{HOME_VAR}:-$(git config --get pipeline.home)}}"
script="$root/hooks/pre-commit-secret-scan.py"
if [ -z "$root" ] || [ ! -f "$script" ]; then
  echo "Push blocked: secret scanner not found (looked in '$root')." >&2
  echo "Set {HOME_VAR} or run: git config --global pipeline.home <pipeline plugin root>" >&2
  exit 1
fi
for py in python python3; do
  if "$py" -c 'import sys; sys.exit(sys.version_info[0] < 3)' </dev/null >/dev/null 2>&1; then
    exec "$py" "$script" --pre-push "$@"
  fi
done
echo "Push blocked: no Python 3 interpreter found on PATH (tried python, python3)." >&2
exit 1
"""
ZERO_SHA = "0" * 40
REMOTE_REFS_MAX = 200


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
            revs = [local_sha, "--not", "--remotes"]
            code, diff = git(["log", "-p", "-m", "--format="] + revs + ["--"] + EXCLUDES, cwd)
        _, names = git(["log", "--name-only", "--format="] + revs, cwd)
        findings = scan(diff, names.splitlines(), load_allowlist(cwd, local_sha))
        if findings:
            sys.stderr.write("Secret scan blocked this push. The commits leaving this machine "
                             "contain:\n- " + "\n- ".join(findings)
                             + "\nRewrite the affected local commits and rotate the secret."
                             + ALLOW_HINT + "\n")
            sys.exit(1)
        warn_new_allowlist_entries(cwd, local_sha, remote_sha)
    sys.exit(0)


def warn_new_allowlist_entries(cwd, local_sha, remote_sha):
    pushed = allowlist_lines(cwd, local_sha)
    known, note = set(), ""
    if remote_sha == ZERO_SHA:
        _, refs = git(["for-each-ref", "--format=%(objectname)", "refs/remotes"], cwd)
        for ref in dict.fromkeys(refs.split()[:REMOTE_REFS_MAX]):
            known |= load_allowlist(cwd, ref)
        note = " (new remote branch; compared with the remote-tracking branches)"
    elif git(["cat-file", "-e", f"{remote_sha}^{{commit}}"], cwd)[0] != 0:
        note = " (remote state unknown; listing all entries in pushed commits)"
    else:
        known = load_allowlist(cwd, remote_sha)
    new = [line for entry, line in pushed.items() if entry not in known]
    if new:
        sys.stderr.write(f"Warning: this push adds entries to {ALLOWLIST_FILE} (secret-scan exceptions){note}. "
                         "Check that you added each one:\n  " + "\n  ".join(new) + "\n")


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
    os.makedirs(hooks_dir, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(PRE_PUSH_SHIM)
    os.chmod(target, 0o755)
    print(f"installed {target}")
    plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")
    print(f"the hook finds the scanner through ${HOME_VAR} or `git config pipeline.home`; "
          f"set it once per machine: git config --global pipeline.home \"{plugin_root}\"")
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
            if char in "()" and not powershell:
                segments.append(char)
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
    subshells = []
    for segment in split_segments(command, powershell):
        if segment == "(":
            subshells.append(len(steps))
            continue
        if segment == ")":
            if subshells:
                del steps[subshells.pop():]
            continue
        tokens, assigns = tokenize(segment, powershell), []
        while tokens and (tokens[0][0].lower() in WRAPPERS
                          or (not powershell and ASSIGNMENT.match(tokens[0][0]))):
            assigns.append(tokens[0][0])
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
        local, configs, rest = [], [], tokens[1:]
        while rest and rest[0][0].startswith("-"):
            option = rest[0][0]
            if option in GIT_VALUE_OPTIONS and len(rest) > 1:
                if option == "-C":
                    local.append(rest[1])
                elif option in ("-c", "--config-env"):
                    configs.append(rest[1][0])
                rest = rest[2:]
            else:
                if option.startswith("-c") and len(option) > 2:
                    configs.append(option[2:])
                rest = rest[1:]
        if rest:
            ops.append({"op": rest[0][0], "steps": steps + local, "tokens": rest[1:],
                        "configs": configs, "assigns": assigns})
    return ops


def shell_quote(text):
    return "'" + text.replace("'", "'\\''") + "'"


def expand_alias(item, cwd, top):
    code, alias = git(["config", "--get", "alias." + item["op"]], cwd)
    alias = alias.strip()
    if code != 0 or not alias:
        return []
    _, builtins = git(["--list-cmds=builtins"], cwd)
    if item["op"] in builtins.split():
        return []
    if alias.startswith("!"):
        script = alias[1:] + "".join(" " + shell_quote(text) for text, _ in item["tokens"])
        return find_git_ops(script, False, [(top, True)])
    tokens = tokenize(alias, False) + item["tokens"]
    return [{"op": tokens[0][0], "steps": item["steps"], "tokens": tokens[1:]}]


def resolve_cwd(steps, base, powershell):
    cwd = base
    for text, literal in steps:
        cwd = resolve_path(text, literal, cwd, powershell)
        if cwd is None:
            return None
    return cwd


UNVERIFIABLE = ("Cannot verify what this git {op} includes: {what} uses a command substitution "
                "or a variable, which this check cannot expand. Use a literal value and run it "
                "again.")
COMMIT_VALUE_FLAGS = "mFCct"
COMMIT_ATTACHED_FLAGS = "Su"
COMMIT_VALUE_OPTIONS = {"--message", "--file", "--reuse-message", "--reedit-message", "--template",
                        "--author", "--date", "--cleanup", "--fixup", "--squash", "--trailer",
                        "--pathspec-from-file"}
ADD_INTERACTIVE = {"-p", "-i", "-e", "--patch", "--interactive", "--edit"}
PUSH_VALUE_OPTIONS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
MAX_ALIAS_EXPANSIONS = 10


def expanded(token):
    text, literal = token
    return not literal and ("$" in text or "`" in text)


def add_args(tokens):
    paths, index = [], 0
    while index < len(tokens):
        text = tokens[index][0]
        if text == "--":
            paths += tokens[index + 1:]
            break
        if not text.startswith("-") or text == "-":
            paths.append(tokens[index])
        index += 1
    if any(expanded(token) for token in paths):
        return None
    if any(token[0] in ADD_INTERACTIVE for token in tokens):
        return ["-A"]
    return [token[0] for token in tokens]


def parse_commit(tokens):
    stage, paths, index = [], [], 0
    while index < len(tokens):
        text = tokens[index][0]
        if text == "--":
            paths += tokens[index + 1:]
            break
        if text.startswith("--"):
            name = text.split("=", 1)[0]
            if name == "--all":
                stage.append(["-u"])
            elif name == "--pathspec-from-file":
                stage.append(["-A"])
            if name in COMMIT_VALUE_OPTIONS and "=" not in text:
                index += 1
        elif text.startswith("-") and len(text) > 1:
            for position, flag in enumerate(text[1:], 1):
                if flag == "a":
                    stage.append(["-u"])
                if flag in COMMIT_ATTACHED_FLAGS:
                    break
                if flag in COMMIT_VALUE_FLAGS:
                    if position == len(text) - 1:
                        index += 1
                    break
        else:
            paths.append(tokens[index])
        index += 1
    if any(expanded(token) for token in paths):
        return None
    if paths:
        stage.append(["--"] + [token[0] for token in paths])
    return stage


def index_env(cwd, adds):
    _, index_path = git(["rev-parse", "--git-path", "index"], cwd)
    real = os.path.abspath(os.path.join(cwd or os.getcwd(), index_path.strip()))
    handle, copy = tempfile.mkstemp(prefix="secretscan-index-")
    os.close(handle)
    if os.path.exists(real):
        shutil.copyfile(real, copy)
    else:
        os.remove(copy)
    env = dict(os.environ, GIT_INDEX_FILE=copy)
    for add_cwd, args in adds:
        git(["add"] + args, add_cwd, env)
    return env, copy


def commit_reason(cwd, top, adds):
    env, copy = index_env(cwd, adds) if adds else (None, None)
    try:
        _, names = git(["diff", "--cached", "--name-only"], cwd, env)
        _, diff = git(["diff", "--cached", "--"] + EXCLUDES, cwd, env)
    finally:
        if copy:
            for leftover in (copy, copy + ".lock"):
                if os.path.exists(leftover):
                    os.remove(leftover)
    findings = scan(diff, names.splitlines(), load_allowlist(top))
    if findings:
        return ("Secret scan blocked this commit. Findings:\n- " + "\n- ".join(findings)
                + "\n\nRemove the secret from the changes this commit records (staged, staged "
                  "by the same command, or named in it) and try again." + ALLOW_HINT)
    return None


def parse_push(tokens):
    flags, positional, index = set(), [], 0
    while index < len(tokens):
        text = tokens[index][0]
        if text == "--":
            positional += tokens[index + 1:]
            break
        if text.startswith("--"):
            name = text.split("=", 1)[0]
            flags.add(name)
            if name in PUSH_VALUE_OPTIONS and "=" not in text:
                index += 1
        elif text.startswith("-") and len(text) > 1:
            flags.update("-" + flag for flag in text[1:])
            if text in PUSH_VALUE_OPTIONS:
                index += 1
        else:
            positional.append(tokens[index])
        index += 1
    refspecs = positional if "--repo" in flags else positional[1:]
    return flags, refspecs


def commit_refs(cwd, patterns):
    _, out = git(["for-each-ref", "--format=%(objecttype)\t%(objectname)\t%(*objecttype)\t"
                  "%(*objectname)\t%(refname)"] + patterns, cwd)
    refs = []
    for line in out.splitlines():
        fields = line.split("\t")
        if len(fields) != 5:
            continue
        kind, sha, peeled_kind, peeled, name = fields
        if kind == "commit":
            refs.append((name, sha))
        elif kind == "tag" and peeled_kind == "commit":
            refs.append((name, peeled))
    return refs


def push_sources(cwd, flags, refspecs):
    every_branch = flags & {"--all", "--branches", "--mirror"}
    every_tag = flags & {"--tags", "--mirror"}
    sources = []
    if every_branch:
        sources += commit_refs(cwd, ["refs/heads"])
    if every_tag:
        sources += commit_refs(cwd, ["refs/tags"])
    texts, index = [], 0
    while index < len(refspecs):
        if expanded(refspecs[index]):
            return None
        text = refspecs[index][0]
        if text == "tag" and index + 1 < len(refspecs):
            if expanded(refspecs[index + 1]):
                return None
            text = "refs/tags/" + refspecs[index + 1][0]
            index += 1
        texts.append(text)
        index += 1
    for text in texts:
        source = text.lstrip("+").split(":", 1)[0]
        if not source:
            continue
        if "*" in source:
            sources += commit_refs(cwd, [source, "refs/heads/" + source])
            continue
        code, sha = git(["rev-parse", "--verify", "--quiet", source + "^{commit}"], cwd)
        if code == 0 and sha.strip():
            sources.append((source, sha.strip()))
    if not texts and not every_branch and not every_tag:
        code, sha = git(["rev-parse", "--verify", "--quiet", "HEAD^{commit}"], cwd)
        if code == 0 and sha.strip():
            sources.append(("HEAD", sha.strip()))
    return sources


def approved_trees(cwd):
    _, common = git(["rev-parse", "--git-common-dir"], cwd)
    git_dir = os.path.abspath(os.path.join(cwd or os.getcwd(), common.strip()))
    approved = set()
    # manager-approved is the pre-rename file name; keep honoring approvals already recorded there
    for name in ("gate-approved", "manager-approved"):
        path = os.path.join(git_dir, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                approved |= {line.split()[0] for line in handle if line.split()}
    return approved, os.path.join(git_dir, "gate-approved")


def push_reason(cwd, top, tokens):
    flags, refspecs = parse_push(tokens)
    if flags & {"--dry-run", "-n", "--delete", "-d"}:
        return None
    sources = push_sources(cwd, flags, refspecs)
    if sources is None:
        return UNVERIFIABLE.format(op="push", what="a ref in the command")
    outgoing = []
    for name, sha in sources:
        _, count = git(["rev-list", "--count", sha, "--not", "--remotes"], cwd)
        if count.strip() not in ("", "0"):
            outgoing.append((name, sha))
    if not outgoing:
        return None
    findings = []
    for sha in sorted({sha for _, sha in outgoing}):
        _, diff = git(["log", "-p", "-m", "--format=", sha, "--not", "--remotes", "--"]
                      + EXCLUDES, cwd)
        _, names = git(["log", "--name-only", "--format=", sha, "--not", "--remotes"], cwd)
        findings += [finding for finding in scan(diff, names.splitlines(), load_allowlist(cwd, sha))
                     if finding not in findings]
    if findings:
        return ("Secret scan blocked this push: the commits about to leave this machine "
                "contain:\n- " + "\n- ".join(findings)
                + "\n\nRemoving it in a later commit is not enough because it stays in "
                  "the history being pushed. Rewrite the affected local commits first."
                + ALLOW_HINT)
    if os.path.isdir(os.path.join(top, "docs", "quality-reports")):
        approved, approvals = approved_trees(cwd)
        missing = []
        for name, sha in outgoing:
            _, tree = git(["rev-parse", sha + "^{tree}"], cwd)
            if tree.strip() not in approved:
                missing.append(f"{name} (tree {tree.strip()[:12]})")
        if missing:
            return ("Push blocked: this project requires the gate agent's approval before "
                    "anything leaves the machine, and these refs have none recorded: "
                    + ", ".join(missing) + ". Run the gate (manager skill, step 5); on "
                    "APPROVED it records the tree in " + approvals + ". Commits made after "
                    "the approval need a new one. To push without this flow, run git push "
                    "yourself in a terminal.")
    return None


FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
RISKY_GIT_ENV = ("GIT_CONFIG", "GIT_PAGER", "PAGER", "GIT_EXTERNAL_DIFF", "GIT_EXEC_PATH", "GIT_EDITOR",
                 "GIT_SEQUENCE_EDITOR", "EDITOR", "VISUAL")
FILE_READERS = {"cat", "type", "head", "tail", "less", "more", "grep", "rg", "wc", "ls", "dir",
                "get-content", "gc", "select-string", "sls", "get-childitem", "gci", "test-path"}
GIT_READERS = {"diff", "log", "show", "blame", "status", "grep", "ls-files", "cat-file",
               "check-ignore", "commit", "push"}
HARMLESS_REDIRECT = re.compile(r"(?i)\d?>&\d|\d?>\s*(?:/dev/null|\$null|nul)(?![\w.-])")
ALLOWLIST_DENY = (ALLOWLIST_FILE + " is maintained only by the user: the secret scan trusts its "
                  "entries, so an agent may not write, stage, move, restore or delete it. Ask the "
                  "user to add the line `<fingerprint>  # reason` to " + ALLOWLIST_FILE
                  + " at the repo root and stage it (git add " + ALLOWLIST_FILE + "). Entries "
                  "count only once staged (for a commit) or committed (for a push). Reading it "
                  "with git diff/log/show or cat is allowed.")


def names_allowlist(text):
    lower = text.lower()
    if ALLOWLIST_FILE in lower:
        return True
    for word in lower.split():
        name = re.split(r"[\\/:]", word)[-1].strip("'\"")
        if not re.search(r"[*?\[]", name):
            continue
        # a bare * or *.* would flag every broad command; git add and commit ask git what the pathspec covers
        if name.startswith(".") or re.sub(r"[*?.\[\]!]", "", name):
            if fnmatch.fnmatchcase(ALLOWLIST_FILE, name):
                return True
    return False


def allowlist_dirty(cwd, untracked):
    code, out = git(["status", "--porcelain", "--untracked-files=all", "--",
                     f":(top,literal){ALLOWLIST_FILE}"], cwd)
    if code != 0:
        return False
    for line in out.splitlines():
        if line.startswith("??"):
            if untracked:
                return True
        elif len(line) > 1 and line[1] != " ":
            return True
    return False


def pathspecs_reach_allowlist(cwd, pathspecs, tracked_only, force=False):
    args = ["ls-files", "--full-name", "-m", "-d"]
    if not tracked_only:
        args += ["-o"] + ([] if force else ["--exclude-standard"])
    code, out = git(args + ["--"] + pathspecs, cwd)
    if code != 0:
        return allowlist_dirty(cwd, untracked=not tracked_only)
    return any(line.strip().lower() == ALLOWLIST_FILE for line in out.splitlines())


def parse_add(tokens):
    flags, paths, unknown, index = [], [], False, 0
    while index < len(tokens):
        text = tokens[index][0]
        if text == "--":
            paths += tokens[index + 1:]
            break
        if text.startswith("--pathspec-from-file"):
            unknown = True
            index += 1 if "=" in text else 2
            continue
        if text.startswith("-") and text != "-":
            flags.append(text)
        else:
            paths.append(tokens[index])
        index += 1
    short = "".join(flag[1:] for flag in flags if not flag.startswith("--"))
    every = "A" in short or any(flag in ("--all", "--no-ignore-removal") for flag in flags)
    update = "u" in short or "--update" in flags
    interactive = any(flag in ADD_INTERACTIVE for flag in flags) or bool(set(short) & set("pie"))
    force = "f" in short or "--force" in flags
    unknown = unknown or any(expanded(token) for token in paths)
    return [text for text, _ in paths], every, (update or interactive) and not every, force, unknown


def add_reaches_allowlist(tokens, cwd):
    paths, every, tracked_only, force, unknown = parse_add(tokens)
    if unknown:
        return allowlist_dirty(cwd, untracked=not tracked_only)
    if not paths:
        if not (every or tracked_only):
            return False
        paths = [":/"]
    return pathspecs_reach_allowlist(cwd, paths, tracked_only, force)


def commit_reaches_allowlist(stage, cwd):
    for args in stage:
        if args == ["-A"]:
            if allowlist_dirty(cwd, untracked=True):
                return True
        elif args == ["-u"]:
            if pathspecs_reach_allowlist(cwd, [":/"], tracked_only=True):
                return True
        elif args[:1] == ["--"] and pathspecs_reach_allowlist(cwd, args[1:], tracked_only=True):
            return True
    return False


def rewires_git(item):
    texts = [text for text, _ in item["tokens"]]
    return (bool(item.get("configs"))
            or any(assign.split("=", 1)[0].upper().startswith(RISKY_GIT_ENV) for assign in item.get("assigns", []))
            or "--ext-diff" in texts
            or any(text.startswith(("-O", "--open-files-in-pager")) for text in texts))


def git_touches_allowlist(item, mentioned_anywhere, base, powershell):
    tokens = item["tokens"]
    mentioned = any(names_allowlist(text) for text, _ in tokens)
    output = any(text == "--output" or text.startswith("--output=") for text, _ in tokens)
    if mentioned_anywhere and (rewires_git(item) or output):
        return True
    op = "add" if item["op"] == "stage" else item["op"]
    if op not in ("add", "commit"):
        return mentioned and op not in GIT_READERS
    if mentioned and op == "add":
        return True
    stage = parse_commit(tokens) if op == "commit" else None
    if op == "commit":
        if stage is None:
            return False
        if any(names_allowlist(path) for args in stage if args[:1] == ["--"] for path in args[1:]):
            return True
    cwd = resolve_cwd(item["steps"], base, powershell)
    if cwd is None:
        return allowlist_dirty(base, untracked=True)
    return add_reaches_allowlist(tokens, cwd) if op == "add" else commit_reaches_allowlist(stage, cwd)


def git_segment_risky(tokens, assigns):
    if any(assign.split("=", 1)[0].upper().startswith(RISKY_GIT_ENV) for assign in assigns):
        return True
    rest = tokens
    while rest and rest[0][0].startswith("-"):
        option = rest[0][0]
        if option.startswith(("-c", "--config-env")):
            return True
        rest = rest[2:] if option in GIT_VALUE_OPTIONS else rest[1:]
    if not rest:
        return False
    if rest[0][0] not in GIT_READERS:
        return True
    return any(text.startswith(("-O", "--open-files-in-pager")) for text, _ in rest[1:])


def touches_allowlist(command, powershell, base=None):
    segments = split_segments(command, powershell)
    mentioned_anywhere = any(names_allowlist(segment) for segment in segments)
    if mentioned_anywhere and ">" in HARMLESS_REDIRECT.sub("", command):
        return True
    for segment in segments:
        if not names_allowlist(segment):
            continue
        tokens, assigns = tokenize(segment, powershell), []
        while tokens and (tokens[0][0].lower() in WRAPPERS
                          or (not powershell and ASSIGNMENT.match(tokens[0][0]))):
            assigns.append(tokens[0][0])
            tokens = tokens[1:]
        if not tokens:
            continue
        name = program(tokens[0][0])
        if name in FILE_READERS:
            continue
        if name != "git" or git_segment_risky(tokens[1:], assigns):
            return True
    return any(git_touches_allowlist(item, mentioned_anywhere, base, powershell)
               for item in find_git_ops(command, powershell))


def is_allowlist_path(target):
    name = re.split(r"[\\/]", re.sub(r"^[A-Za-z]:", "", str(target).strip()))[-1]
    return name.split(":", 1)[0].rstrip(" .").lower() == ALLOWLIST_FILE


def main():
    if "--pre-push" in sys.argv:
        pre_push()
    if "--install-pre-push" in sys.argv:
        install_pre_push()
    if "--fingerprint" in sys.argv:
        print_fingerprints()
    try:
        payload = json.load(sys.stdin)
    except Exception:
        allow()

    tool_input = payload.get("tool_input") or {}
    if payload.get("tool_name") in FILE_TOOLS:
        target = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if is_allowlist_path(target):
            deny(ALLOWLIST_DENY)
        allow()
    command = tool_input.get("command", "") or ""
    powershell = payload.get("tool_name") == "PowerShell"
    base = payload.get("cwd") or None
    if touches_allowlist(command, powershell, base):
        deny(ALLOWLIST_DENY)
    pending, unknown_add = {}, False
    queue, expansions = find_git_ops(command, powershell), 0
    while queue:
        item = queue.pop(0)
        if item["op"] == "stage":
            item["op"] = "add"
        guarded = item["op"] in ("commit", "push")
        cwd = resolve_cwd(item["steps"], base, powershell)
        if cwd is None:
            if item["op"] == "add":
                unknown_add = True
            if not guarded:
                continue
            deny("Cannot verify which repository this git " + item["op"] + " targets: the path "
                 "in the command uses a command substitution or a variable not set in the "
                 "environment. Use a literal path (or cd to it in a separate command) and run "
                 "it again.")
        code, top = git(["rev-parse", "--show-toplevel"], cwd)
        if code != 0:
            continue
        top = top.strip()
        if item["op"] == "add":
            args = add_args(item["tokens"])
            if args is None:
                unknown_add = True
            else:
                pending.setdefault(top, []).append((cwd, args))
            continue
        if not guarded:
            if expansions < MAX_ALIAS_EXPANSIONS:
                expansions += 1
                queue[:0] = expand_alias(item, cwd, top)
            continue
        if item["op"] == "commit":
            stage = parse_commit(item["tokens"])
            if unknown_add:
                deny(UNVERIFIABLE.format(op="commit", what="a git add earlier in the command"))
            if stage is None:
                deny(UNVERIFIABLE.format(op="commit", what="a path in the command"))
            reason = commit_reason(cwd, top, pending.get(top, []) + [(cwd, args) for args in stage])
        else:
            reason = push_reason(cwd, top, item["tokens"])
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
