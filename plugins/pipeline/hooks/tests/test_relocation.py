import importlib.util, json, os, subprocess, sys, tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pre-commit-secret-scan.py")
base = tempfile.mkdtemp(prefix="hookreloc_")
repo = os.path.join(base, "repo")
elsewhere = os.path.join(base, "elsewhere")
remote = os.path.join(base, "remote.git")
os.makedirs(repo)
os.makedirs(elsewhere)
ALLOW = ".pipeline-secrets-allow"
FP = "ab" * 32
FP2 = "cd" * 32
results = []


def sh(cwd, *a, check=True):
    return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=check)


def hook(command, cwd=repo, tool="Bash"):
    payload = json.dumps({"tool_name": tool, "tool_input": {"command": command}, "cwd": cwd})
    r = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True, encoding="utf-8")
    if not r.stdout.strip():
        return "ALLOW", ""
    return "DENY", json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"]


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("PASS" if ok else "FAIL", name, "" if ok else f"| {detail[-300:]}")


def expect(name, command, expected, cwd=repo, tool="Bash", reason_has=None):
    got, reason = hook(command, cwd, tool)
    ok = got == expected and (reason_has is None or reason_has in reason)
    check(f"[{tool}] {name} -> {got}", ok, reason)


def write(name, text):
    with open(os.path.join(repo, name), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


sh(base, "git", "init", "-q", "--bare", remote)
sh(repo, "git", "init", "-q", "-b", "main")
for k, v in (("user.email", "t@t.com"), ("user.name", "t"), ("core.autocrlf", "false")):
    sh(repo, "git", "config", k, v)
sh(repo, "git", "remote", "add", "origin", remote)
write("a.txt", "base\n")
write(ALLOW, "# user entries\n")
sh(repo, "git", "add", "-A")
sh(repo, "git", "commit", "-q", "-m", "base")
sh(repo, "git", "push", "-q", "origin", "main")

gd, wt = repo.replace("\\", "/") + "/.git", repo.replace("\\", "/")

write("a.txt", "changed\n")
expect("clean allowlist: -c alias to add -A allowed", "git -c alias.x='add -A' x", "ALLOW")
expect("clean allowlist: git log through --git-dir allowed", f'git --git-dir="{gd}" log --oneline', "ALLOW",
       cwd=elsewhere)

write(ALLOW, f"# user entries\n{FP}  # pending\n")
relocated = [
    ("--git-dir/--work-tree from outside", f'cd "{elsewhere}" && git --git-dir="{gd}" --work-tree="{wt}" add -A'),
    ("--git-dir=/--work-tree= attached", f"git --git-dir={gd} --work-tree={wt} add -A"),
    ("GIT_DIR/GIT_WORK_TREE prefix", f'GIT_DIR="{gd}" GIT_WORK_TREE="{wt}" git add -A'),
    ("env wrapper with GIT_DIR", f'env GIT_DIR="{gd}" GIT_WORK_TREE="{wt}" git add -A'),
    ("-C elsewhere plus --git-dir", f'git -C "{elsewhere}" --git-dir="{gd}" add -A'),
    ("export GIT_DIR first", f'export GIT_DIR="{gd}"; git add -A'),
    ("GIT_DIR assigned alone first", f'GIT_DIR="{gd}"; export GIT_DIR; git add -A'),
    ("bash -c with GIT_DIR", f"bash -c 'GIT_DIR={gd} git add -A'"),
    ("GIT_INDEX_FILE on commit", "GIT_INDEX_FILE=/tmp/i git commit -m x"),
    ("GIT_COMMON_DIR on add", f'GIT_COMMON_DIR="{gd}" git add -A'),
    ("--namespace on push", "git --namespace=x push origin main"),
    ("--git-dir on an alias", f'git --git-dir="{gd}" x'),
]
for name, command in relocated:
    expect(name, command, "DENY", cwd=elsewhere, reason_has="--git-dir/--work-tree")
expect("$env:GIT_DIR then git add", f"$env:GIT_DIR = '{gd}'; git add -A", "DENY", cwd=elsewhere,
       tool="PowerShell", reason_has="--git-dir/--work-tree")
expect("Set-Item env:GIT_WORK_TREE then git add", f"Set-Item env:GIT_WORK_TREE '{wt}'; git add -A", "DENY",
       cwd=elsewhere, tool="PowerShell", reason_has="--git-dir/--work-tree")
expect("git status through --git-dir still allowed", f'git --git-dir="{gd}" status', "ALLOW", cwd=elsewhere)
expect("GIT_DIR only mentioned in a commit message is fine", 'git commit -m "document GIT_DIR=x"', "ALLOW")

aliased = [
    ("-c alias to add -A", "git -c alias.x='add -A' x"),
    ("-c alias to a shell git add", "git -c alias.x='!git add -A' x"),
    ("-c alias, attached form", "git -calias.x='add -A' x"),
    ("--config-env alias from a prefixed variable", "AV='add -A' git --config-env=alias.x=AV x"),
    ("--config-env alias from an unknown variable", "git --config-env=alias.x=UNSET_ALIAS_VAR_42 x"),
    ("GIT_CONFIG_* alias", "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.x GIT_CONFIG_VALUE_0='add -A' git x"),
    ("uppercase alias name", "git -c alias.X='add -A' X"),
]
for name, command in aliased:
    expect(name, command, "DENY")
sh(repo, "git", "config", "alias.aa", "add -A")
expect("alias from git config (add -A)", "git aa", "DENY")
expect("alias from git config, pathspec that misses the allowlist", "git aa -- a.txt", "ALLOW")
for index in range(12):
    sh(repo, "git", "config", f"alias.n{index}", f"n{index + 1}" if index < 11 else "add -A")
expect("12 nested aliases ending in add -A", "git n0", "DENY")
sh(repo, "git", "config", "alias.loop", "loop")
expect("self-referencing alias still allowed", "git loop", "ALLOW")

spec = importlib.util.spec_from_file_location("scan", HOOK)
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)
real_git = scanner.git
scanner.git = lambda args, cwd, env=None: (1, "")
check("pathspec fallback fails closed when git cannot answer",
      scanner.pathspecs_reach_allowlist(repo, [":/"], tracked_only=False) is True)
check("add with an unknown pathspec fails closed when git cannot answer",
      scanner.add_reaches_allowlist([("$X", False)], repo) is True)
check("commit -A fails closed when git cannot answer", scanner.commit_reaches_allowlist([["-A"]], repo) is True)
scanner.git = real_git

sh(repo, "git", "add", ALLOW)
sh(repo, "git", "commit", "-q", "-m", "user entry")
write("cfg.txt", "placeholder\n")
sh(repo, "git", "add", "cfg.txt")
sh(repo, "git", "commit", "-q", "-m", "tracked")
write("cfg.txt", "AWS_" + "KEY=AK" + "IAQRSTUVWXYZABCDEF\n")
expect("commit scan: --work-tree/--git-dir commit -am from outside",
       f"git --work-tree={wt} --git-dir={gd} commit -am x", "DENY", cwd=elsewhere, reason_has="--git-dir/--work-tree")
expect("commit scan: plain commit -am from inside is still scanned", "git commit -am x", "DENY",
       reason_has="Secret scan blocked")
sh(repo, "git", "checkout", "--", "cfg.txt")

head = sh(repo, "git", "rev-parse", "HEAD").stdout.strip()
write(ALLOW, f"# user entries\n{FP}  # pending\n{FP2}  # evil \x1b[2K\x1b[1Ahidden\x9b\x07 end\n")
sh(repo, "git", "commit", "-q", "-am", "entries")
head = sh(repo, "git", "rev-parse", "HEAD").stdout.strip()
sh(repo, "git", "update-ref", "refs/remotes/origin/zz", head)


def pre_push(*argv):
    return subprocess.run([sys.executable, HOOK, "--pre-push", *argv], cwd=repo, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          input=f"refs/heads/new {head} refs/heads/new {'0' * 40}\n")


r = pre_push("origin", remote)
check("new branch: a forged remote-tracking ref does not hide new entries (compared with origin/main)",
      r.returncode == 0 and FP2 in r.stderr and FP in r.stderr and "refs/remotes/origin/main" in r.stderr, r.stderr)
sh(repo, "git", "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/zz")
r = pre_push("origin", remote)
check("new branch: origin/HEAD is preferred when present", r.returncode == 0 and "Warning" not in r.stderr, r.stderr)
sh(repo, "git", "symbolic-ref", "--delete", "refs/remotes/origin/HEAD")
r = pre_push()
check("new branch without a remote name: lists every entry and says why",
      r.returncode == 0 and "no default branch known" in r.stderr and FP in r.stderr and FP2 in r.stderr, r.stderr)
r = pre_push("https://example.invalid/x.git", "https://example.invalid/x.git")
check("new branch pushed to a URL: lists every entry", r.returncode == 0 and "no default branch known" in r.stderr,
      r.stderr)
r = pre_push("origin", remote)
check("warning escapes control characters in allowlist comments",
      "\x1b" not in r.stderr and "\x9b" not in r.stderr and "\x07" not in r.stderr
      and "\\x1b[2K\\x1b[1Ahidden\\x9b\\x07 end" in r.stderr, repr(r.stderr))
check("printable() leaves normal text alone", scanner.printable("ok # reason: ção") == "ok # reason: ção")
check("printable() escapes C0, DEL, C1 and bidi controls",
      scanner.printable("a\tb\x7fc\x85d‮e") == "a\\x09b\\x7fc\\x85d\\u202ee")

linked = os.path.join(base, "linked-wt")
sh(repo, "git", "worktree", "add", "-q", "-b", "wt-clean", linked)
for name in ("wt.txt", "a.txt"):
    with open(os.path.join(linked, name), "w", encoding="utf-8", newline="\n") as handle:
        handle.write("clean change\n")
expect("clean add + commit inside a linked worktree", "git add wt.txt && git commit -m wt", "ALLOW", cwd=linked)
expect("clean commit -a inside a linked worktree, entered with cd", f'cd "{linked}" && git commit -am wt', "ALLOW",
       cwd=elsewhere)
with open(os.path.join(linked, "a.txt"), "w", encoding="utf-8", newline="\n") as handle:
    handle.write("AWS_" + "KEY=AK" + "IAQRSTUVWXYZABCDEF\n")
expect("a secret in the same linked worktree is still found", "git commit -am wt", "DENY", cwd=linked,
       reason_has="Secret scan blocked")

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
