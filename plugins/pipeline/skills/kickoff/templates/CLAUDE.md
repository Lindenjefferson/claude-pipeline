# {{PROJECT_NAME}} — convenções do projeto

{{DESCRIPTION}}

## Documentação: `/docs`, não comentário no código

- **Não escrever comentários nem docstrings em classes, funções ou componentes** para explicar o que fazem. O código deve se explicar por nomes e estrutura.
- A documentação vive em [`docs/`](docs/README.md), um arquivo por módulo (`docs/NN-nome-do-modulo.md`), seguindo o template de `docs/README.md`.
- **Toda rodada de código que criar, alterar ou remover algo de um módulo atualiza o `docs/` daquele módulo na mesma rodada** (arquivos-chave, classes/funções principais, decisões de design com o porquê, fluxo de dados, dependências e **Status**). O agente `docs` faz isso.
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

discovery → brainstorming → revisão do spec → plano → dev/db → docs + revisores (security, audit, design, code-review, qa) → gate.

- Antes do plano, os revisores leem o spec aprovado (sem código ainda) e ele é corrigido até todos aprovarem. Obrigatória quando o spec toca auth, permissões, RLS, schema/migrations, segredos ou dados sensíveis/financeiros; opcional nos demais casos.

- A skill `manager` orquestra a entrega e mantém o ledger (`.superpowers/ledger.jsonl`) que sincroniza os agentes; o agente `gate` é a checagem final.
- Commits ficam locais, no branch do worktree. Merge na branch principal e push só depois do veredito APROVADO do `gate`, e só quando o usuário pedir. Correções voltam ao agente dono do arquivo (`dev` ou `db`).
- O plugin `pipeline` está habilitado neste repo (`--scope local`), o que liga o fluxo pessoal aqui. O hook `pre-commit` do git (instalado pelo `kickoff`) bloqueia commits com arquivos `.env` ou linhas com cara de segredo. Nunca usar `--no-verify` nem mexer em `.git/hooks`: um segredo commitado fica no histórico.
- Cada entrega aprovada gera um relatório em `docs/quality-reports/` e uma linha em `history.jsonl`.

## Regras que valem sempre

- Variáveis de ambiente e segredos nunca são commitados.
- _(adicionar aqui as regras de stack decididas no brainstorming: acesso a dados, testes, migrations, deploy)_
