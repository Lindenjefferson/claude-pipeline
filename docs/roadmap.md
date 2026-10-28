# Roadmap do plugin `pipeline`

As ideias para o plugin, de onde quer que venham (feedback de uma entrega real, revisão do próprio plugin, pedido do usuário ou ideia adaptada de outro projeto). O que cada versão entregou está no [histórico](../plugins/pipeline/UPGRADING.md): ao entregar um item, ele sai daqui e vai para a seção da versão, com o PR.

Toda ideia passa pelo filtro do [`CLAUDE.md`](../CLAUDE.md) e termina numa destas seções: **Não triadas** até passar por ele; **Backlog** quando entra, dizendo antes de tudo se é **defeito** (o plugin não faz o que o arquivo dele diz) ou **melhoria**, porque defeito conferido não espera na fila; **Em espera** com o sinal que a traz de volta, sem tipo, porque nada ali foi conferido ainda; ou **Recusado**, com o motivo em uma linha. Um item em espera cujo sinal ficou remoto, pelo que as entregas mostram, sai do arquivo sem ir para Recusado (decisão do dono): o git guarda o texto. Cada item diz de onde veio e o esforço estimado (P, M, G).

## Não triadas

Nenhuma no momento.

## Backlog

Nenhum no momento.

## Em espera (voltam com um sinal)

Cada item diz o sinal que o traz de volta; o detalhe da análise está no histórico do git deste arquivo.

- **Dublê de dependência externa que aceita o que a real recusa** (`app-f0-api` do CF, 1.18.1): o mock aceitava texto onde o módulo real exige bytes, e a suíte ficou verde com o app quebrado. Candidato a princípio no `checklists/general.md`. Volta quando outro projeto tiver um defeito que o dublê escondeu. Esforço: P.
- **Desmontagem de uma cópia com alcance de máquina** (`0.7.4` do `launcher-multimidia`, 1.17.1): o `gradle --stop` de uma cópia derrubou os daemons da outra. Volta na segunda vez: a linha "como derrubá-lo" do template pergunta se o comando alcança só a cópia, e o `parallel.md` só roda o de máquina sem nada em voo. Esforço: P.
- **Leitores de um valor que muda de origem listados no plano** (`0.7.4`, 1.17.1): a revisão do plano pegou dois leitores esquecidos. Candidato a princípio. Volta se um leitor esquecido passar da revisão do plano, ou numa segunda entrega com o mesmo achado. Esforço: P.
- **`add` de uma revisão que passa responde "round 0"** (`0.7.4`, 1.17.1): só a mensagem; sai junto da próxima mudança no `ledger.py`, com teste primeiro, ou antes se a mensagem levar o manager a uma ação errada. Esforço: P.
- **Hook do modo autônomo negando o merge depois de o usuário voltar** (`api-v1-app-nativo` do CF, 1.18.0): a mensagem do `bash-guard.py` não diz que falta o `mode supervised`. Volta na segunda vez: a mensagem passa a dizê-lo, com teste primeiro. Esforço: P.
- **Heartbeat disparando parado na aprovação 2** (`api-v1-app-nativo`, 1.18.0): quatro disparos vazios. Volta na segunda vez: o `status` de um ledger autônomo com o relatório de qualidade gerado diz "delete the heartbeat". Esforço: P.
- **Commit na branch com um `qa --full` em voo** (`api-v1-app-nativo`, 1.18.0): o `Commit:` do `qa` deixou de ser o HEAD. Volta na segunda vez ou se custar uma rodada: o `status` acusa commit depois do `claim` de um `qa` da suíte inteira aberto. Esforço: P.
- **`qa` de rodada de correção com a suíte inteira** (`paginas-legais` do CF, 1.18.0): foi de propósito, as falhas só se reproduziam com a suíte cheia. Volta se um `qa` de correção repetir a suíte inteira sem essa razão. Esforço: P.
- **Limpeza encadeada depois de um cherry-pick com conflito** (`paginas-legais`, 1.18.0): a branch da T7 foi apagada no conflito e voltou pelo `CHERRY_PICK_HEAD`. Volta na segunda vez: o `bash-guard.py` recusa remover branch ou worktree encadeado a um `cherry-pick` ou `merge`. Esforço: P.
- **`dev` editando o plano depois da aprovação** (`paginas-legais`, 1.18.0): alinhou um trecho de código, sem rodada. Volta na segunda vez ou se a edição mudar um critério: o gate aceita mudança no plano depois do `plan --path` só na `## Errata`. Esforço: P.
- **"Comandos" propostos pelo kickoff a partir do manifesto do projeto** (pedido do dono): ler o que o projeto declara (scripts, Makefile) e propor as linhas, medindo o tempo de cada comando. Volta com a primeira entrega do `civic-pulse`, o próximo projeto novo, onde dá para medir. Esforço: M.
- **Links e arquivos soltos conferidos por script** (auditoria do roadmap): o fechamento de cada versão confere à mão os links e os arquivos sem uso. Volta quando um link quebrado ou um arquivo sem uso passar de uma revisão de fechamento. Esforço: P.

## Recusado

- **Saída do gate com acento num console cp1252** (achada no primeiro run do CI; revista na 1.19.0): a premissa estava errada. O `gate.py` já força UTF-8 na saída desde antes do CI (`main`, a reconfiguração do `sys.stdout`); o texto truncado veio de quem capturou a saída, não do gate.
- **Exceção de auditoria lida pelo gate** (entrega `app-f0-api` do CF): o gate só roda o comando "Auditoria" e lê o código de saída; ler pacote e faixa pediria entender a saída de cada gerenciador, o que é de stack, e uma exceção da linha inteira esconderia a vulnerabilidade nova que chegar depois. A exceção versionada com data de revisão mora no comando de Auditoria do projeto (uma ferramenta de auditoria com allowlist que expira), e o relatório de qualidade já mostra a linha e o comando.

- **"Full suite: SKIP" por `Testes (banco)` de novo** (entrega `api-v1-app-nativo` do CF): já entregue na 1.18.1 (PR #67). O `gate-2.log` saiu do código 1.18.0, que a sessão ainda rodava; o `full_suite()` da 1.18.1 contra o `CLAUDE.md` do CF exige o `qa --full` no head final, conferido.
- **Teste que afirma só sobre os dados que criou, como princípio novo** (entrega `api-v1-app-nativo` do CF): já é o item "Each test creates its own data" do `checklists/general.md` ("no dependency on data another test left"); uma contagem global da tabela depende dos dados de outra suíte.
- **Mensagens de `--triage` e `--origin` no ledger** (entrega `paginas-legais` do CF, 1.18.0): `--origin` que não soma o total já é recusado ("must count every finding once: 14 counted, 13 findings", reproduzido na 1.18.0); `--triage` sem valor é o erro padrão do argparse, e o formato está no `-h` e no erro da rodada sem `--triage`.

- **SOLID e design patterns no `checklists/general.md`** (auditoria dos padrões de mercado, a pedido do usuário): são de orientação a objetos e o plugin é independente de stack; o `reviewer` já recusa o que nenhum critério exige e o `cleanup` ataca duplicação.
- **Comentário explicativo no código, como manda o uso comum** (auditoria dos padrões de mercado): comentário mente depois de três refactors e ninguém o confere; a documentação vai para `docs/NN-modulo.md`, que tem dono e `Status`, com exceção do "porquê" não óbvio em uma linha.
- **Biblioteca da entrega como painel de leitura** (pedido do usuário, ideia da Library do app Projetos): markdown longo se lê pior num painel de terminal que no editor, e abrir o arquivo fora pediria um ramo por sistema operacional dentro do mod; a 1.9.8 lista os caminhos no `/andamento`, que basta.
- **A entrega se retomando sozinha pelo mod** (pedido do usuário, ideia do app Projetos; entregue na 1.9.8 e retirada na 1.9.9): o `references/pause.md` já manda o manager dormir a espera da janela num comando em background e dar `resume` quando ele termina, sem o usuário voltar ao terminal — a premissa do item era falsa e não foi conferida antes de implementar. A versão do mod ainda disparava em pausa que não era de uso, em toda sessão que lê o ledger, e podia redespachar uma tarefa já retomada. O que ficou do pedido é a notificação, que não duplica nada.
- **Lista de origens própria no `qa.md`** (feedback da entrega `0.4-launcher-civic`): não havia divergência — o `reviewer.md` define as cinco origens e o `ledger.py` aceita as mesmas; a 1.9.7 só as nomeia no `qa.md`.
- **`reviewer` gravando o próprio relatório** (feedback da entrega `0.4-launcher-civic`): o passo 4.2 já manda o manager gravar o relatório, e o `reviewer` não tem a ferramenta `Write`; o brief daquela entrega pedia ao agente o que ele não pode fazer.
- **Revisão externa no gate** (1.6.0): manda o diff para fora e exige outra CLI e uma chave de LLM; o `reviewer` já cobre, e o gate é sem LLM de propósito.
- **Custo da entrega com o `ccusage`** (pedido do usuário): ele estima dólares pelo preço da API; numa assinatura o que limita é o uso da janela e da semana, que o próprio Claude Code dá ao mod desde a 1.8.10.
- **Levar a entrega em andamento para outra máquina** (exportar o ledger e os relatórios): decisão do usuário, que só troca de computador entre etapas.
- **`code-simplifier`** (plugin oficial, analisado pelo Fable): o prompt traz regras de JavaScript e React, é um agente que edita sozinho fora do `dev`, sem testes nem commit, e repete o Refactor do `dev`, o `cleanup` e a Simplicity do `reviewer`; o Claude Code já tem o `/simplify`.
- **`claude-md-management`** (plugin oficial, analisado pelo Fable): reescreve o `CLAUDE.md` no formato dele, que o gate, os hooks e o kickoff não leem (uma tabela em "Comandos" deixaria o gate sem testes); grava lições sem passar pela checagem do passo 4.5; procura `.claude.local.md`, nome que o Claude Code não usa.
- **WSL2 para o modo multi-instância** (1.8): é escolha de ambiente, não do plugin, que roda no Linux desde a 1.8.6; não resolve o gargalo medido (a suíte longa e, no CF, a memória, que o WSL disputa).
- **Tirar do scan de segredos os lock files de outros ecossistemas** (1.8.5): nenhum falso positivo achado, e a exclusão seria um desvio que um agente controla.
- **Liberar `publish` local no `never_allow` do kickoff** (1.8.5): o custo é uma pergunta ao usuário, que decide.
- **Saídas da lista original da 1.8**: statusline (plugin não instala `statusLine`, e a faixa já mostra o modo e os VALIDAR); `/frentes` abrindo abas (só no Windows e frágil, sem API oficial: título da aba, variáveis herdadas, confiança da pasta nova, mensagem lida só quando a sessão é usada; as frentes ficam listadas no painel); semáforo do recurso compartilhado (o manager já serializa e registra nas notas); linha do tempo em gráfico (ficam tempo e tokens por execução); página de telas; `/aprovar` (a trava não depende dele); aviso de decisão pendente separado (entrou nos avisos). O WSL2 saiu por não resolver o gargalo medido, a suíte de interface longa.
- **Trocar uma lição de "suíte inteira" por uma checagem** (CF, depois da 1.8.7): já é o "can this be a check?" do passo 4.5 do manager.
- **qa de rodada de correção só com os testes afetados** (CF, depois da 1.8.7): já é a regra do `qa.md`; fazer o seletor de afetados seguir os imports é do projeto.
- **Agent Teams no lugar dos subagentes** (pesquisa de ferramentas parecidas): experimental, sem `/resume` dos colegas, e a lista de tarefas e a conversa entre eles ficariam fora do ledger.
- **App de canvas para os agentes** (Maestri, Conductor, Orca e parecidos): é interface, não orquestração; o plugin roda sem mudança no terminal de qualquer um deles.
- **Chat em grupo com moderador** (Maestro): a conversa não passa pelo ledger.
- **Dois `dev` na mesma tarefa para escolher o melhor** (comparação do Conductor): dobra o custo da tarefa.
- **Agente de documentação** (pedido do usuário, analisado pelo Fable; a 1.17.0 cobriu a necessidade sem ele): leria o código inteiro a cada entrega para escrever o que o `dev` já escreve na tarefa; os padrões, o mapa e a operação viraram moldes do kickoff, leitura do `dev` e do `reviewer` e a checagem `Docs` do gate.
- **Papéis do BMAD** (analyst, PM, architect, scrum master, PO): o manager e o `reviewer` nos modos spec e plano já cobrem, e mais papéis contrariam o "enxuto".
