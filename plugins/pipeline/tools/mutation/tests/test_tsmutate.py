import hashlib
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tsmutate.py")
sys.path.insert(0, os.path.join(HERE, ".."))
import tsmutate as ts  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS" if ok else "FAIL"), name, "" if ok else f"| {str(detail)[:400]}")


SOURCE = """import type { Papel } from "./tipos";
// a < b in a comment
const LIMITE: Array<number> = [1, 2];
const re = /a>=b/g;
const msg = `total ${a > b ? "x" : "y"} > 3`;

export function podeEditar(papel: Papel, nivel: number): boolean {
  if (papel === "admin" && nivel >= 2) {
    return true;
  }
  return nivel > 10 || papel !== "membro";
}

export const ehAdmin = (p: Papel) => p === "admin";
export const sempre = () => false;

export function total(xs: number[]): number {
  if (xs.length < 1) return 0;
  return xs.reduce((a, b) => a + b, 0);
}

export function limite(n: number) {
  return n <= 100
    && n >= 0;
}
"""

mutants = ts.generate_mutants(SOURCE)
by_op = {}
for m in mutants:
    by_op.setdefault(m.operator, []).append((SOURCE[m.start:m.end], m.replacement))

comment_start = SOURCE.index("// a < b")
comment_end = SOURCE.index("\n", comment_start)
template_start = SOURCE.index("`total")
template_end = SOURCE.index("\n", template_start)
regex_start = SOURCE.index("/a>=b/")
generic_at = SOURCE.index("Array<number>") + len("Array")
protected = [(comment_start, comment_end), (template_start, template_end), (regex_start, regex_start + 7),
             (generic_at, generic_at + 9)]
check("no mutants inside comments, template literals, regex literals or generics",
      not any(a <= m.start < b for m in mutants for a, b in protected),
      [(SOURCE[m.start:m.end], m.operator) for m in mutants if any(a <= m.start < b for a, b in protected)])
comparisons = by_op.get("comparison", [])
check("comparison swaps relational and equality operators",
      {("===", "!=="), (">=", ">"), (">", ">="), ("!==", "==="), ("<", "<="), ("<=", "<")} <= set(comparisons), comparisons)
check("arrow => and generics are never comparison mutants",
      all(src != "=>" for src, _ in comparisons) and ("<", "<=") in comparisons
      and sum(1 for src, _ in comparisons if src == "<") == 1, comparisons)
check("boundary bumps numbers next to relational operators",
      {("2", "3"), ("2", "1"), ("10", "11"), ("10", "9"), ("1", "2"), ("1", "0"), ("100", "101"), ("100", "99"), ("0", "1")}
      <= set(by_op.get("boundary", [])), by_op.get("boundary"))
array_at = SOURCE.index("[1, 2]")
reduce_zero = SOURCE.index("a + b, 0") + len("a + b, ")
check("boundary skips numbers outside comparisons",
      not any(m.operator == "boundary" and (array_at <= m.start < array_at + 6 or m.start == reduce_zero) for m in mutants))
check("and-or-swap swaps && and ||",
      set(by_op.get("and-or-swap", [])) == {("&&", "||"), ("||", "&&")} and len(by_op["and-or-swap"]) == 3, by_op.get("and-or-swap"))
negations = by_op.get("negate-condition", [])
check("negate-condition wraps if conditions",
      ('papel === "admin" && nivel >= 2', '!(papel === "admin" && nivel >= 2)') in negations
      and ("xs.length < 1", "!(xs.length < 1)") in negations, negations)
flips = by_op.get("return-flip", [])
check("return-flip flips boolean literals in returns and arrow bodies",
      ("true", "false") in flips and ("false", "true") in flips, flips)
check("return-flip negates boolean return expressions, including multi-line ones",
      ('nivel > 10 || papel !== "membro"', '!(nivel > 10 || papel !== "membro")') in flips
      and any(src.startswith("n <= 100") and src.endswith("n >= 0") for src, _ in flips), flips)
check("return-flip leaves non-boolean returns alone",
      not any("reduce" in src for src, _ in flips) and ("0", "1") not in flips, flips)
only = ts.generate_mutants(SOURCE, ("and-or-swap",))
check("operator filter", {m.operator for m in only} == {"and-or-swap"})
applied = ts.apply_mutant(SOURCE, mutants[0])
check("apply_mutant changes exactly one site", len(applied) == len(SOURCE) - (mutants[0].end - mutants[0].start)
      + len(mutants[0].replacement) and applied != SOURCE)
check("killing_hint strips ANSI and finds the failing line",
      ts.killing_hint("\x1b[31m FAIL \x1b[0m lib/x.test.ts > caso\n") == "FAIL lib/x.test.ts > caso"
      and ts.killing_hint("Tests 3 passed (3)\n") is None)

root = os.path.join(tempfile.gettempdir(), f"tsmutate_test_{int(time.time() * 1000)}")
os.makedirs(root)


def sh(*args):
    return subprocess.run(args, cwd=root, capture_output=True, text=True, check=True).stdout.strip()


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


CALC = "export function pode(n) {\r\n  return n >= 10 && n < 99;\r\n}\r\n// ação\r\n"
calc = os.path.join(root, "calc.js")
open(calc, "wb").write(CALC.encode("utf-8"))
fake_test = os.path.join(root, "fake_test.py")
open(fake_test, "w", encoding="utf-8").write(
    "import sys\n"
    "src = open(sys.argv[1], encoding='utf-8').read()\n"
    "if 'n >= 10' not in src:\n"
    "    print('FAIL calc.test > boundary 10')\n"
    "    sys.exit(1)\n"
    "if len(sys.argv) > 2 and sys.argv[2] == 'vandal':\n"
    "    open(sys.argv[1], 'w').write('garbage')\n"
    "if len(sys.argv) > 2 and sys.argv[2] == 'slow' and '&&' not in src:\n"
    "    import time; time.sleep(30)\n"
    "print('Tests 1 passed')\n")
sh("git", "init", "-q")
sh("git", "config", "user.email", "t@example.com")
sh("git", "config", "user.name", "t")
sh("git", "config", "core.autocrlf", "false")
sh("git", "add", ".")
sh("git", "commit", "-q", "-m", "init")
original_hash = sha(calc)


def cmd(*extra):
    return " ".join([f'"{sys.executable}"', f'"{fake_test}"', f'"{calc}"', *extra])


def tool(*args):
    return subprocess.run([sys.executable, TOOL, *args], cwd=root, capture_output=True, text=True, encoding="utf-8")


r = tool(calc, "--test-cmd", cmd(), "--json")
check("CLI run exits 0 with survivors", r.returncode == 0, r.stdout + r.stderr)
import json  # noqa: E402
data = json.loads(r.stdout) if r.returncode == 0 else {"mutants": [], "summary": {}}
killed = [m for m in data["mutants"] if m["status"] == "killed"]
check("mutants touching n >= 10 are killed and name the failing test",
      killed and all(m["killed_by"] == "FAIL calc.test > boundary 10" for m in killed), data["mutants"])
check("other mutants survive", any(m["status"] == "survived" for m in data["mutants"]), data["summary"])
check("file restored byte-for-byte (CRLF and UTF-8 kept)", sha(calc) == original_hash)
check("git status clean after the run", sh("git", "status", "--porcelain") == "")

r = tool(calc, "--test-cmd", cmd(), "--fail-on-survivors")
check("--fail-on-survivors exits 1 and prints the table", r.returncode == 1 and "survived" in r.stdout, r.stdout + r.stderr)

r = tool(calc, "--test-cmd", cmd("vandal"))
check("a test command that overwrites the file still ends with the original", r.returncode == 0 and sha(calc) == original_hash,
      r.stderr)

open(calc, "ab").write(b"// dirty\n")
r = tool(calc, "--test-cmd", cmd())
check("refuses a file with uncommitted changes", r.returncode == 2 and "dirty" in r.stderr, r.stderr)
dirty_hash = sha(calc)
r = tool(calc, "--test-cmd", cmd(), "--allow-dirty")
check("--allow-dirty runs and restores the dirty content", r.returncode == 0 and sha(calc) == dirty_hash, r.stderr)
sh("git", "checkout", "--", "calc.js")

other = os.path.join(root, "novo.js")
open(other, "w").write("export const f = (n) => n > 1;\n")
r = tool(other, "--test-cmd", cmd())
check("refuses an untracked file", r.returncode == 2 and "untracked" in r.stderr, r.stderr)
os.remove(other)

r = tool(calc, "--list")
check("--list prints mutants without running anything", r.returncode == 0 and "comparison" in r.stdout and sha(calc) == original_hash,
      r.stdout + r.stderr)

r = tool(calc, "--test-cmd", f'"{sys.executable}" -c "import sys; sys.exit(3)"')
check("baseline failure is a tool error and leaves the file intact", r.returncode == 2 and "baseline" in r.stderr
      and sha(calc) == original_hash, r.stderr)

rows = ts.collect_rows(CALC, ts.generate_mutants(CALC, ("and-or-swap",)), "calc.js")
ts.run_all(calc, rows, cmd("slow"), root, 3)
check("a hanging test run is killed, reported as timeout, and the file restored",
      rows[0]["status"] == "timeout" and sha(calc) == original_hash, rows)


def interrupting_runner():
    calls = {"n": 0}

    def run(command, cwd, timeout):
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeyboardInterrupt()
        return 0, "ok"
    return run


rows = ts.collect_rows(CALC, ts.generate_mutants(CALC), "calc.js")
try:
    ts.run_all(calc, rows, "unused", root, 5, runner=interrupting_runner())
    interrupted = False
except KeyboardInterrupt:
    interrupted = True
check("an interrupt mid-mutant restores the original", interrupted and sha(calc) == original_hash)


def bad_writer(path, data):
    with open(path, "wb") as fh:
        fh.write(data + b"x")


rows = ts.collect_rows(CALC, ts.generate_mutants(CALC), "calc.js")
try:
    ts.run_all(calc, rows, cmd(), root, 30, writer=bad_writer)
    raised = False
except ts.RestoreError:
    raised = True
check("a restore that does not match the original hash aborts loudly", raised)
backups = [d for d in os.listdir(tempfile.gettempdir()) if d.startswith("tsmutate-")]
check("the backup copy is kept when the restore fails",
      any(open(os.path.join(tempfile.gettempdir(), d, "calc.js.orig"), "rb").read() == CALC.encode("utf-8")
          for d in backups if os.path.exists(os.path.join(tempfile.gettempdir(), d, "calc.js.orig"))))
ts.write_bytes(calc, CALC.encode("utf-8"))
check("fixture restored for cleanup", sha(calc) == original_hash)

r = subprocess.run([sys.executable, TOOL, "--help"], capture_output=True, text=True, encoding="utf-8")
check("--help documents restore, dirty check and exit codes",
      r.returncode == 0 and "sha256" in r.stdout and "--allow-dirty" in r.stdout and "Exit codes" in r.stdout)

print(f"\n{'ALL PASS' if all(results) else 'FAILURES'} ({sum(results)}/{len(results)})")
sys.exit(0 if all(results) else 1)
