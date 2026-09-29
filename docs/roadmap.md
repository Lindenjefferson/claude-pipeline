# Roadmap do plugin `pipeline`

Backlog vivo do plugin. Cada item diz de onde veio (feedback de uma entrega real, revisão do próprio plugin ou ideia adaptada do ECC) e o esforço estimado (P, M, G). Ao entregar um item, mover para a seção da versão correspondente com o PR.

## 1.6.0 — em andamento (branch `refactor/simplify-hook-guard`)

O hook volta ao objetivo original: não deixar passar o óbvio (`.env`, segredos e tokens explícitos) no commit.

- [x] **Só o `pre-commit` nativo**: `pre-commit-secret-scan.py` de 3.022 para 353 linhas; testes do hook de 3.298 para ~550. Ficam o scanner, a allowlist por fingerprint e o `--fingerprint`.
- [x] **Sai o `PreToolUse`** (parser e guard de desvios) e o `pre-push` (estado do remoto, `insteadOf`). Um `pre-push` de versão antiga vira no-op e a reinstalação o remove.
- [x] **Gate sem bloqueio**: o `gate` continua como etapa do `manager` (verificação e relatório), mas nada bloqueia o push; sai o `gate-approved` e o `pipeline.gate`.
- [x] **Kickoff**: instala só o `pre-commit`; `permissions.deny` ganha `git commit --no-verify`/`-n`.

## 1.5.1 — pronta (commit `63b9f03`, branch `fix/hook-false-denials-and-report-capture`, sem PR)

Minors aceitos nas revisões finais da 1.5.0:

- [x] Hook: `git config` libera chaves inofensivas de `remote.*` (prune, tagOpt, pushDefault…); valores iguais a nomes de seção (`git config user.name core`) passam; `--show-names` na lista de leitura.
- [x] Hook: `find` com alternativas `-o` entre parênteses e `-empty` combinado com filtro; `node -e "..." --no-verify` (argumento do script) passa.
- [x] Hook: cópia a partir de caminho derivado do git (origem de `cp` não é alvo de escrita) e remoção de `*.lock` direto no diretório do git.
- [x] Hook: marcação de variáveis respeita a ordem dos comandos (o valor de uma atribuição é expandido na hora; referência a variável ainda indefinida não herda o que ela vira depois).
- [x] Hook: depois de `cd` para variável não resolvida, escrita relativa com segmento `.git` ou na pasta do `core.hooksPath` é verificada.
- [x] Hook: chave de `git config` vinda de variável ou de `$(...)`; `Get-ChildItem <git> | Remove-Item` e atribuições em script blocks no PowerShell.
- [x] Testes do hook e do manager sem instabilidade (`tempfile.mkdtemp` em todos; rodam em paralelo).
- [x] Relatório do agente gravado sem transcrição manual (hook `SubagentStop` para uma caixa de entrada, ou `save-report --inbox` pelos revisores com Bash).
- [x] Kickoff (Next): propor `@playwright/test` e `npm run e2e:smoke`; `dev`/`qa` usam o script do projeto quando existe.

Candidatos baratos que ficaram de fora da 1.5.1:

- [ ] **Retomada depois de compactação** (ECC `session-start`/`pre-compact`): hook `SessionStart` com matcher `compact|resume` injeta um resumo curto do `ledger.py status --head HEAD` quando existe ledger (teto de ~3000 caracteres). P.
- [ ] **Bloquear servidor de dev solto** (ECC `pre-bash-dev-server-block`): negar `npm|pnpm|yarn run dev`, `next dev` sem `run_in_background`/`timeout`, com a forma certa na mensagem. Custou uma rodada de QA e um processo órfão no Módulo 1. P.
- [ ] **Encoding no commit**: o hook recusa linhas adicionadas que não decodificam como UTF-8 (Latin-1 misturado em testes no Módulo 1). P.
- [ ] **`ledger.py metrics`**: rodadas por tarefa e revisor, reprovações por causa, rerrevisões escopadas × completas, para comparar entregas. P.

## Próximos

- [ ] **Revisores exigidos já no plano**: `package.py plan-check` lê os `Files` de cada tarefa do plano e completa os revisores exigidos (mesmas regras do aviso de revisor faltando do `status`). O gate do Módulo 1 bloqueou por revisores marcados errado à mão. M.
- [ ] **Worktree com base e seed** (ECC `tmux-worktree-orchestrator`): `package.py worktree --name <n> --branch <b> --base <branch-do-módulo> --seed .superpowers` cria o worktree a partir da branch do módulo e copia ledger, relatórios, briefs e lições. P.
- [ ] **Aviso de config de qualidade alterada** (ECC `config-protection`): o pacote de revisão marca diffs em `eslint.config.*`, `tsconfig*.json`, `vitest.config.*`, `.prettierrc*`, `supabase/config.toml`; o `code-review` justifica. P.
- [ ] **Menos reabertura do spec**: nota "correção de detalhe" conferida só pelo revisor do domínio, em vez de deixar as quatro revisões de spec desatualizadas. P–M.
- [ ] **Âncora de teste por requisito** (ECC `spec-miner`): cada invariante do spec aponta o teste que a cobre; o `gate` confere. P (como convenção no template de spec).
- [ ] **Aviso de "racionalização" no gate** (ECC `delivery-gate`): listar frases como "pre-existing", "will fix later", "not related" nos relatórios, sem bloquear. P.

## Decisões pendentes do usuário

- [ ] **Ruído do graphify**: o plugin graphify injeta "MANDATORY: run graphify" em quase todo Bash/Read, gastando contexto em toda chamada. Opção: o kickoff instala o hook do graphify só para `Read|Grep|Glob`. Mexe em outro plugin.
- [ ] **Lições novas do Módulo 1**: montar a lista (contraste do destrutivo, foco depois de desmontar linha, `rev-parse` em worktree, revisor por domínio no plano…) e promover item a item com aprovação.

## Entregues

- **1.5.0** (PR #4): rerrevisão escopada; relatório por tarefa; STALE por arquivo e domínio; revisores exigidos no `status`; ferramentas de mutação; `pre-commit` nativo; estado do remoto por `ls-remote`; `git config` fechado por padrão; sem exceção para caminhos derivados do git.
- **1.4.0** (PR #3): lições com contadores e injeção por caminho; checklists por stack; validação do relatório do implementador; `save-report`; adendos em arquivos; kickoff com allowlist e complementos Next/Supabase; allowlist de segredos por fingerprint.
