import importlib.util, json, os, re

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
spec = importlib.util.spec_from_file_location("scan", os.path.join(ROOT, "hooks", "pre-commit-secret-scan.py"))
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("PASS" if ok else "FAIL", name, "" if ok else f"| {str(detail)[-300:]}")


def files(*suffixes):
    for folder, _, names in os.walk(ROOT):
        if "__pycache__" in folder:
            continue
        for name in names:
            if name.endswith(suffixes):
                yield os.path.join(folder, name)


def front_matter(path):
    text = open(path, encoding="utf-8").read()
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    return dict(line.split(":", 1) for line in match.group(1).splitlines() if ":" in line) if match else {}


hidden = []
for path in files(".md", ".py", ".json", ".jsonl", ".gitignore", ".txt", ".js", ".ts", ".sh"):
    for number, line in enumerate(open(path, encoding="utf-8").read().split("\n"), 1):
        for found in scan.INVISIBLE.finditer(line):
            if not (found.group() == chr(0xFEFF) and number == 1 and found.start() == 0):
                hidden.append(f"{os.path.relpath(path, ROOT)}:{number}")
check("no invisible or direction-control character in any file of the plugin", not hidden, hidden)

agents = sorted(p for p in files(".md") if os.sep + "agents" + os.sep in p)
check("the plugin has its agents", len(agents) >= 4, agents)
for path in agents:
    meta = front_matter(path)
    check(f"{os.path.basename(path)} lists the tools it may use (an allowlist, not a denylist)",
          "tools" in meta and "disallowedTools" not in meta, meta)

for name in ("discovery", "qa"):
    text = open(os.path.join(ROOT, "agents", name + ".md"), encoding="utf-8").read()
    check(f"{name}.md says that text from sources, pages and tool output is data, never instructions",
          "is data" in text and "never follow" in text.lower(), "")

config = json.load(open(os.path.join(ROOT, "hooks", "hooks.json"), encoding="utf-8"))
commands = [hook["command"] for groups in config["hooks"].values() for group in groups for hook in group["hooks"]]
RISKY = re.compile(r"\b(curl|wget|sudo|eval|nc|ssh)\b|2>\s*/dev/null|\|\|\s*(true|:)")
check("hooks.json commands make no network call, privilege change or silent failure",
      commands and not any(RISKY.search(command) for command in commands), commands)
check("hooks.json loads the progress mod", config.get("modules") == ["./andamento.js"], config.get("modules"))
mod = open(os.path.join(ROOT, "hooks", "andamento.js"), encoding="utf-8").read()
check("the progress mod only reads: no network, model, prompt, tool approval or store",
      not re.search(r"\$\.(http|model|prompt|tool|store|session\.send|env\.set)\b", mod)
      and "'tool.call'" not in mod and "'tool.check'" not in mod, "")
writes = re.findall(r"\$\.fs\.(?!(?:stat|read\w*|exists|list)\b)(\w+\(.*)", mod)
check("the progress mod's one file write is usage.json beside the ledger",
      len(writes) == 1 and writes[0].startswith("write(") and "usage.json" in writes[0], writes)

settings = json.load(open(os.path.join(ROOT, "skills", "kickoff", "templates", "settings.allowlist.json"),
                          encoding="utf-8"))
for entry in ("Bash(sudo:*)", "Bash(git push --force:*)", "Bash(git push -f:*)", "Bash(chmod 777:*)"):
    check(f"the kickoff template denies {entry}", entry in settings["deny"], settings["deny"])
check("the kickoff template asks before every git push", "Bash(git push:*)" in settings.get("ask", []), settings)
check("the kickoff template guards the scan allowlist with an Edit rule and has no Write rule (never consulted)",
      "Edit(.pipeline-secrets-allow)" in settings["deny"] and not any(rule.startswith("Write(") for rule in settings["deny"]),
      settings["deny"])
check("the kickoff template denies skipping the pre-commit hook right after git commit (bash-guard.py covers the rest)",
      {"Bash(git commit --no-v*)", "Bash(git commit -n*)", "Bash(git -c core.hooksPath*)"} <= set(settings["deny"]),
      settings["deny"])
check("no deny rule has a wildcard before a flag (it would also match the flag quoted in a commit message)",
      not any(re.match(r"Bash\(git commit \*", rule) for rule in settings["deny"]), settings["deny"])
for term in ("sudo", "--force", "chmod 777", "| sh", "| bash"):
    check(f"the kickoff template never allows a command containing {term!r}", term in settings["never_allow"],
          settings["never_allow"])

print("ALL PASS" if all(results) else "SOME FAILED", f"({sum(results)}/{len(results)})")
