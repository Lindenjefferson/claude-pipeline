# Documentação do projeto

Esta pasta é a documentação viva do código: registra **o que existe e por quê**, para não depender de comentário em classe/função. Regra completa em [`CLAUDE.md`](../CLAUDE.md).

## Índice por módulo

| Doc | Módulo |
|---|---|
| _(criado pelo agente `dev` na primeira tarefa do módulo)_ | — |

## Outras pastas

- [`discovery/`](discovery/) — achados estruturados das fontes brutas (gerados pelo agente `discovery`).
- [`quality-reports/`](quality-reports/) — um relatório por entrega aprovada (gerado pelo `gate`).
- `lessons.md` — regras curtas aprendidas com erros das entregas; o `dev` e o `reviewer` leem antes de cada tarefa.

## Diferença em relação à especificação

- Arquivos de especificação (decididos antes de codar) não mudam a cada PR, só quando uma decisão muda.
- `docs/*.md` documenta o **código real**, atualizado a cada rodada que toca aquele módulo. Se spec e código divergirem, o código manda e o doc do módulo reflete isso (com uma nota se a divergência for intencional).

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
