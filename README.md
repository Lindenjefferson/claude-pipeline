# claude-pipeline

> *In English:* a Claude Code plugin that runs a small multi-agent dev team (manager, dev, reviewer, qa) in short, test-first cycles, with a delivery ledger and a local gate, so you only decide product questions and approve the plan and the merge. The docs are in Portuguese; the agent prompts are in English.

Um time de desenvolvimento multiagente e independente para o [Claude Code](https://code.claude.com), que constrói produtos pequenos de forma autônoma e leva cada um pelo ciclo inteiro (descoberta, triagem, desenvolvimento, testes, documentação, auditoria, segurança e operação), com a qualidade de um produto grande. O `manager` orquestra e gere a entrega; agentes especializados implementam, revisam e validam; você só decide as questões de produto e aprova o plano e o merge.

O objetivo é que nada errado saia da máquina sem que você precise acompanhar cada passo: o trabalho anda em ciclos curtos, com testes primeiro, revisão e validação em todo ciclo e um gate local antes do merge.

## Propósito e princípios

- **Só orquestração.** O plugin conduz e gere o desenvolvimento (skills, agentes, `ledger.py`, `gate.py`, princípios gerais). Não traz código, template nem configuração de produto.
- **Independente de stack.** Nada de framework, fornecedor ou linguagem. Regra de stack ou de projeto mora no `CLAUDE.md` e no `docs/lessons.md` de cada projeto.
- **Enxuto.** Toda mudança remove o que ficou desnecessário, duplicado ou sem uso. Uma regra geral curta vale mais que várias específicas.

## Como funciona

Cada entrega tem um *slug*, o nome curto que vai na branch e nos arquivos dela em `docs/`. O registro do que cada agente fez (o *ledger*) e os relatórios ficam em `.superpowers/`, fora do git (a pasta de trabalho que ele divide com o plugin `superpowers`). As decisões que o manager tomou por você, quando não pôde perguntar, ficam na lista *VALIDAR*, que você confere depois.

```
tamanho → (spec) → plano ✋ → ciclos: dev por tarefa (as independentes em paralelo)
        → reviewer ‖ qa → correção 1× ↺ → limpeza → gate.py → merge/push ✋
```

1. O `manager` classifica o pedido (pequeno, padrão, grande); isso decide quantas etapas rodam.
2. Nos pedidos grandes há uma spec; nos padrões e grandes, um plano revisado pelo `reviewer` que você aprova (✋ 1).
3. Cada ciclo tem até ~6 tarefas: o `dev` implementa cada uma com o teste primeiro; o `reviewer` e o `qa` conferem o ciclo inteiro ao mesmo tempo; o `dev` corrige tudo numa rodada só.
4. O `gate.py` confere localmente o ledger, os critérios de aceite com teste (e avisa quando o teste veio no mesmo commit do código), build, tipos, lint, testes (a suíte inteira no head final, rodada por ele ou por um `qa`), auditoria de dependências e segredos, e grava um relatório de qualidade com as métricas da entrega.
5. Você decide o merge e o push (✋ 2). Nada sai da máquina sem esse pedido.

O passo a passo, com o que você digita e o que vê em cada etapa, está em [Como é uma entrega](docs/como-e-uma-entrega.md).

Com você ausente, o [modo autônomo](plugins/pipeline/skills/manager/references/autonomous.md) do manager troca as aprovações por uma lista VALIDAR e não faz merge nem push.

## Começo rápido

**Você precisa de:**

- [Claude Code](https://code.claude.com) v2.1.287 ou mais nova (testado na v2.1.302);
- Python 3 e git no `PATH` (o Python como `python` ou `python3`);
- no Windows, o Git Bash, onde rodam os hooks e os comandos do gate;
- Windows ou Linux (o macOS ainda não foi testado).

Os quatro plugins de que ele depende (`superpowers`, `frontend-design`, `claude-code-setup` e `claude-security`, do marketplace oficial) são instalados junto com ele, e o kickoff confere que estão lá.

**Instalar:**

```bash
# uma vez por máquina
claude plugin marketplace add Lindenjefferson/claude-pipeline

# em cada projeto, só nele (o escopo local não vai para o git); num projeto novo basta a pasta vazia
cd meu-projeto
claude plugin install pipeline@linden-plugins --scope local
```

**Usar:** abra o Claude Code na pasta do projeto, ligue o modo de permissão `auto` do Claude Code (sem ele, a entrega para em cada prompt de permissão) e digite:

1. `prepara este projeto com o kickoff` (ou `/pipeline:kickoff`): uma vez, cria a estrutura;
2. o que você quer entregar, como `implementar a exportação do extrato em CSV` ou `corrigir o bug do login`: o **manager** conduz do plano ao gate.

Para tirar de um projeto: `claude plugin uninstall pipeline@linden-plugins --scope local`.

Os scripts leem algumas seções do `CLAUDE.md` do projeto pelo título, em português ("Comandos", "Testes", "Versão" e as outras que o kickoff escreve): mantenha esses títulos como estão. O resto do arquivo, e a conversa com o Claude, podem ser em qualquer língua.

Noutro computador, num projeto que já usa o plugin: clone, instale o plugin e peça o kickoff, que prepara a máquina pelo `CLAUDE.md` do projeto.

## Componentes

| Componente | Função |
|---|---|
| [`kickoff`](plugins/pipeline/skills/kickoff/SKILL.md) | Prepara um projeto novo ou existente: `CLAUDE.md`, `CLAUDE.local.md`, `docs/`, `.gitignore`, hook de segredos e permissões dos agentes. |
| [`manager`](plugins/pipeline/skills/manager/SKILL.md) | Conduz a entrega do tamanho ao merge, em ciclos, com duas aprovações suas; o que vale só numa situação (modo autônomo, pausa, telas, paralelo, várias sessões) está em [`references/`](plugins/pipeline/skills/manager/references/), lido quando ela ocorre. |
| [`validar`](plugins/pipeline/skills/validar/SKILL.md) | Percorre com você, item a item, as decisões tomadas em seu nome (lista VALIDAR) e grava cada resposta. |
| [`atualizar`](plugins/pipeline/skills/atualizar/SKILL.md) | Atualiza o plugin num projeto num ponto de parada da entrega e, na sessão nova, acrescenta as linhas novas dos templates e aplica as notas de cada versão pulada. |
| [`feedback-plugin`](plugins/pipeline/skills/feedback-plugin/SKILL.md) | No fim da entrega, escreve o pedido para a sessão do plugin, com métricas e lições candidatas a regra geral. |
| [`discovery`](plugins/pipeline/agents/discovery.md) | Extrai fatos das fontes brutas (planilhas, apps de referência, documentos) antes do design e prepara o debate da spec (o pré-respondido, opções e sugestão para o resto; stacks num projeto novo). |
| [`dev`](plugins/pipeline/agents/dev.md) | Implementa uma tarefa com o teste primeiro e atualiza a doc do módulo. |
| [`reviewer`](plugins/pipeline/agents/reviewer.md) | Revisa a spec, o plano e o diff de cada ciclo; só reporta o que consegue provar. |
| [`qa`](plugins/pipeline/agents/qa.md) | Roda a suíte e confere os critérios de aceite do ciclo, com a verificação de interface do projeto quando há tela. |
| [`ledger.py`](plugins/pipeline/skills/manager/ledger.py) | Registro da entrega: o que cada agente concluiu, o que falta, itens adiados e métricas. |
| [`gate.py`](plugins/pipeline/skills/manager/gate.py) | Checagem final local, sem agente: READY ou NOT READY e o relatório de qualidade. |
| [`general.md`](plugins/pipeline/checklists/general.md) | Princípios gerais de qualidade que o `dev` e o `reviewer` aplicam, divididos em fatias lidas conforme o produto. |
| [`agents-shared.md`](plugins/pipeline/checklists/agents-shared.md) | O que `dev` e `qa` têm em comum (servidor de dev, processos que iniciam). |
| [`spec-checklist.md`](plugins/pipeline/skills/manager/templates/spec-checklist.md) | O que toda spec e todo plano respondem, com o pré-mortem de cada escrita. |
| [Hook de segredos e UTF-8](plugins/pipeline/hooks/pre-commit-secret-scan.py) | `pre-commit` que bloqueia `.env`, linhas com cara de segredo e texto que não é UTF-8 ou tem caracteres invisíveis. |
| [Hook de retomada](plugins/pipeline/hooks/session-start.py) | Ao abrir ou retomar uma sessão, devolve ao manager o estado da entrega. |
| [Guarda dos comandos](plugins/pipeline/hooks/bash-guard.py) | Antes de cada comando: nega pular o `pre-commit`, publicar na branch principal no modo autônomo e o servidor de dev fora do background; pergunta antes do push da principal e antes de iniciar uma entrega fora do modo de permissão `auto` do Claude Code. |
| [Andamento](plugins/pipeline/hooks/andamento.js) | Mod do Claude Code (uma extensão da interface): até três linhas sob o prompt com o andamento da entrega e o que espera você, e o painel `/andamento`. |

## O que fica no seu projeto

Vai para o git, no mesmo slug da entrega: a spec (`docs/specs/<slug>.md`, nas entregas grandes), o plano (`docs/plans/<slug>.md`), o mockup das telas (`docs/mockups/<slug>.html`) e o relatório de qualidade do gate (`docs/quality-reports/`). Ficam também a doc de cada módulo em `docs/modulos/`, com o índice em `docs/README.md`, os padrões que todo código segue e o mapa dos módulos em `docs/arquitetura.md`, o roteiro de publicar, guardar e reverter em `docs/operacao.md`, as lições em `docs/lessons.md`, os achados do `discovery` em `docs/discovery/` e as convenções do projeto no `CLAUDE.md`. Ficam fora do git: `.superpowers/`, com o ledger e os relatórios de cada agente, e o `CLAUDE.local.md`, com o que vale só para este computador.

## Quando não usar

- Produto grande, com muitas equipes e módulos: o plugin foi desenhado e medido em produtos pequenos.
- Time com vários humanos no mesmo repositório: as aprovações e as decisões de produto são de um dono só.
- Deploy contínuo pelo agente: o plugin nunca publica nem faz push sem o seu pedido.
- macOS: ainda não testado (Windows e Linux são).

## Atualização

Peça "atualizar o plugin" na sessão do projeto: a skill [`atualizar`](plugins/pipeline/skills/atualizar/SKILL.md) espera um ponto de parada da entrega e aplica as notas de cada versão do [histórico](plugins/pipeline/UPGRADING.md). Ative também a proteção de push contra segredos do seu provedor (no GitHub, *secret scanning push protection*): o hook local evita acidentes, não quem o pula.

## Para onde vai

As ideias em avaliação e as recusadas estão no [roadmap](docs/roadmap.md); o que cada versão entregou, no [histórico](plugins/pipeline/UPGRADING.md).

## Licença

[MIT](LICENSE). Feito e usado no dia a dia pelo autor nos próprios projetos; issues e sugestões são bem-vindas, sem garantia de suporte.

Para contribuir ou mudar o plugin, as premissas e as regras estão no [`CLAUDE.md`](CLAUDE.md); um clone local (`claude plugin marketplace add ./claude-pipeline`) é carregado do disco, e as edições valem na próxima sessão.
