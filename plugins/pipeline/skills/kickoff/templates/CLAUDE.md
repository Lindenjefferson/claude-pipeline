# {{PROJECT_NAME}} — convenções do projeto

{{DESCRIPTION}}

## Documentação: `/docs`, não comentário no código

- **Não escrever comentários nem docstrings em classes, funções ou componentes** para explicar o que fazem. O código deve se explicar por nomes e estrutura.
- A documentação vive em [`docs/`](docs/README.md), um arquivo por módulo (`docs/NN-nome-do-modulo.md`), seguindo o template de `docs/README.md`.
- **Toda rodada de código que criar, alterar ou remover algo de um módulo atualiza o `docs/` daquele módulo na mesma rodada** (arquivos-chave, classes/funções principais, decisões de design com o porquê, fluxo de dados, dependências e **Status**). O agente `dev` faz isso na mesma tarefa.
- Única exceção de comentário inline: um "porquê" realmente não óbvio (restrição escondida, workaround de bug específico), em uma linha. Nunca "o que" a função faz.
- Arquivos de **especificação** (decididos antes de codar) não mudam a cada PR. `docs/` descreve o código real. Se divergirem, o código manda: atualizar o doc do módulo e, se for mudança de decisão, registrar também na spec.

## Comandos

Os agentes (`dev`, `qa`) usam esta seção para rodar e verificar o projeto, e o `gate.py` roda as linhas Build, Typecheck, Lint, Testes e Auditoria antes de qualquer merge (só Testes é obrigatória). Preencher assim que a stack existir, com o comando entre crases (ex.: `- Testes:` seguido do comando de testes entre crases):

- Instalar dependências: _(comando)_
- Rodar em desenvolvimento (o servidor de dev; o hook do plugin o nega fora do modo background): _(comando)_
- Build: _(comando)_
- Typecheck: _(comando)_
- Lint: _(comando)_
- Testes: _(comando)_
- Testes afetados (um arquivo ou filtro, para o `dev`): _(comando)_
- Arquivos de teste (globs separados por espaço; o `gate.py` procura neles o id de cada critério de aceite): _(globs)_
- Auditoria (vulnerabilidades das dependências; opcional): _(comando)_
- Verificação de interface (se houver tela): _(comando)_
- Servidor para a verificação de interface (o mesmo que o runner sobe, com as variáveis do ambiente de teste; quem sobe o servidor à mão usa este): _(comando)_
- Migrations (aplicar/criar): _(comando)_

## Execução em paralelo

O `manager` roda em paralelo, cada uma numa worktree do git, as tarefas que não dependem uma da outra nem tocam os mesmos arquivos. Sem esta seção preenchida, as tarefas rodam uma de cada vez.

- Como rodar N cópias ao mesmo tempo (o que muda por worktree): _(porta, variáveis de ambiente, dados de teste)_
- Armazenamento de dados por cópia: _(outra instância com portas próprias ou um esquema por cópia; ou "compartilhado", e a verificação que grava roda uma tarefa por vez)_
- Como preparar as dependências de uma cópia (o `manager` faz antes de despachar): _(reaproveitar as dependências já instaladas ou instalar; copiar o arquivo de ambiente)_
- Quanto uma cópia ocupa no pico, com a preparação e o armazenamento de dados: _(memória e disco; ou "a medir")_
- Pasta de saída dos testes por execução: _(a variável de ambiente que o runner lê; o `qa` usa sempre uma pasta própria)_
- Limites do ambiente de teste que atrapalham execuções simultâneas e como afrouxá-los só no ambiente local: _(ex.: taxa de login)_
- Testes de interface reaproveitam uma sessão autenticada pronta em vez de autenticar a cada teste: _(como)_
- Recursos que não dá para isolar (a verificação que os usa roda uma tarefa por vez): _(ex.: limite de taxa de um serviço externo, um serviço único)_
- Números sequenciais reservados no plano: _(ex.: migrations)_

## Fluxo de entrega

A skill `manager` conduz cada entrega, do tamanho do pedido ao `gate.py` (o fluxo está nela), com duas aprovações do usuário: o plano e o merge/push.

- O trabalho acontece numa branch `feat/...` ou `fix/...`; nada vai para a branch principal sem aprovação.
- O ledger (`.superpowers/ledger.jsonl`) registra o que cada agente concluiu e o que falta.
- O que não dá para virar checagem automática (teste, helper, lint) vira uma linha em `docs/lessons.md`, que o `dev` e o `reviewer` leem.
- O hook `pre-commit` do git (instalado pelo `kickoff`) bloqueia commits com arquivos `.env` ou linhas com cara de segredo. Nunca usar `--no-verify` nem mexer em `.git/hooks`: um segredo commitado fica no histórico.
- Cada entrega aprovada pelo `gate.py` gera um relatório em `docs/quality-reports/`.
- Ambiente de testes antes de produção: _(onde a entrega é publicada primeiro, como as migrations passam por ele, como fazer backup e reverter)_

## Regras que valem sempre

- Variáveis de ambiente e segredos nunca são commitados.
- Antes de escrever ou corrigir um comando de scaffold ou instalação (aqui, numa spec ou num plano), conferir a versão e as flags atuais no gerenciador de pacotes do stack, no `--help` e na documentação atual; nunca de memória.
- _(adicionar aqui as regras de stack decididas no brainstorming: acesso a dados, testes, migrations, deploy)_
