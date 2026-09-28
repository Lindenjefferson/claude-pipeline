#!/usr/bin/env python3
"""PreToolUse hook for Claude Code Bash calls that run `git commit` or `git push`.

commit: blocks when the staged diff (plus tracked changes for `commit -a`) adds a
        secret-looking string or an .env-style file.
push:   blocks when the commits about to leave the machine add such content, and,
        in repos that opted in (a docs/quality-reports/ directory exists at the repo
        root), blocks unless the gate agent recorded approval of the current tree
        in <git-common-dir>/gate-approved (legacy name: manager-approved).

Run as a Claude hook it guards Claude's own git calls against accidents; it reads
only the command text, so a script that calls git inside is not seen, and it does
not affect commands typed in a user terminal. `--install-pre-push` writes a real
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


def resolve_path(path, base):
    single_quoted = path.startswith("'")
    path = path.strip("\"'")
    if "`" in path or "$(" in path:
        return None
    if not single_quoted:
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
    match = re.search(
        r"(^|[;&|]\s*)git\s+((?:-C\s+(?:\"[^\"]+\"|'[^']+'|\S+)\s+)*)(commit|push)\b",
        command)
    if not match:
        allow()
    op = match.group(3)

    cwd = payload.get("cwd") or None
    steps = re.findall(r"(?:^|[;&|]\s*)cd\s+(\"[^\"]+\"|'[^']+'|[^\s;&|]+)\s*(?:&&|;)",
                       command[:match.start(3)])
    dash_c = re.search(r"-C\s+(\"[^\"]+\"|'[^']+'|\S+)", match.group(2) or "")
    if dash_c:
        steps.append(dash_c.group(1))
    for step in steps:
        cwd = resolve_path(step, cwd)
        if cwd is None:
            deny("Cannot verify which repository this git " + op + " targets: the path in "
                 "the command uses a command substitution or a variable not set in the "
                 "environment. Use a literal path "
                 "(or cd to it in a separate command) and run it again.")

    code, top = git(["rev-parse", "--show-toplevel"], cwd)
    if code != 0:
        allow()
    top = top.strip()

    if op == "commit":
        _, names = git(["diff", "--cached", "--name-only"], cwd)
        _, diff = git(["diff", "--cached", "--"] + EXCLUDES, cwd)
        if re.search(r"(\s-[a-zA-Z]*a[a-zA-Z]*(\s|$))|\s--all\b", command):
            _, unstaged = git(["diff", "--"] + EXCLUDES, cwd)
            diff += "\n" + unstaged
        findings = scan(diff, names.splitlines())
        if findings:
            deny("Secret scan blocked this commit. Findings:\n- " + "\n- ".join(findings)
                 + "\n\nRemove the secret from the staged changes and try again. "
                   "For a false positive, unstage that file/line and commit the rest.")
        allow()

    if re.search(r"--dry-run|\s-n(\s|$)", command):
        allow()

    _, unpushed = git(["rev-list", "HEAD", "--not", "--remotes"], cwd)
    if unpushed.strip():
        _, diff = git(["log", "-p", "-m", "--format=", "HEAD", "--not", "--remotes", "--"]
                      + EXCLUDES, cwd)
        _, names = git(["log", "--name-only", "--format=", "HEAD", "--not", "--remotes"], cwd)
        findings = scan(diff, names.splitlines())
        if findings:
            deny("Secret scan blocked this push: the commits about to leave this machine "
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
            deny("Push blocked: this project requires the gate agent's approval before "
                 "anything leaves the machine, and the current tree (" + tree.strip()[:12]
                 + ") has none recorded. Run the gate (manager skill, step 4); on "
                   "APPROVED it records the tree in " + approvals + ". Commits made after "
                   "the approval need a new one. To push without this flow, run git push "
                   "yourself in a terminal.")
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
