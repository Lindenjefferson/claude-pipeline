#!/usr/bin/env python3
"""Secret scan for git commits, run as a native git pre-commit hook.

  --install-pre-commit  writes a pre-commit hook that runs --pre-commit. An existing pre-commit hook
                        is kept as pre-commit.pipeline-chained and runs first. A pre-push hook left by
                        an older version of this scanner is removed.
  --pre-commit          scans the index git is about to commit (git sets GIT_INDEX_FILE for it) and
                        blocks on .env-style files and secret-looking lines (cloud keys, tokens,
                        private keys, JWTs other than the public anon key, password/secret
                        assignments with a literal value).
  --fingerprint         prints the fingerprints of the flagged lines read from stdin (a diff, or a
                        file with --path <path>).

A flagged line whose fingerprint (sha256 of its file path and the line with whitespace collapsed) is
listed in .pipeline-secrets-allow at the repo root is not reported; the list is read from the index,
so only staged entries count. This stops accidental leaks, not a determined bypass (git commit
--no-verify skips it); server-side push protection (e.g. GitHub secret scanning) is the last line."""
import base64
import collections
import hashlib
import json
import math
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


class HookError(Exception):
    pass


def git(args, cwd, env=None, data=None, timeout=30):
    feed = {"input": data} if data is not None else {"stdin": subprocess.DEVNULL}
    try:
        result = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, env=env,
                                encoding="utf-8", errors="replace", timeout=timeout, **feed)
        return result.returncode, result.stdout or ""
    except Exception:
        return 1, ""


def git_checked(args, cwd, env=None, data=None):
    code, out = git(args, cwd, env, data=data) if data is not None else git(args, cwd, env)
    if code != 0:
        raise HookError("git " + " ".join(args[:2]) + " failed")
    return out


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
              "entries count; you may not edit "
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
CHAINED = "pre-commit.pipeline-chained"
SHIM = """#!/bin/sh
# """ + HOOK_MARKER + """
chained="$(dirname "$0")/""" + CHAINED + """"
if [ -x "$chained" ]; then
  "$chained" "$@" || exit $?
fi
root="${""" + HOME_VAR + """:-$(git config --get pipeline.home)}"
script="$root/hooks/pre-commit-secret-scan.py"
if [ -z "$root" ] || [ ! -f "$script" ]; then
  echo "Commit blocked: secret scanner not found (looked in '$root')." >&2
  echo "Set """ + HOME_VAR + """ or run: git config --global pipeline.home <pipeline plugin root>" >&2
  exit 1
fi
for py in python python3; do
  if "$py" -c 'import sys; sys.exit(sys.version_info[0] < 3)' </dev/null >/dev/null 2>&1; then
    exec "$py" "$script" --pre-commit "$@"
  fi
done
echo "Commit blocked: no Python 3 interpreter found on PATH (tried python, python3)." >&2
exit 1
"""


def pre_commit():
    cwd = os.getcwd()
    names = git_checked(["diff", "--cached", "--name-only"], cwd)
    diff = git_checked(["diff", "--cached", "--no-ext-diff", "--no-textconv", "--text", "--"] + EXCLUDES, cwd)
    findings = scan(diff, names.splitlines(), load_allowlist(cwd))
    if findings:
        sys.stderr.write("Secret scan blocked this commit. The changes being committed contain:\n- "
                         + "\n- ".join(findings) + "\nRemove the secret from the staged changes and "
                         "commit again." + ALLOW_HINT + "\n")
        sys.exit(1)
    sys.exit(0)


def owned(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        return HOOK_MARKER in handle.read()


def install():
    code, hooks_dir = git(["rev-parse", "--git-path", "hooks"], None)
    if code != 0:
        sys.stderr.write("Not inside a git repository.\n")
        sys.exit(2)
    hooks_dir = os.path.abspath(hooks_dir.strip())
    os.makedirs(hooks_dir, exist_ok=True)
    target, chained = os.path.join(hooks_dir, "pre-commit"), os.path.join(hooks_dir, CHAINED)
    if os.path.exists(target) and not owned(target):
        if os.path.exists(chained):
            sys.stderr.write(f"{target} is not this scanner's hook and {chained} already exists; not overwriting "
                             "either. Merge them by hand and run the install again.\n")
            sys.exit(2)
        os.replace(target, chained)
        print(f"kept the existing pre-commit hook as {chained}; the new hook runs it first")
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(SHIM)
    os.chmod(target, 0o755)
    print(f"installed {target}")
    old_push = os.path.join(hooks_dir, "pre-push")
    if os.path.exists(old_push) and owned(old_push):
        os.remove(old_push)
        print(f"removed {old_push} (this scanner no longer runs on push)")
    plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")
    print(f"the hook finds the scanner through ${HOME_VAR} or `git config pipeline.home`; "
          f"set it once per machine: git config --global pipeline.home \"{plugin_root}\"")
    sys.exit(0)


def run():
    if "--pre-push" in sys.argv:
        # pre-push hooks installed by older versions still call this; the scan now runs only on commit
        sys.exit(0)
    if "--pre-commit" in sys.argv:
        pre_commit()
    if "--install-pre-commit" in sys.argv:
        install()
    if "--fingerprint" in sys.argv:
        print_fingerprints()
    sys.stderr.write("usage: pre-commit-secret-scan.py --install-pre-commit | --pre-commit | --fingerprint "
                     "[--path <file>]\n")
    sys.exit(2)


if __name__ == "__main__":
    try:
        run()
    except Exception as error:
        sys.stderr.write(f"Secret scan failed ({error!r}); blocking the commit. Ask the user to check the "
                         "scanner: a commit made while it fails is not scanned.\n")
        sys.exit(1)
