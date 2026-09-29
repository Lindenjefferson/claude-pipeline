#!/usr/bin/env python3
"""Secret scan and push gate for git, run as a Claude Code PreToolUse hook and as native git hooks.

Native git hooks (the enforcement; kickoff installs both):
  --install-pre-commit  writes a pre-commit hook that runs --pre-commit: it scans the index git is
                        about to commit (git sets GIT_INDEX_FILE for it), with the allowlist read
                        from that index. An existing pre-commit hook is kept as
                        pre-commit.pipeline-chained and runs first.
  --install-pre-push    writes a pre-push hook that runs --pre-push: it scans the commits leaving
                        the machine. What the remote already has comes from `git ls-remote` of the
                        push URL, never from remote-tracking refs alone; when a url.*.insteadOf
                        rewrite would send that ls-remote to another URL than the push, it warns and
                        uses that remote's remote-tracking refs (at most 1000 unknown commits).
                        ls-remote runs ssh in batch mode and is killed with its process tree on
                        timeout.
                        It only scans: the gate is not checked here.
  --enable-gate         sets `git config pipeline.gate true`, which turns the push gate on.

Threat model: these are client-side hooks. They stop accidental leaks and a cooperative agent's
shortcuts; an agent that deliberately writes scripts, calls interpreters or crafts git config can
still get around them. The last line is server-side push protection (e.g. GitHub secret scanning
push protection).

PreToolUse (first line, parses the command text of Claude's Bash/PowerShell calls):
commit: blocks when what the commit would record adds a secret-looking string or an .env-style
        file (staged diff plus what the same command stages first, paths given to the commit,
        `commit -a`), staged into a throwaway copy of the index.
push:   blocks when the commits about to leave the machine add such content, and, when the gate
        is on (pipeline.gate config, or docs/quality-reports/ in the working tree or the pushed
        tree), unless the gate agent recorded approval of the tree of every pushed ref in
        <git-common-dir>/gate-approved (legacy name: manager-approved). When insteadOf would
        send ls-remote to another URL than the push (pushInsteadOf, else insteadOf) goes to, it
        does not trust ls-remote and uses the remote-tracking refs.
It also denies what would switch the native hooks off or fool the push check: --no-verify on git
and no-verify inside the inline code of an interpreter (-c, -e, -Command, a heredoc) or after
git in xargs, eval or find -exec, core.hooksPath writes (reads pass),
git config writes of pipeline.*, url.*.insteadOf and remote.*.url/pushurl/fetch, writes to the
global git config files (the destination of a copy, not its source), edits of .git/hooks, the
core.hooksPath folder, .git/config and config.worktree (paths normalised, globs considered,
$variables resolved and an unresolved one counted when the rest of the path can end there, cd
into the git dir followed by a write, find -delete or a writing -exec over it unless the
expression excludes it before the action, by a negated -path or by a -name/-path that matches
neither a hook file, the config nor their parent folders), repointing
refs/remotes/*, fetching into refs/remotes/* with an explicit refspec, and remotes that point at
a local path. It warns on stderr on every commit and push while the native hooks are missing.
A flagged line whose fingerprint (sha256 of its file path and the line with whitespace collapsed)
is listed in .pipeline-secrets-allow at the repo root is not reported; the list is read from the
index for a commit and from each pushed ref's tree for a push, and agents may not edit it.
`--fingerprint` prints the fingerprints of flagged lines read from stdin.
On an internal error the PreToolUse hook denies any command that may run a git add, commit, push,
config, fetch or ref change (aliases included) or that names the allowlist; the native hooks block."""
import base64
import collections
import fnmatch
import hashlib
import json
import math
import os
import re
import shutil
import signal
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
CHAINED_SUFFIX = ".pipeline-chained"
SHIM_CHAIN = """chained="$(dirname "$0")/{stage}""" + CHAINED_SUFFIX + """"
if [ -x "$chained" ]; then
  "$chained" "$@" || exit $?
fi
"""
SHIM_BODY = """root="${{""" + HOME_VAR + """:-$(git config --get pipeline.home)}}"
script="$root/hooks/pre-commit-secret-scan.py"
if [ -z "$root" ] || [ ! -f "$script" ]; then
  echo "{what} blocked: secret scanner not found (looked in '$root')." >&2
  echo "Set """ + HOME_VAR + """ or run: git config --global pipeline.home <pipeline plugin root>" >&2
  exit 1
fi
for py in python python3; do
  if "$py" -c 'import sys; sys.exit(sys.version_info[0] < 3)' </dev/null >/dev/null 2>&1; then
    exec "$py" "$script" --{stage} "$@"
  fi
done
echo "{what} blocked: no Python 3 interpreter found on PATH (tried python, python3)." >&2
exit 1
"""
NATIVE_HOOKS = {"pre-commit": ("Commit", True), "pre-push": ("Push", False)}
ZERO_SHA = "0" * 40
LS_REMOTE_TIMEOUT = 15
FALLBACK_CAP = 1000
UNKNOWN_REMOTE = ("Cannot tell which commits {remote} already has: git ls-remote failed (offline, no "
                  "access, or a transport this check does not run), and {count} commits of {ref} are not "
                  "on its remote-tracking refs, more than the {cap} this check scans without knowing the "
                  "remote's state. Check the connection, or run git fetch for that remote to refresh its "
                  "remote-tracking refs, and push again.")
REWRITE_WARNING = ("Warning: a git URL rewrite sends git ls-remote for {remote} to a different URL than "
                   "the push ({rewrites}). This check is using the remote-tracking refs of {remote} "
                   "instead, which may be stale.\n")
URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/@\s]*@")


def redact(text):
    return URL_USERINFO.sub(r"\1", str(text))


def shown(text):
    return printable(redact(text))


def url_rewrites(cwd):
    code, out = git(["config", "-z", "--get-regexp", r"^url\..*\.(push)?insteadof$"], cwd)
    if code not in (0, 1):
        raise HookError("git config --get-regexp url.*.insteadOf failed")
    rules = {"fetch": [], "push": []}
    for entry in out.split("\0"):
        key, newline, prefix = entry.partition("\n")
        if not newline:
            continue
        kind = "push" if key.lower().endswith(".pushinsteadof") else "fetch"
        base = key[len("url."):key.rfind(".")]
        rules[kind].append((prefix, base, key))
    return rules


def rewritten(url, rules):
    matches = [rule for rule in rules if url.startswith(rule[0])]
    if not matches:
        return url, None
    prefix, base, key = max(matches, key=lambda rule: len(rule[0]))
    return base + url[len(prefix):], f"{key} = {prefix}"


def configured_push_urls(cwd, remote, rules):
    found = {}
    for key in ("url", "pushurl"):
        code, out = git(["config", "--get-all", f"remote.{remote}.{key}"], cwd)
        found[key] = [line.strip() for line in out.splitlines() if line.strip()] if code == 0 else []
    if found["pushurl"]:
        return [rewritten(url, rules["fetch"])[0] for url in found["pushurl"]]
    targets = []
    for url in found["url"] or [remote]:
        pushed, rule = rewritten(url, rules["push"])
        targets.append(pushed if rule else rewritten(url, rules["fetch"])[0])
    return targets


def split_rewrites(rules, push_targets):
    active = []
    for target in push_targets:
        listed, rule = rewritten(target, rules["fetch"])
        if listed != target:
            active.append(f"{rule} (ls-remote would ask {listed}, the push goes to {target})")
    return active


def shim(stage):
    what, chains = NATIVE_HOOKS[stage]
    body = SHIM_BODY.format(what=what, stage=stage)
    return "#!/bin/sh\n# " + HOOK_MARKER + "\n" + (SHIM_CHAIN.format(stage=stage) if chains else "") + body


def batch_ssh_command(cwd):
    command = os.environ.get("GIT_SSH_COMMAND")
    if not command:
        code, out = git(["config", "core.sshCommand"], cwd)
        command = out.strip() if code == 0 else ""
    if not command and os.environ.get("GIT_SSH"):
        return None
    return (command or "ssh") + " -o BatchMode=yes -o ConnectTimeout=10"


def kill_tree(process):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True, timeout=10)
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except Exception:
        process.kill()


def run_bounded(args, cwd, env, timeout):
    group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})
    try:
        process = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, encoding="utf-8", errors="replace", **group)
    except Exception:
        return 1, ""
    try:
        out, _ = process.communicate(timeout=timeout)
        return process.returncode, out or ""
    except subprocess.TimeoutExpired:
        kill_tree(process)
        try:
            process.communicate(timeout=5)
        except Exception:
            pass
        return 1, ""


def ls_remote(cwd, url):
    if not url or url.startswith("-"):
        return None
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    ssh = batch_ssh_command(cwd)
    if ssh:
        env["GIT_SSH_COMMAND"] = ssh
    code, out = run_bounded(["git", "-c", "protocol.ext.allow=never", "ls-remote", url], cwd, env,
                            LS_REMOTE_TIMEOUT)
    if code != 0:
        return None
    return {line.split()[0] for line in out.splitlines() if re.match(r"^[0-9a-f]{40,64}\s", line)}


def local_commits(cwd, shas):
    if not shas:
        return []
    out = git_checked(["cat-file", "--batch-check=%(objectname) %(objecttype)"], cwd,
                      data="".join(sha + "^{commit}\n" for sha in sorted(shas)))
    return sorted({line.split()[0] for line in out.splitlines() if line.endswith(" commit")})


def tracking_commits(cwd, name):
    if not name or git(["check-ref-format", f"refs/remotes/{name}/x"], cwd)[0] != 0:
        return set()
    return set(git_checked(["for-each-ref", "--format=%(objectname)", f"refs/remotes/{name}/"], cwd).split())


def remote_bases(cwd, urls, name, known=(), trust_remote=True):
    seen = None
    for url in urls if trust_remote else []:
        shas = ls_remote(cwd, url)
        if shas is None:
            seen = None
            break
        seen = shas if seen is None else seen & shas
    if seen is not None:
        return local_commits(cwd, seen | set(known)), False
    return local_commits(cwd, tracking_commits(cwd, name) | set(known)), True


def revs_input(sha, bases):
    return sha + "\n" + "".join("^" + base + "\n" for base in bases)


def outgoing_count(cwd, sha, bases):
    return int(git_checked(["rev-list", "--count", "--stdin"], cwd, data=revs_input(sha, bases)).strip() or 0)


def outgoing_changes(cwd, sha, bases):
    data = revs_input(sha, bases)
    diff = git_checked(["log", "-p", "-m", "--no-ext-diff", "--no-textconv", "--text", "--format=", "--stdin", "--"]
                       + EXCLUDES, cwd, data=data)
    names = git_checked(["log", "--name-only", "-m", "--format=", "--stdin"], cwd, data=data)
    return diff, names.splitlines()


def pre_push():
    cwd = os.getcwd()
    args = sys.argv[sys.argv.index("--pre-push") + 1:]
    remote = args[0] if args else None
    url = args[1] if len(args) > 1 else remote
    updates = [(parts[1], parts[3]) for parts in (line.split() for line in sys.stdin)
               if len(parts) >= 4 and parts[1] != ZERO_SHA]
    if not updates:
        sys.exit(0)
    rewrites = split_rewrites(url_rewrites(cwd), [url] if url else [])
    if rewrites:
        sys.stderr.write(REWRITE_WARNING.format(remote=shown(remote or url or "the remote"),
                                                rewrites=shown("; ".join(rewrites))))
    known = {remote_sha for _, remote_sha in updates if remote_sha != ZERO_SHA}
    bases, fallback = remote_bases(cwd, [url] if url else [], remote, known, trust_remote=not rewrites)
    for local_sha, remote_sha in updates:
        count = outgoing_count(cwd, local_sha, bases)
        if fallback and count > FALLBACK_CAP:
            sys.stderr.write("Push blocked. " + UNKNOWN_REMOTE.format(
                remote=shown(url or "the remote"), count=count, ref=local_sha[:12], cap=FALLBACK_CAP) + "\n")
            sys.exit(1)
        diff, names = outgoing_changes(cwd, local_sha, bases) if count else ("", [])
        findings = scan(diff, names, load_allowlist(cwd, local_sha))
        if findings:
            sys.stderr.write("Secret scan blocked this push. The commits leaving this machine "
                             "contain:\n- " + "\n- ".join(findings)
                             + "\nRewrite the affected local commits and rotate the secret."
                             + ALLOW_HINT + "\n")
            sys.exit(1)
        warn_new_allowlist_entries(cwd, local_sha, remote_sha, remote)
    sys.exit(0)


def staged_findings(cwd, env=None, allowed=None):
    names = git_checked(["diff", "--cached", "--name-only"], cwd, env)
    diff = git_checked(["diff", "--cached", "--no-ext-diff", "--no-textconv", "--text", "--"] + EXCLUDES, cwd, env)
    return scan(diff, names.splitlines(), load_allowlist(cwd) if allowed is None else allowed)


def pre_commit():
    findings = staged_findings(os.getcwd())
    if findings:
        sys.stderr.write("Secret scan blocked this commit. The changes being committed contain:\n- "
                         + "\n- ".join(findings) + "\nRemove the secret from the staged changes and "
                         "commit again." + ALLOW_HINT + "\n")
        sys.exit(1)
    sys.exit(0)


def printable(text):
    return "".join(char if char.isprintable()
                   else f"\\x{ord(char):02x}" if ord(char) < 0x100
                   else f"\\u{ord(char):04x}" if ord(char) < 0x10000
                   else f"\\U{ord(char):08x}"
                   for char in text)


def remote_default_branch(cwd, remote):
    if not remote:
        return None
    for name in ("HEAD", "main", "master"):
        ref = f"refs/remotes/{remote}/{name}"
        if git(["check-ref-format", ref], cwd)[0] != 0:
            return None
        code, sha = git(["rev-parse", "--verify", "--quiet", ref + "^{commit}"], cwd)
        if code == 0 and sha.strip():
            return ref, sha.strip()
    return None


def warn_new_allowlist_entries(cwd, local_sha, remote_sha, remote):
    pushed = allowlist_lines(cwd, local_sha)
    known, note = set(), ""
    if remote_sha == ZERO_SHA:
        default = remote_default_branch(cwd, remote)
        if default:
            known = load_allowlist(cwd, default[1])
            note = f" (new remote branch; compared with {default[0]})"
        else:
            note = (" (new remote branch and no default branch known for this remote; listing every "
                    "entry in the pushed allowlist)")
    elif git(["cat-file", "-e", f"{remote_sha}^{{commit}}"], cwd)[0] != 0:
        note = " (remote state unknown; listing every entry in the pushed allowlist)"
    else:
        known = load_allowlist(cwd, remote_sha)
    new = [line for entry, line in pushed.items() if entry not in known]
    if new:
        sys.stderr.write(f"Warning: this push adds entries to {ALLOWLIST_FILE} (secret-scan exceptions)"
                         f"{printable(note)}. Check that you added each one:\n  "
                         + "\n  ".join(printable(line) for line in new) + "\n")


def install_native(stage, hooks_dir):
    target = os.path.join(hooks_dir, stage)
    chained = target + CHAINED_SUFFIX
    if os.path.exists(target):
        with open(target, encoding="utf-8", errors="replace") as handle:
            foreign = HOOK_MARKER not in handle.read()
        if foreign and not NATIVE_HOOKS[stage][1]:
            sys.stderr.write(f"A {stage} hook already exists at {target}; not overwriting it.\n")
            return False
        if foreign and os.path.exists(chained):
            sys.stderr.write(f"{target} is not this scanner's hook and {chained} already exists; "
                             "not overwriting either. Merge them by hand and run the install again.\n")
            return False
        if foreign:
            os.replace(target, chained)
            print(f"kept the existing {stage} hook as {chained}; the new hook runs it first")
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(shim(stage))
    os.chmod(target, 0o755)
    print(f"installed {target}")
    return True


def install():
    code, hooks_dir = git(["rev-parse", "--git-path", "hooks"], None)
    if code != 0:
        sys.stderr.write("Not inside a git repository.\n")
        sys.exit(2)
    hooks_dir = os.path.abspath(hooks_dir.strip())
    ok, stages = True, [stage for stage in NATIVE_HOOKS if f"--install-{stage}" in sys.argv]
    if stages:
        os.makedirs(hooks_dir, exist_ok=True)
    for stage in stages:
        ok = install_native(stage, hooks_dir) and ok
    if "--enable-gate" in sys.argv:
        if git(["config", "--local", "pipeline.gate", "true"], None)[0] == 0:
            print("push gate on: git config pipeline.gate true")
        else:
            sys.stderr.write("Could not set git config pipeline.gate true.\n")
            ok = False
    if stages:
        plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")
        print(f"the hooks find the scanner through ${HOME_VAR} or `git config pipeline.home`; "
              f"set it once per machine: git config --global pipeline.home \"{plugin_root}\"")
    sys.exit(0 if ok else 2)


SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
POWERSHELLS = {"powershell", "pwsh"}
WRAPPERS = {"command", "builtin", "exec", "nohup", "time", "env", "sudo", "noglob", "&", "."}
CD_BASH = {"cd", "pushd"}
CD_POWERSHELL = {"cd", "chdir", "set-location", "sl", "pushd", "push-location"}
GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path",
                     "--super-prefix", "--config-env", "--list-cmds"}
RELOCATING_OPTIONS = {"--git-dir", "--work-tree", "--namespace"}
RELOCATING_ENV = {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_NAMESPACE"}
CONFIG_ENV = {"GIT_CONFIG", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"}
WATCHED_ENV = RELOCATING_ENV | CONFIG_ENV
RELOCATING_NAMES = "(?:" + "|".join(sorted(RELOCATING_ENV)) + ")"
RELOCATING_DEFAULT = re.compile(r"\$\{" + RELOCATING_NAMES + r":?=")
BASH_SETTERS = {"export", "declare", "typeset", "local", "readonly", "read"}
PS_ENV_WRITERS = {"set-item", "si", "new-item", "ni", "set-content", "sc", "add-content", "ac", "copy-item",
                  "copy", "cpi", "move-item", "mi", "rename-item", "rni"}
PS_ENV_ASSIGN = re.compile(r"(?i)\$\{?env:([^\s=}]+)\}?\s*[+]?=(?!=)")
PS_SET_ENV = re.compile(r"(?i)environment\]::setenvironmentvariable\(\s*(?:(['\"])([^'\"]*)\1\s*,)?")
SOURCING = {"source", ".", "eval", "invoke-expression", "iex"}
REMOTE_REF_TOOLS = {"update-ref", "symbolic-ref"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
BASH_ESCAPABLE_IN_QUOTES = '$`"\\\n'


def is_escape(text, index, powershell, quoted):
    if index + 1 >= len(text):
        return False
    if powershell:
        return text[index] == "`"
    if text[index] != "\\":
        return False
    return not quoted or text[index + 1] in BASH_ESCAPABLE_IN_QUOTES


def split_segments(command, powershell):
    segments, current, quote, index, braces = [], [], None, 0, 0
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
        elif char == "{" and command[index + 1:index + 2] == "}":
            current.append("{}")
            index += 1
        elif char == "{" and current and current[-1] == "$":
            current.append(char)
            braces += 1
        elif char == "}" and braces:
            current.append(char)
            braces -= 1
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
        elif is_escape(segment, index, powershell, False):
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


def strip_reserved(tokens, powershell):
    while tokens and not powershell and tokens[0][0] in BASH_RESERVED:
        tokens = tokens[1:]
    return tokens


def inline_script(tokens, flags):
    for position, (text, _) in enumerate(tokens[:-1]):
        if text.lower() in flags:
            return tokens[position + 1][0]
    return None


def assignment_value(name, assigns):
    for assign in reversed(assigns):
        key, _, value = assign.partition("=")
        if key == name:
            return value
    return os.environ.get(name)


def git_options(tokens, assigns):
    local, configs, pairs, relocated, rest = [], [], [], False, tokens
    while rest and rest[0][0].startswith("-"):
        option = rest[0][0]
        name, has_value, attached = option.partition("=")
        relocated = relocated or name in RELOCATING_OPTIONS
        setting, from_env = None, False
        if name == "--config-env" and has_value:
            setting, from_env, rest = attached, True, rest[1:]
        elif option in GIT_VALUE_OPTIONS and len(rest) > 1:
            if option == "-C":
                local.append(rest[1])
            elif option in ("-c", "--config-env"):
                setting, from_env = rest[1][0], option == "--config-env"
            rest = rest[2:]
        else:
            if option.startswith("-c") and len(option) > 2:
                setting = option[2:]
            rest = rest[1:]
        if setting is not None:
            key, _, value = setting.partition("=")
            configs.append(setting)
            pairs.append((key.lower(), assignment_value(value, assigns) if from_env else value))
    return local, configs, pairs, relocated, rest


def dynamic_or_watched(name):
    return name.upper() in WATCHED_ENV or bool(re.search(r"[$`(*?\[]", name))


def bash_sets_env(name, texts):
    if name == "printf":
        texts = texts + [""]
        targets = [text[2:] or texts[index + 1] for index, text in enumerate(texts[:-1]) if text.startswith("-v")]
        return any(dynamic_or_watched(target) for target in targets)
    if name in BASH_SETTERS:
        return any(dynamic_or_watched(text.split("=", 1)[0]) for text in texts if not text.startswith(("-", "+")))
    return False


def powershell_sets_env(name, texts):
    if name not in PS_ENV_WRITERS:
        return False
    lowered = [text.lower() for text in texts]
    for text in texts:
        path = re.match(r"(?i)^env:[\\/]?(.*)$", text)
        if path:
            target = path.group(1)
            if not target and "-name" in lowered[:-1]:
                target = texts[lowered.index("-name") + 1]
            if not target or dynamic_or_watched(target):
                return True
    return False


def sets_relocating_var(segment, tokens, assigns, powershell):
    if any(assign.split("=", 1)[0].upper() in RELOCATING_ENV for assign in assigns):
        return True
    unquoted = " ".join(text for text, _ in tokens)
    if RELOCATING_DEFAULT.search(segment) or RELOCATING_DEFAULT.search(unquoted):
        return True
    if not tokens:
        return False
    name, texts = program(tokens[0][0]), [text for text, _ in tokens[1:]]
    if powershell:
        return powershell_sets_env(name, texts)
    return bash_sets_env(name, texts)


def runs_sourced_code(tokens, stripped, powershell):
    if any(text.lower() in SOURCING for text in stripped):
        return True
    if not tokens:
        return False
    name = program(tokens[0][0])
    if name in SOURCING:
        return True
    texts = [text for text, _ in tokens[1:]]
    return (not powershell and name == "set"
            and (any(re.fullmatch(r"-[A-Za-z]*a[A-Za-z]*", text) for text in texts) or "allexport" in texts))


def find_git_ops(command, powershell, steps=None, ops=None, env=None):
    steps = [] if steps is None else steps
    ops = [] if ops is None else ops
    env = {"relocated": False} if env is None else env
    if powershell and (any(dynamic_or_watched(match.group(1)) for match in PS_ENV_ASSIGN.finditer(command))
                       or any(match.group(2) is None or dynamic_or_watched(match.group(2))
                              for match in PS_SET_ENV.finditer(command))):
        env["relocated"] = True
    subshells = []
    for segment in split_segments(command, powershell):
        if segment == "(":
            subshells.append(len(steps))
            continue
        if segment == ")":
            if subshells:
                del steps[subshells.pop():]
            continue
        tokens, assigns = strip_reserved(tokenize(segment, powershell), powershell), []
        while tokens and (tokens[0][0].lower() in WRAPPERS
                          or (not powershell and ASSIGNMENT.match(tokens[0][0]))):
            assigns.append(tokens[0][0])
            tokens = strip_reserved(tokens[1:], powershell)
        if (sets_relocating_var(segment, tokens, assigns, powershell)
                or runs_sourced_code(tokens, assigns, powershell)):
            env["relocated"] = True
        if not tokens:
            continue
        name = program(tokens[0][0])
        if name in SHELLS:
            script = inline_script(tokens[1:], {"-c"})
            if script:
                find_git_ops(script, False, list(steps), ops, env)
            continue
        if name in POWERSHELLS:
            script = inline_script(tokens[1:], {"-c", "-command"})
            if script:
                find_git_ops(script, True, list(steps), ops, env)
            continue
        if name in (CD_POWERSHELL if powershell else CD_BASH):
            paths = [t for t in tokens[1:] if not t[0].startswith("-")]
            if paths:
                steps.append(paths[0])
            continue
        if name != "git":
            continue
        local, configs, pairs, relocated, rest = git_options(tokens[1:], assigns)
        relocated = (relocated or env["relocated"]
                     or any(assign.split("=", 1)[0].upper() in RELOCATING_ENV for assign in assigns)
                     or any(key == "core.worktree" for key, _ in pairs)
                     or any(assign.upper().startswith("GIT_CONFIG") and "core.worktree" in assign.lower()
                            for assign in assigns))
        if rest:
            ops.append({"op": rest[0][0], "steps": steps + local, "tokens": rest[1:],
                        "configs": configs, "pairs": pairs, "assigns": assigns,
                        "relocated": relocated, "chain": ()})
    return ops


def shell_quote(text):
    return "'" + text.replace("'", "'\\''") + "'"


def config_env(assigns):
    overrides = {}
    for assign in assigns:
        key, _, value = assign.partition("=")
        if not key.upper().startswith("GIT_CONFIG"):
            continue
        value = os.path.expandvars(value)
        if "$" in value or "`" in value:
            return None
        overrides[key] = value
    return dict(os.environ, **overrides) if overrides else os.environ


def alias_value(item, cwd):
    key = "alias." + item["op"].lower()
    given = [value for name, value in item.get("pairs", []) if name == key]
    if given:
        return None if given[-1] is None else given[-1].strip()
    env = config_env(item.get("assigns", []))
    if env is None:
        return None
    code, alias = git(["config", "--get", key], cwd, env)
    if code not in (0, 1):
        return None
    return alias.strip() if code == 0 else ""


def expand_alias(item, base, powershell):
    cwd = resolve_cwd(item["steps"], base, powershell) or base
    alias = alias_value(item, cwd)
    if alias is None:
        item["unverifiable"] = True
    if not alias:
        return []
    inherited = {"chain": item["chain"] + (item["op"].lower(),)}
    if alias.startswith("!"):
        code, top = git(["rev-parse", "--show-toplevel"], cwd)
        start = [(top.strip(), True)] if code == 0 else list(item["steps"])
        script = alias[1:] + "".join(" " + shell_quote(text) for text, _ in item["tokens"])
        expansions = find_git_ops(script, False, start)
        for inner in expansions:
            inner.update(inherited, configs=item["configs"] + inner["configs"],
                         pairs=item["pairs"] + inner["pairs"], assigns=item["assigns"] + inner["assigns"],
                         relocated=item["relocated"] or inner["relocated"])
        return expansions
    tokens = tokenize(alias, False) + item["tokens"]
    if not tokens:
        return []
    return [dict(item, op=tokens[0][0], tokens=tokens[1:], **inherited)]


def expand_ops(ops, base, powershell):
    if not ops:
        return []
    _, listed = git(["--list-cmds=builtins"], base)
    builtins = set(listed.split())
    result, queue, expansions = [], list(ops), 0
    while queue:
        item = queue.pop(0)
        if item["op"] == "stage":
            item["op"] = "add"
        known = item["op"] in builtins
        if item["relocated"] and (item["op"] in SCANNED_OPS or not known):
            deny(RELOCATED.format(op=item["op"]))
        result.append(item)
        if known or item["op"] in SCANNED_OPS or item["op"].lower() in item["chain"]:
            continue
        expanded = expand_alias(item, base, powershell)
        if expanded and expansions >= MAX_ALIAS_EXPANSIONS:
            item["unverifiable"] = True
            continue
        expansions += bool(expanded)
        queue[:0] = expanded
    return result


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
SCANNED_OPS = {"add", "commit", "push"}
RELOCATED = ("Cannot verify what this git {op} touches: it points git at a repository through "
             "--git-dir, --work-tree, --namespace or GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE/"
             "GIT_COMMON_DIR/GIT_NAMESPACE (or sets GIT_CONFIG_GLOBAL/GIT_CONFIG_SYSTEM/GIT_CONFIG_COUNT, "
             "or runs code with source, ., eval or set -a that may set them), which this check does "
             "not follow. Run git from inside the repository without --git-dir/--work-tree (cd into it, "
             "or use git -C <repo>) and without those variables; run a sourced script in a separate "
             "command.")
UNRESOLVED = ("Cannot verify what this git {op} touches: git finds no working tree at {cwd}, the "
              "folder this check resolved for it (the folder does not exist yet, holds no "
              "repository, or holds a bare repository, which has no files to add or commit). Run "
              "git from inside the repository's working tree without --git-dir/--work-tree (cd "
              "into it with a literal path, or use git -C <repo>). If this same command creates "
              "the folder or the repository (mkdir, git init, git clone), create it first in a "
              "separate command.")
REMOTE_REFS_DENY = ("This command repoints a remote-tracking ref (refs/remotes/*), which the push "
                    "checks trust to know what the remote already has. Ask the user to run it "
                    "(or git fetch, which updates those refs from the remote itself).")
HOOK_ERROR = ("Secret-scan hook error ({error}): the check failed before it could verify this "
              "command, and a command that may add, commit or push, or that names "
              + ALLOWLIST_FILE + ", is blocked when that happens. Run it again; if it keeps "
              "failing, tell the user the secret-scan hook is failing on this command.")
ALIAS_UNVERIFIABLE = ("Cannot verify what the git alias `{op}` runs: its definition comes from an "
                      "environment variable or a GIT_CONFIG* setting this check cannot read, or it "
                      "nests too many aliases. Run the git command it stands for directly.")
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
    index_path = git_checked(["rev-parse", "--git-path", "index"], cwd)
    real = os.path.abspath(os.path.join(cwd or os.getcwd(), index_path.strip()))
    handle, copy = tempfile.mkstemp(prefix="secretscan-index-")
    os.close(handle)
    if os.path.exists(real):
        # why: copy2 keeps the index mtime, so git still re-reads entries modified in the same second
        shutil.copy2(real, copy)
    else:
        os.remove(copy)
    env = dict(os.environ, GIT_INDEX_FILE=copy)
    for add_cwd, args in adds:
        git(["add"] + args, add_cwd, env)
    return env, copy


def commit_reason(cwd, top, adds):
    env, copy = index_env(cwd, adds) if adds else (None, None)
    try:
        findings = staged_findings(cwd, env, load_allowlist(top))
    finally:
        if copy:
            for leftover in (copy, copy + ".lock"):
                if os.path.exists(leftover):
                    os.remove(leftover)
    if findings:
        return ("Secret scan blocked this commit. Findings:\n- " + "\n- ".join(findings)
                + "\n\nRemove the secret from the changes this commit records (staged, staged "
                  "by the same command, or named in it) and try again." + ALLOW_HINT)
    return None


def parse_push(tokens):
    flags, positional, repo, index = set(), [], None, 0
    while index < len(tokens):
        text = tokens[index][0]
        if text == "--":
            positional += tokens[index + 1:]
            break
        if text.startswith("--"):
            name, attached, value = text.partition("=")
            flags.add(name)
            if name in PUSH_VALUE_OPTIONS and not attached:
                index += 1
                value = tokens[index][0] if index < len(tokens) else ""
            if name == "--repo":
                repo = (value, tokens[index][1] if index < len(tokens) else True)
        elif text.startswith("-") and len(text) > 1:
            flags.update("-" + flag for flag in text[1:])
            if text in PUSH_VALUE_OPTIONS:
                index += 1
        else:
            positional.append(tokens[index])
        index += 1
    if repo is None and positional:
        repo = positional[0]
        positional = positional[1:]
    return flags, positional, repo


def commit_refs(cwd, patterns):
    out = git_checked(["for-each-ref", "--format=%(objecttype)\t%(objectname)\t%(*objecttype)\t"
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


def default_remote(cwd):
    code, branch = git(["symbolic-ref", "--short", "-q", "HEAD"], cwd)
    branch = branch.strip() if code == 0 else ""
    keys = ([f"branch.{branch}.pushRemote"] if branch else []) + ["remote.pushDefault"]
    keys += [f"branch.{branch}.remote"] if branch else []
    for key in keys:
        code, value = git(["config", "--get", key], cwd)
        if code == 0 and value.strip():
            return value.strip()
    return "origin"


def push_urls(cwd, remote):
    code, out = git(["remote", "get-url", "--push", "--all", remote], cwd)
    urls = [line.strip() for line in out.splitlines() if line.strip()] if code == 0 else []
    return urls or [remote]


GATE_OFF = {"false", "no", "off", "0"}


def gate_enabled(cwd, top, shas):
    code, values = git(["config", "--get-all", "pipeline.gate"], cwd)
    if code != 1 and (code != 0 or any(value.strip().lower() not in GATE_OFF
                                       for value in values.splitlines() or [""])):
        return True
    if top and os.path.isdir(os.path.join(top, "docs", "quality-reports")):
        return True
    return any(git(["cat-file", "-e", sha + ":docs/quality-reports"], cwd)[0] == 0 for sha in shas)


def push_reason(cwd, top, tokens):
    flags, refspecs, repo = parse_push(tokens)
    if flags & {"--dry-run", "-n", "--delete", "-d"}:
        return None
    sources = push_sources(cwd, flags, refspecs)
    if sources is None or (repo is not None and expanded(repo)):
        return UNVERIFIABLE.format(op="push", what="a ref or the remote in the command")
    remote = repo[0] if repo is not None else default_remote(cwd)
    rules = url_rewrites(cwd)
    urls = configured_push_urls(cwd, remote, rules) if rules["fetch"] or rules["push"] else push_urls(cwd, remote)
    rewrites = split_rewrites(rules, urls)
    if rewrites:
        sys.stderr.write(REWRITE_WARNING.format(remote=shown(remote), rewrites=shown("; ".join(rewrites))))
    bases, fallback = remote_bases(cwd, urls, remote, trust_remote=not rewrites)
    outgoing = []
    for name, sha in sources:
        count = outgoing_count(cwd, sha, bases)
        if fallback and count > FALLBACK_CAP:
            return "Push blocked. " + UNKNOWN_REMOTE.format(remote=shown(remote), count=count, ref=shown(name),
                                                            cap=FALLBACK_CAP)
        if count:
            outgoing.append((name, sha))
    if not outgoing:
        return None
    findings = []
    for sha in sorted({sha for _, sha in outgoing}):
        diff, names = outgoing_changes(cwd, sha, bases)
        findings += [finding for finding in scan(diff, names, load_allowlist(cwd, sha))
                     if finding not in findings]
    if findings:
        return ("Secret scan blocked this push: the commits about to leave this machine "
                "contain:\n- " + "\n- ".join(findings)
                + "\n\nRemoving it in a later commit is not enough because it stays in "
                  "the history being pushed. Rewrite the affected local commits first."
                + ALLOW_HINT)
    if gate_enabled(cwd, top, [sha for _, sha in outgoing]):
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
FILE_READERS = {"cat", "type", "head", "tail", "less", "more", "grep", "rg", "wc", "ls", "dir", "stat", "file",
                "sha256sum", "sha1sum", "sha512sum", "md5sum", "du", "get-content", "gc", "select-string",
                "sls", "get-childitem", "gci", "test-path", "get-filehash"}
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
        return None
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
        return allowlist_dirty(cwd, untracked=not tracked_only) is not False
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
        return allowlist_dirty(cwd, untracked=not tracked_only) is not False
    if not paths:
        if not (every or tracked_only):
            return False
        paths = [":/"]
    return pathspecs_reach_allowlist(cwd, paths, tracked_only, force)


def commit_reaches_allowlist(stage, cwd):
    for args in stage:
        if args == ["-A"]:
            if allowlist_dirty(cwd, untracked=True) is not False:
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
        return allowlist_dirty(base, untracked=True) is not False
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


def touches_allowlist(command, powershell, base, ops):
    segments = split_segments(command, powershell)
    mentioned_anywhere = any(names_allowlist(segment) for segment in segments)
    if mentioned_anywhere and ">" in HARMLESS_REDIRECT.sub("", command):
        return True
    for segment in segments:
        if not names_allowlist(segment):
            continue
        tokens, assigns = strip_reserved(tokenize(segment, powershell), powershell), []
        while tokens and (tokens[0][0].lower() in WRAPPERS
                          or (not powershell and ASSIGNMENT.match(tokens[0][0]))):
            assigns.append(tokens[0][0])
            tokens = strip_reserved(tokens[1:], powershell)
        if not tokens:
            continue
        name = program(tokens[0][0])
        if name in FILE_READERS:
            continue
        if name != "git" or git_segment_risky(tokens[1:], assigns):
            return True
    return any(git_touches_allowlist(item, mentioned_anywhere, base, powershell)
               for item in ops)


def is_allowlist_path(target):
    name = re.split(r"[\\/]", re.sub(r"^[A-Za-z]:", "", str(target).strip()))[-1]
    return name.split(":", 1)[0].rstrip(" .").lower() == ALLOWLIST_FILE


def is_git_internal_path(target):
    path = str(target).replace("\\", "/").lower()
    return bool(re.search(r"(?:^|/)\.git/+(?:hooks(?:/|$)|config(?:\.worktree)?$|worktrees/+[^/]+/+config\.worktree$)",
                          path))


def is_remote_ref_path(target):
    path = str(target).replace("\\", "/").lower()
    return ".git/" in path and ("/refs/remotes/" in path or path.rstrip("/").endswith("/packed-refs"))


GLOB_CHARS = re.compile(r"[*?\[]")
REDIRECT_TOKEN = re.compile(r"^\d*>>?\|?")
HARMLESS_TARGET = re.compile(r"(?i)^(?:&\d|/dev/null|\$null|nul)$")
VARIABLE_MARK = re.compile(r"\$|`")
UNRESOLVED_REACH = "unresolved"
GIT_SOURCE_HINT = re.compile(r"(?i)--(?:absolute-)?git-(?:dir|path|common-dir)|(?<![\w.-])\.git(?![\w-])|hookspath")
GIT_LOCATION_VARS = {"GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE"}
VARIABLE_SOURCE = re.compile(r"(?i)\$(\{)?(?:env:|global:|script:|local:|private:)?([A-Za-z_]\w*|\d)?([^}]*\})?")
POWERSHELL_SCOPE = r"(?:global|script|local|private):"
POWERSHELL_ASSIGNMENT = re.compile(r"(?is)^(?:\[[^\]]*\]\s*)*\$(?:(env:)|" + POWERSHELL_SCOPE
                                   + r")?([A-Za-z_]\w*)\s*=\s*(.*)$")
POWERSHELL_LITERAL = re.compile(r"""^(?:'([^']*)'|"([^"$`]*)")$""")
POWERSHELL_BLOCK_OPEN = re.compile(r"(?<!\$)\{")
BASH_RESERVED = {"if", "then", "elif", "else", "while", "until", "do", "!", "{"}
BASH_DECLARERS = ("export", "declare", "typeset", "local", "readonly")
POWERSHELL_BLOCK_KEYWORDS = {"if", "elseif", "while", "foreach", "for", "switch", "until", "catch", "function",
                             "filter", "param", "trap", "do"}
GENERIC_PROTECTED = (([".git", "hooks"], "hooks"), ([".git", "config"], "config"),
                     ([".git", "config.worktree"], "config"))
HOOK_CANDIDATES = ("pre-commit", "pre-push", "pre-commit.pipeline-chained")
SUBSTITUTION_MARK = "$__substitution__"
GIT_SUBSTITUTION_MARK = "$__git_substitution__"
GIT_PARENT_MARK = "$__git_parent_substitution__"
GIT_DIR_MARK = "$__git_dir_substitution__"
GIT_MARKS = (GIT_SUBSTITUTION_MARK, GIT_DIR_MARK)
GIT_DIR_QUERY = r"git(?:\.exe)?\s+rev-parse\s+--(?:absolute-git-dir|git-dir|git-common-dir)"
PLAIN_GIT_DIR = re.compile(r"(?i)^\s*" + GIT_DIR_QUERY + r"\s*$")
PARENT_OF_GIT_DIR = re.compile(r"""(?is)^\s*(?:\S*[\\/])?(?:dirname|split-path)(?:\.exe)?(?:\s+-parent)?\s+(["']?)"""
                               r"(?:\$?\(\s*" + GIT_DIR_QUERY + r"\s*\)|" + re.escape(GIT_DIR_MARK) + r")\1\s*$")
COPY_PROGRAMS = {"cp", "copy", "copy-item", "cpi", "rsync", "xcopy"}
MOVE_PROGRAMS = {"mv", "move", "move-item", "mi"}
PS_COPY_VALUE_PARAMS = ("-path", "-literalpath", "-pspath", "-filter", "-include", "-exclude", "-credential",
                        "-tosession", "-fromsession")
DELETE_WRITE_PROGRAMS = {"rm", "rmdir", "unlink", "mv", "cp", "tee", "ln", "install", "truncate", "shred",
                         "touch", "chmod", "dd", "remove-item", "ri", "del", "erase", "rd", "move-item",
                         "mi", "move", "copy-item", "cpi", "copy", "rename-item", "rni", "set-content",
                         "sc", "add-content", "ac", "out-file", "new-item", "ni", "clear-content", "clc"}
FIND_ACTIONS = {"-delete", "-exec", "-execdir", "-ok", "-okdir"}


def lexical_parts(path):
    parts = []
    for part in str(path).replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == ".." and parts and parts[-1] != "..":
            parts.pop()
        else:
            parts.append(part)
    return parts


def part_matches(name, pattern, powershell):
    if not GLOB_CHARS.search(pattern):
        return pattern.lower() == name.lower()
    if name.startswith(".") and not pattern.startswith(".") and not powershell:
        return False
    return fnmatch.fnmatchcase(name.lower(), pattern.lower())


def parts_cover(target, parts, powershell, inside):
    if len(parts) < len(target) or (not inside and len(parts) != len(target)):
        return False
    return all(part_matches(name, pattern, powershell) for name, pattern in zip(target, parts))


def reaches_git_internals(parts, powershell):
    for index, part in enumerate(parts[:-1]):
        if part_matches(".git", part, powershell):
            rest = parts[index + 1:]
            if part_matches("hooks", rest[0], powershell):
                return True
            if len(rest) == 1 and any(part_matches(name, rest[0], powershell)
                                      for name in ("config", "config.worktree")):
                return True
            if (len(rest) == 3 and part_matches("worktrees", rest[0], powershell)
                    and part_matches("config.worktree", rest[2], powershell)):
                return True
    return False


def expand_home(text):
    home = os.path.expanduser("~")
    text = re.sub(r"(?i)\$\{?env:(USERPROFILE|HOME)\}?|\$\{?HOME\}?(?![\w])", lambda _: home, text)
    text = re.sub(r"(?i)\$\{?env:([A-Za-z_]\w*)\}?", lambda m: os.environ.get(m.group(1), m.group(0)), text)
    text = re.sub(r"%([A-Za-z_]\w*)%", lambda m: os.environ.get(m.group(1), m.group(0)), text)
    text = os.path.expandvars(text)
    msys = re.match(r"^/([a-zA-Z])/(.*)", text)
    if msys:
        text = msys.group(1) + ":/" + msys.group(2)
    return os.path.expanduser(text)


def config_key(path):
    return tuple(part.split(":", 1)[0].rstrip(" .").lower() or part for part in lexical_parts(os.path.abspath(path)))


def global_gitconfigs():
    home = os.path.expanduser("~")
    paths = [os.path.join(home, ".gitconfig"), os.path.join(home, ".config", "git", "config")]
    for var in ("USERPROFILE", "HOME"):
        if os.environ.get(var):
            paths.append(os.path.join(os.environ[var], ".gitconfig"))
    if os.environ.get("XDG_CONFIG_HOME"):
        paths.append(os.path.join(os.environ["XDG_CONFIG_HOME"], "git", "config"))
    if os.environ.get("GIT_CONFIG_GLOBAL"):
        paths.append(os.environ["GIT_CONFIG_GLOBAL"])
    return {config_key(path) for path in paths}


def is_global_gitconfig(target, base=None):
    text = expand_home(str(target).strip())
    if "$" in text or re.search(r"%\w+%", text):
        return bool(re.search(r"(?i)(?:git[\\/]+config|\.gitconfig)[\s.]*$", text))
    if not os.path.isabs(text):
        text = os.path.join(base or os.getcwd(), text)
    return config_key(text) in global_gitconfigs()


def into_directory(destinations, sources, base):
    if len(destinations) != 1:
        return []
    text = destinations[0][0]
    folder = expand_home(text)
    if not os.path.isabs(folder):
        folder = os.path.join(base or os.getcwd(), folder)
    if not (text.endswith(("/", "\\")) or text == "~" or os.path.isdir(folder)):
        return []
    return [(os.path.join(folder, re.split(r"[\\/]", token[0].rstrip("/\\"))[-1]), token[1]) for token in sources]


def copy_destinations(name, targets, powershell):
    if name in ("copy-item", "cpi", "move-item", "mi") or (powershell and name in ("copy", "move")):
        positional, named_path, index = [], False, 0
        while index < len(targets):
            text, literal = targets[index]
            key, colon, _ = text.lower().partition(":")
            if not key.startswith("-") or len(key) < 3:
                positional.append(targets[index])
            elif len(key) >= 4 and "-destination".startswith(key):
                if colon:
                    return [(text.split(":", 1)[1], literal)]
                return targets[index + 1:index + 2] or targets
            elif any(param.startswith(key) for param in PS_COPY_VALUE_PARAMS):
                named_path = named_path or any(param.startswith(key) for param in PS_COPY_VALUE_PARAMS[:3])
                index += 0 if colon else 1
            index += 1
        chosen = positional[:1] if named_path else positional[1:2]
        return chosen or targets
    positional, index = [], 0
    while index < len(targets):
        text = targets[index][0]
        if text in ("-t", "--target-directory"):
            return targets[index + 1:index + 2] or targets
        if text.startswith("--target-directory="):
            return [(text.split("=", 1)[1], targets[index][1])]
        if text.startswith("-t") and not text.startswith("--") and len(text) > 2:
            return [(text[2:], targets[index][1])]
        if not text.startswith("-"):
            positional.append(targets[index])
        index += 1
    return positional[-1:] if len(positional) >= 2 else targets


def segment_targets(tokens):
    targets, redirected, pending = [], [], False
    for token in tokens[1:]:
        text = token[0]
        if pending:
            redirected.append(token)
            pending = False
            continue
        match = REDIRECT_TOKEN.match(text) if text[:1].isdigit() or text[:1] == ">" else None
        if match:
            if text[match.end():]:
                redirected.append((text[match.end():], token[1]))
            else:
                pending = True
            continue
        targets.append(token)
    return targets, [token for token in redirected if not HARMLESS_TARGET.match(token[0])]


def strip_prefix(tokens, powershell, variables):
    tokens = strip_reserved(tokens, powershell)
    while tokens and (tokens[0][0].lower() in WRAPPERS
                      or (not powershell and ASSIGNMENT.match(tokens[0][0]))):
        key, _, value = tokens[0][0].partition("=")
        if not powershell and ASSIGNMENT.match(tokens[0][0]):
            variables[key] = value
        tokens = strip_reserved(tokens[1:], powershell)
    if tokens and not powershell and tokens[0][0] in ("export", "declare", "typeset", "local", "readonly"):
        for text, _ in tokens[1:]:
            if ASSIGNMENT.match(text):
                key, _, value = text.partition("=")
                variables[key] = value
    return tokens


def substitute(token, variables, powershell):
    text, literal = token
    if literal or not variables:
        return token
    key = str.lower if powershell else str
    scope = "(?i:" + POWERSHELL_SCOPE + ")?" if powershell else ""
    return re.sub(r"\$\{?" + scope + r"([A-Za-z_]\w*)\}?", lambda m: variables.get(key(m.group(1)), m.group(0)),
                  text), literal


def protected_git_dirs(state):
    if state["protected"] is None:
        state["protected"] = []
        code, out = git(["rev-parse", "--git-path", "hooks", "--git-path", "config", "--git-path", "config.worktree",
                         "--git-common-dir"], state["base"])
        lines = out.splitlines()
        if code == 0 and len(lines) == 4:
            for line, kind in zip(lines, ("hooks", "config", "config", "gitdir")):
                path = os.path.join(state["base"] or os.getcwd(), line.strip())
                state["protected"].append((lexical_parts(os.path.abspath(path)), kind))
    return state["protected"]


def resolved_parts(token, state, powershell):
    if state["cwd"] is None:
        return None
    resolved = resolve_path(token[0], token[1], state["cwd"], powershell)
    return None if resolved is None else lexical_parts(resolved)


def points_at_git_value(value, state):
    if any(mark in value for mark in GIT_MARKS) or GIT_SOURCE_HINT.search(value):
        return True
    names = (match.group(2) or "" for match in VARIABLE_SOURCE.finditer(value))
    return any(name.upper() in GIT_LOCATION_VARS or name.lower() in state["git_vars"] | state["git_parent_vars"]
               for name in names)


def cd_target_in_git(token, state):
    text, literal = token
    return not literal and any(points_at_git(text[mark.start():], state, entering=True)
                               and not (names_git_dir(text[mark.start():], state)
                                        and climbs_out(reference_tail(text, mark)))
                               for mark in VARIABLE_MARK.finditer(text))


def reference_name(reference):
    match = VARIABLE_SOURCE.match(reference)
    return ((match.group(2) or "") if match else ""), match


def names_git_dir(reference, state):
    if reference.startswith(GIT_DIR_MARK):
        return True
    name, match = reference_name(reference)
    return not (match and match.group(3)) and (name.upper() in ("GIT_DIR", "GIT_COMMON_DIR")
                                               or name.lower() in state["git_dir_vars"])


def points_at_git(reference, state, entering=False):
    if reference.startswith(GIT_MARKS + (GIT_PARENT_MARK, SUBSTITUTION_MARK)):
        return (reference.startswith(GIT_MARKS)
                or (not entering and reference.startswith(GIT_PARENT_MARK)))
    if reference.startswith("`"):
        return bool(GIT_SOURCE_HINT.search(reference))
    name, match = reference_name(reference)
    locations = GIT_LOCATION_VARS - {"GIT_WORK_TREE"} if entering else GIT_LOCATION_VARS
    return (name.upper() in locations or name.lower() in state["git_vars"]
            or bool(match and match.group(3) and GIT_SOURCE_HINT.search(match.group(3)))
            or (not entering and name.lower() in state["git_parent_vars"]))


def reference_tail(text, mark):
    pieces = re.split(r"[\\/]", text[mark.end():], maxsplit=1)
    return pieces[1] if len(pieces) == 2 else ""


def climbs_out(tail):
    depth = 0
    for part in re.split(r"[\\/]", tail):
        depth += -1 if part == ".." else 0 if part in ("", ".") else 1
        if depth < 0:
            return True
    return False


def unresolved_tail_reaches(text, state, powershell):
    marks = list(VARIABLE_MARK.finditer(text))
    return any(tail_reaches(reference_tail(text, mark), text[mark.start():], state, powershell)
               for index, mark in enumerate(marks)
               if index == len(marks) - 1 or points_at_git(text[mark.start():], state))


def tail_reaches(rest, reference, state, powershell):
    if ".." in re.split(r"[\\/]", rest):
        return True
    tail = ["*" if VARIABLE_MARK.search(part) else part for part in lexical_parts(rest)]
    if not tail or (len(tail) == 1 and any(part_matches(name, tail[0], powershell) for name in HOOK_CANDIDATES)):
        return points_at_git(reference, state)
    targets = list(GENERIC_PROTECTED) + [item for item in protected_git_dirs(state) if item[1] != "gitdir"]
    for target, kind in targets:
        for size in range(1, min(len(tail), len(target)) + 1):
            if len(tail) > size and kind != "hooks":
                continue
            if all(part_matches(name, pattern, powershell) for name, pattern in zip(target[-size:], tail[:size])):
                return True
    return False


def first_reach(tokens, state, powershell, variable_rule):
    return next((reach for reach in (reaches_hooks(token, state, powershell, variable_rule) for token in tokens)
                 if reach), False)


def reach_reason(reach, reason):
    return UNRESOLVED_DENY if reach == UNRESOLVED_REACH else reason


def reaches_hooks(token, state, powershell, variable_rule):
    text, literal = token
    if text.startswith("-"):
        return False
    if reaches_git_internals(lexical_parts(text), powershell):
        return True
    parts = resolved_parts(token, state, powershell)
    if parts is None:
        unresolved = variable_rule and not literal and unresolved_tail_reaches(text, state, powershell)
        return UNRESOLVED_REACH if unresolved else False
    return any(parts_cover(target, parts, powershell, inside=kind == "hooks")
               for target, kind in protected_git_dirs(state) if kind != "gitdir")


def enters_git_dir(token, state, powershell):
    if any(part_matches(".git", part, powershell) for part in lexical_parts(token[0])):
        return True
    parts = resolved_parts(token, state, powershell)
    return parts is not None and any(parts_cover(target, parts, powershell, inside=True)
                                     for target, kind in protected_git_dirs(state) if kind != "config")


def find_writing_actions(expression):
    actions, index = [], 0
    while index < len(expression):
        text = expression[index]
        if text == "-delete":
            actions.append((index, text, [], True))
        elif text in FIND_ACTIONS:
            end = next((position for position in range(index + 1, len(expression))
                        if expression[position] in (";", "+")), None)
            args = expression[index + 1:len(expression) if end is None else end]
            if (end is None or not args or program(args[0]) not in FILE_READERS
                    or any(">" in arg for arg in args)):
                actions.append((index, text, args, end is not None))
            index = len(expression) if end is None else end
        index += 1
    return actions


def find_write_action(expression):
    actions = find_writing_actions(expression)
    return actions[0][0] if actions else None


def execdir_names_match_only(arg):
    return "{}" in arg and not re.search(r"[\\/]", arg) and ".." not in arg


def find_escapes_match(actions):
    return any((action in ("-execdir", "-okdir")
                and any(not arg.startswith("-") and not execdir_names_match_only(arg) for arg in args[1:]))
               or any("{}" in arg and ".." in re.split(r"[\\/]", arg) for arg in args)
               for _, action, args, _ in actions)


def find_reaches_git(targets, state, powershell):
    roots = []
    for token in targets:
        if token[0].startswith(("-", "(", "!")):
            break
        roots.append(token)
    expression = [text for text, _ in targets[len(roots):]]
    actions = find_writing_actions(expression)
    if not actions:
        return False
    split = not all(terminated for _, _, _, terminated in actions)
    tests_apply = not find_escapes_match(actions)
    for token in roots or [(".", True)]:
        if any(part_matches(".git", part, powershell) for part in lexical_parts(token[0])):
            return True
        if state["cwd"] is None:
            continue
        parts = resolved_parts(token, state, powershell)
        if parts is None:
            return True
        prefix = token[0].rstrip("/\\") or token[0]
        candidates = []
        for target, kind in protected_git_dirs(state):
            if not all(part_matches(name, pattern, powershell) for name, pattern in zip(target, parts)):
                continue
            if len(parts) >= len(target):
                return True
            path = "/".join([prefix] + target[len(parts):])
            names = HOOK_CANDIDATES if kind != "config" else ("",)
            candidates.extend(((path + "/" + name).rstrip("/"), prefix) for name in names)
        if candidates and (split or not find_excludes(expression, candidates, tests_apply)):
            return True
    return False


FIND_PATH_TESTS = {"-path": False, "-wholename": False, "-ipath": True, "-iwholename": True}
FIND_NAME_TESTS = {"-name": False, "-iname": True}
FIND_TESTS = {**FIND_PATH_TESTS, **FIND_NAME_TESTS}


def find_pattern_matches(test, pattern, path):
    fold = FIND_PATH_TESTS.get(test, FIND_NAME_TESTS.get(test))
    subject = path if test in FIND_PATH_TESTS else path.rsplit("/", 1)[-1]
    return fnmatch.fnmatchcase(subject.lower() if fold else subject, pattern.lower() if fold else pattern)


def find_ancestors(path, prefix):
    parts = path[len(prefix) + 1:].split("/")
    return ["/".join([prefix] + parts[:depth]) for depth in range(1, len(parts) + 1)]


def branch_excludes(branch, path, prefix, tests_apply):
    end = find_write_action(branch)
    tests = branch[:len(branch) if end is None else end]
    for index in range(len(tests) - 1):
        test, pattern = tests[index], tests[index + 1]
        if test not in FIND_TESTS:
            continue
        negated = index > 0 and tests[index - 1] in ("-not", "!")
        if negated and test in FIND_PATH_TESTS and find_pattern_matches(test, pattern, path):
            return True
        if tests_apply and not negated and not any(find_pattern_matches(test, pattern, ancestor)
                                   for ancestor in find_ancestors(path, prefix)):
            return True
    return False


def find_excludes(expression, candidates, tests_apply):
    expression = [text for text in expression if text not in ("(", ")")]
    ors = [index for index, text in enumerate(expression) if text in ("-o", "-or", ",")]
    if not ors:
        return all(branch_excludes(expression, path, prefix, tests_apply) for path, prefix in candidates)
    if ors != [3] or expression[0] not in FIND_TESTS or expression[2] != "-prune":
        return False
    test, pattern = expression[0], expression[1]
    return all(any(find_pattern_matches(test, pattern, ancestor) for ancestor in find_ancestors(path, prefix))
               or branch_excludes(expression[4:], path, prefix, tests_apply)
               for path, prefix in candidates)


def substitution_mark(script):
    if not GIT_SOURCE_HINT.search(script):
        return SUBSTITUTION_MARK
    if PLAIN_GIT_DIR.match(script):
        return GIT_DIR_MARK
    return GIT_PARENT_MARK if PARENT_OF_GIT_DIR.match(script) else GIT_SUBSTITUTION_MARK


def closing_paren(command, start):
    depth, end, quote = 1, start, None
    while end < len(command) and depth:
        if quote:
            quote = None if command[end] == quote else quote
        elif command[end] in "'\"":
            quote = command[end]
        elif command[end] == "(":
            depth += 1
        elif command[end] == ")":
            depth -= 1
        end += 1
    return end, depth == 0


def powershell_expression_paren(command, index):
    if index and (command[index - 1].isalnum() or command[index - 1] in "_)]}.'\"`"):
        return False
    word = re.search(r"([\w-]+)\s*$", command[:index])
    return not (word and word.group(1).lower() in POWERSHELL_BLOCK_KEYWORDS)


def command_substitutions(command, powershell):
    collapsed, inner, quote, index = [], [], None, 0
    while index < len(command):
        char = command[index]
        if quote == "'":
            quote = None if char == "'" else quote
        elif is_escape(command, index, powershell, quote is not None):
            collapsed.append(command[index:index + 2])
            index += 2
            continue
        elif char in "'\"" and quote in (None, char):
            quote = None if quote else char
        elif char == "`" and not powershell:
            end = index + 1
            while end < len(command) and command[end] != "`":
                end += 2 if command[end] == "\\" else 1
            inner.append(command[index + 1:end])
            collapsed.append(substitution_mark(inner[-1]))
            index = end + 1
            continue
        elif command.startswith("$(", index) and not command.startswith("$((", index):
            end, closed = closing_paren(command, index + 2)
            inner.append(command[index + 2:end - 1 if closed else end])
            collapsed.append(substitution_mark(inner[-1]))
            index = end
            continue
        elif powershell and char == "(" and quote is None and powershell_expression_paren(command, index):
            end, closed = closing_paren(command, index + 1)
            script = command[index + 1:end - 1 if closed else end]
            if GIT_SOURCE_HINT.search(script):
                inner.append(script)
                collapsed.append(substitution_mark(script))
                index = end
                continue
        collapsed.append(char)
        index += 1
    return "".join(collapsed), inner


def split_statements(command, powershell):
    statements, start, quote, index = [], 0, None, 0
    while index < len(command):
        char = command[index]
        if quote:
            if quote == '"' and is_escape(command, index, powershell, True):
                index += 1
            elif char == quote:
                quote = None
        elif is_escape(command, index, powershell, False):
            index += 1
        elif char in "'\"":
            quote = char
        elif char in ";\n" or command[index:index + 2] in ("&&", "||"):
            statements.append(command[start:index])
            index += 1 if char in ";\n" else 2
            start = index
            continue
        index += 1
    statements.append(command[start:])
    return [statement.strip() for statement in statements if statement.strip()]


def powershell_assignments(statement):
    assignments = []
    for start in [0] + [match.end() for match in POWERSHELL_BLOCK_OPEN.finditer(statement)]:
        match = POWERSHELL_ASSIGNMENT.match(statement[start:].strip())
        if match:
            env, name, value = match.groups()
            assignments.append((name, value.rstrip().rstrip("}").rstrip() if start else value, bool(env)))
    return assignments


def statement_assignments(statement, powershell):
    if powershell:
        return [(name, value) for name, value, _ in powershell_assignments(statement)]
    tokens = strip_reserved(tokenize(statement.lstrip("({ \t"), powershell), powershell)
    if len(tokens) > 2 and tokens[0][0] == "for" and tokens[2][0] == "in" and ASSIGNMENT.match(tokens[1][0] + "="):
        return [(tokens[1][0], " ".join(text for text, _ in tokens[3:]))]
    if tokens and tokens[0][0] in BASH_DECLARERS:
        tokens = [token for token in tokens[1:] if not token[0].startswith("-")]
    assignments = []
    for text, _ in tokens:
        if not ASSIGNMENT.match(text):
            break
        assignments.append(tuple(text.split("=", 1)))
    return assignments


def track_git_vars(statement, powershell, state):
    for name, value in statement_assignments(statement, powershell):
        key, bare = name.lower(), value.strip().strip("\"'")
        plain_dir = (bare == GIT_DIR_MARK or bool(PLAIN_GIT_DIR.match(bare))) and (
            key not in state["git_vars"] or key in state["git_dir_vars"])
        if bare == GIT_PARENT_MARK or PARENT_OF_GIT_DIR.match(bare):
            state["git_parent_vars"].add(key)
        elif points_at_git_value(value, state):
            state["git_vars"].add(key)
        if plain_dir:
            state["git_dir_vars"].add(key)
        else:
            state["git_dir_vars"].discard(key)
    if powershell:
        for name, value, env in powershell_assignments(statement):
            literal = None if env else POWERSHELL_LITERAL.match(value.strip())
            if literal:
                state["variables"][name.lower()] = next(group for group in literal.groups() if group is not None)
            elif not env:
                state["variables"].pop(name.lower(), None)


def tampers_with_hooks(command, powershell, state):
    command, substitutions = command_substitutions(command, powershell)
    for script in substitutions:
        reason = tampers_with_hooks(script, powershell, dict(state, variables=dict(state["variables"])))
        if reason:
            return reason
    for statement in split_statements(command, powershell):
        track_git_vars(statement, powershell, state)
        reason = segments_tamper(statement, powershell, state)
        if reason:
            return reason
    return None


def segments_tamper(command, powershell, state):
    for segment in split_segments(command, powershell):
        if segment in ("(", ")"):
            continue
        tokens = [substitute(token, state["variables"], powershell)
                  for token in strip_prefix(tokenize(segment, powershell), powershell, state["variables"])]
        if not tokens:
            continue
        name = program(tokens[0][0])
        if name in SHELLS or name in POWERSHELLS:
            inner_powershell = name in POWERSHELLS
            script = inline_script(tokens[1:], {"-c", "-command"} if inner_powershell else {"-c"})
            inner_state = dict(state, variables=dict(state["variables"]))
            reason = tampers_with_hooks(script, inner_powershell, inner_state) if script else None
            if reason:
                return reason
            continue
        targets, redirected = segment_targets(tokens)
        if name in (CD_POWERSHELL if powershell else CD_BASH):
            paths = [token for token in targets if not token[0].startswith("-")]
            if paths:
                state["in_git"] = (state["in_git"] or enters_git_dir(paths[0], state, powershell)
                                   or cd_target_in_git(paths[0], state))
                state["cwd"] = (resolve_path(paths[0][0], paths[0][1], state["cwd"], powershell)
                                if state["cwd"] is not None else None)
            continue
        if name == "find":
            if find_reaches_git(targets, state, powershell):
                return FIND_DENY
            action = find_write_action([text for text, _ in targets])
            reach = (first_reach(targets[action:], state, powershell, True)
                     if action is not None and targets[action][0] != "-delete" else False)
            if reach:
                return reach_reason(reach, FIND_DENY)
            for index, _, args, _ in find_writing_actions([text for text, _ in targets]):
                shell = program(args[0]) if args else ""
                if shell in SHELLS or shell in POWERSHELLS:
                    inner_powershell = shell in POWERSHELLS
                    script = inline_script(targets[index + 2:index + 1 + len(args)],
                                           {"-c", "-command"} if inner_powershell else {"-c"})
                    reason = script and tampers_with_hooks(script, inner_powershell,
                                                           dict(state, variables=dict(state["variables"])))
                    if reason:
                        return reason
        command_writes = name not in FILE_READERS and name not in ("git", "find")
        if not (redirected or command_writes):
            continue
        if state["in_git"]:
            return HOOKS_DENY
        reach = (first_reach(redirected, state, powershell, True)
                 or (command_writes and first_reach(targets, state, powershell, name in DELETE_WRITE_PROGRAMS)))
        if reach:
            return reach_reason(reach, HOOKS_DENY)
    return None


def writes_global_gitconfig(command, powershell, base):
    for segment in split_segments(command, powershell):
        tokens = strip_prefix(tokenize(segment, powershell), powershell, {})
        if not tokens:
            continue
        name = program(tokens[0][0])
        if name in SHELLS or name in POWERSHELLS:
            inner_powershell = name in POWERSHELLS
            script = inline_script(tokens[1:], {"-c", "-command"} if inner_powershell else {"-c"})
            if script and writes_global_gitconfig(script, inner_powershell, base):
                return True
            continue
        targets, redirected = segment_targets(tokens)
        if name in COPY_PROGRAMS | MOVE_PROGRAMS:
            destinations = copy_destinations(name, targets, powershell)
            sources = [token for token in targets if token not in destinations and not token[0].startswith("-")]
            targets = (destinations + into_directory(destinations, sources, base)
                       + (sources if name in MOVE_PROGRAMS else []))
        candidates = redirected + (targets if name not in FILE_READERS and name != "git" else [])
        if any(not text.startswith("-") and is_global_gitconfig(text, base) for text, _ in candidates):
            return True
    return False


REMOTE_REF_REDIRECT = re.compile(r"(?i)>\s*[\"']?[^\s;|&]*(?:refs[\\/]+remotes[\\/]|packed-refs)")


REF_VALUE_OPTIONS = {"-m"}
FETCH_OPS = {"fetch", "pull"}
PROTECTED_KEY = re.compile(r"(?i)^(?:pipeline\..+|core\.hookspath|core\.worktree|include\..+|includeif\..+|"
                           r"url\..+\.(?:push)?insteadof|remote\..+\.(?:url|pushurl|fetch|mirror))$")
PROTECTED_SECTION = re.compile(r"(?i)^(?:pipeline|core|include|includeif(?:\..+)?|url(?:\..+)?|remote(?:\..+)?)$")
PROTECTED_CONFIG_VALUE = re.compile(r"(?i)pipeline\.|hookspath|insteadof|pushurl|include|remote\.[^\s=]*\.(?:url|fetch)")
CONFIG_READ_FLAGS = {"--get", "--get-all", "--get-regexp", "--get-urlmatch", "-l", "--list", "--show-origin",
                     "--show-scope", "--name-only", "-z", "--null", "--includes", "--no-includes", "--global",
                     "--system", "--local", "--worktree", "--bool", "--int", "--bool-or-int", "--path",
                     "--expiry-date", "--all", "--regexp", "--fixed-value"}
CONFIG_READ_VALUE_FLAGS = {"--type", "-t", "--default", "--file", "-f", "--blob", "--value"}
CONFIG_READ_ATTACHED = ("--type=", "--default=", "--file=", "--blob=", "--value=")
CONFIG_GET_FLAGS = {"--get", "--get-all", "--get-regexp"}
CONFIG_READ_SUBCOMMANDS = {"get", "list"}
REMOTE_REF_FILES = re.compile(r"(?i)\.git[\\/]+(?:refs[\\/]+remotes(?![\w.-])|packed-refs(?![\w.-]))")
GIT_INTERNALS = re.compile(r"(?i)\.git[\\/]+(?:hooks(?![\w.-])|config(?:\.worktree)?(?![\w.-])|"
                           r"worktrees[\\/]+[^\\/\s]+[\\/]+config\.worktree(?![\w.-]))")
GUARD_SCOPE = (" These guards stop accidental leaks and shortcuts, not a determined bypass: an agent must "
               "not look for another route around them (a script, an interpreter, git config). Ask the "
               "user instead.")
HOOKS_DENY = ("This command would skip or rewire git's own hooks (--no-verify, also inside a string run "
              "by an interpreter, xargs, eval or find -exec, -n on git commit, core.hooksPath, "
              "include.path, GIT_CONFIG_GLOBAL/GIT_CONFIG_SYSTEM, a change under .git/hooks or the "
              "core.hooksPath folder or to .git/config, or a cd into the git dir followed by a write). Those hooks run the pipeline's "
              "secret scan on every commit and push, so an agent may not bypass them. Commit or push "
              "without that option, or ask the user to run it." + GUARD_SCOPE)
UNRESOLVED_DENY = ("This command writes to a path built from a variable or $(...) that this check cannot resolve "
                   "and that may resolve to the git hooks folder (.git/hooks or the core.hooksPath folder) or "
                   "to .git/config: its value comes from git rev-parse, GIT_DIR or a .git/hooks path, or the "
                   "path climbs out with a .. segment. Write the literal path instead (rm -rf build/hooks, not "
                   "rm -rf \"$dir\"/hooks)." + GUARD_SCOPE)
FIND_DENY = ("This find could delete or modify files under .git or the git hooks folder (.git/hooks or the "
             "core.hooksPath folder): its -delete or writing -exec is not kept away from them. Exclude .git "
             "first (find . -not -path './.git/*' ...), or search a subfolder (find src ...)." + GUARD_SCOPE)
CONFIG_DENY = ("This command changes git settings the secret scan and the push gate rely on "
               "(pipeline.*, core.hooksPath, include.*, url.*.insteadOf, remote.*.url/pushurl/fetch). "
               "Ask the user to run it in a terminal." + GUARD_SCOPE)
GITCONFIG_DENY = ("This would write the global git config (~/.gitconfig, %USERPROFILE%\\.gitconfig, "
                  "$XDG_CONFIG_HOME/git/config or ~/.config/git/config), where URL rewrites, "
                  "core.hooksPath and aliases can switch off or fool the secret scan. Ask the user to "
                  "change it in a terminal." + GUARD_SCOPE)


def ref_write_args(tokens):
    texts, args, index = [text for text, _ in tokens], [], 0
    while index < len(texts):
        text = texts[index]
        if text in REF_VALUE_OPTIONS:
            index += 1
        elif not text.startswith("-"):
            args.append(text)
        index += 1
    writes = len(args) >= 2 or any(text in ("-d", "--delete", "--stdin") for text in texts)
    return writes, texts


def is_local_url(url):
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", url):
        return url.lower().startswith("file://")
    if re.match(r"^[A-Za-z]:[\\/]", url) or url.startswith(("/", "\\", ".", "~")):
        return True
    return not re.match(r"^[^/\\]+:", url)


def remote_points_local(tokens):
    words, index = [], 0
    while index < len(tokens):
        text = tokens[index][0]
        if text in ("-t", "-m"):
            index += 1
        elif not text.startswith("-"):
            words.append(tokens[index])
        index += 1
    if len(words) < 3 or words[0][0] not in ("add", "set-url"):
        return False
    return expanded(words[2]) or is_local_url(words[2][0])


def fetches_into_remote_refs(tokens):
    for text, _ in tokens:
        value = text.split("=", 1)[1] if text.startswith("--refmap=") else text
        if value.startswith("-") or ":" not in value:
            continue
        if value.rsplit(":", 1)[1].lstrip("+").lower().replace("\\", "/").startswith("refs/remotes/"):
            return True
    return False


def repoints_remote_refs(command, ops, powershell=False):
    if REMOTE_REF_REDIRECT.search(command) or writes_path(command, powershell, REMOTE_REF_FILES):
        return True
    for item in ops:
        if item["op"] in REMOTE_REF_TOOLS:
            writes, texts = ref_write_args(item["tokens"])
            if writes and ("--stdin" in texts
                           or any("refs/remotes/" in text.lower().replace("\\", "/") for text in texts)):
                return True
        if item["op"] in FETCH_OPS and fetches_into_remote_refs(item["tokens"]):
            return True
        if item["op"] == "remote":
            words = [text for text, _ in item["tokens"] if not text.startswith("-")]
            if words[:1] == ["set-head"] or remote_points_local(item["tokens"]):
                return True
    return False


def skips_hooks(op, tokens):
    index = 0
    while index < len(tokens):
        text = tokens[index][0]
        if text == "--":
            break
        if text.startswith("--"):
            name = text.split("=", 1)[0]
            if len(name) > len("--no-ver") and "--no-verify".startswith(name):
                return True
            if name in (COMMIT_VALUE_OPTIONS if op == "commit" else PUSH_VALUE_OPTIONS) and "=" not in text:
                index += 1
        elif op == "commit" and text.startswith("-") and len(text) > 1:
            for position, flag in enumerate(text[1:], 1):
                if flag == "n":
                    return True
                if flag in COMMIT_ATTACHED_FLAGS:
                    break
                if flag in COMMIT_VALUE_FLAGS:
                    index += position == len(text) - 1
                    break
        elif text in PUSH_VALUE_OPTIONS:
            index += 1
        index += 1
    return False


def config_read_option(texts, index):
    text = texts[index]
    if text in CONFIG_READ_FLAGS or text.startswith(CONFIG_READ_ATTACHED):
        return 1
    if text in CONFIG_READ_VALUE_FLAGS:
        return 2 if index + 1 < len(texts) else 0
    return 1 if text[:2] in ("-t", "-f") and len(text) > 2 else 0


def is_edit_option(text):
    if text.startswith("--"):
        name = text.split("=", 1)[0]
        return len(name) >= 3 and "--edit".startswith(name)
    if not text.startswith("-"):
        return False
    for letter in text[1:]:
        if letter == "e":
            return True
        if letter in "tf":
            return False
    return False


def mentions_protected(text):
    return any(PROTECTED_KEY.match(part) or PROTECTED_SECTION.match(part) for part in [text, *text.split("=", 1)])


def config_first_word(texts):
    index = 0
    while index < len(texts):
        text = texts[index]
        if text == "--":
            return texts[index + 1] if index + 1 < len(texts) else ""
        if not text.startswith("-") or text == "-":
            return text
        index += 2 if text in CONFIG_READ_VALUE_FLAGS else 1
    return ""


def config_is_plain_read(texts):
    words, reads_value, subcommand, stopped, index = [], False, None, False, 0
    while index < len(texts):
        text = texts[index]
        if stopped:
            words.append(text)
        elif text == "--":
            stopped = True
        elif text.startswith("-") and text != "-":
            consumed = config_read_option(texts, index)
            if not consumed:
                return False
            reads_value = reads_value or text in CONFIG_GET_FLAGS
            index += consumed
            continue
        elif subcommand is None and not words and text in CONFIG_READ_SUBCOMMANDS:
            subcommand = text
            reads_value = reads_value or text == "get"
        else:
            words.append(text)
            stopped = subcommand is None
        index += 1
    if words and "=" in words[0]:
        return False
    return len(words) <= (2 if reads_value else 1)


def config_writes_protected(tokens):
    texts = [text for text, _ in tokens]
    options = texts[:texts.index("--")] if "--" in texts else texts
    if any(is_edit_option(text) for text in options) or config_first_word(texts) == "edit":
        return True
    if not any(mentions_protected(text) for text in texts):
        return False
    return not config_is_plain_read(texts)


def writes_path(command, powershell, pattern):
    for segment in split_segments(command, powershell):
        tokens = tokenize(segment, powershell)
        unquoted = " ".join(text for text, _ in tokens)
        if not (pattern.search(segment) or pattern.search(unquoted)):
            continue
        tokens = strip_reserved(tokens, powershell)
        while tokens and tokens[0][0].lower() in WRAPPERS:
            tokens = strip_reserved(tokens[1:], powershell)
        name = program(tokens[0][0]) if tokens else ""
        if name == "git":
            continue
        if name not in FILE_READERS or ">" in HARMLESS_REDIRECT.sub("", segment):
            return True
    return False


NO_VERIFY = re.compile(r"(?i)no-veri")
INTERPRETERS = re.compile(r"^(?:python[\d.]*|py|node|nodejs|deno|bun|perl|ruby|php|sh|bash|zsh|dash|ksh|pwsh"
                          r"|powershell|cmd)$")
EXEC_WRAPPERS = {"xargs", "parallel", "eval", "invoke-expression", "iex", "start-process", "saps"}
INLINE_CODE_SHORT = re.compile(r"^-[A-Za-z]{0,2}[ceE]$")
INLINE_CODE_FLAGS = {"--eval", "--print", "-p", "-r", "/c", "/k", "eval", "-command"}
GIT_THEN_NO_VERIFY = re.compile(r"(?i)\bgit\b.*no-veri")


def inline_code(rest):
    for index, text in enumerate(rest):
        low = text.lower()
        if INLINE_CODE_SHORT.match(text) or low in INLINE_CODE_FLAGS or (
                len(low) >= 3 and low.startswith("-c") and "-command".startswith(low)):
            return rest[index + 1:]
    return []


def interpreter_no_verify(command, powershell):
    interpreter_seen = False
    for segment in split_segments(command, powershell):
        tokens = strip_prefix(tokenize(segment, powershell), powershell, {})
        if not tokens:
            continue
        name, rest = program(tokens[0][0]), [text for text, _ in tokens[1:]]
        if INTERPRETERS.match(name):
            interpreter_seen = True
            if any(NO_VERIFY.search(text) for text in inline_code(rest)):
                return True
            continue
        if name == "find":
            action = next((index for index, text in enumerate(rest) if text in FIND_ACTIONS - {"-delete"}), None)
            rest = rest[action:] if action is not None else []
        elif name not in EXEC_WRAPPERS:
            continue
        if GIT_THEN_NO_VERIFY.search(" ".join(rest)):
            return True
    return interpreter_seen and "<<" in command and bool(NO_VERIFY.search(command))


def guard_reason(command, powershell, ops, base=None):
    if interpreter_no_verify(command, powershell):
        return HOOKS_DENY
    for item in ops:
        if any(PROTECTED_KEY.match(key) for key, _ in item["pairs"]):
            return CONFIG_DENY
        for assign in item["assigns"]:
            key, _, value = assign.partition("=")
            key = key.upper()
            if key in ("GIT_CONFIG", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM") and item["op"] in SCANNED_OPS:
                return HOOKS_DENY
            if key.startswith("GIT_CONFIG") and PROTECTED_CONFIG_VALUE.search(value):
                return CONFIG_DENY
        if item["op"] in ("commit", "push") and skips_hooks(item["op"], item["tokens"]):
            return HOOKS_DENY
        if item["op"] == "config" and config_writes_protected(item["tokens"]):
            return CONFIG_DENY
    state = {"base": base, "cwd": base or os.getcwd(), "in_git": False, "protected": None, "variables": {},
             "git_vars": set(), "git_parent_vars": set(), "git_dir_vars": set()}
    if writes_path(command, powershell, GIT_INTERNALS):
        return HOOKS_DENY
    reason = tampers_with_hooks(command, powershell, state)
    if reason:
        return reason
    if writes_global_gitconfig(command, powershell, base):
        return GITCONFIG_DENY
    return None


def native_hooks_missing(cwd):
    code, hooks_dir = git(["rev-parse", "--git-path", "hooks"], cwd)
    if code != 0:
        return []
    hooks_dir = os.path.join(cwd or os.getcwd(), hooks_dir.strip())
    missing = []
    for stage in NATIVE_HOOKS:
        try:
            with open(os.path.join(hooks_dir, stage), encoding="utf-8", errors="replace") as handle:
                installed = HOOK_MARKER in handle.read()
        except OSError:
            installed = False
        if not installed:
            missing.append(stage)
    return missing


def warn_missing_hooks(targets, tops):
    for item, cwd in targets:
        if item["op"] not in ("commit", "push") or cwd is None or not tops.get(cwd):
            continue
        missing = native_hooks_missing(cwd)
        if missing:
            script = os.path.abspath(__file__).replace("\\", "/")
            sys.stderr.write(f"Warning: the pipeline's git {' and '.join(missing)} hook(s) are not installed in "
                             f"{tops[cwd]}, so commits and pushes made outside this check are not scanned. "
                             f"Ask the user to run there: python \"{script}\" --install-pre-commit "
                             "--install-pre-push\n")
            return


def is_bare(cwd):
    code, out = git(["rev-parse", "--is-bare-repository"], cwd)
    return code == 0 and out.strip() == "true"


ERROR_RISKY_OPS = SCANNED_OPS | REMOTE_REF_TOOLS | FETCH_OPS | {"stage", "remote", "config"}


def error_word_lists(text, powershell):
    lists = [[word for word in (part.strip("\"'`") for part in re.split(r"[\s;&|(){}]+", text)) if word]]
    for mode in {powershell, False}:
        try:
            lists.append([token.lower() for segment in split_segments(text, mode)
                          for token, _ in tokenize(segment, mode)])
        except Exception:
            lists.append(re.sub(r"[\\'\"`]", "", text).split())
    return lists


def blocks_on_error(raw):
    text = raw.lower()
    if ALLOWLIST_FILE in text:
        return True
    powershell = False
    try:
        payload = json.loads(raw)
        tool_input = payload.get("tool_input") or {}
        if payload.get("tool_name") in FILE_TOOLS:
            target = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
            return (is_allowlist_path(target) or is_remote_ref_path(target) or is_git_internal_path(target)
                    or is_global_gitconfig(target))
        text = str(tool_input.get("command") or "").lower()
        powershell = payload.get("tool_name") == "PowerShell"
    except Exception:
        pass
    if GIT_INTERNALS.search(text):
        return True
    value_options = {option.lower() for option in GIT_VALUE_OPTIONS}
    builtins = None
    for words in error_word_lists(text, powershell):
        for index, word in enumerate(words):
            if program(word) != "git":
                continue
            rest = words[index + 1:]
            while rest and rest[0].startswith("-"):
                rest = rest[2:] if rest[0] in value_options else rest[1:]
            if not rest:
                continue
            if rest[0] in ERROR_RISKY_OPS:
                return True
            if builtins is None:
                builtins = set(git(["--list-cmds=builtins"], None)[1].split())
            if rest[0] not in builtins:
                return True
    return False


def main(raw):
    payload = json.loads(raw)
    tool_input = payload.get("tool_input") or {}
    if payload.get("tool_name") in FILE_TOOLS:
        target = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if is_allowlist_path(target):
            deny(ALLOWLIST_DENY)
        if is_remote_ref_path(target):
            deny(REMOTE_REFS_DENY)
        if is_git_internal_path(target):
            deny(HOOKS_DENY)
        if is_global_gitconfig(target, payload.get("cwd") or None):
            deny(GITCONFIG_DENY)
        allow()
    command = tool_input.get("command", "") or ""
    powershell = payload.get("tool_name") == "PowerShell"
    base = payload.get("cwd") or None
    ops = expand_ops(find_git_ops(command, powershell), base, powershell)
    if repoints_remote_refs(command, ops, powershell):
        deny(REMOTE_REFS_DENY)
    guarded_reason = guard_reason(command, powershell, ops, base)
    if guarded_reason:
        deny(guarded_reason)
    tops, bare, targets = {}, set(), []
    for item in ops:
        cwd = resolve_cwd(item["steps"], base, powershell)
        if cwd is not None and cwd not in tops:
            code, top = git(["rev-parse", "--show-toplevel"], cwd)
            tops[cwd] = top.strip() if code == 0 and top.strip() else None
            if tops[cwd] is None and is_bare(cwd):
                bare.add(cwd)
        if item["op"] in SCANNED_OPS and cwd is not None and tops[cwd] is None:
            if not (item["op"] == "push" and cwd in bare):
                deny(UNRESOLVED.format(op=item["op"], cwd=cwd))
        targets.append((item, cwd))
    if touches_allowlist(command, powershell, base, ops):
        deny(ALLOWLIST_DENY)
    for item in ops:
        if item.get("unverifiable"):
            deny(ALIAS_UNVERIFIABLE.format(op=item["op"]))
    pending, unknown_add = {}, False
    for item, cwd in targets:
        guarded = item["op"] in ("commit", "push")
        if cwd is None:
            if item["op"] == "add":
                unknown_add = True
            if not guarded:
                continue
            deny("Cannot verify which repository this git " + item["op"] + " targets: the path "
                 "in the command uses a command substitution or a variable not set in the "
                 "environment. Use a literal path (or cd to it in a separate command) and run "
                 "it again.")
        top = tops[cwd]
        if top is None and not (item["op"] == "push" and cwd in bare):
            continue
        if item["op"] == "add":
            args = add_args(item["tokens"])
            if args is None:
                unknown_add = True
            else:
                pending.setdefault(top, []).append((cwd, args))
            continue
        if not guarded:
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
    warn_missing_hooks(targets, tops)
    allow()


def run():
    if "--pre-push" in sys.argv:
        pre_push()
    if "--pre-commit" in sys.argv:
        pre_commit()
    if {"--install-pre-push", "--install-pre-commit", "--enable-gate"} & set(sys.argv):
        install()
    if "--fingerprint" in sys.argv:
        print_fingerprints()
    raw = ""
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", "replace")
        main(raw)
    except Exception as error:
        try:
            blocked = blocks_on_error(raw)
        except Exception:
            blocked = "git" in raw.lower()
        if blocked:
            deny(HOOK_ERROR.format(error=f"{type(error).__name__}: {error}"[:300]))
        allow()


if __name__ == "__main__":
    try:
        run()
    except Exception as error:
        for flag, what in (("--pre-push", "push"), ("--pre-commit", "commit")):
            if flag in sys.argv:
                sys.stderr.write(f"Secret scan failed ({redact(repr(error))}); blocking the {what}. Ask the "
                                 f"user to check the scanner: a {what} made while it fails is not scanned.\n")
                sys.exit(1)
        allow()
