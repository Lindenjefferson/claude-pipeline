# Como é uma entrega

O caminho de um pedido do começo ao merge, para quem chega pelo [README](../README.md) e ainda não leu as regras do [`manager`](../plugins/pipeline/skills/manager/SKILL.md), que são a fonte de cada passo. Os números do fim são de uma entrega real.

## 1. Preparar o projeto (uma vez)

Na pasta do projeto, com o plugin instalado, você digita:

> prepara este projeto com o kickoff

(ou `/pipeline:kickoff`). O kickoff cria o `CLAUDE.md` do projeto, com os comandos de build e de teste que o gate vai rodar, a pasta `docs/`, o `.gitignore`, o hook que barra segredos no commit e as permissões dos agentes. Antes de liberar qualquer comando para os agentes, ele mostra a lista a você.

## 2. Pedir uma entrega

> implementar a exportação do extrato em CSV

O `manager` assume a sessão. Ele não escreve código de produto: classifica o pedido (pequeno, padrão ou grande), cria a branch e abre o ledger da entrega, o registro de tudo que cada agente fez.

## 3. O plano e a sua primeira aprovação (✋ 1)

Nos pedidos padrão e grandes, o manager escreve o plano em ciclos de até ~6 tarefas, e cada tarefa traz critérios de aceite que viram teste. O `reviewer` revisa o plano antes de você ver. Você recebe:

- o plano, com os ciclos e as tarefas;
- as decisões de produto que só você pode tomar, cada uma com a recomendação do manager;
- o veredito do `reviewer`.

Você aprova ou pede mudança. Depois disso, a sessão só volta a parar para uma pergunta de produto.

## 4. Os ciclos

Em cada ciclo:

1. **`dev`**, um por tarefa (as que não mexem nos mesmos arquivos rodam em paralelo, cada uma na sua cópia do repositório): escreve o teste, confere que ele falha, implementa e atualiza a doc do módulo.
2. **`reviewer` e `qa` ao mesmo tempo**, sobre o ciclo inteiro: o reviewer lê o diff e só reporta o que consegue provar, e o qa roda a suíte e confere cada critério de aceite, também na tela quando o produto tem uma.
3. **Uma rodada de correção**: o `dev` corrige todos os achados de uma vez, e o que ele tocou é revisado e testado de novo.

Enquanto isso, abaixo do prompt, até três linhas dizem em que ciclo a entrega está, quantas tarefas faltam, o que está rodando e o que espera por você. O `/andamento` abre o painel com o detalhe.

## 5. O gate e a sua segunda aprovação (✋ 2)

O `gate.py` roda local, sem agente, e responde READY ou NOT READY. Ele confere que o ledger não tem nada pendente, que cada critério de aceite tem teste, o build, os tipos, o lint, a suíte inteira, a auditoria de dependências e a varredura de segredos no histórico da branch. Depois grava o relatório de qualidade em `docs/quality-reports/`, com as métricas da entrega.

Com READY, você decide o merge e o push. Nada sai da máquina sem esse pedido.

## Sem você por perto

No [modo autônomo](../plugins/pipeline/skills/manager/references/autonomous.md), as aprovações viram itens VALIDAR, que você confere quando volta com a skill `validar`. O guarda dos comandos nega o merge e o push na branch principal enquanto o modo estiver ligado, salvo a entrega que você aprovou de antemão.

## Quanto custa

Uma entrega real de um app web pequeno (Next.js e Postgres), com 9 tarefas em 2 ciclos, uma migration e telas:

| | |
|---|---|
| Relógio, do início ao READY | 6h09 |
| Com algum agente rodando | 2h42 (44%) |
| Tokens dos agentes | ~2,9M (dev 1,2M, reviewer 1,7M) |
| Revisão do plano | 3 rodadas, 7 Important corrigidos antes do código |
| Achados no código | ciclo 1: 1 Important, 1 rodada de correção; ciclo 2: nenhum |
| Checagens do gate | 18, todas PASS (uma marcada SKIP) |

O resto do relógio é o manager integrando o trabalho e as esperas por você. A [análise de outra entrega](analises/0.5-launcher-civic.md) mostra para onde o tempo vai e o que o plugin mudou por causa disso.
