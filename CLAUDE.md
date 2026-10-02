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
| Preparação de um projeto, allowlist de comandos, template do `CLAUDE.md` dos projetos | [`plugins/pipeline/skills/kickoff/SKILL.md`](plugins/pipeline/skills/kickoff/SKILL.md) e [`templates/`](plugins/pipeline/skills/kickoff/templates/) |
| Papel, escopo e relatório de cada agente | [`plugins/pipeline/agents/`](plugins/pipeline/agents/) (`dev`, `reviewer`, `qa`, `discovery`) |
| Princípios gerais de qualidade (Invariantes, acesso, testes, auth, UI, auditoria) | [`plugins/pipeline/checklists/general.md`](plugins/pipeline/checklists/general.md) |
| O que spec e plano respondem (pré-mortem, premissas, domínio) | [`plugins/pipeline/skills/manager/templates/spec-checklist.md`](plugins/pipeline/skills/manager/templates/spec-checklist.md) |
| Regras exatas do ledger (ciclos, pendências, métricas) | docstring de [`ledger.py`](plugins/pipeline/skills/manager/ledger.py) |
| Checagens do gate e relatório de qualidade | docstring de [`gate.py`](plugins/pipeline/skills/manager/gate.py) |
| Scan de segredos, allowlist e falso positivo | docstring de [`hooks/pre-commit-secret-scan.py`](plugins/pipeline/hooks/pre-commit-secret-scan.py) |
| Testes dos scripts | `plugins/pipeline/skills/manager/tests/`, `plugins/pipeline/hooks/tests/` |
| Versões entregues, notas de atualização, backlog | [`docs/roadmap.md`](docs/roadmap.md) |
| Apresentação, começo rápido, componentes em uma linha | [`README.md`](README.md) |
| Manifesto e marketplace | [`plugins/pipeline/.claude-plugin/plugin.json`](plugins/pipeline/.claude-plugin/plugin.json), [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json) |

## Como as peças se encaixam

O `kickoff` prepara o projeto uma vez. A cada pedido, o `manager` dimensiona o trabalho, escreve spec e plano (o `reviewer` revisa o plano e o usuário aprova: ✋ 1), cria a branch e roda ciclos: `dev` por tarefa, depois `reviewer` e `qa` em paralelo, uma rodada de correção. Cada execução de agente vai para o `ledger.py`, que diz o que falta. No fim, o `gate.py` lê o ledger e o `CLAUDE.md` do projeto e responde READY ou NOT READY; com READY, o usuário aprova merge e push (✋ 2). Os detalhes estão nos arquivos do mapa acima.

## Regras para mudar o plugin

- **Feedback de entregas entra só como regra geral** que garante um bom produto em qualquer stack. O que é de stack ou de projeto volta para o projeto. Uma lição que se repete em dois projetos é candidata a princípio em `checklists/general.md`.
- **Fonte única por componente.** Comportamento novo vai para o arquivo do componente; README e este `CLAUDE.md` ganham no máximo uma linha com link. Ao mudar um componente, conferir que README, `CLAUDE.md`, `docs/roadmap.md` e os outros componentes que o citam continuam consistentes (mesmos termos, nenhuma cópia).
- **Enxugar ao tocar.** Ao editar um arquivo, remover o que ficou obsoleto, duplicado ou sem uso, e listar o que saiu no PR.
- **Teste primeiro** para `ledger.py`, `gate.py` e o hook: o teste novo falha antes da mudança. Ledgers de versões anteriores continuam legíveis, ou a quebra vai para as notas de atualização.
- Arquivos em UTF-8 e LF (`.gitattributes`). Prompts de skills e agentes em inglês; README, este arquivo e o roadmap em português.
- Nunca `git commit --no-verify`.

## Testar e validar

```bash
for t in plugins/pipeline/hooks/tests/test_*.py plugins/pipeline/skills/manager/tests/test_*.py; do python "$t"; done
claude plugin validate plugins/pipeline
claude plugin validate .
```

Cada arquivo de teste roda sozinho com `python` (sem pytest) e imprime `ALL PASS`.

## Versão e release

- Trabalho numa branch `feat/...` ou `fix/...` a partir da `master`, entregue por PR.
- Cada release sobe a `version` de `plugin.json` (instalações do GitHub ficam fixas nela) e move os itens entregues em `docs/roadmap.md` para a seção da versão, com o número do PR e, se algo muda para quem atualiza, uma linha em "Notas de atualização".
- Merge e instalação do plugin atualizado só com pedido explícito do dono.
