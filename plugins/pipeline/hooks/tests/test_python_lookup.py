import json, os, shutil, subprocess, sys, tempfile, time

HOOKS = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PLUGIN = os.path.dirname(HOOKS)
HOOK = os.path.join(HOOKS, "pre-commit-secret-scan.py")
BASH = shutil.which("bash")
base = os.path.join(tempfile.gettempdir(), f"pylookup_{int(time.time() * 1000)}")
repo = os.path.join(base, "repo")
remote = os.path.join(base, "remote.git")
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
subprocess.run(["git", "init", "-q", "--bare", remote], check=True, capture_output=True)
subprocess.run(["git", "remote", "add", "origin", remote], cwd=repo, check=True)
with open(os.path.join(repo, "s.txt"), "w", newline="\n") as handle:
    handle.write("k = AKIA" + "ABCDEFGHIJKLMNOP\n")
subprocess.run(["git", "add", "s.txt"], cwd=repo, check=True)

command = json.load(open(os.path.join(HOOKS, "hooks.json")))["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}, "cwd": repo})


def claude_hook(path_dir):
    return subprocess.run([BASH, "-c", command], input=payload, capture_output=True, text=True,
                          env=env_with(path_dir))


r = claude_hook(only_python3)
check("Claude hook runs with only python3 on PATH", '"deny"' in r.stdout, r.stdout + r.stderr)
r = claude_hook(python2_first)
check("Claude hook skips a python that is not Python 3", '"deny"' in r.stdout, r.stdout + r.stderr)
r = claude_hook(no_python)
check("Claude hook without Python says so on stderr", "Python 3" in r.stderr and r.returncode != 2,
      r.stdout + r.stderr)

file_entry = next(entry for entry in json.load(open(os.path.join(HOOKS, "hooks.json")))["hooks"]["PreToolUse"]
                  if "Write" in entry["matcher"].split("|"))
check("hooks.json guards Write, Edit, MultiEdit and NotebookEdit",
      set(file_entry["matcher"].split("|")) >= {"Write", "Edit", "MultiEdit", "NotebookEdit"}, file_entry["matcher"])
r = subprocess.run([BASH, "-c", file_entry["hooks"][0]["command"]], capture_output=True, text=True,
                   env=env_with(only_python3),
                   input=json.dumps({"tool_name": "Write", "cwd": repo, "tool_input": {
                       "file_path": os.path.join(repo, ".pipeline-secrets-allow"), "content": "x"}}))
check("file-edit hook denies writing the secrets allowlist", '"deny"' in r.stdout, r.stdout + r.stderr)

subprocess.run(["git", "commit", "-q", "-m", "secret"], cwd=repo, check=True)
subprocess.run([sys.executable, HOOK, "--install-pre-push"], cwd=repo, check=True, capture_output=True)
r = subprocess.run(["git", "push", "origin", "main"], cwd=repo, capture_output=True, text=True,
                   env=env_with(only_python3))
check("pre-push runs with only python3 on PATH", "Secret scan blocked" in r.stderr, r.stderr)
r = subprocess.run(["git", "push", "origin", "main"], cwd=repo, capture_output=True, text=True,
                   env=env_with(no_python))
check("pre-push without Python blocks and says so", r.returncode != 0 and "Python 3" in r.stderr, r.stderr)

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
