import json, os, re, subprocess, sys, tempfile, time

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pre-commit-secret-scan.py")
os.environ["CLAUDE_PIPELINE_HOME"] = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
base = os.path.join(tempfile.gettempdir(), f"allowlist_{int(time.time())}")
repo = os.path.join(base, "repo")
remote = os.path.join(base, "remote.git")
os.makedirs(repo)
results = []
# secret-looking values are split so this file's own lines do not trip the scanner
FALSE_POSITIVE = "api_token = " + '"' + "fixture_Value_" + "0123456789" + '"'
REAL = "password = " + '"' + "S3cr3tP4ss" + "w0rd!2026" + '"'
A9 = "update auth.users set encrypted_pass" "word = encrypted_password where id = '00000000-0000-0000-0000-000000000001';"


def sh(cwd, *a, check=True, stdin=None):
    return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=check, input=stdin)


def hook(command, cwd):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd})
    r = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True, encoding="utf-8")
    if not r.stdout.strip():
        return "ALLOW", ""
    return "DENY", json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"]


def check(name, ok, detail=""):
    results.append(ok)
    print("PASS" if ok else "FAIL", name, "" if ok else detail)


def write(name, text):
    with open(os.path.join(repo, name), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def fingerprints(reason):
    return re.findall(r"fingerprint ([0-9a-f]{64})", reason)


sh(base, "git", "init", "-q", "--bare", remote)
sh(repo, "git", "init", "-q")
for k, v in (("user.email", "t@t.com"), ("user.name", "t"), ("core.autocrlf", "false")):
    sh(repo, "git", "config", k, v)
sh(repo, "git", "remote", "add", "origin", remote)
write("a.txt", "base\n")
sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-q", "-m", "base")
sh(repo, "git", "push", "-q", "origin", "HEAD:refs/heads/main")
sh(repo, sys.executable, HOOK, "--install-pre-push")

write("seed.sql", A9 + "\n")
sh(repo, "git", "add", "-A")
decision, reason = hook("git commit -m x", repo)
check("A9 SQL self-assignment commits", decision == "ALLOW", reason)
sh(repo, "git", "commit", "-q", "-m", "seed")

write("fixture.py", FALSE_POSITIVE + "\n")
write("config.py", REAL + "\n")
sh(repo, "git", "add", "-A")
decision, reason = hook("git commit -m x", repo)
marks = fingerprints(reason)
check("two flagged lines block the commit", decision == "DENY", reason)
check("block message shows one fingerprint per finding", len(marks) == 2, reason)
check("block message names each file", "in fixture.py" in reason and "in config.py" in reason, reason)
check("block message explains the allowlist and the command", ".pipeline-secrets-allow" in reason and "--fingerprint" in reason, reason)
listed = sh(repo, sys.executable, HOOK, "--fingerprint", stdin=sh(repo, "git", "diff", "--cached").stdout).stdout
check("--fingerprint on the staged diff prints the same fingerprints", sorted(fingerprints(reason)) == sorted(re.findall(r"^([0-9a-f]{64})", listed, re.M)), listed)
fixture_mark = next(mk for mk in marks if f"in fixture.py (fingerprint {mk})" in reason)

write(".pipeline-secrets-allow", f"{fixture_mark}  # test fixture, not a credential\n")
sh(repo, "git", "add", "-A")
decision, reason = hook("git commit -m x", repo)
check("allowlisted line no longer reported", fixture_mark not in reason, reason)
check("the other flagged line still blocks", decision == "DENY" and "in config.py" in reason, reason)

sh(repo, "git", "rm", "-q", "--cached", "config.py")
os.remove(os.path.join(repo, "config.py"))
decision, reason = hook("git commit -m x", repo)
check("commit with only the allowlisted line passes", decision == "ALLOW", reason)
sh(repo, "git", "commit", "-q", "-m", "fixture")

write("fixture.py", FALSE_POSITIVE.replace("0123", "0124") + "\n")
sh(repo, "git", "add", "-A")
decision, reason = hook("git commit -m x", repo)
check("an edited line needs a new fingerprint", decision == "DENY", reason)
sh(repo, "git", "checkout", "-q", "--", ".")
sh(repo, "git", "reset", "-q", "--hard")

r = sh(repo, "git", "push", "origin", "HEAD:refs/heads/main", check=False)
check("git pre-push honours the allowlist", r.returncode == 0, r.stderr[-300:])

write(".pipeline-secrets-allow", "")
write("fixture2.py", FALSE_POSITIVE + " \n")
sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-q", "-m", "fixture2, no allowlist")
r = sh(repo, "git", "push", "origin", "HEAD:refs/heads/main", check=False)
check("git pre-push blocks without the entry and shows the fingerprint", r.returncode != 0 and fixture_mark in r.stderr, r.stderr[-300:])

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
