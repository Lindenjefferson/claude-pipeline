import importlib.util, os, re, subprocess, sys, tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pre-commit-secret-scan.py")
os.environ["CLAUDE_PIPELINE_HOME"] = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
base = tempfile.mkdtemp(prefix="allowlist_")
repo = os.path.join(base, "repo")
os.makedirs(repo)
results = []
# secret-looking values are split so this file's own lines do not trip the scanner
FALSE_POSITIVE = "api_token = " + '"' + "fixture_Value_" + "0123456789" + '"'
REAL = "password = " + '"' + "S3cr3tP4ss" + "w0rd!2026" + '"'
A9 = "update auth.users set encrypted_pass" "word = encrypted_password where id = '00000000-0000-0000-0000-000000000001';"


def sh(cwd, *a, check=True, stdin=None):
    return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=check, input=stdin)


def commit_check():
    r = sh(repo, sys.executable, HOOK, "--pre-commit", check=False)
    return ("DENY" if r.returncode else "ALLOW"), r.stderr


def check(name, ok, detail=""):
    results.append(ok)
    print("PASS" if ok else "FAIL", name, "" if ok else detail)


def write(name, text):
    with open(os.path.join(repo, name), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def fingerprints(reason):
    return re.findall(r"fingerprint ([0-9a-f]{64})", reason)


sh(repo, "git", "init", "-q")
for k, v in (("user.email", "t@t.com"), ("user.name", "t"), ("core.autocrlf", "false")):
    sh(repo, "git", "config", k, v)
write("a.txt", "base\n")
sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-q", "-m", "base")
sh(repo, sys.executable, HOOK, "--install-pre-commit")

write("seed.sql", A9 + "\n")
sh(repo, "git", "add", "-A")
decision, reason = commit_check()
check("A9 SQL self-assignment commits", decision == "ALLOW", reason)
sh(repo, "git", "commit", "-q", "-m", "seed")

write("fixture.py", FALSE_POSITIVE + "\n")
write("config.py", REAL + "\n")
sh(repo, "git", "add", "-A")
decision, reason = commit_check()
marks = fingerprints(reason)
check("two flagged lines block the commit", decision == "DENY", reason)
check("block message shows one fingerprint per finding", len(marks) == 2, reason)
check("block message names each file", "in fixture.py" in reason and "in config.py" in reason, reason)
check("block message explains the allowlist and the command", ".pipeline-secrets-allow" in reason and "--fingerprint" in reason, reason)
check("the fingerprint command names the Python that ran the scan, not a bare `python`",
      f'| "{sys.executable.replace(chr(92), "/")}" "' in reason, reason)
listed = sh(repo, sys.executable, HOOK, "--fingerprint", stdin=sh(repo, "git", "diff", "--cached").stdout).stdout
check("--fingerprint on the staged diff prints the same fingerprints", sorted(fingerprints(reason)) == sorted(re.findall(r"^([0-9a-f]{64})", listed, re.M)), listed)
fixture_mark = next(mk for mk in marks if f"in fixture.py (fingerprint {mk})" in reason)

plain = sh(repo, sys.executable, HOOK, "--fingerprint", stdin=FALSE_POSITIVE + "\n", check=False)
check("--fingerprint on plain text without --path refuses", plain.returncode == 2 and "--path" in plain.stderr, plain.stderr)
plain = sh(repo, sys.executable, HOOK, "--fingerprint", "--path", "fixture.py", stdin=FALSE_POSITIVE + "\n").stdout
check("--fingerprint --path matches the commit fingerprint", plain.startswith(fixture_mark), plain)

write(".pipeline-secrets-allow", f"{fixture_mark}  # test fixture, not a credential\n")
decision, reason = commit_check()
check("an entry only in the working tree is ignored", decision == "DENY" and fixture_mark in reason, reason)
check("block message tells the agent to have the user stage the entry", "stage it" in reason, reason)
sh(repo, "git", "add", "-A")
decision, reason = commit_check()
check("allowlisted line no longer reported once staged", fixture_mark not in reason, reason)
check("the other flagged line still blocks", decision == "DENY" and "in config.py" in reason, reason)

sh(repo, "git", "rm", "-q", "--cached", "config.py")
os.remove(os.path.join(repo, "config.py"))
decision, reason = commit_check()
check("commit with only the allowlisted line passes", decision == "ALLOW", reason)
sh(repo, "git", "commit", "-q", "-m", "fixture")

write("fixture.py", FALSE_POSITIVE.replace("0123", "0124") + "\n")
sh(repo, "git", "add", "-A")
decision, reason = commit_check()
check("an edited line needs a new fingerprint", decision == "DENY", reason)
sh(repo, "git", "checkout", "-q", "--", ".")
sh(repo, "git", "reset", "-q", "--hard")

spec = importlib.util.spec_from_file_location("scan", HOOK)
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)
check("the same line in another file has another fingerprint",
      scanner.fingerprint("fixture2.py", FALSE_POSITIVE) != fixture_mark)
sh(repo, "git", "rm", "-q", "fixture.py")
sh(repo, "git", "commit", "-q", "-m", "drop fixture")
write("fixture.py", FALSE_POSITIVE + "\n")
sh(repo, "git", "add", "-A")
r = sh(repo, "git", "commit", "-q", "-m", "through git", check=False)
check("the installed git hook honours the staged allowlist", r.returncode == 0, r.stderr[-300:])
write("config.py", REAL + "\n")
sh(repo, "git", "add", "config.py")
r = sh(repo, "git", "commit", "-q", "-m", "real secret", check=False)
check("the installed git hook blocks a real secret", r.returncode != 0 and "in config.py" in r.stderr, r.stderr[-300:])

sh(repo, "git", "reset", "-q", "--hard")
write(".env.test", "PORT=3000\n")
sh(repo, "git", "add", ".env.test")
decision, reason = commit_check()
env_mark = re.search(r"\.env\.test \(fingerprint ([0-9a-f]{64})\)", reason)
check("an .env-style file is blocked, and the message gives the fingerprint of its path",
      decision == "DENY" and env_mark is not None, reason)
write(".pipeline-secrets-allow", f"{fixture_mark}  # test fixture, not a credential\n"
      f"{env_mark.group(1) if env_mark else '-'}  # defaults the framework versions, no secret\n")
sh(repo, "git", "add", "-A")
decision, reason = commit_check()
check("a staged entry with that fingerprint lets that .env-style file in", decision == "ALLOW", reason)
write(".env.test", "PORT=3000\n" + REAL + "\n")
write(".env.local", "PORT=3001\n")
sh(repo, "git", "add", "-A")
decision, reason = commit_check()
check("the lines of an allowed .env-style file are still scanned", decision == "DENY" and "in .env.test" in reason,
      reason)
check("another .env-style file still blocks", ".env.local (fingerprint" in reason, reason)

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
sys.exit(0 if all(results) else 1)
