# Roadmap do plugin `pipeline`

Backlog vivo do plugin. Cada item diz de onde veio (feedback de uma entrega real, revisão do próprio plugin ou ideia adaptada do ECC) e o esforço estimado (P, M, G). Ao entregar um item, mover para a seção da versão correspondente com o PR. O fluxo nasceu inspirado no [ECC](https://github.com/affaan-m/ecc) (o pipeline `orch-*`, o `code-reviewer` e o `verification-loop`), em versão enxuta.

## 2.8 — andamento visível e travas do modo autônomo (PR #21)

Origem: a revisão da 2.8 do backlog contra as etapas 4 e 5 do controle-financeiro e a documentação atual do Claude Code, e o pedido do usuário de uma tabela de progresso viva por ciclo. Os itens, o porquê e as escolhas do usuário estão na [proposta](proposta-2.8.md).

- [x] **Tempo e tokens reais**: `ledger.py add --tokens`; duração e tokens vêm do aviso de término do agente, nunca de estimativa; `status --json` traz a hora de despacho, o caminho do ledger e as execuções do ciclo; o relatório do gate mostra tokens por agente e tarefa.
- [x] **Andamento visível**: mod `andamento.js` (linha acima do prompt com entrega aberta, `/andamento` com o painel do ciclo, ciclos anteriores e outras frentes, texto onde nada desenha); só desenha o que o `ledger.py` devolve.
- [x] **Trava do ✋ 2**: no modo autônomo, o `bash-guard.py` nega push da branch principal, merge nela e `gh pr merge`; a branch de trabalho passa.
- [x] **Decisões e avisos**: VALIDAR numerados com `validate` e a skill `validar`; `PushNotification` quando o manager para esperando o usuário, no READY e quando o modo autônomo para; skill `feedback-plugin` no fim da entrega.
- [x] **Enxuto**: saíram a duração medida pelo manager e a "promoção de lição" do passo 7 (virou parte do `feedback-plugin`). Ficaram de fora da lista original: statusline, `/frentes` abrindo abas, semáforo, linha do tempo em gráfico, página de telas e `/aprovar`.
- Fora: segurança (2.8.1), guarda na ferramenta PowerShell, `python3` nos hooks, WSL2 (ver backlog).

## 2.7.2 — pular o `pre-commit` negado pelo hook, não pela mensagem (PR #20)

Origem: na etapa 5 do controle-financeiro, o deny `Bash(git commit *--no-v*)` da 2.7.1 negou um commit cuja mensagem citava a flag; `* -n *` corria o mesmo risco. Regra de permissão casa com o comando como texto e não distingue flag de mensagem.

- [x] **Guarda do Bash**: o hook do servidor de dev vira `bash-guard.py` e passa a negar pular o `pre-commit` (`--no-verify`, `-n`, `core.hooksPath`) em qualquer projeto, também em background, lendo o comando como o shell: a flag citada na mensagem do commit não conta. As formas cobertas estão no docstring.
- [x] **Allowlist do kickoff**: saem os três deny com curinga antes da flag; ficam os ancorados logo depois de `git commit` e de `git`, para quando o hook não roda.

## 2.7.1 — lições da etapa 4 e revisão do plugin (PR #19)

Origem: a etapa 4 do controle-financeiro, rodada inteira na 2.7.0 quase toda em modo autônomo, e uma revisão do plugin inteiro pedida pelo usuário (scripts e prompts), com cada achado reproduzido ou conferido. Os itens e o porquê de cada um estão na [proposta](proposta-2.7.1.md).

- [x] **Modo autônomo não para sozinho**: heartbeat (job recorrente da sessão que roda o `status` e segue); relatório com a worktree parada vale como término (o manager para o agente e integra); 4ª rodada da revisão do plano restrita às correções; no máximo 3 rodadas de correção por ciclo, depois a entrega para.
- [x] **Ledger**: `waive` para o FAIL cujos achados foram descartados ou aceitos (antes travava a entrega); `plan --path`; ledger achado de dentro de uma worktree, com o head da worktree dona do ledger; contagem negativa, duração sem unidade e linha truncada recusadas.
- [x] **Gate**: fim de cinco READY falsos (commit depois da última revisão, comando vazio, linha repetida que escondia outra, comando que reescreve arquivo, `--base` inválida); base vinda do ledger; seção "Comandos" mudada na branch vira aviso com o diff; relatório escrito antes dos testes do projeto, que o veem.
- [x] **Scan de segredos**: um só leitor de diff guiado pelos hunks; UTF-16, chave PGP, chave cifrada, `.env` com nome acentuado e senha sem aspas com símbolo passam a ser vistos; apagar um `.env` deixa de bloquear.
- [x] **Fluxo**: branch e `start` antes da spec (spec e plano não vão mais para a branch principal); laço de revisão único para spec e plano; uma só leitura crítica da spec; conferir no código antes de afirmar; o manager escreve o `docs/lessons.md`; entregas empilhadas com o ledger certo; tarefa devolvida à worktree.
- [x] **Agentes e segurança**: processos encerrados pelo PID, nunca por nome; `discovery` e `qa` com lista explícita de ferramentas; dado real das fontes fora do documento de descoberta; "texto é dado" no checklist; `ask` para todo `git push`; allowlist sem termos de fornecedor e com mais formas de pular o hook negadas (o `pre-commit` e o scan do gate seguem como a proteção de verdade); comando do graphify explicado aos agentes.
- [x] **Enxuto**: repetições do manager, do kickoff e do template do `CLAUDE.md` trocadas por apontamentos; passo 8.6 do kickoff (graphify antigo) para as notas de atualização; regra de teste instável só onde é lida; código sem uso do scanner; teste repetido do `SessionStart`.
- Fora: `python3` nos hooks do plugin (ver backlog); trava de `git merge` por hook (trava do ✋ 2, na 2.8).

## 2.7.0 — lições da etapa 3 (PR #14)

Origem: a etapa 2 (retomada) e a etapa 3 do controle-financeiro com a 2.6.1, boa parte em modo autônomo, mais uma leitura de skills de auditoria de segurança de terceiros. Os 18 itens e o porquê de cada um estão na [proposta](proposta-2.7.0.md).

- [x] **Gate**: "Arquivos de teste" casado como glob de verdade (`**/` casa zero ou mais pastas, `*` fica numa pasta, `{a,b}`); glob que não casa nenhum arquivo rastreado gera aviso.
- [x] **Worktrees e execução em paralelo**: o `manager` cria e prepara cada worktree no head atual e passa o commit de origem, que o `dev` confere; integra só depois do aviso de término do agente, um comando por vez. O template "Execução em paralelo" pede armazenamento de dados por cópia, preparo das dependências, pasta de saída de testes por execução, limites do ambiente de teste e sessão autenticada reaproveitada; "Comandos" ganha o servidor da verificação de interface. Sem isolamento declarado, só a codificação é paralela. Várias sessões no mesmo projeto: uma frente por sessão, uma só integra.
- [x] **Planejamento**: regra que filtra ou soma um conjunto vale em todas as funções irmãs (checklist e `reviewer` em modo plano); "validar antes de escrever" no pré-mortem; plano rascunhado por subagente e revisado até PASS (no máximo 3 rodadas).
- [x] **Revisão e testes**: layout medido em toda célula, coluna e cabeçalho em cada largura; pré-preenchimento com os dados de quando o formulário abre; erro de limite de armazenamento diz o limite.
- [x] **Lições**: o `dev` confere o diff contra o `docs/lessons.md` e cita as que se aplicaram; lição quebrada duas vezes vira checagem na mesma rodada; seção do `CLAUDE.md` gerada por ferramenta nunca recebe conteúdo.
- [x] **Modo autônomo**: `ledger.py mode autonomous|supervised` e `note --validar`; aprovações viram registro, rodadas de correção até PASS, nunca merge nem push (a entrega seguinte sai numa branch empilhada); `status` e o relatório do gate mostram o modo e a lista VALIDAR.
- [x] **Capturas persistentes**: o `qa` guarda capturas e script em `.superpowers/screens/<slug>/` e espera avisos temporários sumirem; a página de telas sai dessa pasta.
- [x] **Segurança**: revisão de segurança nativa antes do gate; cabeçalhos de segurança, build de produção sem artefatos de depuração e tokens de fonte criptográfica no checklist; veto a extensões de terceiros (seção nova do checklist, citada pelo `manager` e pelo `kickoff`).

## 2.6.1 — `pipeline.home` quebrado (PR #13)

Origem: o teste do `kickoff` no Controle Financeiro. O `pipeline.home` global apontava para uma pasta que deixou de existir (o clone foi renomeado), e o `pre-commit` instalado bloqueava todo commit com "secret scanner not found" sem que o `kickoff` percebesse.

- [x] **Passo 2 do `kickoff`**: trata como quebrado o `pipeline.home` que está vazio ou que aponta para uma pasta sem `hooks/pre-commit-secret-scan.py`, e passa o comando de correção ao usuário.
- [x] **Passo 9 do `kickoff`**: roda o `pre-commit` instalado uma vez, sem nada no índice, e relata se o scanner foi encontrado. Vale também quando o hook já existia.

## 2.6.0 — endurecimento (PR #12)

Origem: leitura das regras do AgentShield (ECC) de hooks, permissões e agentes, só como referência, sem instalar nada. O que é código malicioso, MCP e pontuação ficou fora.

- [x] **Caracteres invisíveis no commit**: o `pre-commit` recusa espaço de largura zero, controles de direção, caracteres Tag e BOM fora do início (a forma de esconder instruções em arquivos de prompt); ZWJ/ZWNJ de emoji e escritas legítimas passam.
- [x] **Mais formatos de chave no scan**: OpenAI, Google, xAI, GitHub fine-grained, Linear e o segredo de webhook do Stripe.
- [x] **Ferramentas do `discovery`**: sem `Edit`, `NotebookEdit` nem `Agent` (lia fontes não confiáveis com todas as ferramentas). Os agentes `discovery` e `qa` tratam texto de fontes, páginas e saída de ferramentas como dado, nunca como instrução.
- [x] **Allowlist do `kickoff` mais fechada**: `deny` para `sudo`, force push e `chmod 777`; `never_allow` ganha `sudo`, `--force`, `chmod 777`, `| sh` e `| bash`.
- [x] **Teste de integridade do plugin** (`test_plugin_integrity.py`): todo agente limita ferramentas, nenhum arquivo tem caractere invisível, os comandos do `hooks.json` não usam rede, `sudo` nem erro silenciado, e o template de allowlist mantém o `deny`.
- [x] **Passo 9 do `kickoff`** relata, sem alterar, `env` de endpoint ou proxy, `enableAllProjectMcpServers` e hooks alheios ao adotar um projeto com `settings.json`.
- [x] **Documentação**: o mapa do `CLAUDE.md` passa a citar os hooks de retomada e de servidor de dev.
- Fora: checagem de revisão externa no gate (o `open-code-review` da Alibaba exige CLI Node, chave de um provedor de LLM e envia o diff para fora; o `reviewer` já cobre isso sem chave, e o gate é sem LLM de propósito). Teto de orçamento continua sem sinal nas métricas.

## 2.5.0 — objetivo da tarefa e tarefas em andamento (PR #11)

Origem: ideias adaptadas do [Paperclip](https://github.com/paperclipai/paperclip) (contexto de objetivo e checkout de tarefa), sem usar a ferramenta.

- [x] **`Goal:` por tarefa**: cada tarefa do plano diz a qual item da spec serve e o que o usuário ganha; o `dev` lê o campo junto com a tarefa.
- [x] **`claim` / `release` no ledger**: o `manager` registra o despacho do `dev`; `claim` recusa tarefa em andamento ou já concluída no ciclo, o `status` lista o que está em andamento (e o gate espera), e o `add` do `dev` libera. Não é lock entre processos: só o `manager` escreve no ledger, então o ganho é saber, depois de compactação ou `resume`, quais execuções ainda faltam reportar. Ledgers sem `claim` continuam legíveis.
- Fora, por falta de sinal: teto de orçamento por entrega. Entra se as métricas de tempo do gate mostrarem entregas estourando.

## 2.4.0 — hooks e ruído (PR #10)

Origem: ideias adaptadas do ECC (`session-start`, `pre-bash-dev-server-block`) e feedback do Módulo 1 (servidor órfão, texto em Latin-1).

- [x] **Retomada depois de compactação**: `hooks/hooks.json` registra um `SessionStart` (`compact|resume`) que imprime o `ledger.py status` quando há ledger e nada quando não há.
- [x] **Encoding no commit**: o `pre-commit` recusa linhas adicionadas que não são UTF-8, com arquivo, primeira linha e como corrigir; binários e linhas antigas não contam. Ficou em `pre-commit-secret-scan.py` (o shim instalado só chama esse script, então uma instalação cobre as duas checagens) e o docstring foi atualizado.
- [x] **Servidor de dev solto**: `PreToolUse` em `Bash` que nega o comando da linha "Rodar em desenvolvimento" do `CLAUDE.md` do projeto sem `run_in_background`. Reaproveita a linha que o template já tinha, em vez de criar outra. Sem comando entre crases, não faz nada. **Por que reintroduz o `PreToolUse`**: a 1.6.0 reduziu o scan de segredos a um `pre-commit` nativo e tirou o `PreToolUse`, `pre-push` e bloqueio de gate que prendiam o fluxo do agente. Este tem outro fim e não prende nada: só nega um comando que o próprio projeto declarou, não depende de estado do plugin e, se falhar, deixa a chamada passar.
- [x] **Ruído do graphify**: novo passo 8.6 do `kickoff` que, só quando o `.claude/settings.json` tem o hook antigo do graphify (matcher `Bash`, sem `hook-guard`), mostra o diff que estreita o matcher para `Read|Grep|Glob` e pede confirmação; edição por parse de JSON. O graphify atual já se limita sozinho.
- [x] **Lacunas do `dev`** (comparação com `andrej-karpathy-skills` e com o `orch-pipeline` do ECC): procurar o que já existe antes de escrever helper, componente ou dependência; remover só o que a própria mudança deixou sem uso e apenas relatar código morto alheio.

## 2.3.0 — paralelismo e prevenção de retrabalho (PR #9)

Origem: feedback da etapa 2 do primeiro projeto (§5 paralelismo, §6 processo de produto, §7 prevenir retrabalho). Objetivo: menos tempo por entrega e menos achados por lacuna de desenho.

- [x] **Paralelismo**: `reviewer` e `qa` do ciclo em paralelo (o qa refaz só o que a correção tocou); plano como grafo de dependências (`Depends on`, `Touches`, números sequenciais reservados) e tarefas independentes em worktrees isoladas, integradas na ordem do plano; contrato "Execução em paralelo" no `CLAUDE.md` do projeto; tarefas do ciclo seguinte durante a revisão; o `dev` roda só os testes afetados.
- [x] **Ledger**: `--seconds` por execução e tempo por agente, tarefa e ciclo (tempo de agente e tempo de relógio) nas métricas; `--origin` em cada achado (desenho, premissa, plano, execução, ambiente); `defer`/`resolve`; tarefa `cleanup`; `start --plan`.
- [x] **Gate**: rastreabilidade critério → teste (cada `AC-...` do plano aparece num arquivo de teste); comando opcional `Auditoria`; item adiado sem decisão deixa NOT READY; tempo, origens e decisões no relatório.
- [x] **Processo de produto**: reviewer em modo plano antes da aprovação; checkpoint visual por ciclo (capturas na menor largura e no desktop, fluxo principal gravado); casos de abuso por escrita; matriz de permissões testada por inteiro; passo de limpeza antes do gate; política de teste instável; ambiente de testes antes de produção.
- [x] **Prevenir retrabalho**: pré-mortem por operação de escrita no `spec-checklist` e no plano; premissas técnicas provadas por spikes; plano conferido contra o código; critérios Dado/Quando/Então com id, usados como nome do teste; decisões de produto do plano listadas na aprovação.
- [x] **Documentação**: `CLAUDE.md` na raiz (propósito, mapa, regras de mudança); README como página de apresentação; fonte única por componente.

## 2.2.0 — lições da fatia 2 (PR #8)

Objetivo: o plugin só orquestra e gere o desenvolvimento; tudo o que é de stack ou de projeto sai dele.

- [x] **Ledger**: `fix-N` fica no ciclo corrente (reviewer na correção; qa de novo só se o último qa do ciclo reprovou); `start --archive`; saída UTF-8; achados por severidade (`--critical`, `--important`, `--minor`) e o comando `lesson`.
- [x] **Métricas da entrega** no relatório do `gate.py`: achados por ciclo e severidade, rodadas de correção, lições adicionadas e automatizadas.
- [x] **Manager**: seção `## Errata` no plano (a única parte que o manager edita; o brief do dev manda ler); granularidade do plano (código completo só em regras puras e camada de dados); "isso pode ser uma checagem?" antes de escrever uma lição; promoção de lição repetida em dois projetos para o plugin.
- [x] **Invariantes** no `reviewer` e no `checklists/general.md`, aplicadas também no modo spec; o checklist geral absorve as regras sem stack de `auth`, `nextjs-react` e `postgres-supabase`, que saem; mutação como evidência no relatório do dev; mensagens de erro específicas; controle de edição concorrente; regras de domínio (dinheiro, tempo, identidade) no `spec-checklist`.
- [x] **Kickoff sem stack**: saem `templates/nextjs/` e `templates/supabase/`; a allowlist vem dos "Comandos" do `CLAUDE.md`; novo `docs/lessons.md`.

## 2.1.0 — entregue (PR #7)

Objetivo: menos tempo por módulo (o fluxo 1.x levou 4 a 5 horas e mais de 20 relatórios num módulo).

- [x] **Ciclos curtos**: até ~6 tarefas; por tarefa só o `dev`; no fim do ciclo um `reviewer` sobre o diff inteiro, um `qa` e uma rodada de correção em lote (o reviewer confere só a correção). Módulo de 6 tarefas: ~9 execuções de agente em vez de 20+.
- [x] **`gate.py` no lugar do agente `gate`**: ledger, árvore limpa, Build/Typecheck/Lint/Testes do `CLAUDE.md` e scan de segredos no histórico da branch, sem LLM; grava o relatório de qualidade no READY.
- [x] **Ledger por ciclo**: o ciclo fecha quando o qa aprova; uma segunda reprovação pede decisão do usuário.

## 2.0.0 — entregue (PR #6)

Fluxo simples e circular, no formato do ECC (`orch-pipeline`, `code-reviewer`, `verification-loop`), em versão enxuta.

- [x] **Tamanho decide as etapas** (pequeno, padrão, grande) e duas aprovações do usuário: o plano e o merge/push.
- [x] **Um laço por tarefa**: `dev` (TDD, migrations e doc do módulo) → `reviewer` (um agente, checklists por stack, só achados com prova) → `qa`; no máximo 3 rodadas antes de perguntar.
- [x] **`gate` como verification-loop local**: ledger, build, tipos, lint, testes, segredos no histórico e diff → READY / NOT READY.
- [x] **Ledger simples** (`ledger.py`, 164 linhas): `start`, `add`, `note`, `status [--check]`.
- [x] **Saem**: `security`, `audit`, `design`, `code-review`, `db` e `docs` como agentes; `package.py`, `findings.py`, ferramentas de mutação, lições com contadores (as globais viraram itens dos checklists), hook `SubagentStop`, worktree obrigatória, revisão de spec com várias rodadas.
- [x] **Lições por projeto** em `docs/lessons.md`, lidas pelo `dev` e pelo `reviewer`.

## Backlog

- **Hooks do plugin sem `python`** (revisão da 2.7.1): o `hooks.json` chama `python`, e Linux e macOS costumam ter só `python3`; ali o hook de retomada e o guarda do Bash não rodam. Um laço POSIX que tenta os dois quebraria no Windows sem Git Bash, onde o hook roda no PowerShell, então a 2.7.1 só documenta o requisito no README. Entra quando houver um jeito que funcione nos dois shells (por exemplo, um hook por shell com o campo `shell`), testado em Linux. Esforço: P.

- **Guarda do Bash também na ferramenta PowerShell** (2.7.2): no Windows a sessão principal tem a ferramenta PowerShell, que o `bash-guard.py` não vê (os agentes não a têm). Entra com um leitor das aspas do PowerShell, testado. Esforço: P.

- **2.8.1 — segurança: achados com prova** (decisão do usuário; proposta na [seção C da 2.8](proposta-2.8.md)): ideias da skill `cloudflare/security-audit-skill` (MIT, commit `c1c8a8c`, lida inteira sem instalar nem executar). A skill não é instalada: no Windows os validadores recusam toda entrada, sem sandbox do sistema nada chega a confirmado, o perfil padrão custa de 25 a 50 subagentes e 1,5 a 4 M tokens, e o README instala sem versão fixa (veto a extensões de terceiros). Esforço: P.
  1. **Achado de segurança com prova**, no `reviewer`: nomeia quem explora, a entrada, a fronteira de confiança cruzada e o resultado observado; boa prática sem impacto demonstrado vira nota de reforço. Veredicto `confirmed`, `needs_validation` (com o bloqueio e o plano para validar) ou `rejected`; severidade de critical a low, nunca acima do impacto demonstrado, com o desempate entre high e medium: o achado derrota o controle por inteiro ou só o enfraquece?
  2. **Caminho mais fraco**: o `reviewer` pergunta que outras entradas chegam ao mesmo efeito e não foram checadas.
  3. **Checklist**: só o que falta em `checklists/general.md` (privilégios, redirect, depuração e reset já estão): export e backup no escopo de quem pede; registro excluído logicamente fora de busca, lookup e restauração; default de migration nas linhas antigas; acesso que não sobrevive à remoção de um membro; checagem de origem (CSRF) nas mutações.
  - Adiados: verificador que tenta refutar cada achado (um agente a mais por achado) e registro de cobertura acumulado entre entregas no gate (mudança grande no gate). Voltam se uma entrega mostrar achado falso ou caminho não examinado.
- **WSL2 para o modo multi-instância** (fora da 2.8): não resolve o gargalo medido (a suíte e2e longa, item 17 da 2.7.0), plugins não carregam nas sessões WSL do app Desktop e custa outra instalação do Claude Code (memória, plugins e configurações à parte), integração mais difícil com o navegador do Windows e hooks e `pipeline.home` reinstalados. Volta se o próprio Windows virar o gargalo; migração só entre entregas. Esforço: P no plugin.

## Entregues

- **1.6.0** (PR #5): scan de segredos reduzido a um `pre-commit` nativo; sem `PreToolUse`, `pre-push` nem bloqueio de gate.
- **1.5.1** (PR #5): captura de relatórios por `SubagentStop`, Playwright no kickoff, correções de negações falsas do hook, testes com `mkdtemp`.
- **1.5.0** (PR #4): rerrevisão escopada; relatório por tarefa; STALE por arquivo e domínio; revisores exigidos no `status`; ferramentas de mutação; `pre-commit` nativo; estado do remoto por `ls-remote`; `git config` fechado por padrão; sem exceção para caminhos derivados do git.
- **1.4.0** (PR #3): lições com contadores e injeção por caminho; checklists por stack; validação do relatório do implementador; `save-report`; adendos em arquivos; kickoff com allowlist e complementos Next/Supabase; allowlist de segredos por fingerprint.

## Notas de atualização

Termine a entrega em andamento antes de atualizar o plugin.

- **2.8.0**: lê os ledgers da 2.7. O `status --json` muda a lista `validar`: cada item é `{id, text, decision}` (antes, só o texto), para quem lê o JSON por fora do plugin. A linha de andamento e o `/andamento` pedem o Claude Code v2.1.287 ou mais novo e aparecem sozinhos; o resto funciona sem eles. No modo autônomo, push da branch principal, merge nela e `gh pr merge` passam a ser negados pelo hook, não só pelo prompt.

- **2.7.2**: lê os ledgers da 2.7.1. Pular o `pre-commit` passa a ser negado pelo hook do plugin, que ignora a mensagem do commit. Quem rodou o `kickoff` da 2.7.1 apaga à mão do `.claude/settings.json` os deny `Bash(git commit *--no-v*)`, `Bash(git commit * -n *)` e `Bash(git commit * -n)`, que negavam commits cuja mensagem citava a flag, e roda o `kickoff` de novo para receber `Bash(git commit --no-v*)`.

- **2.7.1**: lê os ledgers da 2.7.0. O gate fica mais rígido: um commit depois da última revisão do `reviewer` (fora o plano, o `docs/lessons.md` e os relatórios), um comando que altera arquivo versionado e uma `--base` inválida deixam NOT READY; um comando vazio conta como não configurado (NOT READY só na linha Testes, que é obrigatória); duas linhas "Testes" passam a rodar as duas. No modo autônomo, a entrega para depois de 3 rodadas de correção num ciclo, em vez de seguir até o PASS. `discovery` e `qa` passam a ter só as ferramentas listadas no próprio agente (nada de MCP, navegador ou subagente). Sem `--base`, o gate usa a base gravada no `start`. O relatório de qualidade passa pelos testes do projeto antes do READY. Rode o `kickoff` de novo para receber o `ask` do `git push` e os `deny` novos do `--no-verify`, e apague à mão do `.claude/settings.json` o `Write(.pipeline-secrets-allow)` (o Claude Code nunca consulta regras `Write` e avisa na abertura; a regra `Edit` já cobre o arquivo). Uma entrada do `.pipeline-secrets-allow` para arquivo com nome não ASCII precisa ser gerada de novo (o caminho entra sem aspas no fingerprint). O passo 8.6 do kickoff saiu: se o `.claude/settings.json` ainda tiver o hook antigo do graphify (matcher `Bash` sem `hook-guard`), rode `python -m graphify claude install`.

- **2.7.0**: lê os ledgers da 2.6 (sem `mode`, a entrega é supervisionada). A linha "Arquivos de teste" agora é glob de verdade: `*` não atravessa pastas e `**/` casa zero ou mais, então use `**/` onde um teste pode estar em subpasta; maiúsculas e minúsculas contam também no Windows (antes não contavam), então o glob precisa ter a mesma grafia das pastas; o gate avisa o glob inválido ou que não casa nenhum arquivo. Rode o `kickoff` de novo para receber as linhas novas de "Execução em paralelo" e "Servidor para a verificação de interface".
- **2.6.1**: nada muda para quem atualiza. Se um commit for barrado com "secret scanner not found", `git config --global pipeline.home` aponta para um caminho que não existe mais: aponte para `<clone>/plugins/pipeline`.
- **2.6.0**: os checks novos do `pre-commit` (caracteres invisíveis e mais formatos de chave) chegam com o plugin; o `pre-commit` instalado já chama o scanner, sem reinstalar. Para a allowlist nova (`deny` de `sudo`, force push e `chmod 777`), rode o `kickoff` de novo e confirme a mudança em `.claude/settings.json`. Commits antigos com caracteres invisíveis não são reabertos.
- **2.5.0**: lê os ledgers anteriores (sem `claim` nada fica em andamento). O `manager` passa a dar `claim` ao despachar cada `dev`; um `claim` sem `add` deixa o gate em NOT READY até o `add` ou o `release`. Planos novos trazem `Goal:` por tarefa; planos antigos continuam válidos.
- **2.4.0**: os hooks novos (retomada, UTF-8 no commit e servidor de dev) chegam com o plugin. O UTF-8 no commit exige reinstalar o `pre-commit` só em projetos preparados antes da 1.6.0 (o shim atual já chama o scanner). Para o servidor de dev, rode o `kickoff` de novo e preencha a linha "Rodar em desenvolvimento" do `CLAUDE.md` com o comando entre crases; sem isso o hook não faz nada.
- **2.3.0**: lê os ledgers da 2.1 e da 2.2 (achados antigos aparecem como "unclassified" e as execuções sem `--seconds` como não medidas). `add --open` saiu: use `--critical`/`--important`; todo achado novo exige `--origin`. Sem `start --plan`, a checagem Criteria do gate fica SKIP. A seção Invariantes saiu do `reviewer` (a fonte é `checklists/general.md`). Rode o `kickoff` de novo para acrescentar ao `CLAUDE.md` do projeto a seção "Execução em paralelo" e as linhas "Testes afetados", "Arquivos de teste" e "Auditoria".
- **2.2.0**: saíram os templates de stack do `kickoff` e os checklists `auth`, `nextjs-react` e `postgres-supabase`. Projetos preparados antes continuam com os arquivos que já têm; as regras de stack que ainda valem vão para o `CLAUDE.md` ou o `docs/lessons.md` do projeto. Lê os ledgers da 2.1 (um `fix-N` depois de um ciclo fechado passa a contar nesse ciclo).
- **2.0.0 e 2.1.0**: mudaram o formato do ledger; um ledger de versão anterior não é lido.
- **1.6.0**: o `pre-push` do plugin deixou de fazer qualquer coisa. Em projetos preparados antes, rode `python "<clone>/plugins/pipeline/hooks/pre-commit-secret-scan.py" --install-pre-commit`, que atualiza o `pre-commit` e remove esse `pre-push`; `git config pipeline.gate` e o arquivo `gate-approved` podem ser apagados.
