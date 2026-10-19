# claude-pipeline — como trabalhar neste repositório

## Propósito

Este repositório é o plugin `pipeline` do Claude Code: um time de desenvolvimento multiagente e independente que constrói produtos pequenos de forma autônoma. O `manager` orquestra e gere a entrega; agentes especializados implementam (`dev`), revisam (`reviewer`) e validam (`qa`); o usuário só decide as questões de produto e aprova o plano e o merge.

Três princípios valem para toda mudança:
- **Só orquestração.** O plugin conduz e gere o desenvolvimento (skills, agentes, `ledger.py`, `gate.py`, princípios gerais). Não traz código, template nem configuração de produto.
- **Independente de stack.** Nada de framework, fornecedor ou linguagem. Regra de stack ou de projeto mora no `CLAUDE.md` e no `docs/lessons.md` de cada projeto.
- **Enxuto.** Toda mudança remove o que ficou desnecessário, duplicado ou sem uso. Uma regra geral curta vale mais que várias específicas.

## Mapa: onde cada informação mora

Cada componente tem **uma** fonte de verdade, o próprio arquivo. Os outros documentos apontam para ela com uma linha e um link, nunca copiam o comportamento.

| O quê | Onde |
|---|---|
| Fluxo de entrega, passos, regras do manager | [`plugins/pipeline/skills/manager/SKILL.md`](plugins/pipeline/skills/manager/SKILL.md) |
| Validar as decisões tomadas em nome do usuário; pedido de feedback ao plugin | [`skills/validar/SKILL.md`](plugins/pipeline/skills/validar/SKILL.md), [`skills/feedback-plugin/SKILL.md`](plugins/pipeline/skills/feedback-plugin/SKILL.md) |
| Preparação de um projeto, allowlist de comandos, template do `CLAUDE.md` dos projetos | [`plugins/pipeline/skills/kickoff/SKILL.md`](plugins/pipeline/skills/kickoff/SKILL.md) e [`templates/`](plugins/pipeline/skills/kickoff/templates/) |
| Papel, escopo e relatório de cada agente | [`plugins/pipeline/agents/`](plugins/pipeline/agents/) (`dev`, `reviewer`, `qa`, `discovery`) |
| Princípios gerais de qualidade (Invariants, acesso, testes, auth, UI, auditoria) | [`plugins/pipeline/checklists/general.md`](plugins/pipeline/checklists/general.md) |
| O que spec e plano respondem (pré-mortem, premissas, domínio) | [`plugins/pipeline/skills/manager/templates/spec-checklist.md`](plugins/pipeline/skills/manager/templates/spec-checklist.md) |
| Regras exatas do ledger (ciclos, pendências, métricas) | docstring de [`ledger.py`](plugins/pipeline/skills/manager/ledger.py) |
| Checagens do gate e relatório de qualidade | docstring de [`gate.py`](plugins/pipeline/skills/manager/gate.py) |
| Scan de segredos, UTF-8, caracteres invisíveis, allowlist e falso positivo | docstring de [`hooks/pre-commit-secret-scan.py`](plugins/pipeline/hooks/pre-commit-secret-scan.py) |
| Hooks de sessão e de ferramenta (retomada após compactação, `pipeline.home` na versão em uso, pular o `pre-commit`, branch principal no modo autônomo, servidor de dev solto) | docstrings de [`hooks/session-start.py`](plugins/pipeline/hooks/session-start.py) e [`hooks/bash-guard.py`](plugins/pipeline/hooks/bash-guard.py), registrados em [`hooks/hooks.json`](plugins/pipeline/hooks/hooks.json); a escolha entre `python` e `python3`, no topo de [`hooks/python.sh`](plugins/pipeline/hooks/python.sh) |
| Linha de andamento e painel `/andamento` (mod) | comentário do topo de [`hooks/andamento.js`](plugins/pipeline/hooks/andamento.js), listado em `modules` no `hooks.json` |
| Testes dos scripts | `plugins/pipeline/skills/manager/tests/`, `plugins/pipeline/hooks/tests/` (o do mod é `andamento.test.ts`) |
| Versões entregues, notas de atualização, backlog | [`docs/roadmap.md`](docs/roadmap.md) |
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
- **Teste primeiro** para `ledger.py`, `gate.py`, os hooks e o mod: o teste novo falha antes da mudança. Ledgers de versões anteriores continuam legíveis, ou a quebra vai para as notas de atualização.
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
- Cada release sobe a `version` de `plugin.json` (instalações do GitHub ficam fixas nela) e move os itens entregues em `docs/roadmap.md` para a seção da versão, com o número do PR e, se algo muda para quem atualiza, uma linha em "Notas de atualização".
- As lições de uma entrega acumulam na versão seguinte e saem num ponto de parada da entrega (nenhum agente rodando); correção de script quebrado (hook, gate, ledger) pode sair sozinha.
- Merge e instalação do plugin atualizado só com pedido explícito do dono.
