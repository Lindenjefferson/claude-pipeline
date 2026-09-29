#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from collections import namedtuple

Token = namedtuple("Token", "kind text start end")
Mutant = namedtuple("Mutant", "operator start end replacement description")

PUNCTUATORS = sorted("""
>>>= ... === !== **= <<= >>= >>> &&= ||= ??= => == != <= >= && || ?? ?. ++ -- += -= *= /= %= &= |= ^= ** << >>
{ } ( ) [ ] ; , < > + - * / % & | ^ ! ~ ? : = . @ #
""".split(), key=len, reverse=True)
REGEX_PREV_WORDS = {"return", "typeof", "case", "do", "else", "in", "of", "new", "delete", "void", "throw",
                    "instanceof", "yield", "await"}
IDENT_RE = re.compile(r"[A-Za-z_$\u0080-\uffff][A-Za-z0-9_$\u0080-\uffff]*")
NUM_RE = re.compile(r"0[xX][0-9a-fA-F_]+n?|0[bB][01_]+n?|0[oO][0-7_]+n?|(?:\d[\d_]*(?:\.[\d_]*)?|\.\d[\d_]*)(?:[eE][+-]?\d+)?n?")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
FAIL_HINT_RE = re.compile(r"\bFAIL\b|✗|×|\bnot ok\b|AssertionError|\bfailed\b", re.I)

OPERATORS = ("comparison", "boundary", "and-or-swap", "negate-condition", "return-flip")
COMPARISON_SWAP = {"<": "<=", "<=": "<", ">": ">=", ">=": ">", "===": "!==", "!==": "===", "==": "!=", "!=": "=="}
RELATIONAL = {"<", "<=", ">", ">="}

HELP_EPILOG = """\
How it runs:
  1. Refuses to start if FILE has uncommitted changes or is untracked (override: --allow-dirty).
  2. Keeps the original bytes in memory and a backup copy in the temp directory.
  3. Runs --test-cmd once on the original; it must pass.
  4. For each mutant: writes the mutated file, runs --test-cmd, and in a `finally` writes the
     original bytes back and checks their sha256. If the restored file does not match, it
     stops immediately (exit 3) and prints the backup path.
  A mutant is killed when --test-cmd exits non-zero or times out, survived when it exits 0.

Comparison swaps on `<` and `>` only apply with whitespace on both sides (`a < b`), so TS
generics such as `Array<number>` are left alone.

Exit codes: 0 done (survivors are not a failure), 1 survivors with --fail-on-survivors,
2 tool error, 3 the original file could not be restored.
"""


class ToolError(Exception):
    pass


class RestoreError(Exception):
    pass


def regex_allowed(prev):
    if prev is None:
        return True
    if prev.kind == "ident":
        return prev.text in REGEX_PREV_WORDS
    if prev.kind in ("num", "str", "template", "regex"):
        return False
    return prev.text not in (")", "]", "}")


def skip_string(text, i, quote):
    n = len(text)
    i += 1
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == quote or (c == "\n" and quote != "`"):
            return i + 1
        i += 1
    return n


def skip_template(text, i):
    n = len(text)
    i += 1
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "`":
            return i + 1
        if c == "$" and i + 1 < n and text[i + 1] == "{":
            i = skip_braces(text, i + 1)
            continue
        i += 1
    return n


def skip_braces(text, i):
    n = len(text)
    depth = 0
    while i < n:
        c = text[i]
        if c in "'\"":
            i = skip_string(text, i, c)
            continue
        if c == "`":
            i = skip_template(text, i)
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def skip_regex(text, i):
    n = len(text)
    i += 1
    in_class = False
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "\n":
            return i
        if in_class:
            if c == "]":
                in_class = False
        elif c == "[":
            in_class = True
        elif c == "/":
            i += 1
            while i < n and (text[i].isalnum() or text[i] == "_"):
                i += 1
            return i
        i += 1
    return n


def lex(text):
    tokens = []
    i, n = 0, len(text)
    prev = None
    while i < n:
        c = text[i]
        start = i
        if c.isspace():
            while i < n and text[i].isspace():
                i += 1
            tokens.append(Token("ws", text[start:i], start, i))
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            tokens.append(Token("comment", text[start:i], start, i))
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            tokens.append(Token("comment", text[start:i], start, i))
            continue
        if c in "'\"":
            i = skip_string(text, i, c)
            kind = "str"
        elif c == "`":
            i = skip_template(text, i)
            kind = "template"
        elif c == "/" and regex_allowed(prev):
            i = skip_regex(text, i)
            kind = "regex"
        elif c.isdigit() or (c == "." and i + 1 < n and text[i + 1].isdigit()):
            i = NUM_RE.match(text, i).end()
            kind = "num"
        elif IDENT_RE.match(text, i):
            i = IDENT_RE.match(text, i).end()
            kind = "ident"
        else:
            p = next((p for p in PUNCTUATORS if text.startswith(p, i)), c)
            i += len(p)
            kind = "punct"
        tok = Token(kind, text[start:i], start, i)
        tokens.append(tok)
        prev = tok
    return tokens


def significant(tokens):
    return [t for t in tokens if t.kind not in ("ws", "comment")]


def spaced(text, tok):
    return (tok.start > 0 and text[tok.start - 1].isspace()) and (tok.end < len(text) and text[tok.end].isspace())


def gen_comparison(sig, text):
    out = []
    for t in sig:
        if t.kind != "punct" or t.text not in COMPARISON_SWAP:
            continue
        if t.text in ("<", ">") and not spaced(text, t):
            continue
        out.append(Mutant("comparison", t.start, t.end, COMPARISON_SWAP[t.text], f"{t.text} -> {COMPARISON_SWAP[t.text]}"))
    return out


def is_relational(text, tok):
    return tok is not None and tok.kind == "punct" and tok.text in RELATIONAL and (
        tok.text in ("<=", ">=") or spaced(text, tok))


def gen_boundary(sig, text):
    out = []
    for i, t in enumerate(sig):
        if t.kind != "num" or not re.fullmatch(r"\d+(?:\.\d+)?", t.text):
            continue
        prev_t = sig[i - 1] if i else None
        next_t = sig[i + 1] if i + 1 < len(sig) else None
        if not (is_relational(text, prev_t) or is_relational(text, next_t)):
            continue
        value = float(t.text) if "." in t.text else int(t.text)
        for new in (value + 1, value - 1):
            shown = repr(round(new, 10)) if isinstance(new, float) else str(new)
            if new < 0 and prev_t is not None and prev_t.text == "-":
                continue
            out.append(Mutant("boundary", t.start, t.end, shown if new >= 0 else f"({shown})", f"{t.text} -> {shown}"))
    return out


def gen_and_or(sig, text):
    swap = {"&&": "||", "||": "&&"}
    return [Mutant("and-or-swap", t.start, t.end, swap[t.text], f"{t.text} -> {swap[t.text]}")
            for t in sig if t.kind == "punct" and t.text in swap]


def matching(sig, idx, open_text, close_text):
    depth = 0
    for j in range(idx, len(sig)):
        if sig[j].text == open_text:
            depth += 1
        elif sig[j].text == close_text:
            depth -= 1
            if depth == 0:
                return j
    return None


def gen_negate_if(sig, text):
    out = []
    for i, t in enumerate(sig):
        if t.kind == "ident" and t.text == "if" and i + 1 < len(sig) and sig[i + 1].text == "(":
            close = matching(sig, i + 1, "(", ")")
            if close is None or close == i + 2:
                continue
            cond = text[sig[i + 2].start:sig[close - 1].end]
            short = " ".join(cond.split())
            out.append(Mutant("negate-condition", sig[i + 2].start, sig[close - 1].end, f"!({cond})",
                              f"if ({short[:50]}) -> if (!(...))"))
    return out


def return_expression_end(sig, text, idx):
    depth = 0
    for j in range(idx, len(sig)):
        t = sig[j]
        if t.text in ("(", "[", "{"):
            depth += 1
        elif t.text in (")", "]", "}"):
            if depth == 0:
                return j - 1
            depth -= 1
        elif t.text == ";" and depth == 0:
            return j - 1
        if depth == 0 and j + 1 < len(sig):
            gap = text[t.end:sig[j + 1].start]
            continues = t.kind == "punct" and t.text not in (")", "]", "}", "++", "--")
            next_continues = sig[j + 1].kind == "punct" and sig[j + 1].text in (
                "&&", "||", "??", "?", ":", ".", "?.", "===", "!==", "==", "!=", "<", ">", "<=", ">=", "+", "-", "*", "/")
            if "\n" in gap and not continues and not next_continues:
                return j
    return len(sig) - 1


def gen_return_flip(sig, text):
    out = []
    flip = {"true": "false", "false": "true"}
    for i, t in enumerate(sig):
        if t.kind != "ident" or t.text != "return" or i + 1 >= len(sig):
            continue
        nxt = sig[i + 1]
        if "\n" in text[t.end:nxt.start]:
            continue
        if nxt.kind == "ident" and nxt.text in flip:
            after = sig[i + 2] if i + 2 < len(sig) else None
            if after is None or after.text in (";", "}") or "\n" in text[nxt.end:after.start]:
                out.append(Mutant("return-flip", nxt.start, nxt.end, flip[nxt.text], f"return {nxt.text} -> {flip[nxt.text]}"))
            continue
        end = return_expression_end(sig, text, i + 1)
        if end < i + 1:
            continue
        expr_tokens = sig[i + 1:end + 1]
        boolean = any(x.kind == "punct" and x.text in ("===", "!==", "==", "!=", "<=", ">=", "&&", "||") for x in expr_tokens) \
            or any(x.kind == "punct" and x.text in ("<", ">") and spaced(text, x) for x in expr_tokens) \
            or (expr_tokens and expr_tokens[0].text == "!")
        if not boolean or any(x.kind == "punct" and x.text in ("=>", "?") for x in expr_tokens):
            continue
        expr = text[expr_tokens[0].start:expr_tokens[-1].end]
        out.append(Mutant("return-flip", expr_tokens[0].start, expr_tokens[-1].end, f"!({expr})",
                          f"return {' '.join(expr.split())[:50]} -> return !(...)"))
    for i, t in enumerate(sig):
        if t.kind == "punct" and t.text == "=>" and i + 1 < len(sig) and sig[i + 1].kind == "ident" and sig[i + 1].text in flip:
            nxt = sig[i + 1]
            out.append(Mutant("return-flip", nxt.start, nxt.end, flip[nxt.text], f"=> {nxt.text} -> {flip[nxt.text]}"))
    return out


def generate_mutants(text, operators=OPERATORS):
    sig = significant(lex(text))
    found = gen_comparison(sig, text) + gen_boundary(sig, text) + gen_and_or(sig, text) \
        + gen_negate_if(sig, text) + gen_return_flip(sig, text)
    seen, result = set(), []
    for m in sorted(found, key=lambda m: (m.start, m.operator, m.end)):
        key = (m.start, m.end, m.replacement)
        if m.operator in operators and key not in seen:
            seen.add(key)
            result.append(m)
    return result


def apply_mutant(text, mutant):
    return text[:mutant.start] + mutant.replacement + text[mutant.end:]


def line_of(text, offset):
    return text.count("\n", 0, offset) + 1


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def git_state(path):
    folder = os.path.dirname(os.path.abspath(path)) or "."
    name = os.path.basename(path)
    inside = subprocess.run(["git", "-C", folder, "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return "not-in-git"
    tracked = subprocess.run(["git", "-C", folder, "ls-files", "--error-unmatch", "--", name], capture_output=True)
    if tracked.returncode != 0:
        return "untracked"
    status = subprocess.run(["git", "-C", folder, "status", "--porcelain", "--", name], capture_output=True, text=True)
    return "dirty" if status.stdout.strip() else "clean"


def restore(path, original, expected_hash, write=None):
    write = write or write_bytes
    for _ in range(2):
        try:
            write(path, original)
            with open(path, "rb") as fh:
                if sha256(fh.read()) == expected_hash:
                    return
        except OSError:
            pass
    raise RestoreError(f"{path} does not match the original after restore")


def write_bytes(path, data):
    with open(path, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())


def kill_tree(proc):
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()


def run_command(cmd, cwd, timeout):
    kwargs = {"start_new_session": True} if os.name != "nt" else {}
    proc = subprocess.Popen(cmd, shell=True, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        proc.communicate()
        return None, ""
    return proc.returncode, out.decode("utf-8", "replace")


def killing_hint(output):
    for line in ANSI_RE.sub("", output).splitlines():
        if FAIL_HINT_RE.search(line) and not re.search(r"\b0 failed\b", line):
            return " ".join(line.split())[:120]
    return None


def collect_rows(text, mutants, rel):
    return [{"id": f"T{i + 1:03d}", "file": rel, "operator": m.operator, "line": line_of(text, m.start),
             "change": m.description, "status": "pending", "killed_by": None, "_mutant": m}
            for i, m in enumerate(mutants)]


def run_all(path, rows, test_cmd, cwd, timeout, runner=None, writer=None, progress=None):
    runner = runner or run_command
    with open(path, "rb") as fh:
        original = fh.read()
    original_hash = sha256(original)
    text = original.decode("utf-8")
    backup_dir = tempfile.mkdtemp(prefix="tsmutate-")
    backup = os.path.join(backup_dir, os.path.basename(path) + ".orig")
    shutil.copyfile(path, backup)
    ok = False
    try:
        code, out = runner(test_cmd, cwd, timeout)
        if code != 0:
            raise ToolError(f"baseline failed: `{test_cmd}` did not pass on the original file"
                            + (" (timeout)" if code is None else f" (exit {code}): {killing_hint(out) or out.strip()[-300:]}"))
        for row in rows:
            try:
                write_bytes(path, apply_mutant(text, row["_mutant"]).encode("utf-8"))
                code, out = runner(test_cmd, cwd, timeout)
            finally:
                restore(path, original, original_hash, writer)
            if code is None:
                row["status"], row["killed_by"] = "timeout", "timeout"
            elif code != 0:
                row["status"], row["killed_by"] = "killed", killing_hint(out) or f"exit {code}"
            else:
                row["status"] = "survived"
            if progress:
                progress(row)
        ok = True
    finally:
        restore(path, original, original_hash, writer)
        if ok:
            shutil.rmtree(backup_dir, ignore_errors=True)
    return rows


def summarize(rows):
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in ("killed", "survived", "timeout", "pending")}
    scored = counts["killed"] + counts["survived"] + counts["timeout"]
    counts["score"] = round(100.0 * (counts["killed"] + counts["timeout"]) / scored, 1) if scored else None
    return counts


def format_table(rows, columns):
    headers = [c[0] for c in columns]
    data = [[str(c[1](r)) if c[1](r) is not None else "" for c in columns] for r in rows]
    widths = [min(70, max([len(h)] + [len(d[i]) for d in data])) for i, h in enumerate(headers)]
    lines = [" | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)), "-+-".join("-" * w for w in widths)]
    for d in data:
        lines.append(" | ".join(v[:widths[i]].ljust(widths[i]) for i, v in enumerate(d)))
    return "\n".join(lines)


def table_columns(listing):
    cols = [("id", lambda r: r["id"]), ("operator", lambda r: r["operator"]),
            ("line", lambda r: f'{r["file"]}:{r["line"]}'), ("change", lambda r: r["change"])]
    if not listing:
        cols += [("status", lambda r: r["status"]), ("killing test", lambda r: r["killed_by"])]
    return cols


def public_rows(rows):
    return [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]


def build_parser():
    p = argparse.ArgumentParser(
        prog="tsmutate.py",
        description="Textual mutation testing for one TS/JS file (e.g. a lib/calculations module): "
                    "writes each mutant, runs the test command, always restores the original.",
        epilog=HELP_EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("file", help="TS/JS file to mutate")
    p.add_argument("--test-cmd", help="command that runs the relevant tests, e.g. 'npx vitest run lib/calculations'")
    p.add_argument("--cwd", help="working directory for --test-cmd (default: the git root of FILE, else its folder)")
    p.add_argument("--operators", help="comma-separated subset of: " + ", ".join(OPERATORS))
    p.add_argument("--timeout", type=int, default=300, help="seconds per test run (default 300)")
    p.add_argument("--max-mutants", type=int, help="cap on the number of mutants run")
    p.add_argument("--allow-dirty", action="store_true", help="run even if FILE has uncommitted changes")
    p.add_argument("--list", action="store_true", help="only list the mutants, do not write the file")
    p.add_argument("--json", action="store_true", help="print JSON instead of the table")
    p.add_argument("--fail-on-survivors", action="store_true", help="exit 1 when any mutant survives")
    return p


def default_cwd(path):
    folder = os.path.dirname(os.path.abspath(path))
    p = subprocess.run(["git", "-C", folder, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else folder


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    path = os.path.abspath(args.file)
    try:
        if not os.path.isfile(path):
            raise ToolError(f"{args.file} is not a file")
        operators = OPERATORS
        if args.operators:
            operators = tuple(o.strip() for o in args.operators.split(",") if o.strip())
            unknown = [o for o in operators if o not in OPERATORS]
            if unknown:
                raise ToolError(f"unknown operator(s): {', '.join(unknown)}")
        with open(path, "rb") as fh:
            text = fh.read().decode("utf-8")
        cwd = args.cwd or default_cwd(path)
        rel = os.path.relpath(path, cwd).replace("\\", "/")
        rows = collect_rows(text, generate_mutants(text, operators), rel)
        if args.max_mutants is not None:
            rows = rows[:args.max_mutants]
        if args.list:
            if args.json:
                print(json.dumps({"file": rel, "mutants": public_rows(rows)}, indent=2, ensure_ascii=False))
            else:
                print(format_table(rows, table_columns(True)))
                print(f"\n{len(rows)} mutants")
            return 0
        if not args.test_cmd:
            raise ToolError("--test-cmd is required unless --list")
        state = git_state(path)
        if state != "clean" and not args.allow_dirty:
            raise ToolError(f"{args.file} is {state}: commit or stash it first (or pass --allow-dirty); "
                            "a clean file is what guarantees the restore can be checked against git")
        progress = None if args.json else (lambda r: print(f"  {r['id']} {r['status']}", file=sys.stderr, flush=True))
        if not args.json:
            print(f"tsmutate: {len(rows)} mutants in {rel}", file=sys.stderr)
        run_all(path, rows, args.test_cmd, cwd, args.timeout, progress=progress)
        summary = summarize(rows)
        if args.json:
            print(json.dumps({"file": rel, "test_cmd": args.test_cmd, "summary": summary, "mutants": public_rows(rows)},
                             indent=2, ensure_ascii=False))
        else:
            print(format_table(rows, table_columns(False)))
            print(f"\nkilled {summary['killed']}, survived {summary['survived']}, timeout {summary['timeout']}; "
                  f"score {summary['score']}%")
        return 1 if args.fail_on_survivors and summary["survived"] else 0
    except RestoreError as e:
        print(f"tsmutate: RESTORE FAILURE: {e}. The original is kept in the tsmutate-* folder under "
              f"{tempfile.gettempdir()}; restore it (or `git checkout -- {args.file}`) before anything else.",
              file=sys.stderr)
        return 3
    except ToolError as e:
        print(f"tsmutate: error: {e}", file=sys.stderr)
        return 2


def interrupt(signum, frame):
    raise KeyboardInterrupt()


if __name__ == "__main__":
    if os.name != "nt":
        signal.signal(signal.SIGTERM, interrupt)
    sys.exit(main())
