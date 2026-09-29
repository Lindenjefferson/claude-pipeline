# {{PROJECT_NAME}} — convenções do projeto

{{DESCRIPTION}}

## Documentação: `/docs`, não comentário no código

- **Não escrever comentários nem docstrings em classes, funções ou componentes** para explicar o que fazem. O código deve se explicar por nomes e estrutura.
- A documentação vive em [`docs/`](docs/README.md), um arquivo por módulo (`docs/NN-nome-do-modulo.md`), seguindo o template de `docs/README.md`.
- **Toda rodada de código que criar, alterar ou remover algo de um módulo atualiza o `docs/` daquele módulo na mesma rodada** (arquivos-chave, classes/funções principais, decisões de design com o porquê, fluxo de dados, dependências e **Status**). O agente `dev` faz isso na mesma tarefa.
- Única exceção de comentário inline: um "porquê" realmente não óbvio (restrição escondida, workaround de bug específico), em uma linha. Nunca "o que" a função faz.
- Arquivos de **especificação** (decididos antes de codar) não mudam a cada PR. `docs/` descreve o código real. Se divergirem, o código manda: atualizar o doc do módulo e, se for mudança de decisão, registrar também na spec.

## Comandos

Os agentes (`dev`, `qa`) usam esta seção para rodar e verificar o projeto. Preencher assim que a stack existir:

- Instalar dependências: _(comando)_
- Rodar em desenvolvimento: _(comando)_
- Testes: _(comando)_
- Typecheck: _(comando)_
- Lint: _(comando)_
- Migrations (aplicar/criar): _(comando)_

## Fluxo de entrega

A skill `manager` classifica o pedido (pequeno, padrão, grande) e conduz: spec (só nos grandes) → plano (aprovado pelo usuário) → por tarefa `dev` → `reviewer` → `qa` → `gate` (build, tipos, lint, testes e scan de segredos, tudo local) → merge e push só quando o usuário aprovar.

- O trabalho acontece numa branch `feat/...` ou `fix/...`; nada vai para a branch principal sem aprovação.
- O ledger (`.superpowers/ledger.jsonl`) registra o que cada agente concluiu e o que falta.
- Achados do `reviewer` e do `qa` voltam para o `dev`; depois de 3 rodadas sem resolver, o `manager` pergunta.
- Erros que uma regra escrita teria evitado viram uma linha em `docs/lessons.md`, que o `dev` e o `reviewer` leem.
- O hook `pre-commit` do git (instalado pelo `kickoff`) bloqueia commits com arquivos `.env` ou linhas com cara de segredo. Nunca usar `--no-verify` nem mexer em `.git/hooks`: um segredo commitado fica no histórico.
- Cada entrega aprovada pelo `gate` gera um relatório em `docs/quality-reports/`.

## Regras que valem sempre

- Variáveis de ambiente e segredos nunca são commitados.
- _(adicionar aqui as regras de stack decididas no brainstorming: acesso a dados, testes, migrations, deploy)_
