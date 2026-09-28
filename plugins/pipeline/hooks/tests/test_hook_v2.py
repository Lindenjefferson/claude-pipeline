import tempfile
import json, os, subprocess, sys, time

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pre-commit-secret-scan.py")
os.environ["CLAUDE_PIPELINE_HOME"] = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
base = os.path.join(tempfile.gettempdir(), f"hookv2_{int(time.time())}")
repo = os.path.join(base, "repo")
remote = os.path.join(base, "remote.git")
elsewhere = os.path.join(base, "elsewhere")
for d in (repo, elsewhere):
    os.makedirs(d)
results = []


def sh(cwd, *a, check=True):
    return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=check)


def hook(command, cwd):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd})
    r = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True, encoding="utf-8")
    return "DENY" if r.stdout.strip() else "ALLOW"


def check(name, got, expected):
    ok = got == expected
    results.append(ok)
    print("PASS" if ok else "FAIL", name, "->", got)


sh(base, "git", "init", "-q", "--bare", remote)
sh(repo, "git", "init", "-q")
for k, v in (("user.email", "t@t.com"), ("user.name", "t"), ("core.autocrlf", "false")):
    sh(repo, "git", "config", k, v)
sh(repo, "git", "remote", "add", "origin", remote)
open(os.path.join(repo, "a.txt"), "w").write("base\n")
sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-q", "-m", "base")
sh(repo, "git", "push", "-q", "origin", "HEAD:refs/heads/main")
sh(repo, sys.executable, HOOK, "--install-pre-push")

SECRET = "token = abcdefghijklmnopqrstuv1234\n"

open(os.path.join(repo, "pt.md"), "w", encoding="utf-8").write("descrição 📋 ação — status 🚧\n" + SECRET)
sh(repo, "git", "add", "-A")
check("commit: secret next to accents/emoji", hook("git commit -m x", repo), "DENY")
sh(repo, "git", "reset", "-q")
open(os.path.join(repo, "pt.md"), "wb").write(b"\x8d\x81\x8f\x90 raw bytes\n" + SECRET.encode())
sh(repo, "git", "add", "-A")
check("commit: secret next to undefined cp1252 bytes", hook("git commit -m x", repo), "DENY")
sh(repo, "git", "reset", "-q")
open(os.path.join(repo, "pt.md"), "w", encoding="utf-8").write("descrição 📋 ação — sem segredo\n")
sh(repo, "git", "add", "-A")
check("commit: clean non-ASCII file", hook("git commit -m x", repo), "ALLOW")
sh(repo, "git", "reset", "-q")

open(os.path.join(repo, "s.txt"), "w").write(SECRET)
sh(repo, "git", "add", "-A")
check("cd <repo> && git commit (session cwd elsewhere)", hook(f'cd "{repo}" && git commit -m x', elsewhere), "DENY")
check("git -C <repo> commit (session cwd elsewhere)", hook(f'git -C "{repo}" commit -m x', elsewhere), "DENY")
msys = "/" + repo[0].lower() + repo[2:].replace("\\", "/")
check("git -C /c/... MSYS path", hook(f'git -C "{msys}" commit -m x', elsewhere), "DENY")
check("git -C $VAR is unverifiable -> deny", hook('git -C "$WT" commit -m x', elsewhere), "DENY")
check("cd $VAR && git push is unverifiable -> deny", hook('cd $WT && git push', elsewhere), "DENY")
check("unrelated cd + git status", hook('cd "$WT" && git status', elsewhere), "ALLOW")
sh(repo, "git", "reset", "-q")
os.remove(os.path.join(repo, "s.txt"))

os.makedirs(os.path.join(repo, "docs", "quality-reports"))
open(os.path.join(repo, "docs", "quality-reports", ".gitkeep"), "w").write("")
sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-q", "-m", "opt in")
check("push gate via cd form, no approval", hook(f'cd "{repo}" && git push origin HEAD:main', elsewhere), "DENY")

sh(repo, "git", "reset", "-q", "--hard", "HEAD~1")
open(os.path.join(repo, "pt.md"), "w", encoding="utf-8").write("descrição 📋 ação\n" + SECRET)
sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-q", "-m", "pt with secret")
r = sh(repo, "git", "push", "origin", "HEAD:refs/heads/main", check=False)
got = "REJECTED" if r.returncode != 0 and "Secret scan blocked" in r.stderr else f"PASSED-THROUGH rc={r.returncode} {r.stderr[-120:]}"
check("git pre-push rejects secret next to non-ASCII text", got, "REJECTED")
sh(repo, "git", "reset", "-q", "--hard", "HEAD~1")
open(os.path.join(repo, "pt.md"), "w", encoding="utf-8").write("descrição 📋 ação sem segredo\n")
sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-q", "-m", "clean pt")
r = sh(repo, "git", "push", "-q", "origin", "HEAD:refs/heads/main", check=False)
check("git pre-push allows clean non-ASCII push", "OK" if r.returncode == 0 else f"BLOCKED {r.stderr[-160:]}", "OK")

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
