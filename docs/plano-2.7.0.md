# Plano de implementação da 2.7.0

> **Para agentes:** use superpowers:executing-plans (ou subagent-driven-development) tarefa a tarefa; os passos usam checkbox (`- [ ]`).

**Objetivo:** implementar os 18 itens aprovados de [`docs/proposta-2.7.0.md`](proposta-2.7.0.md) como regras gerais do plugin, com o código (gate, ledger) coberto por teste primeiro.

**Arquitetura:** duas mudanças de código (`gate.py`: glob de verdade e aviso de glob vazio; `ledger.py`: `mode autonomous|supervised` e `note --validar`, lidos pelo `status` e pelo relatório do gate). O resto é texto nos componentes, cada regra no arquivo que é a fonte dela, e os outros apontam com uma linha.

**Stack:** Python 3 (sem dependências; testes rodam com `python <arquivo>` e imprimem `ALL PASS`), Markdown.

**Spec:** [`docs/proposta-2.7.0.md`](proposta-2.7.0.md). A seção "Para a 2.8" fica fora (vai para o backlog do roadmap).

## Restrições globais

- Só orquestração, independente de stack, enxuto (CLAUDE.md da raiz). Onde a proposta cita uma stack (`npx`, `postinstall`, `AGENTS.md`, `node_modules`, junction), o texto fica geral: "código baixado e executado sem versão fixa", "scripts de ciclo de vida de pacotes", "arquivos de instrução para agentes", "dependências instaladas".
- Prompts de skills, agentes e checklists em inglês; template do `CLAUDE.md` dos projetos, README e roadmap em português.
- Fonte única: cada regra mora num arquivo; os demais apontam.
- Teste primeiro em `gate.py` e `ledger.py`: o teste novo falha antes da mudança. Ledgers da 2.6 continuam legíveis.
- UTF-8 e LF; nunca `--no-verify`.
- **Não instalar a 2.7 em nenhum projeto.** Merge e push só com aprovação do dono.

## Decisões que tomei (confira na aprovação)

1. **Nome do modo autônomo no ledger:** `ledger.py mode autonomous` / `mode supervised` (um registro novo, `type: "mode"`). Vale a partir do registro, pode ligar e desligar no meio da entrega, e aparece no `status`, então o hook de retomada devolve o modo ao manager depois de compactar. Sem registro de modo = supervisionado (ledgers antigos).
2. **Efeito do modo no ledger:** em modo autônomo some só o pendente "still fails after a fix round: ask the user"; os outros pendentes continuam (a rodada de correção segue até PASS). O fechamento de ciclo não muda.
3. **`note --validar`** (nome que você pediu, mesmo com as outras flags em inglês). Com ele, a nota sai de `notes` e vai para `validar` no `status`; o texto do `status` imprime `VALIDAR: <texto>`. O relatório do gate ganha `Mode: autonomous` (quando ligado) e a seção `## VALIDAR`.
4. **Glob do gate:** `*` e `?` não atravessam `/`; `**/` casa zero ou mais pastas; `**` no fim casa tudo; `[...]` e `[!...]` como no glob; `{a,b}` (sem aninhar) vira alternativa; `./` no início e `\` são normalizados. **Muda o comportamento:** com o `fnmatch`, `tests/*.ts` também pegava `tests/sub/x.ts`; agora não. Vai para as notas de atualização.
5. **Glob que não casa nenhum arquivo rastreado:** o gate imprime `warning: test glob '<glob>' matches no tracked file (...)` e **não** reprova por isso (a proposta diz "avisar"). Se algum critério ficar sem teste por causa disso, a checagem Criteria já reprova.
6. **Capturas persistentes:** `.superpowers/screens/<slug>/` (já ignorado pelo git em todo projeto preparado pelo kickoff), com o script de captura.
7. **Worktree:** o manager cria cada worktree ele mesmo no head atual e a prepara antes de despachar; o `dev` confere o commit de origem e para com NEEDS_CONTEXT se não bater (não faz `reset`).
8. **Revisão de segurança (item 18):** o manager roda a skill nativa `security-review` uma vez antes do gate e registra achados como `fix-N` ou `defer`; sem checagem nova no gate (o gate é sem LLM).
9. **Regra de veto a extensões de terceiros:** fonte única numa seção nova "Third-party extensions" do `checklists/general.md`; manager e kickoff apontam com uma linha.
10. **Este plano sai no último commit** da branch (o conteúdo fica nos commits e no roadmap). A proposta fica em `docs/` como registro, citada pela seção 2.7.0 do roadmap.

## Riscos que nenhum passo testa por acaso (Review Focus)

1. Glob com `./`, `\`, chaves ou ponto (`.spec.ts`): testado na tarefa 1.
2. Projeto cujo glob antigo dependia de `*` atravessar pastas: o critério passa a faltar. Coberto pelo teste "`*` fica numa pasta" e pela nota de atualização.
3. Ledger da 2.6 sem `mode` nem `validar`: teste de legado na tarefa 2.
4. Modo trocado no meio da entrega (autônomo e de volta a supervisionado): teste na tarefa 2.
5. "Arquivos de teste" ausente: o gate continua no comportamento antigo (todo arquivo não Markdown), sem aviso; teste existente segue verde e um novo confere que não há aviso.

---

### Tarefa 1: `gate.py` com glob de verdade e aviso de glob vazio (item 1)

**Arquivos:** modificar `plugins/pipeline/skills/manager/gate.py` (docstring, `import fnmatch`, `traceability`); teste em `plugins/pipeline/skills/manager/tests/test_gate.py` (antes do `print("ALL PASS"...)` final).

**Interfaces:** produz `glob_regex(pattern) -> re.Pattern` e `traceability(plan)` com a mesma assinatura e retorno `(ok, detail)`; o aviso é impresso em stdout.

- [ ] **Passo 1: teste que falha.** Depois do último `check` de `test_gate.py`:

```python
sh("git", "commit", "-q", "--no-verify", "-m", "docs: quality report y")
os.makedirs(os.path.join(repo, "e2e", "flows"), exist_ok=True)
commit("plan.md", "# plan\n- AC-T1-1 a\n- AC-T1-2 b\n- AC-T1.3 c\n- AC-T2-1 d\n- AC-T2-2 e\n## Errata\n", "docs: plan T2")
commit("e2e/home.spec.txt", "test('AC-T2-1 given d')\n", "test: e2e at the folder root")
commit("e2e/flows/pay.spec.txt", "test('AC-T2-2 given e')\n", "test: e2e in a subfolder")


def criteria_with(globs):
    commit("CLAUDE.md", claude_md(test_files=globs, audit=True), f"docs: test files {globs}")
    return gate("--base", "main")


r = criteria_with("tests/* e2e/**/*.spec.txt")
check("**/ matches zero or more folders: tests at the folder root and in a subfolder are found",
      "Criteria:   PASS" in r.stdout and "warning" not in r.stdout, r.stdout)
r = criteria_with("tests/* e2e/*.spec.txt")
trace = r.stdout.split("Criteria:")[1].split("\n    ")[1] if "Criteria:" in r.stdout else ""
check("* stays within one folder: a test in a subfolder is not found",
      "Criteria:   FAIL" in r.stdout and "AC-T2-2" in trace and "AC-T2-1" not in trace, r.stdout)
r = criteria_with("./tests/* e2e/**/*.{spec,test}.txt")
check("a leading ./ and {a,b} alternatives work", "Criteria:   PASS" in r.stdout, r.stdout)
r = criteria_with("tests/* e2e/**/*.spec.txt spec/**/*.txt")
check("a glob that matches no tracked file is a warning that names it, not a failure",
      "Criteria:   PASS" in r.stdout and "warning: test glob 'spec/**/*.txt' matches no tracked file" in r.stdout,
      r.stdout)
```

- [ ] **Passo 2:** `python plugins/pipeline/skills/manager/tests/test_gate.py` → os quatro novos FAIL (o `fnmatch` não casa `e2e/home.spec.txt` com `e2e/**/...`, casa `e2e/flows/pay.spec.txt` com `e2e/*`, não conhece `{}` nem `./`, e não avisa).

- [ ] **Passo 3: implementação.** Em `gate.py`, trocar `import fnmatch` pelo uso de `re` (já importado) e acrescentar antes de `traceability`:

```python
def glob_regex(pattern):
    pattern, out, index = pattern.replace("\\", "/").removeprefix("./"), [], 0
    while index < len(pattern):
        char = pattern[index]
        if pattern.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
            continue
        if pattern.startswith("**", index):
            out.append(".*")
            index += 2
            continue
        end = pattern.find("]" if char == "[" else "}", index + 2) if char in "[{" else -1
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "[" and end > 0:
            body = pattern[index + 1:end]
            out.append("[" + ("^" + body[1:] if body.startswith("!") else body).replace("\\", "\\\\") + "]")
            index = end
        elif char == "{" and end > 0 and "," in pattern[index:end]:
            out.append("(?:" + "|".join(re.escape(part) for part in pattern[index + 1:end].split(",")) + ")")
            index = end
        else:
            out.append(re.escape(char))
        index += 1
    return re.compile("".join(out) + r"\Z")
```

E, em `traceability`, o bloco `if globs:`:

```python
    if globs:
        tracked, names = names, []
        for pattern in globs:
            matched = [name for name in tracked if glob_regex(pattern).match(name)]
            if not matched:
                print(f"warning: test glob '{pattern}' matches no tracked file (Arquivos de teste in CLAUDE.md)",
                      flush=True)
            names += [name for name in matched if name not in names]
```

Docstring: trocar "space-separated, fnmatch style" por "space-separated globs: `*` and `?` stay within one folder, `**/` matches zero or more folders, `{a,b}` is either; a glob that matches no tracked file prints a warning".

- [ ] **Passo 4:** rodar `test_gate.py` → `ALL PASS`.
- [ ] **Passo 5: commit** `gate: test-file globs with real glob semantics and a warning for a glob that matches nothing`.

### Tarefa 2: `ledger.py` com modo autônomo e `note --validar`; relatório do gate (item 15)

**Arquivos:** `plugins/pipeline/skills/manager/ledger.py` (docstring, `cycle_state`, `note`, `status`, `main`, função nova `mode`); `gate.py` (`write_report`); testes em `tests/test_ledger.py` e `tests/test_gate.py`.

**Interfaces:** `status --json` ganha `"autonomous": bool` e `"validar": [str]`; `notes` passa a trazer só as notas sem `--validar`. `cycle_state(cycle, autonomous=False)`. O gate lê os dois campos novos.

- [ ] **Passo 1: testes que falham.** Em `test_ledger.py`, antes do bloco `CLAIMS`:

```python
AUTO = ".superpowers/auto.jsonl"
check("mode before start is refused", run("mode", "autonomous", ledger=AUTO).returncode != 0)
run("start", "--slug", "auto", ledger=AUTO)
check("a delivery starts supervised", status(AUTO)["autonomous"] is False, status(AUTO))
check("an unknown mode is refused", run("mode", "yolo", ledger=AUTO).returncode != 0)
r = run("mode", "autonomous", ledger=AUTO)
check("mode autonomous is recorded and status says so",
      r.returncode == 0 and status(AUTO)["autonomous"] is True and "autonomous" in run("status", ledger=AUTO).stdout,
      r.stderr)
for agent, verdict, task, count in (("dev", "DONE", "T1", 0), ("reviewer", "FAIL", None, 1),
                                    ("dev", "DONE", "fix-1", 0), ("reviewer", "FAIL", None, 1)):
    add(agent, verdict, task, count, ledger=AUTO)
pending = status(AUTO)["pending"]
check("autonomous: a second failed review does not stop for the user, the fix rounds go on",
      not any("ask the user" in item for item in pending) and any("one batch" in item for item in pending), pending)
run("mode", "supervised", ledger=AUTO)
check("back to supervised: the same cycle asks the user again",
      any("ask the user" in item for item in status(AUTO)["pending"]), status(AUTO)["pending"])
run("note", "--text", "page size 50", "--validar", ledger=AUTO)
run("note", "--text", "ruled out a finding", ledger=AUTO)
state = status(AUTO)
check("note --validar goes to the VALIDAR list, apart from plain notes",
      state["validar"] == ["page size 50"] and state["notes"] == ["ruled out a finding"], state)
check("text status shows the VALIDAR list", "VALIDAR: page size 50" in run("status", ledger=AUTO).stdout)
```

E no teste de legado, acrescentar à condição: `and state["autonomous"] is False and state["validar"] == []`.

Em `test_gate.py`, logo antes de `r = gate("--base", "main", "--report", "feature-y")`:

```python
ledger_cmd("mode", "autonomous")
ledger_cmd("note", "--text", "page size 50", "--validar")
```

e depois da última checagem do relatório `feature-y`:

```python
check("the report shows the mode and the VALIDAR list",
      "Mode: autonomous" in text and "## VALIDAR" in text and "- page size 50" in text, text)
```

- [ ] **Passo 2:** os dois arquivos de teste → FAIL nas checagens novas (`mode` e `--validar` não existem).

- [ ] **Passo 3: implementação em `ledger.py`.**
  - `cycle_state(cycle, autonomous=False)`: o laço do "still fails after a fix round: ask the user" só roda com `not autonomous`.
  - Função nova:
    ```python
    def autonomous(entries):
        modes = [entry["mode"] for entry in entries if entry["type"] == "mode"]
        return bool(modes) and modes[-1] == "autonomous"


    def mode(args):
        if not read(args.ledger):
            sys.exit("no delivery started: run start first")
        write(args.ledger, {"type": "mode", "mode": args.mode})
        print(f"mode {args.mode}")
    ```
  - `note`: grava `{"type": "note", "text": args.text}` e, com `--validar`, `"validar": True`; imprime `noted (VALIDAR)` nesse caso.
  - `status`: `auto = autonomous(entries)`; `cycle_state(groups[-1], auto)`; no relatório `"autonomous": auto`, `"notes"` só com notas sem `validar`, `"validar"` com as marcadas. No texto: depois da linha `delivery ...`, `print("mode: autonomous (approvals become VALIDAR notes; never merge or push)")` quando `auto`; depois das notas, `print(f"VALIDAR: {text}")` para cada uma.
  - `main`: subcomando `mode` com `command.add_argument("mode", choices=("autonomous", "supervised"))`; `note` ganha `command.add_argument("--validar", action="store_true", help="the user validates this decision on return")`.
  - Docstring: duas linhas de uso (`mode autonomous|supervised`, `note --text <text> [--validar]`) e uma frase: "In autonomous mode a cycle that still fails after a fix round does not ask the user (the fix rounds go on); notes marked --validar are listed apart, for the user to confirm on return."
- [ ] **Passo 4: `gate.py` `write_report`:** depois de `Cycles:`, `lines.append("Mode: autonomous")` quando `ledger.get("autonomous")`; depois das notas, se `ledger.get("validar")`: `["", "## VALIDAR", ""] + [f"- {text}" for text in ledger["validar"]]`. Docstring do gate: "ledger notes, the VALIDAR list".
- [ ] **Passo 5:** `test_ledger.py` e `test_gate.py` → `ALL PASS`; `test_session_start.py` → `ALL PASS`.
- [ ] **Passo 6: commit** `ledger: autonomous mode and note --validar, listed by status and the quality report`.

### Tarefa 3: checklists (itens 7, 8, 10, 11, 12, 18)

**Arquivos:** `plugins/pipeline/checklists/general.md`, `plugins/pipeline/skills/manager/templates/spec-checklist.md`.

- [ ] **Invariantes**, item novo depois do "Validate the value...":
  `- **A rule that filters or sums a set holds in every function that lists or sums that set** — applied in one function and forgotten in its siblings, totals disagree between screens. Verify: the plan names every function that lists or sums the set, and each has a test of the rule.`
- [ ] **Invariantes**, ampliar "Every layout requirement in the spec is an automatic check..." para:
  `... Verify: widths, touch-target sizes and overflow rules the project states are asserted in the e2e of each screen they apply to; a check of a table or list measures every cell of every column and every header (text inside its cell, no word broken, not touching its neighbor) at each width where that layout applies, and the inner gap of cards in a grid, because fixing one column moves the break to its neighbors.`
- [ ] **Web and UI**, "A predictable failure...": acrescentar ao Verify `(a value above a storage limit says the limit, not "invalid format")`.
- [ ] **Web and UI**, "A form bound to a selected record...": acrescentar `Its prefill comes from the data when the form opens, not from the first render, and a server error for a field the form does not show appears as a general message with a reload.` e o caso no Verify.
- [ ] **Web and UI**, três itens novos:
  - `- **Responses carry security headers** — without them the browser allows framing, mixed content and leaking the referrer. Verify: content policy, strict transport, framing and referrer headers are configured, and a test reads them from a real response.`
  - `- **Production builds ship no debug artifacts** — source maps, detailed errors and diagnostic routes hand an attacker the code and its internals. Verify: the production build has none of them, checked on the build output.`
  - `- **Tokens and secret identifiers come from a cryptographic source** — a predictable generator lets them be guessed. Verify: every token, reset code and secret id uses the platform's cryptographic random source.`
- [ ] **Seção nova no fim**, `## Third-party extensions` (fonte única da regra de veto):
  `- **Read everything before installing someone else's skill, plugin, MCP server or hook** — it runs with your permissions, and the risk is rarely in the main file. Verify: every file was read (hooks, plugin manifest, MCP configuration, instruction files for agents, package lifecycle scripts); refuse it when it downloads and runs code with no pinned version, changes dependencies or configuration by itself, sends content out without saying so, asks for tools beyond what it describes, or tries to change the agent's behavior outside its own scope; check license and origin (a copy without attribution is a warning sign). The outcome is one of three: do not install, copy the idea into a rule of your own, or install at a pinned version.`
- [ ] **spec-checklist §1**, item novo depois de "Each failure":
  `- **Validate before writing:** what is already written if the next validation refuses? Validation and permission come before any write; what must happen together is one atomic operation.`
- [ ] Rodar `test_plugin_integrity.py` → `ALL PASS`. **Commit** `checklists: sibling functions, validate before writing, full layout checks, prefill, headers, third-party extensions`.

### Tarefa 4: agentes (itens 2, 5, 6, 7, 13, 14, 16)

**Arquivos:** `plugins/pipeline/agents/dev.md`, `qa.md`, `reviewer.md`.

- [ ] **dev.md, Scope**, no parágrafo da worktree, antes de "work and commit only there": `The brief gives its origin commit: before touching anything, check that \`git log -1 --format=%H\` in the worktree is that commit; if it is not, or the worktree holds commits that are not yours, stop with NEEDS_CONTEXT.`
- [ ] **dev.md, Scope**, item novo: `When a project rule belongs in \`CLAUDE.md\`, write it only in the project's own sections: a section generated by a tool (recognized by its header) is rewritten when the tool reinstalls and never receives content.`
- [ ] **dev.md, Rules**, item novo: `Before each commit, check your own diff against every line of \`docs/lessons.md\`; the report lists the lines that applied.` E no bloco do relatório: `Lessons: <lines of docs/lessons.md that applied and how the diff meets them, or none applied>`.
- [ ] **dev.md, UI work**: "start one only with the Bash tool's background mode" ganha `, with the UI server command of "Comandos" when the project has one`.
- [ ] **qa.md, Captures**: trocar "in a temp folder outside the project" por `in \`.superpowers/screens/<slug>/\` (the slug from \`ledger.py status\`; git-ignored and kept across sessions), with the script that took them, so a later pass re-captures only the screens that changed; wait for transient notices and animations to finish before each capture`.
- [ ] **qa.md, What you do**: depois da linha do comando completo: `Write test outputs to the folder the brief gives (the per-run output folder of "Execução em paralelo"), never the default one a parallel run may delete.` E, no item de servidor, `with the UI server command of "Comandos" when the project has one`.
- [ ] **reviewer.md, Plan mode**, item novo: `- **Rules across sibling functions** (Invariantes of the general checklist): every function that lists or sums a set the plan filters or sums is named, each with a test of the rule.`
- [ ] Rodar `test_plugin_integrity.py`. **Commit** `agents: origin commit check, lessons against the diff, tool-generated sections, persistent captures, sibling functions`.

### Tarefa 5: manager (itens 2, 3, 4, 5, 9, 13, 15, 16, 17, 18)

**Arquivo:** `plugins/pipeline/skills/manager/SKILL.md`.

- [ ] Linha 12: acrescentar `In autonomous mode (below) neither stops, and nothing is merged or pushed.`
- [ ] **Ledger:** o item `note` ganha `; add \`--validar\` when the user must confirm it on return (every product decision and every approval you take in autonomous mode): \`status\` and the quality report list those apart`. Item novo: `- \`mode autonomous\` when the user turns autonomous mode on, \`mode supervised\` when they are back; \`status\` shows the mode, so it survives a compaction.`
- [ ] **Passo 2:** "then `superpowers:writing-plans`" vira `then \`superpowers:writing-plans\`, or a subagent with the same brief (spec path, lessons, the rules of this step) to draft a long plan without spending your context; you apply the product decisions`. **Plan review** ganha `; run it again until PASS (at most 3 rounds, then ask the user)`.
- [ ] **4.1 In parallel** reescrito: `... dispatch at once every task whose dependencies are integrated and whose \`Touches:\` share nothing with another running task. Create each worktree yourself from the current head and prepare it before dispatching, as that section says (dependencies, environment file, per-copy port and data store; the agent's isolation may refuse those commands), and give the brief the worktree path and its origin commit. Verification that uses a resource the section lists as shared, or a data store it does not isolate per copy, runs one task at a time; the coding does not wait. Without that section, run tasks one at a time.`
- [ ] **4.1 Integrate** reescrito: `**Integrate** a task only after its agent's completion notification (a live agent still locks its worktree), in plan order (fast-forward, or merge the task's commits), one command at a time: integrate, \`add\` to the ledger, then remove the worktree. A conflict or a red test after integrating goes back to that task's \`dev\`.`
- [ ] **4.2:** acrescentar `Each brief names a test output folder of its own (the per-run folder of "Execução em paralelo"), so the two runs do not delete each other's artifacts.`
- [ ] **4.4:** "qa saves captures ..." passa a citar `.superpowers/screens/<slug>/`; acrescentar `Publish the screens page from that folder, one file per delivery.`
- [ ] **4.6:** acrescentar `A lesson broken a second time becomes a check in the same round, with no second chance as text.`
- [ ] **Passo 6:** começa com `Run the \`security-review\` skill (the tool's native security review) once over the delivery branch; each finding goes to the \`dev\` as a \`fix-N\` task or is deferred with a decision, like the reviewer's.`
- [ ] **Passo 7, Where the time went:** acrescentar `When waiting for a shared resource (a single data store, login limits, a long e2e suite) is the largest time sink, propose the isolation lines of "Execução em paralelo" as the first task of the next delivery.`
- [ ] **Seção nova `## Autonomous mode`** (antes de `## Rules`):
  ```
  Only when the user turns it on (for example before leaving), recorded with `mode autonomous`:
  - Approval 1 becomes the plan reviewer's PASS; the plan's product decisions are also `note --validar`.
  - Fix rounds go on until the reviewer and qa pass; every ruling you would have asked the user about is a `note --validar`.
  - Never merge, push or deploy. The next delivery starts on a branch stacked on this one (`git switch -c <branch>` from its head, then `start --archive --base <this branch>`), and its gate runs with `--base <this branch>`.
  - When the user is back: `mode supervised`, then show the VALIDAR list, the deferred items with their decisions and the screens, and run approval 2 for each delivery, oldest first.
  ```
- [ ] **Seção nova `## Several sessions on one project`**:
  ```
  A delivery can be split across sessions (terminals): one front per session, split at a module boundary with no file in common, each in its own worktree (so its own ledger) and branch, with its sequential numbers reserved in the plan. One session integrates: it merges the fronts into the delivery branch and runs the gate. Fronts in different repositories run in separate sessions with no coordination.
  ```
- [ ] **Rules**, item novo: `- Before installing any third-party skill, plugin, MCP server or hook, apply "Third-party extensions" in \`${CLAUDE_PLUGIN_ROOT}/checklists/general.md\` and tell the user the outcome.`
- [ ] **Commit** `manager: worktree preparation and integration order, plan drafting and review rounds, autonomous mode, several sessions, security review`.

### Tarefa 6: kickoff e template (itens 4, 5, 6, 14, 17, 18)

**Arquivos:** `plugins/pipeline/skills/kickoff/SKILL.md`, `plugins/pipeline/skills/kickoff/templates/CLAUDE.md`.

- [ ] **Template, "Comandos"**, depois de "Verificação de interface": `- Servidor para a verificação de interface (o mesmo que o runner sobe, com as variáveis do ambiente de teste; quem sobe o servidor à mão usa este): _(comando)_`
- [ ] **Template, "Execução em paralelo"**, a lista passa a ser:
  ```
  - Como rodar N cópias ao mesmo tempo (o que muda por worktree): _(porta, variáveis de ambiente, dados de teste)_
  - Armazenamento de dados por cópia: _(outra instância com portas próprias ou um esquema por cópia; ou "compartilhado", e a verificação que grava roda uma tarefa por vez)_
  - Como preparar as dependências de uma cópia (o `manager` faz antes de despachar): _(reaproveitar as dependências já instaladas ou instalar; copiar o arquivo de ambiente)_
  - Pasta de saída dos testes por execução: _(a variável de ambiente que o runner lê; `reviewer` e `qa` usam sempre uma pasta própria)_
  - Limites do ambiente de teste que atrapalham execuções simultâneas e como afrouxá-los só no ambiente local: _(ex.: taxa de login)_
  - Testes de interface reaproveitam uma sessão autenticada pronta em vez de autenticar a cada teste: _(como)_
  - Recursos que não dá para isolar (a verificação que os usa roda uma tarefa por vez): _(ex.: limite de taxa de um serviço externo, um serviço único)_
  - Números sequenciais reservados no plano: _(ex.: migrations)_
  ```
- [ ] **SKILL.md passo 5:** acrescentar `Write only in the project's own sections: a section another tool generates (recognized by its header, like the one step 8.3 installs) is rewritten when that tool reinstalls and never receives project content.`
- [ ] **SKILL.md, Notes:** `- Before installing any third-party skill, plugin, MCP server or hook, apply "Third-party extensions" in \`${CLAUDE_PLUGIN_ROOT}/checklists/general.md\`; it applies to the user too.`
- [ ] **Commit** `kickoff: isolation lines for parallel copies, UI server command, tool-generated sections, third-party extensions`.

### Tarefa 7: versão, roadmap, README e limpeza

**Arquivos:** `plugins/pipeline/.claude-plugin/plugin.json`, `docs/roadmap.md`, `README.md`; remover `docs/plano-2.7.0.md`.

- [ ] `plugin.json`: `"version": "2.7.0"`.
- [ ] `roadmap.md`: seção `## 2.7.0 — lições da etapa 3 (PR #N)` no topo, com a origem (a etapa 2 retomada e a etapa 3 do controle-financeiro com a 2.6.1, boa parte em modo autônomo; [proposta](proposta-2.7.0.md)) e um `[x]` por grupo: gate, worktrees e execução em paralelo, planejamento, revisão e testes, lições, modo autônomo, capturas, segurança. Seção nova `## Backlog` antes de "Entregues" com o item da 2.8 (mods para o modo multi-instância, começando pelo protótipo do painel). Nota de atualização **2.7.0**: lê os ledgers da 2.6 (sem `mode` = supervisionado); o glob de "Arquivos de teste" agora é glob de verdade (`*` não atravessa pastas, `**/` casa zero ou mais) — use `**/` onde o teste pode estar em subpasta, e o gate avisa glob que não casa nada; rode o `kickoff` de novo para receber as linhas novas de "Execução em paralelo" e "Servidor para a verificação de interface".
- [ ] `README.md`, "Como funciona": uma linha depois do item 5: `Com você ausente, o modo autônomo do [manager](plugins/pipeline/skills/manager/SKILL.md) troca as aprovações por uma lista VALIDAR e nunca faz merge nem push.`
- [ ] Conferir consistência: `grep -rn "fnmatch\|temp folder outside the project\|Execução em paralelo" README.md CLAUDE.md docs/roadmap.md plugins/` (sem `fnmatch` no docstring; as capturas não citam mais pasta temporária; os nomes das linhas do template batem com o manager, o dev e o qa).
- [ ] `git rm docs/plano-2.7.0.md`. **Commit** `2.7.0: version, roadmap, update notes and 2.8 backlog`.

### Tarefa 8: verificação e revisão final

- [ ] `for t in plugins/pipeline/hooks/tests/test_*.py plugins/pipeline/skills/manager/tests/test_*.py; do python "$t"; done` → todos `ALL PASS`.
- [ ] `claude plugin validate plugins/pipeline` e `claude plugin validate .` → sem erro.
- [ ] Um revisor novo (modelo mais capaz) sobre `master..HEAD` contra a proposta e o CLAUDE.md da raiz; corrigir o que ele provar.
- [ ] Mostrar o resultado e **parar**: push, PR e merge só com a sua aprovação. Nenhuma instalação em projeto.
