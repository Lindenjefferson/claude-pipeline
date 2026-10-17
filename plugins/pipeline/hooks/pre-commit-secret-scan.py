#!/usr/bin/env python3
"""Secret scan, UTF-8 and invisible-character checks for git commits, run as a native git pre-commit hook.

  --install-pre-commit  writes a pre-commit hook that runs --pre-commit. An existing pre-commit hook
                        is kept as pre-commit.pipeline-chained and runs first. A pre-push hook left by
                        an older version of this scanner is removed.
  --pre-commit          scans the index git is about to commit (git sets GIT_INDEX_FILE for it) and
                        blocks on added or changed .env-style files (removing one passes) and
                        secret-looking added lines (cloud keys, tokens, private keys, JWTs other than
                        the public anon key, password/secret assignments with a literal value), and
                        blocks added lines that are not valid UTF-8 or hold invisible characters (see
                        below). Lines are read by the hunk headers of the diff, so an added line that
                        starts with ++ is content; NUL bytes are dropped first, so a UTF-16 file is
                        scanned too. File names come from -z listings, so a non-ASCII name is seen.
  --fingerprint         prints the fingerprints of the flagged lines read from stdin (a diff, or a
                        file with --path <path>).

The hook stores no path: it finds this scanner through CLAUDE_PIPELINE_HOME or `git config pipeline.home`
(the plugin root, <clone>/plugins/pipeline; set once per machine with git config --global) and blocks the
commit when neither resolves.

Not flagged: a column assigned to itself, qualified names (t.col, excluded.col), SQL keywords, written-out
identifiers (with _, or camelCase whose parts each have two lower-case letters and a vowel, up to 40
characters) and environment references (process.env.X, ${VAR}, $VAR, os.environ[...], os.getenv(...),
import.meta.env.X, %VAR%). Still blocked: secret-looking quoted literals (a placeholder passes only as the whole
value, such as changeme, example, xxxx, or starting with your_, your- or <); runs of 16+ characters without _
in one case or alternating case; values where almost every character is unique (Shannon entropy of 3.5
bits/character or more, near the maximum for the length); and, under password/passwd/secret keys, phrases with
_ that name no code word and unquoted values of 12+ characters with three character classes and a symbol other
than - . _ $ (a call, a URL, a template or code such as a type, a subscript or a qualified name does not count).

Invisible characters: added lines with a zero-width space or word joiner (U+200B, U+2060 to U+2064, U+180E), a
direction control (U+202A to U+202E, U+2066 to U+2069), a Tag character (U+E0000 to U+E007F) or a BOM anywhere but
the very start of a file are refused with file, first line and first code point; this is how instructions are
hidden in prompt files. The joiner and non-joiner of emoji and of Persian or Indic text (U+200C, U+200D) and the
direction marks (U+200E, U+200F) are not flagged. Like the UTF-8 check it reads added lines only and has no allowlist.

UTF-8 check: the same --pre-commit run refuses added lines of text files that do not decode as UTF-8 (typically
Latin-1 or Windows-1252 text saved by an old editor) and names each file with its first bad line; the fix is to
re-save the file as UTF-8 (iconv -f WINDOWS-1252 -t UTF-8, or the editor's "Save with Encoding"). Only added lines
count, so a legacy line already committed is not flagged again. Binary files (git sees a NUL byte, as in images
and UTF-16) are skipped, and so are the lock files the secret scan skips. It lives here, not in its own module,
because the installed pre-commit shim runs only this script. It has no allowlist: fix the file.

False positive: the user (never an agent: kickoff denies agents edits to the file) adds the line
`<fingerprint>  # reason` to .pipeline-secrets-allow at the repo root and stages it; the block message gives
the fingerprint, and --fingerprint lists them (git diff --cached --text | python <this file> --fingerprint; for a
whole file, --fingerprint --path <path> < <path>). A fingerprint is the sha256 of the file path and the line
with whitespace collapsed: it frees only that exact line in that file, and editing either needs a new entry.
The list is read from the index, so only staged entries count; there is no in-code suppression, and a real
secret is removed and rotated, never allowlisted. This stops accidental leaks, not a determined bypass (git
commit --no-verify skips it); server-side push protection (e.g. GitHub secret scanning) is the last line."""
import base64
import codecs
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
    ("private key header", r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY( BLOCK)?-----"),
    ("Stripe live key", r"[rs]k_live_[0-9A-Za-z]{16,}"),
    ("Supabase secret key", r"sb_secret_[A-Za-z0-9_\-]{20,}"),
    ("Anthropic API key", r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    ("OpenAI API key", r"\bsk-(?:(?:proj|svcacct|admin)-[A-Za-z0-9_\-]{20,}|[A-Za-z0-9]{40,})"),
    ("Google API key", r"AIza[0-9A-Za-z_\-]{35}"),
    ("xAI API key", r"\bxai-[A-Za-z0-9]{20,}"),
    ("GitHub fine-grained token", r"github_pat_[A-Za-z0-9_]{22,}"),
    ("Linear API key", r"lin_api_[A-Za-z0-9]{30,}"),
    ("Stripe webhook secret", r"whsec_[A-Za-z0-9]{24,}"),
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
CODE_REFERENCE = re.compile(r"[A-Za-z_$][\w$]*(?:\.|::|\?\.|\[|<)")
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


def git_bytes(args, cwd):
    try:
        result = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, stdin=subprocess.DEVNULL, timeout=30)
        return result.returncode, result.stdout or b""
    except Exception:
        return 1, b""


def git(args, cwd):
    code, out = git_bytes(args, cwd)
    return code, out.decode("utf-8", "replace")


def git_checked(args, cwd):
    code, out = git_bytes(args, cwd)
    if code != 0:
        raise HookError("git " + " ".join(args[:2]) + " failed")
    return out


def names(listing):
    """The paths of a -z name listing (git quotes nothing there, so a non-ASCII name stays as it is)."""
    return sorted({name.strip("\n") for name in listing.decode("utf-8", "replace").split("\0")} - {""})


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


def unquoted_password(name, rest):
    words = rest.split()
    word = words[0].rstrip(",;") if words and PASSWORD_KEY.search(name) else ""
    if "(" in word or "://" in word or TEMPLATED.search(word) or PLACEHOLDER.search(word) or CODE_REFERENCE.match(word):
        return False
    return len(word) >= 12 and char_classes(word) >= 3 and bool(re.search(r"[^\w.$-]", word))


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
        elif unquoted_secret(name, rest) or unquoted_password(name, rest):
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


HUNK = re.compile(rb"@@ -\S+ \+(\d+)(?:,(\d+))? @@")


def diff_path(header):
    name = header.strip()
    if name.startswith(b'"') and name.endswith(b'"'):
        name = codecs.escape_decode(name[1:-1])[0]
    path = name.decode("utf-8", "replace")
    return path[2:] if path.startswith("b/") else None if path == "/dev/null" else path


def diff_lines(diff):
    """(path, line number, raw bytes) of every added line of a unified diff, counted by its hunk headers, so an
    added line that starts with ++ is content and a +++ header is only read between hunks."""
    if isinstance(diff, str):
        diff = diff.encode("utf-8", "replace")
    path, number, remaining = None, 0, 0
    for raw in diff.split(b"\n"):
        if remaining <= 0:
            hunk = HUNK.match(raw)
            if raw.startswith(b"+++ "):
                path = diff_path(raw[4:])
            elif hunk:
                number = int(hunk.group(1))
                remaining = int(hunk.group(2) if hunk.group(2) is not None else 1)
            continue
        if raw.startswith((b"-", b"\\")):
            continue
        if raw.startswith(b"+"):
            yield path, number, raw[1:]
        number += 1
        remaining -= 1


def text_of(raw):
    # why: a UTF-16 file has a NUL after (or before) every ASCII character, which hides a key from every pattern
    return raw.replace(b"\0", b"").decode("utf-8", "replace")


def load_allowlist(cwd, rev=""):
    code, text = git(["show", f"{rev}:{ALLOWLIST_FILE}"], cwd)
    entries = (line.split("#", 1)[0].strip().lower() for line in text.splitlines()) if code == 0 else ()
    return {entry for entry in entries if re.fullmatch(r"[0-9a-f]{64}", entry)}


def scan(diff, names, allowed=frozenset()):
    findings = []
    env_files = sorted({n for n in names
                        if re.search(r"(^|/)\.env(\..+)?$", n)
                        and not n.endswith((".example", ".sample"))})
    if env_files:
        findings.append(".env-style file(s): " + ", ".join(env_files))
    seen = set()
    for path, _, raw in diff_lines(diff):
        line = text_of(raw)
        labels = line_findings(line)
        if not labels:
            continue
        mark = fingerprint(path, line)
        if mark in allowed or mark in seen:
            continue
        seen.add(mark)
        where = f" in {path}" if path else " in added lines"
        findings.append(f"possible {', '.join(labels)}{where} (fingerprint {mark})")
    return findings


ALLOW_HINT = ("\n\nFor a false positive, leave that line out and commit the rest, or ask the user "
              "to allowlist that exact line: they add `<fingerprint>  # reason` to " + ALLOWLIST_FILE
              + " at the repo root and stage it (git add " + ALLOWLIST_FILE + "). Only staged "
              "entries count; you may not edit "
              "or stage that file yourself. The fingerprint covers the file path and the line, "
              "so any edit to either changes it. To list the fingerprints of flagged lines: git "
              "diff --cached --text | python \"" + os.path.abspath(__file__).replace("\\", "/")
              + "\" --fingerprint")


def print_fingerprints():
    given = sys.argv[sys.argv.index("--path") + 1] if "--path" in sys.argv[:-1] else None
    data = sys.stdin.buffer.read()
    diff = re.search(rb"^(diff --git|@@ )", data, re.M)
    if not diff and given is None:
        sys.stderr.write("Plain text input needs --path <file path relative to the repo root>, "
                         "because the fingerprint covers the path.\n")
        sys.exit(2)
    entries = diff_lines(data) if diff else ((given, 0, raw) for raw in data.split(b"\n"))
    for path, _, raw in entries:
        line = text_of(raw)
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


INVISIBLE = re.compile(r"[\u180e\u200b\u2060-\u2064\u202a-\u202e\u2066-\u2069\ufeff\U000e0000-\U000e007f]")


def text_problems(cwd):
    """({path: (first line, count)} not valid UTF-8, {path: (first line, count, first code point)} with
    invisible characters) over the added lines of the staged text files."""
    bad, hidden = {}, {}
    diff = git_checked(["diff", "--cached", "--no-ext-diff", "--no-textconv", "-U0", "--"] + EXCLUDES, cwd)
    for path, number, raw in diff_lines(diff):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            first, count = bad.get(path, (number, 0))
            bad[path] = (first, count + 1)
            continue
        for match in INVISIBLE.finditer(text):
            if match.group() == "\ufeff" and number == 1 and match.start() == 0:
                continue
            first, count, code = hidden.get(path, (number, 0, match.group()))
            hidden[path] = (first, count + 1, code)
            break
    return bad, hidden


def pre_commit():
    cwd = os.getcwd()
    staged = names(git_checked(["diff", "--cached", "--name-only", "-z", "--diff-filter=d"], cwd))
    diff = git_checked(["diff", "--cached", "--no-ext-diff", "--no-textconv", "--text", "--"] + EXCLUDES, cwd)
    findings = scan(diff, staged, load_allowlist(cwd))
    bad_encoding, hidden = text_problems(cwd)
    if findings:
        sys.stderr.write("Secret scan blocked this commit. The changes being committed contain:\n- "
                         + "\n- ".join(findings) + "\nRemove the secret from the staged changes and "
                         "commit again." + ALLOW_HINT + "\n")
    if bad_encoding:
        listed = [f"{path or 'added lines'}:{first} ({count} line{'s' * (count != 1)})"
                  for path, (first, count) in sorted(bad_encoding.items(), key=str)]
        sys.stderr.write("UTF-8 check blocked this commit. Added lines that are not valid UTF-8:\n- "
                         + "\n- ".join(listed) + "\nRe-save each file as UTF-8 (iconv -f WINDOWS-1252 -t UTF-8 "
                         "<file> > <tmp>, then move <tmp> over the file; or the editor's \"Save with "
                         "Encoding\"), stage it again and commit again.\n")
    if hidden:
        listed = [f"{path or 'added lines'}:{first} ({count} line{'s' * (count != 1)}, first U+{ord(code):04X})"
                  for path, (first, count, code) in sorted(hidden.items(), key=str)]
        sys.stderr.write("Invisible-character check blocked this commit. Added lines with invisible or "
                         "direction-control characters (they can hide instructions in prompts and code):\n- "
                         + "\n- ".join(listed) + "\nRemove them (delete and retype the line, or search for the "
                         "code point), stage the file again and commit again.\n")
    sys.exit(1 if findings or bad_encoding or hidden else 0)


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
