# {{PROJECT_NAME}} — convenções do projeto

{{DESCRIPTION}}

## Documentação: `/docs`, não comentário no código

- **Não escrever comentários nem docstrings em classes, funções ou componentes** para explicar o que fazem. O código deve se explicar por nomes e estrutura.
- A documentação vive em [`docs/`](docs/README.md), um arquivo por módulo (`docs/NN-nome-do-modulo.md`), seguindo o template de `docs/README.md`.
- **Toda rodada de código que criar, alterar ou remover algo de um módulo atualiza o `docs/` daquele módulo na mesma rodada** (arquivos-chave, classes/funções principais, decisões de design com o porquê, fluxo de dados, dependências e **Status**). O agente `dev` faz isso na mesma tarefa.
- Única exceção de comentário inline: um "porquê" realmente não óbvio (restrição escondida, workaround de bug específico), em uma linha. Nunca "o que" a função faz.
- Arquivos de **especificação** (decididos antes de codar) não mudam a cada PR. `docs/` descreve o código real. Se divergirem, o código manda: atualizar o doc do módulo e, se for mudança de decisão, registrar também na spec.

## Comandos

Os agentes (`dev`, `qa`) usam esta seção para rodar e verificar o projeto, e o `gate.py` roda as linhas Build, Typecheck, Lint e Testes antes de qualquer merge. Preencher assim que a stack existir, com o comando entre crases (ex.: `- Testes:` seguido de `npm test` entre crases):

- Instalar dependências: _(comando)_
- Rodar em desenvolvimento: _(comando)_
- Build: _(comando)_
- Typecheck: _(comando)_
- Lint: _(comando)_
- Testes: _(comando)_
- Verificação de interface (se houver tela): _(comando)_
- Migrations (aplicar/criar): _(comando)_

## Fluxo de entrega

A skill `manager` classifica o pedido (pequeno, padrão, grande) e conduz em ciclos curtos: spec (só nos grandes) → plano (aprovado pelo usuário) → ciclos de até ~6 tarefas (`dev` em cada tarefa, depois um `reviewer` e um `qa` sobre o ciclo inteiro e uma rodada de correção) → `gate.py` (build, tipos, lint, testes e scan de segredos, tudo local) → merge e push só quando o usuário aprovar.

- O trabalho acontece numa branch `feat/...` ou `fix/...`; nada vai para a branch principal sem aprovação.
- O ledger (`.superpowers/ledger.jsonl`) registra o que cada agente concluiu e o que falta.
- Achados do `reviewer` e do `qa` voltam para o `dev` numa rodada só; se ainda sobrar algo, o `manager` pergunta.
- Erros que uma regra teria evitado viram uma checagem automática (teste, helper, lint) sempre que possível; o que não dá para automatizar vira uma linha em `docs/lessons.md`, que o `dev` e o `reviewer` leem.
- O hook `pre-commit` do git (instalado pelo `kickoff`) bloqueia commits com arquivos `.env` ou linhas com cara de segredo. Nunca usar `--no-verify` nem mexer em `.git/hooks`: um segredo commitado fica no histórico.
- Cada entrega aprovada pelo `gate.py` gera um relatório em `docs/quality-reports/`.

## Regras que valem sempre

- Variáveis de ambiente e segredos nunca são commitados.
- Antes de escrever ou corrigir um comando de scaffold ou instalação (aqui, numa spec ou num plano), conferir a versão e as flags atuais no gerenciador de pacotes do stack, no `--help` e na documentação atual; nunca de memória.
- _(adicionar aqui as regras de stack decididas no brainstorming: acesso a dados, testes, migrations, deploy)_
