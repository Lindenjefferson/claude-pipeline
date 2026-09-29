# claude-pipeline

Plugin do [Claude Code](https://code.claude.com) que conduz entregas de software (módulos, features e correções) por uma equipe de agentes especializados, com revisão independente, registro de progresso e um gate final antes de qualquer código sair da máquina.

O plugin é habilitado **por projeto**, nunca globalmente: onde não está ativo, nenhum agente, skill ou hook dele é carregado.

## Como funciona

```
discovery → brainstorming → revisão do spec → plano → dev / db → docs + revisores → gate
```

1. **`pipeline:kickoff`** prepara o projeto: `CLAUDE.md`, convenção de documentação em `docs/`, `.gitignore`, grafo de conhecimento opcional, os hooks `pre-commit` e `pre-push` de segredos do git e a trava do gate (`git config pipeline.gate true`).
2. **`pipeline:manager`** conduz cada entrega: planeja, despacha os agentes, encaminha cada problema ao dono do arquivo e registra tudo em um ledger.
3. Na **revisão do spec**, antes do plano, os revisores leem o spec aprovado pelo brainstorming (ainda sem código) e ele é corrigido até todos aprovarem.
4. Os **revisores** analisam cada tarefa em paralelo, cada um no seu domínio.
5. O **`gate`** confere se todos os revisores exigidos aprovaram os commits atuais, varre o histórico em busca de segredos e, ao aprovar, grava um relatório de qualidade com nota.

## Componentes

| Componente | Função |
|---|---|
| `pipeline:kickoff` | Prepara um projeto novo ou existente para o fluxo. |
| `pipeline:manager` | Orquestra uma entrega e mantém o ledger (`ledger.py`) e os pacotes de revisão (`package.py`). |
| `pipeline:discovery` | Extrai e estrutura fatos das fontes brutas antes do design. |
| `pipeline:dev` | Implementa uma tarefa do plano. |
| `pipeline:db` | Schema, migrations e políticas de acesso; também revisa essas mudanças. |
| `pipeline:docs` | Mantém a documentação viva em `docs/`. |
| `pipeline:code-review` | Corretude, duplicação, testes e complexidade. |
| `pipeline:security` | Autenticação, autorização, segredos e validação de entrada. |
| `pipeline:audit` | Rastreabilidade de escritas sensíveis e erros silenciados. |
| `pipeline:design` | Consistência de UI e acessibilidade. |
| `pipeline:qa` | Roda os testes e valida os critérios de aceite de ponta a ponta. |
| `pipeline:gate` | Verificação final e relatório de qualidade. |
| Hook de segredos | Duas camadas. Os hooks nativos do git (`pre-commit` e `pre-push`, instalados pelo `kickoff`) são a trava de verdade: o git os roda em todo commit e push, venha de onde vier, e eles varrem o índice que está sendo commitado e os commits que saem da máquina. O hook `PreToolUse` do Claude é a primeira linha: lê o texto dos comandos, bloqueia `git commit` e `git push` do Claude que contenham segredos, exige a aprovação do `gate` para o push quando o gate está ligado e nega o que desligaria os hooks nativos (`--no-verify`, `core.hooksPath`, mudanças em `pipeline.*`). Entende aliases do git. |

### Revisão do spec

Um erro de design (uma política de acesso no escopo errado, um convite que atravessa a fronteira entre contas, uma escrita financeira sem rastro) pego no spec custa uma edição; pego depois do código, custa uma migration nova e retrabalho. Por isso, depois que o brainstorming aprova o spec e antes do `writing-plans`, o `manager` despacha em paralelo os revisores do domínio do spec, em **modo spec** (somente leitura, entrada é o documento, não um diff):

| O spec toca | Revisor |
|---|---|
| Auth, permissões, sessões, segredos, RLS | `security` |
| Schema, migrations, RLS, queries | `db` (modo revisor) |
| Escrita de dados sensíveis ou financeiros | `audit` |
| Telas e fluxos de UI | `design` |
| Contratos e interfaces complexos | `code-review` (opcional) |

- **Obrigatória** quando o spec toca auth, permissões, RLS, schema/migrations, segredos ou dados sensíveis/financeiros; nos demais casos o `manager` pergunta ao usuário. Quando não roda, o motivo fica registrado como nota `ruling` da tarefa `spec`.
- Cada achado aponta a seção do spec, o cenário concreto e a correção proposta no design. Achados Critical/Important são corrigidos no spec pela sessão principal (decisões de produto vão ao usuário) e os mesmos revisores rodam de novo até aprovar, com no máximo 5 rodadas; na nova rodada cada um lê só o diff do spec desde a sua revisão anterior e o próprio relatório anterior (`security` e `db` releem o spec inteiro). Minors são aplicados ou registrados como `deferred`.
- Evidência: relatórios em `.superpowers/reports/spec.md` (uma seção por agente e rodada) e entradas no ledger com a tarefa `spec` e o caminho do spec revisado. Esses achados ficam fora das notas de qualidade (foram pegos antes do código) e aparecem à parte no relatório do `gate`.
- O `gate` bloqueia a entrega que toca esses domínios sem revisão de spec aprovada nem nota explicando a ausência, e pede nova revisão se o spec mudou depois dela.

O spec responde, antes da revisão, às seções de [`skills/manager/templates/spec-checklist.md`](plugins/pipeline/skills/manager/templates/spec-checklist.md): trilha de auditoria das escritas sensíveis, estados de UI, concorrência e invariantes, auth (oráculos de conta, pré-cadastro, confirmar ≠ logar, sessões), privilégios padrão, tabela de códigos de erro e plano de testes com alvos de mutação. Seção sem resposta no domínio de um revisor é achado.

### Ledger

Cada entrega tem um ledger em `.superpowers/ledger.jsonl`, escrito só pelo `ledger.py`. Ele registra, por tarefa e agente, o intervalo de commits revisado, o veredito, os problemas encontrados e em aberto e as decisões tomadas. Linhas inválidas são recusadas na entrada, e `status --head HEAD` aponta revisões que ficaram para trás: um commit posterior que altera um arquivo do intervalo revisado sem que uma entrada PASS posterior do mesmo agente (em qualquer tarefa) o cubra, ou que nenhum revisor de outra tarefa cobriu, deixa a revisão `STALE`, e o `status` lista cada commit desses com os arquivos que ele tocou (para a tarefa `spec`, só quando o próprio spec mudou). Para revisores de domínio (todos menos `code-review` e `qa`), só contam os arquivos que as mesmas regras do `MISSING` abaixo exigiriam daquele agente (o `design` só por caminhos de UI): um `package.json` alterado depois de uma revisão de `design` não a deixa `STALE`, um `supabase/config.toml` depois de uma do `db` deixa. Para revisores que não são o `docs`, mudanças em `docs/**` não contam como tocar o intervalo. Um commit de outra tarefa que não toca nenhum arquivo da revisão e já foi revisado lá não a invalida. O `status` também lista, como aviso (`MISSING`, `missing_reviewers` no `--json`), os revisores que os caminhos de cada commit exigem e que nenhuma entrada PASS cobre: os `paths`/`agents` do frontmatter dos checklists, mais regras fixas (SQL e migrations pedem `db` e `security`; env, `.env*`, permissões e navegação pedem `security`; arquivos `actions` e funções SQL pedem `audit`; `.tsx` e `components/**` pedem `design`; qualquer código pede `code-review` e `qa`). Avisa também as tarefas com Minors abertos sem nota `deferred`/`parked`. Um relatório que revisa várias tarefas de uma vez entra com `append --task T1,T2`: uma linha por tarefa com o mesmo `report_group`, e `totals`/`open_totals` (a pontuação do `gate`) contam esse relatório uma vez só, desde que as linhas do grupo concordem em `report`, `report_sha256`, veredito e contagens; se discordarem, cada linha conta e o `status` lista o grupo como inconsistente em `invalid`. Cada tarefa da lista passa pelas mesmas validações de nome e de spec.

- `save-report` grava o relatório do agente, sem transcrição à mão, como uma seção nova de `.superpowers/reports/<tarefa>.md` (um arquivo por tarefa, só cresce; cabeçalho com agente, rodada e intervalo `--from..--head`) e imprime `<caminho>#<âncora>` (`<agente>-r<N>`) para o `append`. A rodada é automática, contada por tarefa, agente e papel, como no `append`. O `db` exige `--role implementer|reviewer`, e a revisão dele fica na âncora `db-review-r<N>`. O arquivo `<tarefa>.md.sums` guarda o hash do arquivo até o fim de cada seção: o `save-report` se recusa a anexar a um arquivo editado à mão, e `ledger.py verify-reports` (que o `gate` roda) confere que nenhuma seção mudou, que toda âncora citada existe e que os bytes de cada relatório batem com o `report_sha256` que o `append` gravou na entrada do ledger; `show-report <caminho>#<âncora>` imprime uma seção. Esses hashes detectam adulteração, não a impedem: quem escreve em `.superpowers/` pode reescrever relatório, `.sums` e ledger juntos, e por isso o `gate` continua lendo os relatórios e conferindo vereditos e contagens. Vários revisores podem gravar na mesma tarefa ao mesmo tempo: cada `save-report` segura o arquivo `<tarefa>.md.lock` (espera até uns 10 s e assume uma trava cujo processo morreu ou que tem mais de 30 s, movendo para o lado exatamente aquele arquivo de trava, para que dois `save-report` à espera não a assumam juntos; cada um só apaga a própria trava). Se um `save-report` for interrompido entre escrever a seção e registrá-la no `.sums`, sobram bytes não registrados no fim do arquivo: `save-report` e `verify-reports` recusam e indicam `ledger.py repair-reports --task <tarefa>`, que mostra esses bytes (e se são a seção interrompida) e só os corta com `--yes`; depois grave o relatório de novo. O `append` também confere que a âncora é do agente (e do papel, no `db`) da linha e que o cabeçalho da seção tem o mesmo `--from..--head`. Ledgers iniciados antes da 1.5.0 (ou com `start --layout per-file`) mantêm um arquivo por relatório, `<tarefa>-<agente>-r<N>.md`, e continuam válidos.
- Revisão depois de uma correção: `package.py review --fix-of <tarefa> --agent <agente>` lê no ledger a última revisão daquele agente na tarefa e monta o pacote com a linha `Scope:` e o relatório anterior. `fix-only` (só o diff da correção) quando todo arquivo que a correção toca, fora de `docs/**` (sempre isento), está citado nos achados abertos dos revisores da tarefa: a união dos achados do último relatório de cada revisor até o `head` anterior deste agente, o dele incluído, porque um mesmo brief de correção costuma responder a vários revisores; `full` (o intervalo inteiro da tarefa) quando toca outro arquivo, quando nenhum achado cita arquivo, quando um relatório não pode ser lido, e sempre para `security` e `db`. O revisor `fix-only` lê o diff inteiro da correção, inclusive o que responde a outros revisores. Os achados são as seções abertas por um título ou rótulo de severidade (`## Important`, `**Minor**`, `Findings:`) até o próximo título ou rótulo de outro tipo (`Notes:`, `Open questions:`, `Checked:`, `## Other domains`). Um caminho citado casa com um arquivo alterado quando é igual a ele ou um sufixo delimitado por `/`; um nome solto ou abreviado (`04_privilegios.sql`, `0002:226`) casa quando identifica um único arquivo da tarefa pelo começo do nome. Proporções (`4.5:1`, `16:9`), `e.g.`/`i.e.`, URLs e tokens sem letra não contam como caminho. O `append --scope fix` exige que o `--from` seja o `head` anterior daquele revisor, refaz essa mesma checagem dos arquivos citados e recusa `--scope fix` para `security` e `db`; o ledger encadeia as entradas: revisão completa seguida de revisões `fix` contíguas cobre a tarefa inteira. O `gate` continua revisando o branch todo.
- `--head`/`--from` aceitam qualquer ref (`HEAD`) e gravam o SHA.
- O `append` valida o relatório de `dev`, `db` e `docs`: recusa relatório sem linha `LEDGER`, curto demais (200 caracteres em `DONE`/`DONE_WITH_CONCERNS`; motivo de 40 nos demais vereditos) ou "placeholder", relatório de `dev`/`db` sem o SHA do commit ou em que nenhuma linha rotulada (`Commit:`, `SHA:`, `Head:` no começo da linha, com ou sem negrito ou marcador) traz um SHA em hexa (`<sha>`, "see git rev-parse", `HEAD`; o agente cola o SHA curto real de `git rev-parse --short HEAD`); mencionar `git rev-parse` em prosa, ou uma linha `Head: igual à r1` ao lado de um `Commit:` com SHA, passa, e arquivo citado que não está em `git diff FROM..HEAD` (`--allow-unlisted '<motivo>'` para exceções; o motivo é obrigatório e vira nota de decisão).

### Briefs, adendos e lições

- `package.py brief` aceita ids como `T1.2`, `3` e `A-1`, e anexa ao texto da tarefa os adendos de `.superpowers/briefs/<tarefa>.addenda/*.md` e `.superpowers/briefs/all.addenda/*.md`. O manager nunca edita um brief gerado, então reextrair não perde nada.
- **Lições**: regras atômicas (até 280 caracteres) que teriam evitado um achado. As globais ficam versionadas no plugin, em `plugins/pipeline/lessons/<stack>.jsonl` (`postgres-supabase`, `nextjs-react`, `auth`, `general`), e as da entrega em `.superpowers/lessons.jsonl`, escritas só por `ledger.py lesson add|mark|list|promote|sync`. O `brief` injeta até 6 lições (8000 caracteres) cujos `paths` casam com os arquivos da tarefa. Primeiro entram as de `priority` (opcional, nas lições centrais de RLS, `security definer`, `revoke`, argumentos NULL de RPC e, em auth, oráculo de existência de conta, tomada de conta pré-cadastrada e sessões após troca de senha), mas sem tirar a vaga de nenhuma stack que casou com a tarefa. Depois as vagas são preenchidas em rodízio por stack (`auth`, `nextjs-react`, `postgres-supabase`, `general`), a stack com menos vagas primeiro, para nenhuma stack ocupar todas. Dentro de cada stack a ordem é: `priority`, especificidade do glob que casa (quantos caracteres literais ele tem, então `**/*login*/**` pesa 5 e `app/**` pesa 3; um glob exato vence `**`), quantos arquivos casam, `held - 2*recurred` com bônus para as da entrega, e o id. Lições `general` sem `paths` só completam as vagas que sobrarem. As lições de UI e acessibilidade casam com `**/*.tsx` e `components/**`, as de Server Action com `**/actions.ts`, e as de guarda com `**/page.tsx`, `**/layout.tsx` e o `proxy.ts`; as sobre escrever testes pgTAP casam com `supabase/tests/**`; as sobre escrever migrations e funções, com `supabase/migrations/**`. Cada lição conta `injected`, `held` (preveniu) e `recurred` (reincidiu); `injected` conta uma vez por tarefa: os ids já injetados ficam em `<brief>.lessons`, e regerar o brief só conta as lições novas. Os contadores das lições globais ficam numa linha de override na entrega, e só vão para os arquivos globais com `lesson sync`, que pode ser repetido depois de uma interrupção sem somar duas vezes: o diário da sincronização fica do lado da entrega (`.superpowers/lessons.sync.json`, com o hash de cada arquivo global antes e depois), e os arquivos globais versionados recebem só os contadores. Se um arquivo global mudou entre a interrupção e a nova tentativa, o `sync` para e pede conferência manual. No fechamento, o manager mostra cada lição da entrega e só promove para o global as que o usuário aprovar, uma a uma, e só sincroniza os contadores se o usuário aprovar.

### Checklists por stack

`plugins/pipeline/checklists/{postgres-supabase,nextjs-react,auth}.md`, cada um com frontmatter `stack`, `paths` e `agents`. O `package.py review` lista no cabeçalho do pacote os checklists cujos `paths` casam com os arquivos alterados (lockfiles ficam fora do diff, com as linhas de nome, versão, `resolved` e `integrity` alteradas numa seção `## Dependency changes`), e cada revisor abre os que citam o seu papel. Item não atendido é achado como outro qualquer. O de auth (e as lições `auth`) casa também com nomes em português e fluxos de conta: `*convite*`, `*cadastro*`, `*senha*`, `*reset*`, além de `*invite*`, `*signup*`, `*login*`, `*password*` e `*session*`.

### Revisores e implementadores

- Revisores (`code-review`, `security`, `db` revisor, `audit`, `design`) passam por um *pre-report gate*: Critical/Important exigem prova (arquivo:linha e cenário concreto ou reprodução), zero achados é resultado válido, sem enchimento de estilo.
- O `code-review` sempre roda mutação independente em tarefas com migrations, funções SQL ou módulos de regra pura (NULL, fronteira `>=`/`>`, janela de tempo, filtro de escopo, auditoria em laço, checagem de permissão) e relata as sobreviventes.
- `dev` e `db` seguem RED primeiro (o teste rodou e falhou pelo motivo certo antes da correção), listam os arquivos a partir de `git show --stat`, gravam só UTF-8, sobem servidores só em background ou com `timeout`, e o `db` entrega a tabela mutação → teste que falhou.
- Verificação no navegador (`dev` e `qa`): script Playwright numa pasta temporária fora do projeto (`npm install playwright` lá, reaproveitando o Chromium do cache do Playwright ou instalando-o ali), que abre a página, age, verifica e sai; nunca um daemon ou servidor de depuração. O `next dev` nunca fica rodando: reaproveita-se o que já serve a pasta (o Next só aceita um por diretório) ou sobe-se um em background e para-se no fim. O Claude in Chrome pode não alcançar `localhost`.

### Ferramentas de mutação

Em `plugins/pipeline/tools/mutation/` (só Python da biblioteca padrão), usadas pelo `code-review` na mutação independente:

- **`pgmutate.py`**: mutação de funções SQL do Postgres/Supabase contra a suíte pgTAP. Recebe as funções (`--function schema.nome`) ou as descobre nas migrations alteradas de um intervalo (`--from <rev> --to <rev>`), lê a última definição de cada uma em `supabase/migrations` (ou `--sql-dir`) e gera mutantes de um catálogo fixo: guarda de NULL removida/negada, `>=`↔`>`, `<=`↔`<`, constantes de janela de tempo e de limite, filtro de escopo (tenant) e de papel removidos do `where`, `insert`/`perform` de auditoria removido, `raise` removido, `and`↔`or` em guardas e default de `coalesce` removido. Cada mutante roda com cada arquivo de teste em uma única transação enviada ao `psql -X -v ON_ERROR_STOP=1` (sem psqlrc): `begin; create or replace function ...; <teste sem o begin/rollback próprio>; rollback;`. O arquivo de teste é recusado quando tem qualquer outro controle de transação no nível de topo (`begin`, `start transaction`, `commit`, `end`, `abort`, `rollback` que não seja `rollback to`, `prepare transaction`, `commit`/`rollback prepared`) ou qualquer barra invertida fora de string, identificador entre aspas, comentário e corpo `$tag$`: o `psql` executa meta-comandos em qualquer ponto da linha (`select 1; \! cmd`, `\c`, `\g |cmd`, `\gexec`, `\lo_export`, `\setenv`...), então nenhum é aceito, nem `\set`. Uma impressão digital das funções antes e depois garante que o banco não mudou. Só roda em banco local: host localhost, 127.0.0.1, ::1, host.docker.internal ou nome de serviço docker sem ponto (nunca um nome só numérico ou `0x...`, que o resolvedor lê como IP); todas as variáveis `PG*` (PGHOST, PGSERVICE, PGSSL*...) e `PSQLRC` saem do ambiente do `psql`, então a senha vai na URL; com container, o `DOCKER_HOST` ou o endpoint do contexto docker atual (`DOCKER_CONTEXT`/`docker context use`) precisa ser local. Sem `--db-url`/`--container`, usa o `DB_URL` do `supabase status` ou o container `supabase_db_<project_id>`.
- **`tsmutate.py`**: mutação textual de um arquivo TS/JS (troca de comparadores, ±1 em números de comparações, `&&`↔`||`, negação de condição de `if`, inversão de retorno booleano). Por padrão não escreve no arquivo: cria um `git worktree` temporário (`tsmutate-wt-<pid>-*` na pasta temporária) a partir do HEAD, copia para ele a versão do arquivo na árvore de trabalho, liga o `node_modules` do projeto (junction `mklink /J` no Windows, symlink nos demais) e roda `--test-cmd` (por exemplo `npx vitest run lib/calculations`) com o diretório de trabalho dentro do worktree, restaurando a cópia a cada mutante, sem cópia de segurança na pasta temporária (o arquivo do projeto nunca é escrito). No fim remove o worktree (primeiro os links, sem segui-los) e roda `git worktree prune`; se o processo for morto à força (timeout da ferramenta Bash, `taskkill /F /T`), o projeto fica intacto e a próxima execução remove os worktrees de processos que não existem mais. Os caminhos em `--test-cmd` são relativos ao `--cwd`; os demais arquivos vêm do HEAD (a execução avisa quais alterações locais ficaram de fora); ferramentas que gravam cache em `node_modules` (vite, vitest) gravam no do projeto, pelo link. `--in-place` mantém o modo antigo, por opção explícita: escreve cada mutante no próprio arquivo e restaura em `finally` conferindo o sha256 (código 3 se não bate), recusa arquivo com alterações não commitadas salvo `--allow-dirty`, e uma morte forçada deixa o mutante no arquivo.

Ambas imprimem a tabela (id, função/arquivo, operador, linha, morto/sobrevivente, teste que matou) ou `--json`, listam os mutantes sem executar com `--list`, limitam a execução com `--max-mutants`, e saem com 0 mesmo com sobreviventes (1 com `--fail-on-survivors`, 2 em erro da ferramenta). Uma execução leva minutos: pela ferramenta Bash, use `timeout: 600000` ou `run_in_background`. Os detalhes estão em `--help`.

### Hooks nativos do git e trava do gate

O hook `PreToolUse` lê o texto do comando, e texto sempre tem uma forma nova de esconder o git (`g\it`, `eval`, um script). Por isso a trava fica onde o próprio git roda:

**Modelo de ameaça.** Os hooks deste plugin rodam na sua máquina. Eles param vazamentos acidentais e os atalhos de um agente que coopera; um agente deliberadamente adversário, que escreve scripts, chama interpretadores ou monta configuração do git, ainda consegue contornar um hook do lado do cliente. A última linha de defesa é a proteção do lado do servidor: **ative o push protection do secret scanning do GitHub** (ou o equivalente do seu provedor) em cada repositório. Mesmo assim, as travas baratas abaixo continuam valendo a pena.

- `python "<clone>/plugins/pipeline/hooks/pre-commit-secret-scan.py" --install-pre-commit --install-pre-push --enable-gate` (o `kickoff` roda isso, com a sua permissão).
- **`pre-commit`**: varre o índice que o git está commitando (`git diff --cached` no ambiente do hook, com o `GIT_INDEX_FILE` que o git define), com a allowlist lida desse índice. Índice relocado, `update-index`/`read-tree` ou qualquer outra forma de pôr algo no stage deixam de importar. Um `pre-commit` que já existia vira `pre-commit.pipeline-chained` e roda antes; se ele falhar, o commit para. Se já existir um `pre-commit.pipeline-chained`, a instalação recusa e não mexe em nada.
- **`pre-push`**: varre os commits que saem da máquina. O que o remoto já tem vem de `git ls-remote` na URL de push (timeout de 15 s), nunca só das refs `refs/remotes/*`, que qualquer comando local reescreve (`git fetch . main:refs/remotes/origin/main`, `git remote add loop . && git fetch loop`, cópia de arquivo em `.git/refs/remotes/`). Sai tudo o que é alcançável do commit enviado e não está em nenhuma ref do remoto. Se o `ls-remote` falhar, usa só as refs de rastreamento daquele remoto e, acima de 1000 commits a varrer, bloqueia dizendo que não sabe o estado do remoto. O hook `PreToolUse` calcula o push do mesmo jeito.
- **Reescrita de URL** (`url.*.insteadOf`/`pushInsteadOf`): o `ls-remote` usa o `insteadOf` e o push usa o `pushInsteadOf`, então uma reescrita dividida faz o `ls-remote` consultar um servidor falso que já "tem" os commits enquanto o push vai para o verdadeiro. O git passa ao `pre-push` a URL de push já reescrita; se um `insteadOf` ainda casa com ela (ou seja, o `ls-remote` consultaria outra URL que não a do push), o `pre-push` não confia no `ls-remote`: avisa no stderr qual reescrita encontrou e usa as refs de rastreamento daquele remoto, escaneando no máximo 1000 commits que elas não conhecem (acima disso bloqueia e pede um `git fetch`). Assim, um setup comum de "fetch por HTTPS, push por SSH" continua funcionando. O `ls-remote` roda o ssh do usuário (`GIT_SSH_COMMAND`, senão `core.sshCommand`, senão `ssh`) com `-o BatchMode=yes -o ConnectTimeout=10` e, no timeout, mata a árvore de processos inteira (`taskkill /T` no Windows, grupo de processos no POSIX). O `PreToolUse` faz a mesma comparação: calcula a URL do push (`pushInsteadOf`, senão `insteadOf`, sobre `remote.<nome>.url`; `insteadOf` sobre `pushurl`) e a que o `ls-remote` usaria (`insteadOf` sobre a URL do push); só quando elas diferem ele não confia no `ls-remote`, usa as refs de rastreamento daquele remoto e avisa no stderr qual reescrita encontrou. Uma reescrita comum, como `url."git@github.com:".insteadOf https://github.com/`, não muda nada: o push e o `ls-remote` vão para a mesma URL. Numa reescrita dividida, a base do push passa a ser as refs de rastreamento remoto, que só são tão confiáveis quanto a fonte de onde vieram no último fetch.
- O `pre-push` **só varre segredos**. O gate é um controle de processo aplicado no `PreToolUse` (aos pushes do Claude); um push que você faz no seu terminal é seu e não passa pelo gate.
- URLs com credenciais (`https://user:token@host`) aparecem nas mensagens sem a parte `user:token@`.
- Commits feitos por encanamento (`commit-tree`, `stash`, `rebase`, `cherry-pick`) não passam pelo `pre-commit`, mas passam pelo `pre-push` antes de sair da máquina.
- **Trava do gate**: o gate do push fica ligado quando `git config pipeline.gate` tem qualquer valor que não seja um booleano falso (`false`, `no`, `off`, `0`; um valor inválido conta como ligado) **ou** existe `docs/quality-reports/` na árvore de trabalho ou na árvore enviada. O `--enable-gate` grava a configuração, e o agente não consegue desligá-la apagando a pasta.
- O hook `PreToolUse` nega o que desligaria essas travas: `--no-verify` num comando git (também abreviado, como `--no-veri`), `no-verify` (maiúsculas ou minúsculas) dentro do código inline de um interpretador (`python -c`, `node -e`, `perl -e`, `ruby -e`, `php -r`, `bash -c`, `pwsh -Command`, `cmd /c`, ou um heredoc para um interpretador) ou depois de `git` num executor (`xargs`, `eval`, `find -exec`, `Invoke-Expression`); argumentos de um script (`python scripts/x.py --no-verify-ssl`, `node build.js --no-verify`) passam, e um arquivo de script está fora do alcance, `git commit -n` (também agrupado ou por alias), `-c core.hooksPath`/`include.*`, `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM` num add/commit/push, `git config` que grava (o git para de ler opções na chave e trata tudo o que vem depois dela como valor, até `--` e palavras com hífen: ler passa só sem nada depois da chave, com as flags de leitura antes dela, como `git config --show-origin --get core.hooksPath`, ou pelos subcomandos `get`/`list`; `git config core.hooksPath --show-origin` grava o valor `--show-origin` e é negado) `pipeline.*`, `core.hooksPath`, `include.*`, `url.*.insteadOf`/`pushInsteadOf` ou `remote.*.url`/`pushurl`/`fetch` (ou `git config --edit`), qualquer escrita em `.git/hooks/`, na pasta do `core.hooksPath` (como `.husky/`) ou em `.git/config` e `config.worktree` (`.git/config.worktree`, `.git/worktrees/*/config.worktree`; ler com `cat`/`grep` continua permitido) e `git remote add`/`set-url` com um caminho local (`.`, `../x`, `file://`). Os caminhos são normalizados antes (`./.git/./hooks`, `.git//hooks`, `.git/x/../hooks`), globs que podem casar com `.git/hooks/*` ou `.git/config` contam (`.gi?/hooks`, `.git/hook*`, `.git/*`), assim como variáveis: as definidas no próprio comando ou no ambiente são resolvidas e o caminho resultante é comparado com `.git/hooks` e a pasta do `core.hooksPath` (então `rm -rf $OUT/hooks` com `OUT=build` ou `cp $HOME/templates/hooks/useAuth.ts src/hooks/` passam: uma pasta `hooks/` comum de React não é protegida); só uma variável que não resolve (não definida, `$(...)`, crases) num `rm`/`mv`/`cp`/`tee`/redirecionamento conta quando o resto do caminho pode terminar numa pasta protegida (`rm $NAO_DEFINIDA/hooks/pre-push`, `d=.git; rm $d/hooks/pre-push`) ou quando depois dela não vem nada ou só um nome de hook (`rm -rf $(git rev-parse --git-path hooks)`, `rm $(git rev-parse --git-path hooks)/pre-push`; `rm -rf $(mktemp -d)/build` passa), um `cd`/`pushd`/`Set-Location` para dentro do diretório do git seguido de escrita no mesmo comando (`cd .git && rm -f hooks/*`) e um `find` com `-delete` ou `-exec` que grava cuja raiz inclui o `.git` (`find . -name pre-push -delete`), a menos que a expressão exclua o `.git` antes da ação, sem `-o`: um `-not -path` que casa com ele (`find . -not -path './.git/*' -name '*.tmp' -delete`), um `-prune` na frente (`find . -path ./.git -prune -o -name '*.tmp' -delete`) ou um `-name`/`-iname`/`-path` positivo que não casa com nenhum arquivo de hook (`pre-commit`, `pre-push`, `pre-commit.pipeline-chained`), com o `config` nem com as pastas acima deles (`.git`, `hooks`): `find . -name "*.log" -delete` e `find . -type d -name __pycache__ -exec rm -rf {} +` passam, `find . -name hooks -exec rm -rf {} +`, `find . -name 'pre-*' -delete` e `find . -path '*/.git/*' -delete` não. Um `{}` é argumento literal (também dentro de uma palavra, como `{}/x`), então o `-o` depois de um `-exec ... \;` continua na expressão (`find . -name '*.log' -exec gzip {} \; -o -mtime +30 -delete` é negado); um `-exec` sem `;`/`+` conta como expressão cortada e nada a exclui. Os testes positivos (`-name`, `-path`) também deixam de excluir quando a ação que grava é `-execdir`/`-okdir` ou tem um argumento que junta `{}` com `..` (`find . -name info -type d -exec rm -rf {}/../hooks \;`, `find . -name info -type d -execdir rm -rf hooks \;`); o `-not -path` e o `-prune` continuam valendo. Um `-exec` de leitura (`grep`, `rg`, `cat`, `head`, `wc`, `ls`, `stat`, `file`, `sha256sum`…) sem redirecionamento não é ação de escrita (`find . -name "*.ts" -exec grep -l useX {} +` passa). A negação de um `find` tem mensagem própria: sugere excluir o `.git` (`-not -path './.git/*'`) ou buscar numa subpasta (`find src ...`). Um `-exec` que grava em `.git/hooks` é negado em qualquer caso. Citar `no-verify` fora disso (`grep no-verify README.md`, `git commit -m "docs: explica no-verify"`) continua permitido. Também nega Write/Edit, redirecionamento, `cp`, `mv` ou `tee` para o git config global (só o destino de uma cópia conta, e só os caminhos reais do config global, não qualquer arquivo chamado `.gitconfig`: `cp ~/.gitconfig backup.gitconfig` e um fixture `tests/fixtures/.gitconfig` passam) (`~/.gitconfig`, `%USERPROFILE%\.gitconfig`, `$XDG_CONFIG_HOME/git/config`, `~/.config/git/config`), onde reescritas de URL e `core.hooksPath` também desligariam o scan. Sempre que os hooks nativos estiverem ausentes, ele avisa no stderr a cada commit ou push, com o gate ligado ou não.

### Falso positivo no scan de segredos

O hook bloqueia o commit (ou o push) e lista cada achado com o arquivo e uma impressão digital (fingerprint), por exemplo:

```
- possible generic API key/secret/token assignment in supabase/seed.sql (fingerprint ed29c450272198d3fe54a8f66fa145022361507670c0ce8f2e0cac0cad46ca03)
```

Se aquela linha **não** é um segredo, libere só ela:

1. Copie o fingerprint da mensagem de bloqueio. Para listar os fingerprints das linhas sinalizadas, rode na raiz do repositório:
   ```
   git diff --cached | python "<clone>/plugins/pipeline/hooks/pre-commit-secret-scan.py" --fingerprint
   ```
   Para commits já feitos, use `git show <commit>`; para um arquivo inteiro, informe o caminho dele relativo à raiz do repositório: `python ... --fingerprint --path supabase/seed.sql < supabase/seed.sql`.
2. Acrescente você mesmo uma linha em `.pipeline-secrets-allow` na raiz do repositório, com o motivo:
   ```
   ed29c450272198d3fe54a8f66fa145022361507670c0ce8f2e0cac0cad46ca03  # seed de teste, não é credencial
   ```
3. Coloque o arquivo no stage: `git add .pipeline-secrets-allow`. Depois peça ao agente para fazer o commit de novo (o `.pipeline-secrets-allow` entra junto).

Regras:
- A entrada só vale depois de estar no stage: o commit lê o `.pipeline-secrets-allow` do índice, e o push lê o de cada commit enviado. Uma entrada que existe só no arquivo de trabalho é ignorada.
- O fingerprint é o sha256 do caminho do arquivo mais a linha com os espaços normalizados. Mudar o conteúdo da linha, ou a mesma linha em outro arquivo, exige uma nova entrada; só reindentar não exige.
- Cada entrada libera só aquela linha exata daquele arquivo. As outras continuam sendo verificadas.
- Não existe supressão por comentário no código.
- Quem adiciona entradas é você, não o agente. O hook do plugin nega ao agente editar o arquivo (Write/Edit/MultiEdit/NotebookEdit) e qualquer comando Bash/PowerShell que o altere, coloque no stage, mova ou restaure (ler com `git diff`, `git show` ou `cat` continua permitido); o `kickoff` também põe `Edit(.pipeline-secrets-allow)` e `Write(.pipeline-secrets-allow)` em `permissions.deny`. O arquivo é versionado: mudanças nele exigem a revisão de `security`, e o `gate` lista cada entrada nova no relatório com a linha que ela cobre.
- Um segredo de verdade nunca vai para a allowlist: remova-o e troque-o (rotacione).
- O agente também não pode levar o arquivo junto por um comando amplo: enquanto o `.pipeline-secrets-allow` tiver mudança fora do stage (ou não estiver versionado), o hook pergunta ao próprio git (`git ls-files`, na pasta em que o comando roda) se o pathspec de `git add`/`git commit` alcança o arquivo, e nega se alcançar (`-A`, `.`, `-u`, `-a`, `*.*`, `:/**`, `..` a partir de uma subpasta). `git add .` dentro de uma subpasta continua permitido. Se o git não conseguir responder, nega. Aliases entram na conta (`git -c alias.x='add -A' x`, ou um `alias.x` gravado no `git config`). Coloque-o no stage antes de pedir o commit.
- O hook só verifica `git add`, `git commit` e `git push` rodados de dentro do repositório. Ele nega esses comandos (e aliases) quando apontam o git para um repositório por `--git-dir`, `--work-tree`, `--namespace`, `core.worktree` ou pelas variáveis `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`, `GIT_COMMON_DIR` e `GIT_NAMESPACE` (definidas no próprio comando, com `export`, `declare`, `typeset`, `local`, `readonly`, `read`, `printf -v`, `$env:`, `Set-Item`, `New-Item Env:`, `Set-Content env:`, `[Environment]::SetEnvironmentVariable` etc., mesmo com o nome partido por aspas ou barra, como `GIT_INDEX""_FILE` ou `GIT_\DIR`, ou com um nome que vem de variável no PowerShell). Nega também quando o mesmo comando roda código com `source`, `.`, `eval`, `set -a`, `Invoke-Expression`/`iex` antes de um `add`/`commit`/`push` (rode o script em outro comando). Só citar o nome fora de um contexto que atribui variável (`echo`, `grep`, `python -c "...os.environ.get('GIT_DIR')..."`) não conta. Nega também quando a pasta em que rodam não tem working tree: pasta ou repositório criado no mesmo comando (`mkdir`, `git init`, `git clone`; crie antes, em outro comando) ou repositório bare. Num repositório bare, `git push` é permitido e verificado como qualquer outro (e exige a aprovação do `gate` se `pipeline.gate` estiver ligado ou o commit enviado tiver `docs/quality-reports/`). Rode o git de dentro do repositório (`cd` para ele ou `git -C <repo>`), sem `--git-dir`/`--work-tree`. Comandos de leitura (`git log`, `git status`) continuam liberados.
- Variáveis `GIT_CONFIG_*` num comando `git` que não é `add`/`commit`/`push` (como `GIT_CONFIG_NOSYSTEM=1 git lfs ls-files`) não bloqueiam mais: o hook lê o alias com essas mesmas variáveis e só nega quando o valor delas vem de outra variável que ele não consegue expandir.
- O agente não pode reapontar refs de rastreamento remoto (`refs/remotes/*`), que o push ainda usa quando o `ls-remote` falha: `git update-ref`/`git symbolic-ref` que gravam em `refs/remotes/...` (dois argumentos, `-d`/`--delete` ou `--stdin`; ler com `git symbolic-ref refs/remotes/origin/HEAD` ou `--short` continua permitido), `git remote set-head`, `git fetch`/`git pull` com refspec cujo destino explícito está em `refs/remotes/`, e escrita direta em `.git/refs/remotes/` ou `.git/packed-refs` (redirecionamento, `cp`, `mv`...) são negados. Se precisar, rode você mesmo (ou use `git fetch <remoto>`).
- O nome do programa é lido depois de tirar aspas e barras, como o bash faz: `g\it push`, `g''it commit` e `"g"it add -A` são tratados como `git`.
- Se o próprio hook falhar (erro interno), ele nega com "hook error" qualquer comando que possa fazer `git add`, `git commit`, `git push`, `git config`, `git fetch`/`pull` ou mexer em refs (`update-ref`, `symbolic-ref`, `git remote`), inclusive por alias ou com o nome escrito com aspas ou barras, que cite `.git/hooks`/`.git/config` ou o `.pipeline-secrets-allow`; os demais comandos seguem liberados, para um bug do hook não travar trabalho que não tem a ver com git. Nos hooks nativos (`pre-commit`, `pre-push`), um erro sempre bloqueia.
- Um comando `git` que cita o arquivo é negado se usar `-c`/`--config-env`, variáveis como `GIT_CONFIG_*`, `GIT_PAGER` ou `GIT_EXTERNAL_DIFF`, `-O` do `git grep`, ou um subcomando que não seja de leitura (aliases incluídos).
- No push pelo git (hook `pre-push` instalado com `--install-pre-push`), se o `.pipeline-secrets-allow` enviado tem entradas que o do remoto ainda não tem, o hook mostra um aviso com essas linhas (não bloqueia). A comparação é entre o conteúdo do arquivo nos dois commits, então um atributo `binary`/`-diff` não esconde nada. Se o commit do remoto não existe localmente, o aviso diz "remote state unknown" e lista todas as entradas; numa branch nova, compara com a branch padrão do remoto para onde vai o push (`refs/remotes/<remoto>/HEAD`, ou `main`/`master`) e, se ela não existir localmente, lista todas as entradas. Caracteres de controle nos comentários das entradas aparecem escapados (`\x1b`). Confira se cada uma foi você que acrescentou.

O scan já não sinaliza auto-atribuição de uma coluna a ela mesma, nomes qualificados (`t.col`, `excluded.col`), palavras-chave SQL, identificadores escritos (`new_password_value`, `DEFAULT_API_KEY_NAME`, `hashedPasswordValue`: com `_`, ou camelCase em que cada parte tem ao menos duas minúsculas e uma vogal, até 40 caracteres) e referências a variáveis de ambiente (`process.env.X`, `${VAR}`, `$VAR`, `os.environ[...]`, `os.getenv(...)`, `import.meta.env.X`, `%VAR%`). Continuam bloqueando: valores literais entre aspas com cara de segredo (um placeholder só é aceito quando é o valor inteiro, como `changeme`, `example`, `xxxx...`, ou começa com `your_`, `your-` ou `<`); sequências sem `_` de 16 caracteres ou mais em uma só caixa ou com caixa alternada (`xKqPz...`); valores em que quase todo caractere aparece uma vez só (entropia de Shannon de 3,5 bits/caractere ou mais e perto do máximo para o tamanho); e, sob chaves `password`/`passwd`/`secret`, frases com `_` que não citam nenhuma palavra de código (`correct_horse_battery_staple` bloqueia, `user_input_value` passa).

### Kickoff: complementos por stack e allowlist de comandos

O `kickoff` sempre instala o núcleo (hooks, `.gitignore`, `docs/`, `CLAUDE.md`, grafo de conhecimento). Depois detecta o stack pelos arquivos do projeto e acrescenta convenções específicas só para o que encontrar, para o contexto dos agentes ficar pequeno:

- **Allowlist de comandos.** Junta os comandos do próprio projeto (seção "Comandos" do `CLAUDE.md` e scripts do `package.json`) em `permissions.allow` do `.claude/settings.json`, para os agentes não serem barrados pelo classificador do auto mode em lint, testes, build ou comandos de banco. Cada script vira uma entrada exata (`Bash(npm run db:types)`), nunca um curinga como `Bash(npm run db:*)`, que liberaria scripts futuros e qualquer argumento. Antes de liberar um script, o kickoff lê o corpo dele (e dos scripts que ele chama) e recusa se aparecer um termo proibido: `db push`, `db dump`, `--linked`, `--db-url`, `link`, `migration repair`, `secrets set`, `deploy`, `vercel`, `git push`, `rm -rf`. Rode o kickoff de novo sempre que os scripts mudarem. Também põe `Edit(.pipeline-secrets-allow)` e `Write(.pipeline-secrets-allow)` em `permissions.deny`. Nunca sobrescreve nem remove permissões existentes e mostra o diff antes.
- **Next.js 16 ou superior.** Põe `agentRules: false` para o `next dev` não reescrever o `CLAUDE.md`, registra que a interceptação vive em `proxy.ts` e, em projetos mobile-first, dá aos primitivos do shadcn alvos de toque de 44px no mobile (`h-11 md:h-N`). Acrescenta aos "Comandos" do `CLAUDE.md` como verificar no navegador (script Playwright numa pasta temporária fora do projeto, `node <pasta>/check.mjs`), sem instalar Playwright no projeto nem liberar nada novo na allowlist.
- **Supabase.** Acrescenta uma migration base de privilégios (`anon` sem acesso a tabelas; `authenticated` sem truncate, references, trigger e maintain; sem privilégios em sequências; `EXECUTE` de funções revogado por padrão, inclusive para objetos futuros) e uma varredura pgTAP que falha se `anon` ou `authenticated` puderem executar função fora de uma allowlist por assinatura exata, se alguma tabela estiver sem RLS, se alguma view não tiver `security_invoker=true`, ou se `anon`/`authenticated` tiverem qualquer privilégio em materialized views ou foreign tables (o RLS não vale nelas). Os schemas verificados ficam no topo do arquivo, junto do marcador `ALLOWLIST` (padrão `public`; acrescente todo schema exposto pela API).
- **Versões atuais.** Antes de escrever comandos de scaffold, o kickoff e os planos conferem as versões e flags atuais (`npm view`, documentação) em vez de confiar na memória.

O kickoff é idempotente: rode de novo depois do scaffold de um projeto novo para aplicar os complementos.

### Relatórios de qualidade

Toda entrega aprovada gera `docs/quality-reports/<data>-<slug>.md` e uma linha em `docs/quality-reports/history.jsonl`, com notas por dimensão (segurança, auditoria, design, code review, banco de dados e testes) calculadas a partir do ledger. Isso permite acompanhar a evolução da qualidade do projeto ao longo do tempo.

## Requisitos

- Claude Code com suporte a plugins.
- Python 3 (como `python` ou `python3`) e git no `PATH`. Sem Python 3, o hook do Claude avisa no stderr e deixa passar, e o `pre-commit` e o `pre-push` bloqueiam.
- Plugin [`superpowers`](https://github.com/obra/superpowers), instalado do marketplace oficial (`superpowers@claude-plugins-official`) e declarado como dependência.
- Opcional: [graphify](https://github.com/Graphify-Labs/graphify) (`pip install graphifyy`) para o grafo de conhecimento do projeto.

## Instalação

Adicione o marketplace uma vez por máquina. Para desenvolver o plugin, use um clone local: um marketplace de pasta local é carregado direto do disco, então as edições valem na próxima sessão.

```bash
git clone https://github.com/Lindenjefferson/claude-pipeline.git
claude plugin marketplace add ./claude-pipeline
```

Para só usar, sem editar, o marketplace pode vir direto do GitHub (repositório privado: exige acesso configurado no git):

```bash
claude plugin marketplace add Lindenjefferson/claude-pipeline
```

O marketplace se chama `linden-plugins` e contém o plugin `pipeline`.

## Uso

Habilite o plugin na pasta do projeto. O escopo `local` grava em `.claude/settings.local.json`, que não vai para o git:

```bash
claude plugin install pipeline@linden-plugins --scope local
```

Em uma sessão nessa pasta:

- peça o **kickoff** para preparar a estrutura (ele pergunta antes de instalar hooks persistentes);
- peça uma entrega, por exemplo "implementar o módulo de relatórios", e o **manager** conduz do plano ao gate.

Nada é enviado ao repositório remoto sem pedido explícito: os commits ficam em uma branch de worktree, e o merge e o push só acontecem depois da aprovação do `gate`.

Para desabilitar em um projeto:

```bash
claude plugin uninstall pipeline@linden-plugins --scope local
```

## Estrutura

```
.claude-plugin/marketplace.json     marketplace linden-plugins
plugins/pipeline/
  .claude-plugin/plugin.json        manifesto e dependências
  agents/                           os 10 agentes
  skills/kickoff/                   skill e templates do kickoff
  skills/manager/                   skill, ledger.py, package.py, findings.py, templates/spec-checklist.md e testes
  checklists/                       checklists por stack, listados no pacote de revisão
  lessons/                          lições globais por stack (JSONL), injetadas nos briefs
  hooks/                            hooks.json, scanner de segredos e testes
  tools/mutation/                   pgmutate.py e tsmutate.py (testes de mutação) e testes
```

## Desenvolvimento

Validar o plugin e o marketplace:

```bash
claude plugin validate plugins/pipeline
claude plugin validate .
```

Rodar os testes (cada arquivo imprime `ALL PASS`):

```bash
for t in plugins/pipeline/hooks/tests/test_*.py plugins/pipeline/skills/manager/tests/test_*.py plugins/pipeline/tools/mutation/tests/test_*.py; do python "$t"; done
```

Observações:

- Os hooks `pre-commit` e `pre-push` que o `kickoff` instala em cada projeto não guardam caminho: localizam o scanner pela variável `CLAUDE_PIPELINE_HOME` ou por `git config pipeline.home` (raiz do plugin, isto é, `<clone>/plugins/pipeline`). Configure uma vez por máquina com `git config --global pipeline.home "<clone>/plugins/pipeline"` (você, num terminal: o hook do Claude nega ao agente gravar `pipeline.*`). Se o clone mudar de lugar, só esse valor muda, sem reinstalar os hooks nos projetos. Se o scanner não for encontrado, o commit ou o push é bloqueado com uma mensagem, nunca liberado em silêncio.
- Projetos preparados antes desta versão têm só o `pre-push` (e, antes da 1.2.0, um que chama `python` fixo): rode em cada um `python "<clone>/plugins/pipeline/hooks/pre-commit-secret-scan.py" --install-pre-commit --install-pre-push`, mais `--enable-gate` nos que têm `docs/quality-reports/` (sobrescreve só os hooks que ele mesmo instalou; um `pre-commit` de outra origem é preservado e encadeado).
- O registro de aprovação (`<git-common-dir>/gate-approved`) protege contra acidentes, não contra um agente mal-intencionado: qualquer processo com shell no repositório pode escrever nele. Quem garante a aprovação é o fluxo do `manager`, não o arquivo.
- Instalações feitas a partir do GitHub ficam fixas na `version` de `plugin.json`: aumente a versão a cada release para que `claude plugin update` traga as mudanças.
- Os arquivos são mantidos em LF (`.gitattributes`).

## Licença

Projeto pessoal e privado. Todos os direitos reservados.
