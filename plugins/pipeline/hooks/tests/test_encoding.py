import os, subprocess, sys, tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pre-commit-secret-scan.py")
os.environ["CLAUDE_PIPELINE_HOME"] = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
repo = tempfile.mkdtemp(prefix="hookenc_")
results = []


def sh(*a, check=True):
    return subprocess.run(list(a), cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          check=check)


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("PASS" if ok else "FAIL", name, "" if ok else f"| {detail[-400:]}")


def put(name, data):
    path = os.path.join(repo, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)


def commit(message):
    return sh("git", "commit", "-q", "-m", message, check=False)


sh("git", "init", "-q", "-b", "main")
for k, v in (("user.email", "t@t.com"), ("user.name", "t"), ("core.autocrlf", "false")):
    sh("git", "config", k, v)
sh(sys.executable, HOOK, "--install-pre-commit")

put("ok.txt", "ação válida\n".encode("utf-8"))
sh("git", "add", "-A")
r = commit("utf-8 text")
check("UTF-8 text with accents passes", r.returncode == 0, r.stderr)

put("bom.txt", b"\xef\xbb\xbfcom BOM\n")
sh("git", "add", "-A")
r = commit("bom")
check("UTF-8 with a BOM passes", r.returncode == 0, r.stderr)

put("pic.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\xe7\xff\xfe\x80\x81\x00\x00")
put("wide.txt", "texto em utf-16\n".encode("utf-16"))
sh("git", "add", "-A")
r = commit("binaries")
check("binary files (image, UTF-16 with NULs) do not trip the check", r.returncode == 0, r.stderr)

put("src/latin.txt", b"linha um\nlinha dois\nconfigura\xe7\xe3o\n")
sh("git", "add", "-A")
r = commit("latin-1")
check("a Latin-1 line is refused", r.returncode != 0, r.stderr)
check("the message names file and line", "src/latin.txt:3" in r.stderr, r.stderr)
check("the message says how to fix", "UTF-8" in r.stderr and "iconv" in r.stderr, r.stderr)

put("src/latin.txt", "linha um\nlinha dois\nconfiguração\n".encode("utf-8"))
sh("git", "add", "-A")
r = commit("fixed")
check("after re-saving as UTF-8 the commit passes", r.returncode == 0, r.stderr)

put("src/latin.txt", "linha um\nlinha dois\nconfiguração\n".encode("utf-8") + b"nova linha caf\xe9\n")
sh("git", "add", "-A")
r = commit("edit")
check("only added lines count and the line number follows the hunk", r.returncode != 0 and "src/latin.txt:4" in r.stderr,
      r.stderr)
sh("git", "reset", "-q", "--hard")

put("old.txt", b"antigo caf\xe9\n")
sh("git", "add", "-f", "old.txt")
sh("git", "-c", "core.hooksPath=/nonexistent", "commit", "-q", "-m", "legacy file already committed")
put("old.txt", b"antigo caf\xe9\nlinha nova ok\n")
sh("git", "add", "-A")
r = commit("append a UTF-8 line to a legacy file")
check("a legacy line already committed is not re-flagged", r.returncode == 0, r.stderr)

put("lines.txt", b"++ not a header\nok\n")
sh("git", "add", "-A")
r = commit("line that looks like a diff header")
check("an added line starting with '++ ' is content, not a header", r.returncode == 0, r.stderr)

put("sp ace/ç.txt", b"ol\xe1\n")
sh("git", "add", "-A")
r = commit("odd path")
check("a path with spaces and accents is still reported", r.returncode != 0 and "UTF-8" in r.stderr and ".txt:1" in r.stderr,
      r.stderr)

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
