import importlib.util, json, os, re, subprocess, sys, tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pre-commit-secret-scan.py")
os.environ["CLAUDE_PIPELINE_HOME"] = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
base = tempfile.mkdtemp(prefix="allowlist_")
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

plain = sh(repo, sys.executable, HOOK, "--fingerprint", stdin=FALSE_POSITIVE + "\n", check=False)
check("--fingerprint on plain text without --path refuses", plain.returncode == 2 and "--path" in plain.stderr, plain.stderr)
plain = sh(repo, sys.executable, HOOK, "--fingerprint", "--path", "fixture.py", stdin=FALSE_POSITIVE + "\n").stdout
check("--fingerprint --path matches the commit fingerprint", plain.startswith(fixture_mark), plain)

write(".pipeline-secrets-allow", f"{fixture_mark}  # test fixture, not a credential\n")
decision, reason = hook("git commit -m x", repo)
check("an entry only in the working tree is ignored", decision == "DENY" and fixture_mark in reason, reason)
check("block message tells the agent to have the user stage the entry", "stage it" in reason, reason)
sh(repo, "git", "add", "-A")
decision, reason = hook("git commit -m x", repo)
check("allowlisted line no longer reported once staged", fixture_mark not in reason, reason)
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

spec = importlib.util.spec_from_file_location("scan", HOOK)
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)
fixture2_mark = scanner.fingerprint("fixture2.py", FALSE_POSITIVE)
check("the same line in another file has another fingerprint", fixture2_mark != fixture_mark)
write("fixture2.py", FALSE_POSITIVE + " \n")
sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-q", "-m", "fixture2, no entry for it")
r = sh(repo, "git", "push", "origin", "HEAD:refs/heads/main", check=False)
check("git pre-push blocks without the entry and shows the fingerprint", r.returncode != 0 and fixture2_mark in r.stderr, r.stderr[-300:])
write(".pipeline-secrets-allow", f"{fixture_mark}  # fixture\n{fixture2_mark}  # fixture2\n")
r = sh(repo, "git", "push", "origin", "HEAD:refs/heads/main", check=False)
check("git pre-push ignores an entry only in the working tree", r.returncode != 0 and fixture2_mark in r.stderr, r.stderr[-300:])
decision, reason = hook("git push origin HEAD:refs/heads/main", repo)
check("Claude push hook ignores an entry only in the working tree", decision == "DENY" and fixture2_mark in reason, reason)
sh(repo, "git", "add", "-A")
r = sh(repo, "git", "push", "origin", "HEAD:refs/heads/main", check=False)
check("git pre-push ignores an entry only staged", r.returncode != 0 and fixture2_mark in r.stderr, r.stderr[-300:])
sh(repo, "git", "commit", "-q", "-m", "allow fixture2")
decision, reason = hook("git push origin HEAD:refs/heads/main", repo)
check("Claude push hook honours an entry in the pushed tree", decision == "ALLOW", reason)
r = sh(repo, "git", "push", "origin", "HEAD:refs/heads/main", check=False)
check("git pre-push honours an entry in the pushed tree", r.returncode == 0, r.stderr[-300:])


def tool(name, tool_input):
    payload = json.dumps({"tool_name": name, "tool_input": tool_input, "cwd": repo})
    r = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True, encoding="utf-8")
    return "DENY" if r.stdout.strip() else "ALLOW"


allow_path = os.path.join(repo, ".pipeline-secrets-allow")
denied = [
    ("Write", {"file_path": allow_path, "content": "x"}),
    ("Edit", {"file_path": allow_path.replace("\\", "/"), "old_string": "a", "new_string": "b"}),
    ("MultiEdit", {"file_path": ".pipeline-secrets-allow", "edits": []}),
    ("NotebookEdit", {"notebook_path": allow_path, "new_source": "x"}),
    ("Bash", {"command": "echo abc >> .pipeline-secrets-allow"}),
    ("Bash", {"command": "cp /tmp/x .pipeline-secrets-allow"}),
    ("Bash", {"command": "git add .pipeline-secrets-allow && git commit -m x"}),
    ("Bash", {"command": "git checkout -- .pipeline-secrets-allow"}),
    ("Bash", {"command": "bash -c 'tee -a .pipeline-secrets-allow < x'"}),
    ("Bash", {"command": "sed -i 's/a/b/' .PIPELINE-SECRETS-ALLOW"}),
    ("PowerShell", {"command": "Add-Content .pipeline-secrets-allow 'abc'"}),
    ("PowerShell", {"command": "Set-Content -Path .\\.pipeline-secrets-allow -Value x"}),
]
for name, tool_input in denied:
    check(f"{name} denied: {tool_input.get('command') or tool_input.get('file_path') or tool_input.get('notebook_path')}", tool(name, tool_input) == "DENY")
allowed = [
    ("Write", {"file_path": os.path.join(repo, "notes.txt"), "content": "x"}),
    ("Edit", {"file_path": os.path.join(repo, "pipeline-secrets-allow.md"), "old_string": "a", "new_string": "b"}),
    ("Bash", {"command": "git diff main -- .pipeline-secrets-allow"}),
    ("Bash", {"command": "git log -p -- .pipeline-secrets-allow 2>&1"}),
    ("Bash", {"command": "cat .pipeline-secrets-allow"}),
    ("Bash", {"command": "git show HEAD:.pipeline-secrets-allow 2>/dev/null"}),
    ("PowerShell", {"command": "Get-Content .pipeline-secrets-allow"}),
]
for name, tool_input in allowed:
    check(f"{name} allowed: {tool_input.get('command') or tool_input.get('file_path')}", tool(name, tool_input) == "ALLOW")

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
