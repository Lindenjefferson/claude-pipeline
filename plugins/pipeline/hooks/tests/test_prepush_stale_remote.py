import os, subprocess, sys, tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pre-commit-secret-scan.py")
os.environ["CLAUDE_PIPELINE_HOME"] = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
base = tempfile.mkdtemp(prefix="prepushstale_")
remote = os.path.join(base, "remote.git")
repo = os.path.join(base, "repo")
peer = os.path.join(base, "peer")
os.makedirs(base, exist_ok=True)
results = []


def run(cwd, *a, check=True):
    return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True, check=check)


def check(name, ok, detail=""):
    results.append(ok)
    print("PASS" if ok else "FAIL", name, "" if ok else f"| {detail[-300:]}")


def configure(path):
    for k, v in (("user.email", "t@t.com"), ("user.name", "t"), ("core.autocrlf", "false")):
        run(path, "git", "config", k, v)


run(base, "git", "init", "-q", "--bare", remote)
os.makedirs(repo, exist_ok=True)
run(repo, "git", "init", "-q", "-b", "main")
configure(repo)
run(repo, "git", "remote", "add", "origin", remote)
open(os.path.join(repo, "a.txt"), "w").write("base\n")
run(repo, "git", "add", "-A"); run(repo, "git", "commit", "-q", "-m", "base")
run(repo, "git", "push", "-q", "origin", "main")
run(repo, sys.executable, HOOK, "--install-pre-push")

run(base, "git", "clone", "-q", "-b", "main", remote, peer)
configure(peer)
open(os.path.join(peer, "p.txt"), "w").write("peer\n")
run(peer, "git", "add", "-A"); run(peer, "git", "commit", "-q", "-m", "peer")
run(peer, "git", "push", "-q", "origin", "main")

open(os.path.join(repo, ".env"), "w").write("FOO=bar\n")
run(repo, "git", "add", "-A"); run(repo, "git", "commit", "-q", "-m", "env file")
r = run(repo, "git", "push", "--force", "origin", "main", check=False)
check("force push over an unfetched remote commit still flags an .env file",
      r.returncode != 0 and ".env-style file" in r.stderr, r.stderr)

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
