import os, subprocess, sys, tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pre-commit-secret-scan.py")
os.environ["CLAUDE_PIPELINE_HOME"] = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
base = tempfile.mkdtemp(prefix="hooknative_")
repo = os.path.join(base, "repo")
os.makedirs(repo)
SECRET_LINE = "AWS_" + "KEY=AK" + "IAABCDEFGHIJKLMNOP\n"
results = []


def sh(cwd, *a, check=True, env=None, stdin=None):
    return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          check=check, env=env, input=stdin)


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("PASS" if ok else "FAIL", name, "" if ok else f"| {detail[-300:]}")


def write(folder, name, text):
    path = os.path.join(folder, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def configure(path):
    for k, v in (("user.email", "t@t.com"), ("user.name", "t"), ("core.autocrlf", "false")):
        sh(path, "git", "config", k, v)


sh(repo, "git", "init", "-q", "-b", "main")
configure(repo)
hooks_dir = os.path.join(repo, ".git", "hooks")
write(hooks_dir, "pre-commit", "#!/bin/sh\necho chained-ran >> \"$(git rev-parse --git-dir)/chained.log\"\n"
                               "[ ! -f block-me ] || { echo chained-blocked >&2; exit 3; }\n")
os.chmod(os.path.join(hooks_dir, "pre-commit"), 0o755)

write(hooks_dir, "pre-push", "#!/bin/sh\n# secretscan-managed\nexit 0\n")
r = sh(repo, sys.executable, HOOK, "--install-pre-commit", check=False)
check("install writes the pre-commit hook", r.returncode == 0 and "installed" in r.stdout, r.stdout + r.stderr)
check("install removes a pre-push hook left by an older version",
      not os.path.exists(os.path.join(hooks_dir, "pre-push")) and "removed" in r.stdout, r.stdout)
check("foreign pre-commit kept as pre-commit.pipeline-chained",
      "chained-ran" in open(os.path.join(hooks_dir, "pre-commit.pipeline-chained")).read())
check("pre-commit shim carries the marker", "secretscan-managed" in open(os.path.join(hooks_dir, "pre-commit")).read())
plugin_root = os.environ["CLAUDE_PIPELINE_HOME"].replace("\\", "/")
local_home = sh(repo, "git", "config", "--local", "--get", "pipeline.home", check=False).stdout.strip()
check("install points the repository's pipeline.home at this plugin, with no step by hand",
      local_home == plugin_root and "git config --global" not in r.stdout, local_home + " | " + r.stdout)
r = sh(repo, sys.executable, HOOK, "--install-pre-commit", check=False)
check("reinstall is idempotent and keeps the chained hook", r.returncode == 0
      and os.path.exists(os.path.join(hooks_dir, "pre-commit.pipeline-chained")), r.stderr)
other = os.path.join(base, "other")
os.makedirs(other)
sh(other, "git", "init", "-q")
write(os.path.join(other, ".git", "hooks"), "pre-commit", "#!/bin/sh\nexit 0\n")
write(os.path.join(other, ".git", "hooks"), "pre-commit.pipeline-chained", "#!/bin/sh\nexit 0\n")
r = sh(other, sys.executable, HOOK, "--install-pre-commit", check=False)
check("foreign hook plus an existing chained file: refuses, overwrites nothing",
      r.returncode == 2 and "secretscan" not in open(os.path.join(other, ".git", "hooks", "pre-commit")).read(), r.stderr)

write(repo, "cfg.txt", SECRET_LINE)
sh(repo, "git", "add", "cfg.txt")
r = sh(repo, "git", "commit", "-q", "-m", "initial with secret", check=False)
check("native pre-commit blocks a secret in the first commit (no HEAD yet)",
      r.returncode != 0 and "Secret scan blocked this commit" in r.stderr, r.stderr)
check("the chained hook ran first", "chained-ran" in open(os.path.join(repo, ".git", "chained.log")).read())
sh(repo, "git", "rm", "-q", "--cached", "cfg.txt")
os.remove(os.path.join(repo, "cfg.txt"))
write(repo, "a.txt", "base\n")
write(repo, ".pipeline-secrets-allow", "# user entries\n")
sh(repo, "git", "add", "-A")
r = sh(repo, "git", "commit", "-q", "-m", "base", check=False)
check("clean commit passes the hook", r.returncode == 0, r.stderr)
write(repo, "block-me", "x\n")
r = sh(repo, "git", "commit", "-q", "--allow-empty", "-m", "chained blocks", check=False)
check("a failing chained hook blocks the commit", r.returncode != 0 and "chained-blocked" in r.stderr, r.stderr)
os.remove(os.path.join(repo, "block-me"))

alt_index = os.path.join(base, "alt-index")
env = dict(os.environ, GIT_INDEX_FILE=alt_index)
sh(repo, "git", "read-tree", "HEAD", env=env)
write(repo, "cfg.txt", SECRET_LINE)
sh(repo, "git", "add", "cfg.txt", env=env)
r = sh(repo, "git", "commit", "-q", "-m", "relocated index", env=env, check=False)
check("native pre-commit scans a relocated GIT_INDEX_FILE", r.returncode != 0 and "Secret scan blocked" in r.stderr,
      r.stderr)
blob = sh(repo, "git", "hash-object", "-w", "cfg.txt").stdout.strip()
sh(repo, "git", "update-index", "--add", "--cacheinfo", f"100644,{blob},plumb.txt")
r = sh(repo, "git", "commit", "-q", "-m", "plumbing", check=False)
check("native pre-commit scans what update-index staged", r.returncode != 0 and "plumb.txt" in r.stderr, r.stderr)
r = sh(repo, "git", "commit", "-q", "-m", "commit -a", "-a", check=False)
check("native pre-commit scans commit -a", r.returncode != 0, r.stderr)
sh(repo, "git", "reset", "-q")
os.remove(os.path.join(repo, "cfg.txt"))
fp = sh(repo, sys.executable, HOOK, "--fingerprint", "--path", "cfg.txt", stdin=SECRET_LINE).stdout.split()[0]
write(repo, "cfg.txt", SECRET_LINE)
write(repo, ".pipeline-secrets-allow", f"# user entries\n{fp}  # test fixture\n")
sh(repo, "git", "add", "cfg.txt")
r = sh(repo, "git", "commit", "-q", "-m", "allowlist only in the working tree", check=False)
check("native pre-commit ignores an allowlist entry that is not staged", r.returncode != 0, r.stderr)
sh(repo, "git", "add", ".pipeline-secrets-allow")
r = sh(repo, "git", "commit", "-q", "-m", "allowlisted", check=False)
check("native pre-commit honours the allowlist read from the index", r.returncode == 0, r.stderr)
sh(repo, "git", "reset", "-q", "--hard", "HEAD~1")
write(hooks_dir, "pre-push", "#!/bin/sh\nexit 0\n")
sh(repo, sys.executable, HOOK, "--install-pre-commit")
check("a foreign pre-push hook is left alone", os.path.exists(os.path.join(hooks_dir, "pre-push")))
r = sh(repo, sys.executable, HOOK, "--pre-push", "origin", "x", stdin="refs/heads/main x refs/heads/main y\n",
       check=False)
check("--pre-push from an old shim exits 0 without scanning", r.returncode == 0, r.stderr)

write(repo, ".env.produção", "X=1\n")
sh(repo, "git", "add", "-A")
r = sh(repo, "git", "commit", "-q", "-m", "accented env", check=False)
check("an .env file with an accented name is blocked", r.returncode != 0 and ".env" in r.stderr, r.stderr)
sh(repo, "git", "reset", "-q")
os.remove(os.path.join(repo, ".env.produção"))
write(repo, ".env", "X=1\n")
sh(repo, "git", "add", ".env")
sh(repo, "git", "commit", "-q", "--no-verify", "-m", "tracked env (old mistake)")
sh(repo, "git", "rm", "-q", ".env")
r = sh(repo, "git", "commit", "-q", "-m", "remove the tracked env", check=False)
check("removing a tracked .env file is not blocked", r.returncode == 0, r.stderr)
with open(os.path.join(repo, "wide.txt"), "wb") as handle:
    handle.write(("KEY=" + "AKIAABCDEF" "GHIJKLMNOP\n").encode("utf-16"))
sh(repo, "git", "add", "wide.txt")
r = sh(repo, "git", "commit", "-q", "-m", "utf-16 secret", check=False)
check("a secret in a UTF-16 file is blocked", r.returncode != 0 and "wide.txt" in r.stderr, r.stderr)
sh(repo, "git", "reset", "-q")
os.remove(os.path.join(repo, "wide.txt"))
write(repo, "plus.txt", "++ " + "AKIAABCDEF" "GHIJKLMNOP\n")
sh(repo, "git", "add", "plus.txt")
r = sh(repo, "git", "commit", "-q", "-m", "plus line", check=False)
check("a secret on a line that starts with ++ is blocked", r.returncode != 0 and "plus.txt" in r.stderr, r.stderr)
sh(repo, "git", "reset", "-q")
os.remove(os.path.join(repo, "plus.txt"))

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
sys.exit(0 if all(results) else 1)
