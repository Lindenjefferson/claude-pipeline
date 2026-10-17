# Proposta 2.8: andamento visível e travas do modo autônomo

**Status: aprovada pelo usuário, com três escolhas:** a trava do item 4 nega só o que chega na branch principal (push para ela, `gh pr merge` e merge com ela em checkout; o push da branch de trabalho segue o `ask`); a seção C vai para uma 2.8.1; a faixa do item 2 fica sempre visível com entrega aberta.

Origem: a revisão da 2.8 do backlog contra as etapas 4 e 5 do controle-financeiro e a documentação atual do Claude Code (decisão do usuário), mais o pedido de uma tabela de progresso viva por ciclo ("sempre fico perguntando como tá o andamento"). Saíram da lista original: a statusline (plugin não instala `statusLine`; a faixa mostra o modo e os VALIDAR); o `/frentes` abrindo abas (só no Windows e frágil: título da aba, variáveis `CLAUDE_CODE_*` herdadas, confiança da pasta nova, mensagem lida só quando a sessão é usada; não há API oficial; as frentes ficam listadas no painel); o semáforo do recurso compartilhado (o manager já serializa e registra nas notas); a linha do tempo em gráfico (ficam tempo e tokens por execução); a página de telas; o `/aprovar` (a trava não depende dele); o aviso de decisão pendente separado (entrou nos avisos). O WSL2 saiu da 2.8: não resolve o gargalo medido, a suíte e2e longa.

Cada item diz o problema, a mudança e onde ela entra. **Teste primeiro** marca o que muda `ledger.py`, `gate.py` ou um hook: o teste novo falha antes da mudança. **Decisão** marca o que tem mais de um caminho razoável.

## A. Andamento visível

1. **Tempo e tokens reais no ledger** (teste primeiro). Nas etapas 4 e 5, quatro durações foram estimadas antes do aviso de término e corrigidas depois por nota (o fix-1 da etapa 5 ficou com 1500 s; o real foi 211 s). O aviso de término do agente já traz a duração e os tokens.
   - `ledger.py add` ganha `--tokens N`. `status` mostra tokens por agente e por tarefa ao lado do tempo, e o `--json` passa a trazer a hora do despacho de cada tarefa em andamento (hoje só no texto da pendência), para o tempo decorrido.
   - O manager grava `--seconds` e `--tokens` com os números do aviso de término. Quando integra antes do aviso (relatório entregue e worktree parada), grava sem os dois: nunca estima.
   - O relatório do gate mostra tempo e tokens por agente.
   - Ledgers antigos seguem legíveis (sem `tokens`, a coluna fica vazia).
   - Onde: `ledger.py`, `gate.py`, `manager/SKILL.md`.

2. **Tabela de progresso viva** (mod do Claude Code, a partir da v2.1.287). Um módulo JavaScript dentro do próprio plugin (`hooks/andamento.js`, listado em `modules` no `hooks.json`, ao lado dos hooks de hoje).
   - **Faixa acima do prompt**, só quando o ledger da worktree tem uma entrega aberta: `pipeline · etapa-5 · cycle 2 · autonomous · ▶ T2.1 14m · reviewer FAIL · qa — · VALIDAR 1 · next: <a primeira pendência>` (os textos do plugin ficam em inglês, como os do `ledger.py`), com o modo autônomo marcado.
   - **`/andamento`**, que abre um painel na hora, mesmo com o manager no meio de um trabalho: a tabela do ciclo atual (tarefa, estado, tempo, tokens), reviewer e qa (veredito, achados, tempo), pendências, VALIDAR e adiados abertos; uma linha por ciclo anterior; e as outras frentes (cada worktree com ledger próprio, uma linha cada). Onde o mod não desenha (`claude -p`, sessão WSL do app), `/andamento` responde em texto.
   - **Dados**: o mod roda `ledger.py status --json` e só desenha; nenhuma regra no JavaScript. Para não rodar o Python à toa, confere a data do arquivo do ledger a cada 5 s e só relê quando ela muda; o tempo decorrido corre no próprio mod.
   - **Testes**: `claude plugin test plugins/pipeline` (testes `.test.ts` que simulam o `ledger.py`), somado à seção "Testar e validar" do `CLAUDE.md`.
   - **Protótipo primeiro**: testado numa sessão de teste com uma cópia de ledger real, sem tocar no controle-financeiro, antes de virar release.
   - **Risco**: a API de mods é nova e muda a cada versão do Claude Code, e o plugin passa a ter JavaScript além do Python. O README diz a versão mínima testada.
   - Onde: `hooks/andamento.js`, `hooks/hooks.json`, `ledger.py` (item 1), README, `CLAUDE.md`.

3. **Avisos.** Com várias frentes abertas, o usuário não vê quando uma sessão para esperando por ele. O manager chama `PushNotification` (uma linha, o que fazer primeiro) quando para esperando o usuário (pergunta de produto, ✋ 1, ✋ 2), no READY e quando o modo autônomo para a entrega. A ferramenta não dispara com o usuário no terminal. Sem código. Onde: `manager/SKILL.md`.

## B. Travas e decisões do modo autônomo

4. **Trava do ✋ 2** (teste primeiro). A regra "nunca merge nem push no modo autônomo" hoje depende só do prompt. O `bash-guard.py` lê o modo no ledger da worktree e, no modo autônomo, nega o que chega na branch principal: `git push` para ela (também sem argumentos com ela em checkout), `gh pr merge` e `git merge` com ela em checkout, com o motivo e o que fazer (registrar em VALIDAR, o usuário aprova na volta). No modo supervisionado nada muda: o `ask` do `git push` segue.
   - Onde: `hooks/bash-guard.py`.

5. **`/validar`** (teste primeiro no ledger). A lista VALIDAR cresce no modo autônomo (a etapa 5 aprovou o plano com 13 itens) e é confirmada de memória no chat.
   - Cada item VALIDAR ganha um id pela ordem (V1, V2...), também nos ledgers antigos. `ledger.py validate --id V2 --decision <texto>` grava a decisão; `status` lista só os pendentes, e o relatório do gate mostra cada um com a decisão.
   - Skill `validar` (`/pipeline:validar`): percorre os pendentes um a um com uma pergunta (confirmar, mudar ou deixar para depois) e grava cada resposta. "Mudar" vira tarefa ou correção da entrega, conduzida pelo manager.
   - VALIDAR pendente não trava o gate, como hoje; no ✋ 2 o manager oferece o `/validar` antes do merge.
   - Onde: `ledger.py`, `gate.py`, `skills/validar/SKILL.md`, `manager/SKILL.md`.

6. **`/feedback-plugin`.** O pedido da 2.7.1 foi montado à mão a partir de notas soltas.
   - Skill `feedback-plugin`: no fim da entrega, lê o `status --json`, as notas, os adiados e as lições novas, e escreve `.superpowers/pedido-plugin.md` com métricas (tempo, tokens, rodadas de correção, origem dos achados), atritos e lições candidatas a regra geral, cada uma com a evidência. Deixa de fora o que é de stack ou do projeto, como manda o `CLAUDE.md` do plugin. Não envia nada: o usuário leva o arquivo à sessão do plugin.
   - Onde: `skills/feedback-plugin/SKILL.md`; o manager cita a skill no fim da entrega com uma linha.

## C. Segurança: achados com prova

Vai para a 2.8.1 (decisão do usuário), para a 2.8 ficar focada no andamento e nas travas e ser testada numa etapa real.

7. **Achado de segurança com prova** no `reviewer`: nomeia quem explora, a entrada, a fronteira de confiança cruzada e o resultado observado; boa prática sem impacto demonstrado vira nota de reforço. Veredicto `confirmed`, `needs_validation` (com o bloqueio e o plano para validar) ou `rejected`; severidade de critical a low, nunca acima do impacto demonstrado; desempate entre high e medium: o achado derrota o controle por inteiro ou só o enfraquece? Onde: `agents/reviewer.md`.
8. **Caminho mais fraco**: o `reviewer` pergunta que outras entradas chegam ao mesmo efeito e não foram checadas. Uma linha. Onde: `agents/reviewer.md`.
9. **Checklist**: as cinco lacunas de `checklists/general.md` (export e backup no escopo de quem pede; registro excluído logicamente fora de busca, lookup e restauração; default de migration nas linhas antigas; acesso que não sobrevive à remoção de um membro; checagem de origem nas mutações). Onde: `checklists/general.md`.

## D. Rodada de design de tela (pedido do usuário, depois da aprovação)

Pedido do usuário a partir de uma sessão de design do controle-financeiro: o Dashboard redesenhado numa página de comparação antes do código encaixou melhor os cartões na tela grande. Entra na 2.8 (decisão do usuário), só como prompt e checklist, sem um terceiro ponto de parada.

10. **Rodada de design** antes do plano, quando o pedido cria ou redesenha uma tela: o manager (a sessão principal, que tem a ferramenta Skill; o `dev` não tem) carrega a `frontend-design` (e uma skill de visualização de dados, se houver, para gráficos e dashboards) e produz uma página de comparação com cada tela na menor largura e no desktop, em todos os temas, com dados de exemplo. Tokens de cor (claro e escuro, contraste medido), regras de layout por largura e o mock viram insumo do plano; a página é aprovada no ✋ 1 com o plano (no modo autônomo, `note --validar`). Pedido que cria ou redesenha tela é pelo menos padrão. Onde: `manager/SKILL.md`, README (plugin opcional).
11. **Revisão contra o mock**: o `reviewer` confere a tela contra o mock e os tokens aprovados. Onde: `agents/reviewer.md`.
12. **Cores medidas**: no checklist, cor só por token, contraste AA calculado em todos os temas, paleta categórica conferida para daltonismo por cálculo e cores de significado reservadas, com a marca e as categóricas fora das matizes delas. Onde: `checklists/general.md`.

## E. Enxuto

- A regra do manager que manda medir a duração sai, substituída pelos números do aviso de término (item 1).
- Ao tocar `manager/SKILL.md`, os trechos que só repetem o que `ledger.py status` já mostra viram apontamento.
- Fica de fora desta proposta (está no backlog): o guarda do Bash também na ferramenta PowerShell e o `python3` nos hooks.

## Ordem de implementação

1, 4 e 5 primeiro (ledger e hook, com teste primeiro), depois o protótipo do mod (2), por fim 3 e 6 (prompts). Cada um com a suíte inteira verde antes do commit e uma revisão independente no fim, como na 2.7.2.
