# Roadmap do plugin `pipeline`

Backlog vivo do plugin. Cada item diz de onde veio (feedback de uma entrega real, revisão do próprio plugin ou ideia adaptada do ECC) e o esforço estimado (P, M, G). Ao entregar um item, mover para a seção da versão correspondente com o PR.

## 2.0.0 — em andamento (branch `refactor/simple-flow`)

Fluxo simples e circular, no formato do ECC (`orch-pipeline`, `code-reviewer`, `verification-loop`), em versão enxuta.

- [x] **Tamanho decide as etapas** (pequeno, padrão, grande) e duas aprovações do usuário: o plano e o merge/push.
- [x] **Um laço por tarefa**: `dev` (TDD, migrations e doc do módulo) → `reviewer` (um agente, checklists por stack, só achados com prova) → `qa`; no máximo 3 rodadas antes de perguntar.
- [x] **`gate` como verification-loop local**: ledger, build, tipos, lint, testes, segredos no histórico e diff → READY / NOT READY.
- [x] **Ledger simples** (`ledger.py`, 164 linhas): `start`, `add`, `note`, `status [--check]`.
- [x] **Saem**: `security`, `audit`, `design`, `code-review`, `db` e `docs` como agentes; `package.py`, `findings.py`, ferramentas de mutação, lições com contadores (as globais viraram itens dos checklists), hook `SubagentStop`, worktree obrigatória, revisão de spec com várias rodadas.
- [x] **Lições por projeto** em `docs/lessons.md`, lidas pelo `dev` e pelo `reviewer`.

## Próximos

- [ ] **Retomada depois de compactação** (ECC `session-start`): hook `SessionStart` com matcher `compact|resume` mostra o `ledger.py status` quando há ledger. P.
- [ ] **Bloquear servidor de dev solto** (ECC `pre-bash-dev-server-block`): negar `npm run dev` / `next dev` fora do modo background, com a forma certa na mensagem. Custou uma rodada de QA e um processo órfão no Módulo 1. P.
- [ ] **Encoding no commit**: o `pre-commit` recusa linhas adicionadas que não decodificam como UTF-8. P.
- [ ] **Âncora de teste por requisito** (ECC `spec-miner`): cada critério de aceite do plano aponta o teste que o cobre; o `qa` confere. P.

## Decisões pendentes do usuário

- [ ] **Ruído do graphify**: o plugin graphify injeta "MANDATORY: run graphify" em quase todo Bash/Read, gastando contexto em toda chamada. Opção: o kickoff instala o hook do graphify só para `Read|Grep|Glob`. Mexe em outro plugin.

## Entregues

- **1.6.0** (PR #5): scan de segredos reduzido a um `pre-commit` nativo; sem `PreToolUse`, `pre-push` nem bloqueio de gate.
- **1.5.1** (PR #5): captura de relatórios por `SubagentStop`, Playwright no kickoff, correções de negações falsas do hook, testes com `mkdtemp`.
- **1.5.0** (PR #4): rerrevisão escopada; relatório por tarefa; STALE por arquivo e domínio; revisores exigidos no `status`; ferramentas de mutação; `pre-commit` nativo; estado do remoto por `ls-remote`; `git config` fechado por padrão; sem exceção para caminhos derivados do git.
- **1.4.0** (PR #3): lições com contadores e injeção por caminho; checklists por stack; validação do relatório do implementador; `save-report`; adendos em arquivos; kickoff com allowlist e complementos Next/Supabase; allowlist de segredos por fingerprint.
