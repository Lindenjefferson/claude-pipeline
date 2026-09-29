import os, shutil, subprocess, sys, tempfile

HOOKS = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PLUGIN = os.path.dirname(HOOKS)
HOOK = os.path.join(HOOKS, "pre-commit-secret-scan.py")
BASH = shutil.which("bash")
base = tempfile.mkdtemp(prefix="pylookup_")
repo = os.path.join(base, "repo")
os.makedirs(repo)
results = []
PYTHON_NAMES = {"python", "python3", "python.exe", "python3.exe"}


def check(name, ok, detail=""):
    results.append(ok)
    print("PASS" if ok else "FAIL", name, "" if ok else f"| {detail[-300:]}")


def bin_dir(name, target):
    path = os.path.join(base, name)
    os.makedirs(path)
    return path, target


def fake(directory, name, script):
    path = os.path.join(directory, name)
    with open(path, "w", newline="\n") as handle:
        handle.write(script)
    os.chmod(path, 0o755)


def env_with(*dirs):
    kept = [d for d in os.environ.get("PATH", "").split(os.pathsep)
            if d and not (os.path.isdir(d) and PYTHON_NAMES & {n.lower() for n in os.listdir(d)})]
    env = dict(os.environ, PATH=os.pathsep.join(list(dirs) + kept), CLAUDE_PLUGIN_ROOT=PLUGIN,
               CLAUDE_PIPELINE_HOME=PLUGIN)
    return env


exe = sys.executable.replace("\\", "/")
only_python3 = os.path.join(base, "only-python3"); os.makedirs(only_python3)
fake(only_python3, "python3", f'#!/bin/sh\nexec "{exe}" "$@"\n')
python2_first = os.path.join(base, "python2-first"); os.makedirs(python2_first)
fake(python2_first, "python", "#!/bin/sh\necho 'Python 2.7.18' >&2\nexit 1\n")
fake(python2_first, "python3", f'#!/bin/sh\nexec "{exe}" "$@"\n')
no_python = os.path.join(base, "no-python"); os.makedirs(no_python)

for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@t.com"),
             ("config", "user.name", "t"), ("config", "core.autocrlf", "false")):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
with open(os.path.join(repo, "s.txt"), "w", newline="\n") as handle:
    handle.write("k = AKIA" + "ABCDEFGHIJKLMNOP\n")
subprocess.run(["git", "add", "s.txt"], cwd=repo, check=True)

subprocess.run([sys.executable, HOOK, "--install-pre-commit"], cwd=repo, check=True, capture_output=True)


def commit(path_dir):
    return subprocess.run(["git", "commit", "-q", "-m", "secret"], cwd=repo, capture_output=True, text=True,
                          env=env_with(path_dir))


r = commit(only_python3)
check("pre-commit runs with only python3 on PATH", "Secret scan blocked" in r.stderr, r.stderr)
r = commit(python2_first)
check("pre-commit skips a python that is not Python 3", "Secret scan blocked" in r.stderr, r.stderr)
r = commit(no_python)
check("pre-commit without Python blocks and says so", r.returncode != 0 and "Python 3" in r.stderr, r.stderr)

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
