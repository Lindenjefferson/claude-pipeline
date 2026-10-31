# {{PROJECT_NAME}} — convenções do projeto

{{DESCRIPTION}}

## Documentação: `/docs`, não comentário no código

- **Não escrever comentários nem docstrings em classes, funções ou componentes** para explicar o que fazem. O código deve se explicar por nomes e estrutura.
- A documentação vive em [`docs/`](docs/README.md), um arquivo por módulo (`docs/modulos/NN-nome-do-modulo.md`), seguindo o template de `docs/README.md`.
- Os padrões que todo código segue (camadas, nomes, erros, logs, testes, o mapa dos módulos e as decisões) ficam em [`docs/arquitetura.md`](docs/arquitetura.md), e publicar, backup, restauração e reversão em [`docs/operacao.md`](docs/operacao.md). Um padrão novo entra lá na tarefa que o adota; o `reviewer` aponta o código que diverge, e o `gate.py` confere o índice e os links.
- **Toda rodada de código que criar, alterar ou remover algo de um módulo atualiza o `docs/` daquele módulo na mesma rodada** (arquivos-chave, classes/funções principais, decisões de design com o porquê, fluxo de dados, dependências e **Status**). O agente `dev` faz isso na mesma tarefa.
- A documentação da API pública (quando o projeto é uma biblioteca ou expõe uma API a outros programas), no formato da ferramenta de documentação da linguagem, não conta como comentário: segue a convenção da linguagem.
- Exceção de comentário inline: um "porquê" realmente não óbvio (restrição escondida, workaround de bug específico), em uma linha. Nunca "o que" a função faz.
- Arquivos de **especificação** (decididos antes de codar) não mudam a cada PR. `docs/` descreve o código real. Se divergirem, o código manda: atualizar o doc do módulo e, se for mudança de decisão, registrar também na spec.

## Comandos

Os agentes (`dev`, `qa`) usam esta seção para rodar e verificar o projeto, e o `gate.py` roda as linhas Build, Typecheck, Lint, Testes e Auditoria antes de qualquer merge (só Testes é obrigatória). Preencher assim que a stack existir, com o comando entre crases (ex.: `- Testes:` seguido do comando de testes entre crases). Cada comando é escrito para o shell da ferramenta Bash (no Windows, o Git Bash), onde os agentes e o `gate.py` o rodam:

- Instalar dependências: _(comando)_
- Rodar em desenvolvimento (o servidor de dev; o hook do plugin o nega fora do modo background): _(comando)_
- Build: _(comando)_
- Typecheck: _(comando)_
- Lint: _(comando)_
- Testes: _(comando)_ (outra suíte que precisa passar antes do merge, como a de interface ou a do banco, vai numa linha "Testes (<nome>)", que o gate também roda; com a de interface fora delas, o `manager` roda um `qa` final com a suíte inteira)
- Testes afetados (um arquivo ou filtro, para o `dev`): _(comando)_
- Testes (verificação do projeto): _(comando dos testes que vigiam o projeto inteiro, como o que proíbe um padrão em qualquer arquivo; o `dev` o roda a cada tarefa e o `reviewer` confere o plano contra eles; opcional)_
- Arquivos de teste (globs separados por espaço; o `gate.py` procura neles o id de cada critério de aceite): _(globs)_
- Auditoria (vulnerabilidades das dependências; opcional): _(comando)_
- Versão (os arquivos que guardam a versão do produto, separados por espaço; todos com o mesmo `x.y.z`, sem sufixo de pré-lançamento, que o `gate.py` exige acima do da branch principal): _(ex.: `package.json`)_
- Tempo máximo de cada comando do gate, em minutos (padrão 15): _(número entre crases, só quando um comando passa disso)_
- Verificação de interface (se houver tela): _(comando)_
- Servidor para a verificação de interface (o mesmo que o runner sobe, com as variáveis do ambiente de teste; quem sobe o servidor à mão usa este): _(comando)_
- Migrations (aplicar/criar; se houver): _(comando)_

## Preparar uma máquina

O que um computador novo precisa para trabalhar no projeto, depois de clonar e instalar o plugin, para o kickoff deixá-lo pronto quase sozinho, na ordem em que as linhas estão (mude a ordem quando um valor depende de um serviço de pé). Ele mostra cada comando, recusa os perigosos e roda o resto com uma confirmação do usuário, nunca improvisa um que não está aqui e nunca copia, inventa ou adivinha um segredo.

- Pré-requisitos (cada ferramenta, a versão, o comando que a confere e, por sistema, o que a instala ou abre): _(ex.: a versão do runtime, o comando que a mostra e o instalador do Windows e do Linux; um serviço que precisa estar aberto e como abri-lo)_
- Arquivos de ambiente (de qual exemplo copiar e de onde vêm os valores: o comando que grava o arquivo com eles, do serviço onde o projeto roda ou de um serviço local já de pé, ou os que o usuário preenche à mão): _(ou "nenhum")_
- Extensões do Claude Code que o projeto usa (cada `plugin@marketplace`, instalado no escopo do `pipeline`; os servidores MCP do projeto ficam no `.mcp.json`, que vem no clone): _(ou "nenhuma")_
- Serviços locais (o que subir antes de trabalhar): _(comando, ou "nenhum")_
- Prova de que a máquina está pronta: _(comando curto, como os testes rápidos e o status dos serviços)_

As dependências do projeto são a linha "Instalar dependências" de "Comandos".

## Execução em paralelo

O `manager` roda em paralelo, cada uma numa worktree do git, as tarefas que não dependem uma da outra nem tocam os mesmos arquivos (exceto o doc do módulo). Sem esta seção preenchida, as tarefas rodam uma de cada vez.

- Como rodar N cópias ao mesmo tempo (o que muda por worktree): _(porta, variáveis de ambiente, dados de teste)_
- Armazenamento de dados por cópia: _(outra instância com portas próprias ou um esquema por cópia; ou "compartilhado", e a verificação que grava roda uma tarefa por vez)_; como derrubá-lo com os dados dele e conferir que caiu (o `manager` faz antes de remover a worktree): _(nenhum processo nem porta da cópia de pé)_
- Como preparar as dependências de uma cópia e conferir que ela funciona (o `manager` faz antes de despachar): _(reaproveitar as dependências já instaladas ou instalar; copiar o arquivo de ambiente; um comando curto de cada ferramenta que a verificação usa e o status do armazenamento)_
- O que a verificação grava fora da worktree (saída dos testes, temporário de ferramenta) e a pasta da cópia para onde vai, dentro da worktree ou em `../_temp/<projeto>-worktrees/<cópia>-saida`: _(a variável de cada ferramenta; o `qa` usa sempre uma pasta própria; o `manager` a apaga com a worktree)_
- Limites do ambiente de teste que atrapalham execuções simultâneas e como afrouxá-los só no ambiente local: _(ex.: taxa de login)_
- Testes de interface reaproveitam uma sessão autenticada pronta em vez de autenticar a cada teste (se houver login): _(como)_
- Recursos que não dá para isolar (a verificação que os usa roda uma tarefa por vez): _(ex.: limite de taxa de um serviço externo, um serviço único)_
- Números sequenciais reservados no plano: _(ex.: migrations)_

## Fluxo de entrega

A skill `manager` conduz cada entrega, do tamanho do pedido ao `gate.py` (o fluxo está nela), com duas aprovações do usuário: o plano e o merge/push.

- O trabalho acontece numa branch `feat/...` ou `fix/...`; nada vai para a branch principal sem aprovação.
- O ledger (`.superpowers/ledger.jsonl`) registra o que cada agente concluiu e o que falta.
- O que não dá para virar checagem automática (teste, helper, lint) vira uma linha em `docs/lessons.md`, que o `dev` e o `reviewer` leem.
- O hook `pre-commit` do git (instalado pelo `kickoff`) bloqueia commits com arquivos `.env` ou linhas com cara de segredo. Nunca usar `--no-verify` nem mexer em `.git/hooks`: um segredo commitado fica no histórico.
- Cada entrega aprovada pelo `gate.py` gera um relatório em `docs/quality-reports/`.
- Formatos de tela que a rodada de design, as capturas e a revisão visual cobrem (se houver tela): _(ex.: a menor largura suportada e o desktop; celular e tablet; a resolução do jogo)_
- Ambiente de testes antes de produção: _(onde a entrega é publicada primeiro e como as migrations passam por ele; os procedimentos ficam em `docs/operacao.md`)_

## Regras que valem sempre

- Variáveis de ambiente e segredos nunca são commitados.
- O que vale só para este computador (quanto uma cópia ocupa aqui, caminhos e limites da máquina) vai no `CLAUDE.local.md`, que fica fora do git; nunca neste arquivo.
- Antes de escrever ou corrigir um comando de scaffold ou instalação (aqui, numa spec ou num plano), conferir a versão e as flags atuais no gerenciador de pacotes do stack, no `--help` e na documentação atual; nunca de memória.
- Se houver tela: toda mudança de tela, mockup ou layout, dentro ou fora de uma entrega (brainstorming, pedido avulso, `fix-N`), carrega a skill `frontend-design` antes de desenhar e termina com uma captura de cada formato de tela, conferida antes de ir ao usuário. Toda pergunta ao usuário sobre o que ele vai ver (layout, caminho de cliques, agrupamento, estados de uma tela), na spec, no plano, num `fix-N` ou num pedido avulso, vai como desenho com as opções clicáveis no visual companion do `superpowers`, não em texto; a escolha vai para a spec ou o plano, e, numa tela com mock, para o `docs/mockups/<slug>.html`.
- _(adicionar aqui as regras de stack decididas no brainstorming: acesso a dados, testes, migrations, deploy)_
