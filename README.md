# claude-pipeline

Um time de desenvolvimento multiagente e independente para o [Claude Code](https://code.claude.com), que constrói produtos pequenos de forma autônoma. O `manager` orquestra e gere a entrega; agentes especializados implementam, revisam e validam; você só decide as questões de produto e aprova o plano e o merge.

O objetivo é que nada errado saia da máquina sem que você precise acompanhar cada passo: o trabalho anda em ciclos curtos, com testes primeiro, revisão e validação em todo ciclo e um gate local antes do merge.

## Propósito e princípios

- **Só orquestração.** O plugin conduz e gere o desenvolvimento (skills, agentes, `ledger.py`, `gate.py`, princípios gerais). Não traz código, template nem configuração de produto.
- **Independente de stack.** Nada de framework, fornecedor ou linguagem. Regra de stack ou de projeto mora no `CLAUDE.md` e no `docs/lessons.md` de cada projeto.
- **Enxuto.** Toda mudança remove o que ficou desnecessário, duplicado ou sem uso. Uma regra geral curta vale mais que várias específicas.

As regras para mudar o plugin estão no [`CLAUDE.md`](CLAUDE.md).

## Como funciona

```
tamanho → (spec) → plano ✋ → ciclos: dev por tarefa (as independentes em paralelo)
        → reviewer ‖ qa → correção 1× ↺ → limpeza → gate.py → merge/push ✋
```

1. O `manager` classifica o pedido (pequeno, padrão, grande); isso decide quantas etapas rodam.
2. Nos pedidos grandes há uma spec; nos padrões e grandes, um plano revisado pelo `reviewer` que você aprova (✋ 1).
3. Cada ciclo tem até ~6 tarefas: o `dev` implementa cada uma com o teste primeiro; o `reviewer` e o `qa` conferem o ciclo inteiro ao mesmo tempo; o `dev` corrige tudo numa rodada só.
4. O `gate.py` confere localmente o ledger, os critérios de aceite com teste, build, tipos, lint, testes (a suíte inteira no head final, rodada por ele ou por um `qa`), auditoria de dependências e segredos, e grava um relatório de qualidade com as métricas da entrega.
5. Você decide o merge e o push (✋ 2). Nada sai da máquina sem esse pedido.

Com você ausente, o modo autônomo do [manager](plugins/pipeline/skills/manager/SKILL.md) troca as aprovações por uma lista VALIDAR e não faz merge nem push.

## Começo rápido

Requisitos: Claude Code com plugins (a linha de andamento e o `/andamento` pedem a v2.1.287 ou mais nova, testados na v2.1.302), Python 3 e git no `PATH` (o Python com o nome `python` ou `python3`; testado no Windows e no Linux, ainda não no macOS), no Windows o Git Bash, onde rodam os hooks do plugin e o `gate.py` roda os comandos do projeto, e os plugins [`superpowers`](https://github.com/obra/superpowers) (`superpowers@claude-plugins-official`) e `frontend-design@claude-plugins-official` (rodada e revisão de design, só em produtos com tela), declarados como dependência; o `kickoff` avisa quando falta um e diz como instalar. Opcional: [graphify](https://github.com/Graphify-Labs/graphify) (`pip install graphifyy`) para o grafo de conhecimento.

```bash
# uma vez por máquina (repositório privado: o git da máquina precisa estar autenticado no GitHub)
claude plugin marketplace add Lindenjefferson/claude-pipeline

# em cada projeto: habilitado só nele, nunca globalmente (o escopo local não vai para o git)
claude plugin install pipeline@linden-plugins --scope local
```

Numa sessão na pasta do projeto, peça o **kickoff** para preparar a estrutura e depois uma entrega ("implementar o módulo de relatórios", "corrigir o bug do login"): o **manager** conduz do tamanho ao gate. Para desabilitar: `claude plugin uninstall pipeline@linden-plugins --scope local`.

Para atualizar: `claude plugin marketplace update linden-plugins` e, em cada projeto, `claude plugin update pipeline@linden-plugins --scope local`; uma sessão aberta segue na versão que carregou até reiniciar. Para desenvolver o plugin, use um clone local (`claude plugin marketplace add ./claude-pipeline`), que é carregado do disco: as edições valem na próxima sessão.

## Componentes

| Componente | Função |
|---|---|
| [`kickoff`](plugins/pipeline/skills/kickoff/SKILL.md) | Prepara um projeto novo ou existente: `CLAUDE.md`, `CLAUDE.local.md`, `docs/`, `.gitignore`, hook de segredos, permissões dos agentes e grafo. |
| [`manager`](plugins/pipeline/skills/manager/SKILL.md) | Conduz a entrega do tamanho ao merge, em ciclos, com duas aprovações suas. |
| [`validar`](plugins/pipeline/skills/validar/SKILL.md) | Percorre com você, item a item, as decisões tomadas em seu nome (lista VALIDAR) e grava cada resposta. |
| [`feedback-plugin`](plugins/pipeline/skills/feedback-plugin/SKILL.md) | No fim da entrega, escreve o pedido para a sessão do plugin, com métricas e lições candidatas a regra geral. |
| [`discovery`](plugins/pipeline/agents/discovery.md) | Extrai fatos das fontes brutas (planilhas, apps de referência, documentos) antes do design. |
| [`dev`](plugins/pipeline/agents/dev.md) | Implementa uma tarefa com o teste primeiro e atualiza a doc do módulo. |
| [`reviewer`](plugins/pipeline/agents/reviewer.md) | Revisa a spec, o plano e o diff de cada ciclo; só reporta o que consegue provar. |
| [`qa`](plugins/pipeline/agents/qa.md) | Roda a suíte e confere os critérios de aceite do ciclo, com a verificação de interface do projeto quando há tela. |
| [`ledger.py`](plugins/pipeline/skills/manager/ledger.py) | Registro da entrega: o que cada agente concluiu, o que falta, itens adiados e métricas. |
| [`gate.py`](plugins/pipeline/skills/manager/gate.py) | Checagem final local, sem agente: READY ou NOT READY e o relatório de qualidade. |
| [`general.md`](plugins/pipeline/checklists/general.md) | Princípios gerais de qualidade que o `dev` e o `reviewer` aplicam. |
| [`spec-checklist.md`](plugins/pipeline/skills/manager/templates/spec-checklist.md) | O que toda spec e todo plano respondem, com o pré-mortem de cada escrita. |
| [Hook de segredos e UTF-8](plugins/pipeline/hooks/pre-commit-secret-scan.py) | `pre-commit` do git que bloqueia `.env`, linhas com cara de segredo e linhas adicionadas que não são UTF-8 ou têm caracteres invisíveis; o docstring explica falso positivo e a correção. |
| [Hook de retomada](plugins/pipeline/hooks/session-start.py) | `SessionStart` (toda sessão): depois de compactação ou retomada, devolve ao manager o `status` do ledger; em toda sessão, mantém o `pipeline.home` do repositório na versão do plugin em uso. Registrado em [`hooks.json`](plugins/pipeline/hooks/hooks.json). |
| [Guarda do Bash](plugins/pipeline/hooks/bash-guard.py) | `PreToolUse` em `Bash`: nega pular o `pre-commit` (`--no-verify`, `-n`, `core.hooksPath`), o que chega na branch principal no modo autônomo e o comando da linha "Rodar em desenvolvimento" do `CLAUDE.md` do projeto fora do modo background. |
| [Andamento](plugins/pipeline/hooks/andamento.js) | Mod do Claude Code: com entrega aberta, uma linha em português acima do prompt com o ciclo do plano, as tarefas em andamento, o que vem depois e quantas tarefas e ciclos faltam; `/andamento` abre o painel com a tabela do ciclo e as outras frentes; grava o uso da conta ao lado do ledger, para o manager economizar ou pausar. |

## Atualização

- Instalações a partir do GitHub ficam fixas na `version` do `plugin.json` (como atualizar: "Começo rápido").
- Termine a entrega em andamento antes de atualizar. O que muda de uma versão para outra (formato do ledger, arquivos que saíram) está em [`docs/roadmap.md`](docs/roadmap.md#notas-de-atualização).
- Ative também a proteção de push contra segredos do seu provedor (no GitHub, secret scanning push protection): o hook local é contra acidentes, não contra quem o pula.

## Licença

Projeto pessoal e privado. Todos os direitos reservados.
