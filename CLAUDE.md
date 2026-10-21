# claude-pipeline — como trabalhar neste repositório

## Propósito

Este repositório é o plugin `pipeline` do Claude Code: um time de desenvolvimento multiagente e independente que constrói produtos pequenos de forma autônoma. O `manager` orquestra e gere a entrega; agentes especializados implementam (`dev`), revisam (`reviewer`) e validam (`qa`); o usuário só decide as questões de produto e aprova o plano e o merge.

Três princípios valem para toda mudança:
- **Só orquestração.** O plugin conduz e gere o desenvolvimento (skills, agentes, `ledger.py`, `gate.py`, princípios gerais). Não traz código, template nem configuração de produto.
- **Independente de stack.** Nada de framework, fornecedor ou linguagem. Regra de stack ou de projeto mora no `CLAUDE.md` e no `docs/lessons.md` de cada projeto.
- **Enxuto.** Toda mudança remove o que ficou desnecessário, duplicado ou sem uso. Uma regra geral curta vale mais que várias específicas.

## O que rege o plugin

Antes das regras de como mudá-lo, para que ele existe. Estas premissas valem dos dois lados, para mudar o plugin e para o que ele entrega; toda decisão de desenho responde a elas, e o que contraria uma delas não entra:

- **Nenhum agente parado.** Orquestrar é manter o trabalho andando: despachar o que já pode andar e nunca encerrar a vez à espera de uma notificação ou de um relógio. A vez só termina esperando o usuário numa decisão que é dele (✋ 1, ✋ 2, o passo `ask`), e depois de despachar o que já podia andar. Espera que dá para medir é defeito, não paciência.
- **Reduzir o tempo até a entrega pronta.** O que o plugin ganha se mede no relógio da entrega, não no número de etapas que ele cumpre. Etapa que não encurta o caminho nem evita retrabalho sai.
- **Duvidar de tudo que é proposto, inclusive do que o próprio plugin propõe.** Pedido, achado e relatório valem pelo que se confere, não por quem os trouxe — outro agente, outro modelo ou o plugin. Um pedido do dono diz por que uma ideia entra, nunca se ela é viável; o filtro de ideias abaixo diz como se confere.
- **Não executar o que não se entendeu.** Perguntar antes custa menos que uma rodada de correção: na dúvida sobre o que foi pedido, confirmar; sobre a tarefa, devolver em vez de adivinhar.
- **Simplificar em vez de complicar.** A menor mudança que resolve: ajuste cirúrgico no arquivo certo em vez de caminho novo, e o mecanismo que já existe em vez de um segundo para a mesma coisa.
- **Um repositório que o dev entende, e no git só o que é fonte.** Organização é parte da entrega, não arrumação no fim: cada arquivo que uma rodada cria é decidido entre entrar no git (fonte, documento, artefato que alguém vai ler) ou ficar fora (área de trabalho de agente, material que vem de fora, saída de build e de teste), e o que entra tem nome e lugar previsíveis, no mesmo slug da entrega. Artefato que o usuário vai ler nunca mora em pasta ignorada. O que a IA escreveu se enxuga ao tocar, como qualquer arquivo do plugin; remover o que o usuário escreveu vai para a aprovação dele.
- **Critério objetivo antes de começar.** Cada mudança diz qual é a meta de sucesso antes de entrar; sem ela não há como saber se funcionou, nem como aplicar o filtro de ideias, que cobra o número dessa meta.

## Mapa: onde cada informação mora

Cada componente tem **uma** fonte de verdade, o próprio arquivo. Os outros documentos apontam para ela com uma linha e um link, nunca copiam o comportamento.

| O quê | Onde |
|---|---|
| Fluxo de entrega, passos, regras do manager | [`plugins/pipeline/skills/manager/SKILL.md`](plugins/pipeline/skills/manager/SKILL.md); o que vale só numa situação (modo autônomo, pausa e uso do plano, telas, execução em paralelo, várias sessões), em [`references/`](plugins/pipeline/skills/manager/references/), um arquivo por situação |
| Validar as decisões tomadas em nome do usuário; pedido de feedback ao plugin | [`skills/validar/SKILL.md`](plugins/pipeline/skills/validar/SKILL.md), [`skills/feedback-plugin/SKILL.md`](plugins/pipeline/skills/feedback-plugin/SKILL.md) |
| Preparação de um projeto e de uma máquina nova, allowlist de comandos, template do `CLAUDE.md` dos projetos | [`plugins/pipeline/skills/kickoff/SKILL.md`](plugins/pipeline/skills/kickoff/SKILL.md) e [`templates/`](plugins/pipeline/skills/kickoff/templates/) |
| Papel, escopo e relatório de cada agente | [`plugins/pipeline/agents/`](plugins/pipeline/agents/) (`dev`, `reviewer`, `qa`, `discovery`); o que `dev` e `qa` têm em comum (servidor de dev, processos), em [`checklists/agents-shared.md`](plugins/pipeline/checklists/agents-shared.md) |
| Princípios gerais de qualidade (Invariants, acesso, testes, auth, UI, auditoria) | [`plugins/pipeline/checklists/general.md`](plugins/pipeline/checklists/general.md), o índice, e as fatias que ele lista, lidas quando o produto tem o que os itens delas tratam ([`access-and-data.md`](plugins/pipeline/checklists/access-and-data.md), [`auth-and-sessions.md`](plugins/pipeline/checklists/auth-and-sessions.md), [`web-and-ui.md`](plugins/pipeline/checklists/web-and-ui.md)) |
| O que spec e plano respondem (pré-mortem, premissas, domínio) | [`plugins/pipeline/skills/manager/templates/spec-checklist.md`](plugins/pipeline/skills/manager/templates/spec-checklist.md) |
| Regras exatas do ledger (ciclos, pendências, métricas) | docstring de [`ledger.py`](plugins/pipeline/skills/manager/ledger.py) |
| Checagens do gate e relatório de qualidade | docstring de [`gate.py`](plugins/pipeline/skills/manager/gate.py) |
| Scan de segredos, UTF-8, caracteres invisíveis, allowlist e falso positivo | docstring de [`hooks/pre-commit-secret-scan.py`](plugins/pipeline/hooks/pre-commit-secret-scan.py) |
| Hooks de sessão e de ferramenta (retomada após compactação, `pipeline.home` na versão em uso, atualização pela metade, pular o `pre-commit`, branch principal no modo autônomo, servidor de dev solto) | docstrings de [`hooks/session-start.py`](plugins/pipeline/hooks/session-start.py) e [`hooks/bash-guard.py`](plugins/pipeline/hooks/bash-guard.py), registrados em [`hooks/hooks.json`](plugins/pipeline/hooks/hooks.json); a escolha entre `python` e `python3`, no topo de [`hooks/python.sh`](plugins/pipeline/hooks/python.sh) |
| Linha de andamento, painel `/andamento` e o uso da conta em `usage.json` (mod) | comentário do topo de [`hooks/andamento.js`](plugins/pipeline/hooks/andamento.js), listado em `modules` no `hooks.json` |
| Testes dos scripts | `plugins/pipeline/skills/manager/tests/`, `plugins/pipeline/hooks/tests/` (o do mod é `andamento.test.ts`) |
| Versões entregues, backlog | [`docs/roadmap.md`](docs/roadmap.md) |
| Notas de atualização (vão com a versão instalada) e como atualizar um projeto | [`plugins/pipeline/UPGRADING.md`](plugins/pipeline/UPGRADING.md), aplicadas pela skill [`atualizar`](plugins/pipeline/skills/atualizar/SKILL.md) |
| Apresentação, começo rápido, componentes em uma linha | [`README.md`](README.md) |
| Manifesto e marketplace | [`plugins/pipeline/.claude-plugin/plugin.json`](plugins/pipeline/.claude-plugin/plugin.json), [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json) |

## Como as peças se encaixam

O `kickoff` prepara o projeto uma vez. A cada pedido, o `manager` dimensiona o trabalho, cria a branch, escreve spec e plano (o `reviewer` revisa o plano, e a spec num domínio sensível, e o usuário aprova o plano: ✋ 1) e roda ciclos: `dev` por tarefa, depois `reviewer` e `qa` em paralelo, uma rodada de correção. Cada execução de agente vai para o `ledger.py`, que diz o que falta. No fim, o `gate.py` lê o ledger e o `CLAUDE.md` do projeto e responde READY ou NOT READY; com READY, o usuário aprova merge e push (✋ 2). Os detalhes estão nos arquivos do mapa acima.

## Regras para mudar o plugin

- **Toda ideia passa pelo mesmo filtro antes de entrar**, venha de uma entrega, de uma revisão ou de outro modelo:
  1. o problema é conferido no código ou no ledger (tarefa, rodada, horas, tokens), de preferência com um teste que falha, e não só na descrição de quem o relatou. Uma ocorrência só entra quando custou uma rodada, mais de uma hora ou quebrou um script, ou quando é uma regra do próprio plugin impossível de seguir; o resto vai para "Em espera" até o segundo caso;
  2. a mudança cabe nos três princípios: regra geral que garante um bom produto em qualquer stack (o que é de stack ou de projeto volta para o projeto), no arquivo do componente e sem cópia;
  3. a ideia tenta primeiro virar checagem (teste, ledger, gate, hook); texto de prompt fica para o que um script não confere, e regra de prompt ignorada duas vezes vira checagem. O prompt não cresce numa versão: linha que entra tira outra, ou o PR diz por que cresceu;
  4. cada regra nova diz que número do ledger deve mudar (rodadas por ciclo, achados por origem por ciclo, horas por agente); o `feedback-plugin` da entrega seguinte traz esses números, e a regra que não mudou nada em duas entregas sai;
  5. o que muda o desenho do fluxo (tirar uma etapa, mudar quem faz o quê, mexer na segurança) vai para o usuário decidir.

  Toda ideia termina no roadmap: na versão, em "Em espera" com o sinal que a traz de volta, ou em "Recusado" com o motivo em uma linha; a que veio de um projeto é marcada, no arquivo de atritos dele, com a versão ou o destino. Antes de fechar cada versão, uma revisão por outro modelo, com base nos ledgers e relatórios das entregas, e uma revisão do diff inteiro e dos arquivos que ele toca tiram o que ficou repetido, específico de stack, impossível de conferir ou sem uso, e conferem que a documentação e o repositório continuam organizados: cada informação no arquivo que o mapa diz, links válidos, nenhum arquivo solto ou sem uso. Uma lição que se repete em dois projetos é candidata a princípio em `checklists/general.md`.
- **Fonte única por componente.** Comportamento novo vai para o arquivo do componente; README e este `CLAUDE.md` ganham no máximo uma linha com link. Ao mudar um componente, conferir que README, `CLAUDE.md`, `docs/roadmap.md` e os outros componentes que o citam continuam consistentes (mesmos termos, nenhuma cópia). Única cópia permitida: os três princípios acima, idênticos palavra por palavra na seção "Propósito e princípios" do README; as duas cópias mudam juntas, no mesmo commit.
- **Enxugar ao tocar.** Ao editar um arquivo, remover o que ficou obsoleto, duplicado ou sem uso, e listar o que saiu no PR.
- **Teste primeiro** para `ledger.py`, `gate.py`, os hooks e o mod: o teste novo falha antes da mudança. Ledgers de versões anteriores continuam legíveis, ou a quebra vai para as notas de atualização (`plugins/pipeline/UPGRADING.md`).
- Sem datas no texto dos documentos: o git registra quando cada coisa mudou. A origem vai como versão, PR ou "decisão do usuário".
- Arquivos em UTF-8 e LF (`.gitattributes`). Prompts de skills e agentes em inglês; README, este arquivo e o roadmap em português.
- Nunca `git commit --no-verify`.

## Testar e validar

```bash
for t in plugins/pipeline/hooks/tests/test_*.py plugins/pipeline/skills/manager/tests/test_*.py; do sh plugins/pipeline/hooks/python.sh "$t"; done
(cd plugins/pipeline && claude plugin test)
claude plugin validate plugins/pipeline
claude plugin validate .
```

Cada arquivo de teste Python roda sozinho com o Python 3 (sem pytest) e imprime `ALL PASS`; o `claude plugin test` roda os testes `.test.ts` do mod.

## Versão e release

- Trabalho numa branch `feat/...` ou `fix/...` a partir da `master`, entregue por PR.
- Cada release sobe a `version` de `plugin.json` (instalações do GitHub ficam fixas nela) e move os itens entregues em `docs/roadmap.md` para a seção da versão, com o número do PR, e uma linha da versão em `plugins/pipeline/UPGRADING.md` ("nada muda" quando nada muda, para a skill `atualizar` saber).
- As lições de uma entrega acumulam na versão seguinte e saem num ponto de parada da entrega (nenhum agente rodando); correção de script quebrado (hook, gate, ledger) pode sair sozinha.
- Merge e instalação do plugin atualizado só com pedido explícito do dono.
