# Proposta 2.7.1: lições da etapa 4 e revisão do plugin

**Status: aprovada pelo usuário, com quatro ajustes:** o item 36 só deixa de negar comando inofensivo (heredoc e texto entre aspas), sem os prefixos novos; o item 33 fica estreito (só chaves de senha ou segredo, valor com caractere especial, testes de falso positivo antes); o item 46 não junta os arquivos de teste; o item 28 segue o caminho (a), aviso. Os itens 21 (curinga no `deny`) e 35 (`python3` nos hooks) pedem cuidado extra na implementação e na revisão.

**Na implementação, conferido na documentação do Claude Code:** o item 35 não mudou o `hooks.json`. No Windows o hook roda no Git Bash, ou no PowerShell quando não há Git Bash, e o laço POSIX quebraria ali; o README passou a pedir `python` no PATH e o item foi para o backlog. O item 21 foi além do previsto: regras `Write(...)` de permissão nunca são consultadas (só as `Edit(...)`, que também cobrem redirecionamento do shell), então `Write(.pipeline-secrets-allow)` saiu do template; o curinga no meio do padrão é aceito, então os `deny` do `--no-verify` cobrem a flag em qualquer posição. Implementação na branch `fix/2.7.1-licoes-etapa-4`, com PR e aprovação de merge.

Origem: o pedido da etapa 4 do controle-financeiro, rodada inteira na 2.7.0 quase toda em modo autônomo (itens 1 a 10), e uma revisão do plugin inteiro pedida pelo usuário (itens 11 em diante), feita por dois revisores: um nos scripts, outro nos prompts e documentos. Todo achado da revisão foi conferido: os dos scripts com um script que reproduz o erro, os dos prompts no texto. Os 284 testes atuais passam. Toda regra é geral, sem stack.

Cada item diz o problema, a mudança e onde ela entra. **Teste primeiro** marca o que muda `ledger.py`, `gate.py` ou um hook: o teste novo falha antes da mudança. **Decisão** marca o que tem mais de um caminho razoável.

## A. Modo autônomo não para sozinho (pedido)

1. **Heartbeat e relatório valendo como término.** O relatório do `dev` ou do `qa` chega e o aviso de término demora (ou nunca vem, com um processo de fundo esquecido); o manager fica ocioso.
   - Ao ligar `mode autonomous`, o manager cria um job recorrente da sessão (`CronCreate`, a cada 15 min, fora de :00 e :30) com o prompt "heartbeat do pipeline: rode `ledger.py status` e siga a entrega". Apaga com `CronDelete` ao voltar para `supervised` e quando nada mais anda sem o usuário (gate READY, ou entrega parada com `note --validar`). Numa sessão retomada em modo autônomo sem o job (`CronList`), recria. O job só dispara com a sessão ociosa, vive só nessa sessão e expira em 7 dias.
   - Integrar (passo 4.1): depois do aviso de término, **ou** quando o relatório chegou e a worktree está parada (`git status` só com ignorados, nada escutando na porta da cópia): pare o agente com `TaskStop` e integre. Vale também para um `qa` que reportou e ficou pendurado.
   - Onde: `manager/SKILL.md`.
2. **Rodada extra na revisão do plano.** No modo autônomo, se a 3ª rodada deixa achados abertos, o manager corrige e roda uma 4ª rodada restrita a conferir só essas correções; PASS segue (achados e correções em `note --validar`), FAIL para a entrega como hoje. Entra no laço único do item 9. Onde: `manager/SKILL.md`.

## B. Agentes e processos (pedido)

3. e 4. **Nenhum processo deixado para trás, e só o próprio é encerrado.** Antes de reportar, o agente encerra todo servidor e shell de fundo que abriu, cada um pelo PID (o processo que escuta na porta que ele subiu, ou o id do shell de fundo), nunca por nome de programa ou imagem: outras cópias e os serviços do usuário rodam o mesmo programa. O relatório de `dev` e `qa` ganha `Processes: none left running`. O brief de tarefa paralela repete a regra. Onde: `agents/dev.md`, `agents/qa.md`, `manager/SKILL.md`.
5. **Comando do graphify.** A mensagem errada vem do hook do próprio graphify (`hook-guard`), que manda rodar `graphify query`; sem esse binário no PATH, o agente cai no grep. O plugin não muda o texto do graphify. O parágrafo "Knowledge graph" dos agentes passa a dizer: "um hook que pede `graphify query` quer dizer este comando; sem `graphify` no PATH, use `python -m graphify`". O `qa`, que não tem o parágrafo, ganha. Onde: `agents/dev.md`, `reviewer.md`, `qa.md`.

## C. Ledger e gate (pedido)

6. **Ledger achado de dentro de uma worktree** (teste primeiro). Sem `--ledger`, o padrão deixa de ser relativo ao cwd: o ledger da raiz da worktree atual, se existir; senão, e se o comando não for `start`, o da worktree principal (`git rev-parse --git-common-dir`). Cobre cwd em subpasta, `claim` de dentro da worktree de uma tarefa e as frentes de "várias sessões", que seguem com o ledger próprio. `--ledger` explícito continua igual. Onde: `ledger.py`.
7. **Relatório do gate testado antes do READY** (teste primeiro). Com `--report`, o gate escreve o relatório depois de "Clean tree" e antes de Build, Typecheck, Lint, Testes e Auditoria, para os comandos do projeto o verem; no READY regrava só os resultados das checagens (palavras do gate) e faz o stage; no NOT READY apaga. A seção Ledger do manager ganha: notas, adiados, decisões e lições vão para o relatório commitado e seguem as regras do projeto para arquivo versionado (nada de caminho de material local nem dado real). Onde: `gate.py`, `manager/SKILL.md`.

## D. Spec (pedido)

8. **Uma só leitura crítica da spec.** Quando a spec vai para o `reviewer` em modo spec, o brief do brainstorming manda pular o builder check, e o modo spec do reviewer lista também as perguntas que um construtor ainda teria de fazer ao usuário (viram decisões de produto). Sem modo spec, o builder check fica. Onde: `manager/SKILL.md` passo 1, `agents/reviewer.md`.
9. **Laço de revisão definido uma vez.** Spec e plano: o manager aplica as correções e roda o reviewer de novo sobre elas até PASS, no máximo 3 rodadas (mais a do item 2 no autônomo). O passo 1 aponta para esse laço. Onde: `manager/SKILL.md`.
10. **Conferir no código antes de afirmar.** Regra: antes de dizer ao usuário que o código já faz ou já tem algo, achar no código e dar o caminho. "Checked against the code" do plano passa a ser aplicação dela. Onde: `manager/SKILL.md` (Rules).

## E. Revisão: fluxo do manager

11. **Achado descartado ou aceito trava a entrega** (teste primeiro). Quando o manager descarta um achado errado, ou o usuário aceita um achado aberto, nenhum comando do ledger registra isso: o último FAIL fica, `status --check` e o gate ficam NOT READY para sempre. Novo `ledger.py waive --agent reviewer|qa --reason '<texto>'`, aceito só quando a última execução daquele agente no ciclo é FAIL: conta como a aprovação dele naquele ponto, aparece nas notas (e na lista VALIDAR no autônomo) e no relatório. O brief da re-revisão passa ao reviewer os achados descartados, para ele não os reabrir. Onde: `ledger.py`, `manager/SKILL.md`.
12. **Rodadas de correção sem limite no autônomo.** "Fix rounds go on until PASS": um achado errado ou duas correções que se desfazem rodam a noite inteira. Mesmo teto do plano: no máximo 3 rodadas de correção por ciclo; depois, a entrega para com os achados abertos em `note --validar` (o heartbeat é apagado). Onde: `ledger.py` (o ledger pede a decisão também no autônomo depois do teto; teste primeiro), `manager/SKILL.md`.
13. **Nada é registrado antes do passo 3, e spec e plano são commitados na branch principal.** `mode autonomous`, as `note --validar` do plano e a parada da revisão do plano acontecem antes do `start`, que só roda no passo 3: o ledger recusa ("no delivery started") ou grava na entrega anterior, que o `start --archive` leva embora. E "Commit the spec" e "Commit the plan" vêm antes de criar a branch, então os dois caem na principal (no autônomo, sem aprovação nenhuma), fora do scan de segredos do gate. Mudança: a branch e o `start` vêm logo depois de dimensionar o trabalho, em todos os tamanhos; spec e plano são commitados nela; novo `ledger.py plan --path <plano>` grava o plano aprovado (hoje só o `start` aceita `--plan`). Onde: `manager/SKILL.md` (passos renumerados), `ledger.py` (teste primeiro).
14. **O manager não pode escrever `docs/lessons.md`** (Rules: só spec, plano e Errata), mas o passo 4.6 manda escrever a lição lá; mandar ao `dev` com outro id abre um ciclo novo. A lista de documentos que o manager edita ganha `docs/lessons.md` e o commit do relatório de qualidade. Onde: `manager/SKILL.md`.
15. **Entregas empilhadas no autônomo leem o ledger errado.** Na volta do usuário, o ✋ 2 da entrega 1 e uma correção pedida nela gravam no ledger da entrega 2 e o gate lê o estado dela. Mudança: para a entrega 1, trocar para a branch dela e passar `--ledger .superpowers/ledger-<slug>.jsonl` ao `ledger.py` e ao `gate.py`; depois da correção, rebasear a branch empilhada. Com o item 22, a `--base` deixa de precisar ser passada. Onde: `manager/SKILL.md`.
16. **Tarefa devolvida à worktree esbarra na checagem do `dev`.** "Conflito ou teste vermelho volta ao dev da tarefa", mas o dev novo vê os commits da execução anterior e para com NEEDS_CONTEXT, e `claim` recusa a tarefa já DONE. Mudança: ao devolver, o commit de origem do brief é o head atual da worktree; depois do `add`, é um `fix-N` na branch da entrega. Onde: `manager/SKILL.md`.
17. **Pequenos desencontros do fluxo.** O passo 4.2 dá ao `reviewer` uma pasta de saída de testes que ele nunca usa (só o `qa` ganha); o `qa` pega o slug "de `ledger.py status`" sem saber o caminho do script (passa a vir no brief); o passo 7 termina com `superpowers:finishing-a-development-branch` depois do merge e push, e essa skill pergunta de novo e pode apagar a branch (passa a dizer: usar para executar o merge ou o push que o usuário escolheu). Onde: `manager/SKILL.md`, `agents/qa.md`.

## F. Revisão: segurança dos prompts e da allowlist

18. **`discovery` e `qa` herdam todas as ferramentas da sessão.** Os dois só listam o que é proibido, então recebem WebFetch e todo servidor MCP (escrita no Bitbucket e no Jira, o Chrome logado do usuário) justamente enquanto leem o conteúdo menos confiável; o `qa` pode até disparar subagentes. Mudança: lista explícita do que é permitido. `discovery`: Read, Grep, Glob, Write, Bash, WebFetch, Skill. `qa`: Read, Grep, Glob, Bash. O teste de integridade passa a exigir `tools:` em todo agente. Onde: `agents/discovery.md`, `agents/qa.md`, `test_plugin_integrity.py`.
19. **Dado real das fontes vai para arquivo versionado.** O `discovery` grava `docs/discovery/<slug>-findings.md`, commitado, citando valores de célula. Uma linha: citar células, fórmulas e estrutura; nunca copiar dado pessoal, credencial ou valor real de uma fonte: usar um marcador e dizer que é marcador. Onde: `agents/discovery.md`.
20. **O ✋ 2 depende só do prompt.** A allowlist nega o force push, mas não o `git push` comum. Mudança: `"ask": ["Bash(git push:*)"]` no template, que o passo 7 do kickoff já junta: todo push passa pelo usuário, nos dois modos. O `git merge` não dá para travar assim (o manager integra worktrees com ele); fica o item 10 do backlog 2.8. Onde: `kickoff/templates/settings.allowlist.json`, notas de atualização.
21. **Allowlist com termos de fornecedor e regras fáceis de contornar.** `never_allow` traz comandos de um CLI de banco específico e o nome de um provedor de hospedagem (fere "independente de stack"): ficam só os termos gerais, mais uma linha do kickoff ("e todo comando do projeto que escreve num ambiente remoto, listado no `CLAUDE.md` dele"). Os `deny` de `--no-verify` só casam o prefixo exato (`git commit -m x --no-verify` passa): usar curinga no meio, **se** a sintaxe de permissões do Claude Code aceitar (confiro antes de escrever). O texto do kickoff diz que `deny` de arquivo não cobre escrita pelo Bash. Onde: `kickoff/templates/settings.allowlist.json`, `kickoff/SKILL.md`.
22. **"Texto é dado" só vale para `discovery` e `qa`.** O `dev` e o `reviewer` consultam um grafo que inclui páginas da web e documentos de descoberta. A linha entra em `checklists/general.md`, que os dois leem; `discovery` e `qa`, que não leem o checklist, ficam com a linha própria. Onde: `checklists/general.md`, agentes.

## G. Revisão: `gate.py` (todos com teste primeiro)

Cinco formas reproduzidas de o gate dizer READY quando não deveria, o pior resultado possível dele.

23. **O código revisado não é conferido contra o HEAD.** Um commit depois do último reviewer e qa, sem nada no ledger, passa. O ledger já grava o `head` de cada execução e ninguém lê. Mudança: NOT READY quando há commits depois do head da última execução do reviewer ou do qa que tocam algo além do plano, do `docs/lessons.md` e do relatório de qualidade.
24. **Comando de teste vazio passa.** `` - Testes: ` ` `` ou `--cmd Testes=` rodam `""`, que sai com 0. Comando vazio passa a valer como não configurado (Testes é obrigatório, então NOT READY).
25. **Duas linhas com o mesmo rótulo: só a última roda.** `- Testes: <unidade>` e `- Testes (e2e): <e2e>` viram um só Testes, e a unidade nunca roda. Mudança: rodar cada linha, com o nome da linha inteira (`Testes (e2e)`).
26. **Comando que reescreve arquivo passa.** Um Lint que corrige sozinho altera arquivos versionados depois de "Clean tree": o que foi checado não é o que está commitado. Mudança: conferir a árvore de novo depois dos comandos (fora o relatório do item 7).
27. **`--base` inválida cai em silêncio na base padrão**, e um segredo fora desse intervalo passa. Mudança: `--base` inválida é erro; sem `--base`, usar a `base` que o ledger gravou no `start` antes de adivinhar. Isso também resolve o repositório sem remoto e com branch principal de outro nome, e as entregas empilhadas (item 15).
28. **A branch muda os comandos que o gate roda** (**decisão**). Um commit troca a linha Testes por `exit 0` e o gate dá READY. Caminhos:
    - (a) **aviso**: o gate detecta que a seção "Comandos" mudou em `<base>..HEAD`, mostra a diferença na saída e no relatório, e o manager a leva ao ✋ 2; o reviewer trata como achado toda mudança numa linha de "Comandos" ou num script por trás dela (também cobre a allowlist, que deixa esses comandos rodarem sem pergunta). Recomendado.
    - (b) **trava**: NOT READY enquanto a seção mudou, até o usuário rodar o gate com uma confirmação explícita. Mais seguro, mas toda entrega que muda um comando de propósito para no gate, inclusive no autônomo.

## H. Revisão: scan de segredos e hooks (teste primeiro)

29. **`.env` com nome acentuado passa no hook e no gate.** O git escreve nomes não ASCII entre aspas e com escapes, e a regex não casa (`.env.produção` passa). Mudança: listas de nomes com `-z` (separadas por NUL); no gate também, que hoje separa nomes por espaço.
30. **Arquivo UTF-16 pula o scan inteiro.** O `>` do PowerShell 5.1 grava UTF-16 por padrão; o git trata como binário e nenhum padrão casa (uma chave da AWS passou). Mudança: decodificar como UTF-16 o conteúdo que começa com BOM UTF-16 antes de escanear.
31. **Chave PGP e chave privada cifrada não são vistas.** O padrão não casa `BEGIN PGP PRIVATE KEY BLOCK` nem `BEGIN ENCRYPTED PRIVATE KEY`. Mudança: `-----BEGIN [A-Z ]*PRIVATE KEY( BLOCK)?-----`.
32. **Apagar um `.env` versionado é bloqueado**, e a única saída é `--no-verify`, que o kickoff proíbe. Mudança: o hook e o gate ignoram arquivos removidos (`--diff-filter=d`).
33. **Senha sem aspas não é vista.** `POSTGRES_PASSWORD: Pr0d#Db!2024x` passa; com aspas é pego. Mudança: em chaves de senha/segredo, o valor sem aspas até o espaço passa pelo mesmo teste do valor entre aspas (12+ caracteres, 3 classes), com testes de falso positivo (`${VAR}`, marcadores, `changeme`).
34. **Linha adicionada que começa com `++ ` é lida como cabeçalho** e não é escaneada. Mudança: um só leitor de diff, o que conta as linhas do hunk (hoje há dois). Remove o duplicado.
35. **Os hooks do plugin chamam só `python`.** Em macOS e Debian/Ubuntu padrão só existe `python3`, e o guard do servidor de dev e a retomada depois de compactação nunca rodam. O shim do `pre-commit` já tenta os dois. Mudança: o mesmo laço `python`/`python3` do shim no `hooks.json`, conferido contra as regras do teste de integridade (sem erro silenciado). Só dá para testar aqui no Windows; o Linux fica coberto pelo teste da string do comando.
36. **O hook do servidor de dev nega comando inofensivo e deixa passar o real.** Nega um heredoc que escreve um README com o comando e um `git commit -m "... (npm run dev)"`; deixa passar `cd web & ...`, `nohup ...`, `env PORT=3 ...`. Mudança: ignorar corpo de heredoc e texto entre aspas; reconhecer `&` simples e os prefixos `nohup`, `env`, `exec`.

## I. Revisão: `ledger.py` (teste primeiro)

A contagem de ciclos foi conferida em todos os caminhos (fix-N, cleanup, FAIL tardio, claims em paralelo) e está certa.

37. **Contagem negativa aceita.** `--verdict PASS --critical 1 --important -1` fecha o ciclo com um Critical registrado. Mudança: só inteiros não negativos.
38. **`--seconds 1h30` vira 1h30s.** Mudança: com `h` ou `m`, o último número exige unidade; senão é erro.
39. **Uma linha JSON truncada derruba todo comando** com traceback. Mudança: erro claro com o número da linha (sem pular a linha, que poderia esconder um FAIL).

## J. Simplificações (enxugar ao tocar)

40. **`manager/SKILL.md`**: o parágrafo "The cycle" repete os passos 4.1 a 4.6 (vira uma linha); "Assumptions", a frase de casos de abuso e "Invariants and layout" do passo 2 repetem o `spec-checklist` e o `checklists/general.md` (viram um apontamento cada); a última frase do 4.4 repete o passo 7; "You never deploy" repete as Rules.
41. **Regra de teste instável dita 5 vezes**: fica no `checklists/general.md`, nas Rules do manager e no `qa` (que não lê o checklist); sai do `dev` e do `reviewer`.
42. **`kickoff/SKILL.md`**: os passos 1 e 4 recontam o docstring do hook e do gate (ficam o comando e o que perguntar); o passo 10 reconta o fluxo pela terceira vez (vira "resumir o 'Fluxo de entrega' do `CLAUDE.md` do projeto e perguntar se começa"); o passo 8.6 (migração de instalações antigas do graphify) sai e vira uma linha nas notas de atualização.
43. **Template `CLAUDE.md` do projeto**: "Fluxo de entrega" copia o fluxo do manager e já está errado ("se ainda sobrar algo, o manager pergunta" é falso no autônomo). Fica com as aprovações, a regra da branch e onde está o ledger; o resto aponta para a skill.
44. **`checklists/general.md`**: o título "Invariantes" vira "Invariants" (prompt em inglês; o `reviewer` cita nos dois lugares); as duas regras de ambiente de teste e a de layout saem de Invariants para Tests e Web e UI, e a de layout encurta; o item de formulário fica com a regra e um teste.
45. **`pre-commit-secret-scan.py`**: parâmetros `env` e `data` que ninguém passa, um `if` que faz o mesmo nos dois lados, um dicionário cujos valores nunca são lidos, um conjunto que guarda o caminho junto de uma marca que já o inclui.
46. **Testes**: `test_patterns.py` e `test_secret_rules.py` usam o mesmo arnês e viram um arquivo; a checagem do `SessionStart` repetida em `test_dev_server_block.py` sai (a de `test_session_start.py` é mais rígida).

## Fora desta versão

- **Reconferir scripts por trás de "Comandos"** quando mudam: coberto pelo item 28 em vez de uma checagem nova no kickoff.
- **Trava de `git merge` por hook**: segue no backlog 2.8 (item 10).

## Notas de atualização (rascunho)

- Lê os ledgers da 2.7.0. `ledger.py` rodado de dentro de uma worktree acha o ledger da árvore principal; o gate usa a `base` do ledger quando não recebe `--base`.
- O relatório de qualidade passa pelos testes do projeto antes do READY.
- O gate fica mais rígido: comando vazio, linhas repetidas, árvore alterada pelos comandos e commits depois da última revisão viram NOT READY.
- Rode o `kickoff` de novo para receber o `ask` do `git push` e a allowlist sem termos de fornecedor.
- `discovery` e `qa` passam a ter só as ferramentas listadas.
