import atexit, os, shutil, stat, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "..", "gate.py")
LEDGER = os.path.join(HERE, "..", "ledger.py")
base_dir = tempfile.mkdtemp(prefix="gate_")
repo = os.path.join(base_dir, "repo")
PY = sys.executable.replace("\\", "/")
SECRET = "AWS_" + "KEY=AK" + "IAABCDEFGHIJKLMNOP\n"
results = []


def cleanup():
    def retry(func, path, _):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except OSError:
            pass
    shutil.rmtree(base_dir, onerror=retry)


atexit.register(cleanup)
os.environ["GIT_CONFIG_GLOBAL"] = os.path.join(base_dir, "global.gitconfig")
open(os.environ["GIT_CONFIG_GLOBAL"], "w").close()


def sh(*args):
    return subprocess.run(list(args), cwd=repo, capture_output=True, text=True, encoding="utf-8", check=True).stdout


def write(name, text):
    with open(os.path.join(repo, name), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def commit(name, text, message):
    write(name, text)
    sh("git", "add", name)
    sh("git", "commit", "-q", "--no-verify", "-m", message)


def gate(*args):
    return subprocess.run([sys.executable, GATE, *args], cwd=repo, capture_output=True, text=True, encoding="utf-8")


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("PASS" if ok else "FAIL", name, "" if ok else f"| {str(detail)[-500:]}")


def claude_md(lint_ok=True, tests=True):
    lines = ["# p", "", "## Comandos", "", f"- Build: `{PY} -c \"print('built')\"`",
             f"- Lint: `{PY} -c \"import sys; sys.exit({0 if lint_ok else 1})\"`"]
    if tests:
        lines.append(f"- Testes: `{PY} -c \"print('3 passed')\"`")
    return "\n".join(lines + ["", "## Outra seção", "- Testes: `false`", ""])


os.makedirs(repo)
sh("git", "init", "-q", "-b", "main")
sh("git", "config", "user.email", "t@t.com")
sh("git", "config", "user.name", "t")
write(".gitignore", ".superpowers/\n")
sh("git", "add", ".gitignore")
commit("CLAUDE.md", claude_md(), "base")
sh("git", "switch", "-q", "-c", "feat/x")

r = gate("--base", "main")
check("no ledger: NOT READY", r.returncode == 1 and "Ledger:     FAIL" in r.stdout, r.stdout)

subprocess.run([sys.executable, LEDGER, "start", "--slug", "x", "--base", "main"], cwd=repo, check=True,
               capture_output=True)
commit("a.txt", "clean\n", "feat: a")
for args in (["--agent", "dev", "--task", "T1", "--verdict", "DONE"], ["--agent", "reviewer", "--verdict", "PASS"]):
    subprocess.run([sys.executable, LEDGER, "add", *args], cwd=repo, check=True, capture_output=True)
r = gate("--base", "main")
check("open cycle (qa missing): NOT READY", r.returncode == 1 and "qa has not run" in r.stdout, r.stdout)
subprocess.run([sys.executable, LEDGER, "add", "--agent", "qa", "--verdict", "PASS"], cwd=repo, check=True,
               capture_output=True)

r = gate("--base", "main")
check("closed cycle, clean tree, commands pass, no secrets: READY", r.returncode == 0 and "READY" in r.stdout, r.stdout)
check("commands come from the Comandos section only", "Build:      PASS" in r.stdout and "Testes:     PASS" in r.stdout
      and "Typecheck:  SKIP" in r.stdout, r.stdout)

write("dirty.txt", "x\n")
r = gate("--base", "main")
check("dirty tree: NOT READY", r.returncode == 1 and "Clean tree: FAIL" in r.stdout, r.stdout)
os.remove(os.path.join(repo, "dirty.txt"))

r = gate("--base", "main", "--cmd", f"Lint={PY} -c \"import sys; sys.exit(2)\"")
check("--cmd overrides a command and a failing one blocks", r.returncode == 1 and "Lint:       FAIL" in r.stdout,
      r.stdout)

commit("CLAUDE.md", claude_md(tests=False), "docs: no tests")
r = gate("--base", "main")
check("no test command: NOT READY", r.returncode == 1 and "Testes:     FAIL" in r.stdout, r.stdout)
commit("CLAUDE.md", claude_md(), "docs: tests back")

commit("cfg.txt", SECRET, "oops")
sh("git", "rm", "-q", "cfg.txt")
sh("git", "commit", "-q", "--no-verify", "-m", "remove it")
r = gate("--base", "main")
check("a secret added and removed in the branch history: NOT READY",
      r.returncode == 1 and "Secrets:    FAIL" in r.stdout and "cfg.txt" in r.stdout, r.stdout)
sh("git", "reset", "-q", "--hard", "HEAD~2")

commit(".env", "X=1\n", "env")
r = gate("--base", "main")
check("an .env file in the branch: NOT READY", r.returncode == 1 and ".env" in r.stdout, r.stdout)
sh("git", "reset", "-q", "--hard", "HEAD~1")

def ledger(*args):
    subprocess.run([sys.executable, LEDGER, "add", *args], cwd=repo, check=True, capture_output=True)


commit("b.txt", "minor fixed\n", "fix: minor")
ledger("--agent", "dev", "--task", "fix-1", "--verdict", "DONE")
r = gate("--base", "main")
check("a fix round after the closed cycle needs its review: NOT READY",
      r.returncode == 1 and "reviewer has not reviewed" in r.stdout, r.stdout)
ledger("--agent", "reviewer", "--verdict", "PASS")
r = gate("--base", "main")
check("the fix reviewed and qa passed before it: READY without another qa", r.returncode == 0, r.stdout)

r = gate("--base", "main", "--report", "feature-x")
report = [name for name in os.listdir(os.path.join(repo, "docs", "quality-reports"))] if r.returncode == 0 else []
check("--report writes and stages the quality report on READY",
      r.returncode == 0 and report and "docs/quality-reports/" in sh("git", "diff", "--cached", "--name-only"),
      r.stdout)

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
