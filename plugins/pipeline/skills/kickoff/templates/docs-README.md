# Documentação do projeto

Esta pasta é a documentação viva do código: registra **o que existe e por quê**, para não depender de comentário em classe/função. Regra completa em [`CLAUDE.md`](../CLAUDE.md).

## Índice por módulo

| Doc | Módulo |
|---|---|
| _(criado pelo agente `dev` na primeira tarefa do módulo)_ | — |

## Outras pastas

Só estas, e a pasta própria do projeto que este índice nomear aqui: o `gate.py` recusa o resto de `docs/`.

- `modulos/` — um documento por módulo (`NN-nome.md`), listado no índice acima.
- [`arquitetura.md`](arquitetura.md) — os padrões que todo código segue e o mapa dos módulos; o `dev` lê antes de cada tarefa.
- [`operacao.md`](operacao.md) — publicar, backup e restauração, reverter e onde ler os logs.
- [`discovery/`](discovery/) — achados estruturados das fontes brutas (gerados pelo agente `discovery`).
- `specs/` — uma spec por entrega grande (`<slug>.md`), decidida antes de codar.
- `plans/` — um plano por entrega (`<slug>.md`), o que o `manager` executa e o `gate.py` rastreia (e recusa em outro lugar).
- `mockups/` — um mockup por entrega com tela (`<slug>.html`), feito na rodada de design.

Os três usam o **mesmo slug da entrega**, e cada pasta aparece na primeira entrega que a tem.
- [`quality-reports/`](quality-reports/) — um relatório por entrega aprovada (gerado pelo `gate.py`).
- [`lessons.md`](lessons.md) — regras curtas aprendidas com erros das entregas, só as que não viraram checagem automática; o `dev` e o `reviewer` leem antes de cada tarefa.

## Diferença em relação à especificação

- Arquivos de especificação (decididos antes de codar) não mudam a cada PR, só quando uma decisão muda.
- `docs/modulos/` documenta o **código real**, atualizado a cada rodada que toca aquele módulo. Se spec e código divergirem, o código manda e o doc do módulo reflete isso (com uma nota se a divergência for intencional).

## Template de cada arquivo de módulo

```markdown
# Módulo N — Nome

**Status**: 📋 planejado | 🚧 em desenvolvimento | ✅ implementado

**Spec de origem**: <arquivo e seção>

## Propósito
## Arquivos-chave
## Classes / Funções principais
## Decisões de design
## Fluxo de dados
## Dependências
```
