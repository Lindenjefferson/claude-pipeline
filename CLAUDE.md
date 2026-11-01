# claude-pipeline — como trabalhar neste repositório

## Propósito

Este repositório é o plugin `pipeline` do Claude Code: um time de desenvolvimento multiagente e independente que constrói produtos pequenos de forma autônoma e leva cada um pelo ciclo inteiro (descoberta, triagem, desenvolvimento, testes, documentação, auditoria, segurança e operação), com a qualidade de um produto grande. O `manager` orquestra e gere a entrega; agentes especializados implementam (`dev`), revisam (`reviewer`) e validam (`qa`); o usuário só decide as questões de produto e aprova o plano e o merge.

Três princípios valem para toda mudança:
- **Só orquestração.** O plugin conduz e gere o desenvolvimento (skills, agentes, `ledger.py`, `gate.py`, princípios gerais). Não traz código, template nem configuração de produto.
- **Independente de stack.** Nada de framework, fornecedor ou linguagem. Regra de stack ou de projeto mora no `CLAUDE.md` e no `docs/lessons.md` de cada projeto.
- **Enxuto.** Toda mudança remove o que ficou desnecessário, duplicado ou sem uso. Uma regra geral curta vale mais que várias específicas.

## O que rege o plugin

Antes das regras de como mudá-lo, para que ele existe. Estas premissas valem dos dois lados, para mudar o plugin e para o que ele entrega; toda decisão de desenho responde a elas, e o que contraria uma delas não entra:

- **Nenhum agente parado.** Orquestrar é manter o trabalho andando: despachar de uma vez tudo o que já pode andar, salvo o que colide (os mesmos arquivos, um recurso que não se isola, uma dependência declarada ou falta de capacidade), e nunca encerrar a vez à espera de uma notificação ou de um relógio. A vez só termina esperando o usuário numa decisão que é dele (✋ 1, ✋ 2, o passo `ask`), e depois de despachar o que já podia andar. Espera que dá para medir é defeito, não paciência.
- **Reduzir o tempo até a entrega pronta.** O que o plugin ganha se mede no relógio da entrega, não no número de etapas que ele cumpre. Etapa que não encurta o caminho nem evita retrabalho sai.
- **Duvidar de tudo que é proposto, inclusive do que o próprio plugin propõe.** Pedido, achado e relatório valem pelo que se confere, não por quem os trouxe — outro agente, outro modelo ou o plugin. Um pedido do dono diz por que uma ideia entra, nunca se ela é viável; o filtro de ideias abaixo diz como se confere.
- **Não executar o que não se entendeu.** Perguntar antes custa menos que uma rodada de correção: na dúvida sobre o que foi pedido, confirmar; sobre a tarefa, devolver em vez de adivinhar.
- **Simplificar em vez de complicar.** A menor mudança que resolve: ajuste cirúrgico no arquivo certo em vez de caminho novo, e o mecanismo que já existe em vez de um segundo para a mesma coisa.
- **Um repositório que o dev entende, e no git só o que é fonte.** Organização é parte da entrega, não arrumação no fim: cada arquivo que uma rodada cria é decidido entre entrar no git (fonte, documento, artefato que alguém vai ler) ou ficar fora (área de trabalho de agente, material que vem de fora, saída de build e de teste), e o que entra tem nome e lugar previsíveis, no mesmo slug da entrega. Artefato que o usuário vai ler nunca mora em pasta ignorada; a exceção são as capturas e gravações do `qa` em `.superpowers/screens/`, binárias e refeitas a cada entrega, que o relatório do `qa` nomeia uma a uma. O que a IA escreveu se enxuga ao tocar, como qualquer arquivo do plugin; remover o que o usuário escreveu vai para a aprovação dele.
- **Critério objetivo antes de começar.** Cada mudança diz qual é a meta de sucesso antes de entrar; sem ela não há como saber se funcionou, nem como aplicar o filtro de ideias, que cobra o número dessa meta.
- **O plugin não entrega o que não cumpre.** O que ele passa a exigir de uma entrega vale para ele mesmo: ou a mesma garantia existe aqui, ou este arquivo diz por que o risco é diferente. Menos aparato que uma entrega de produto é legítimo (o plugin não tem usuário, dado em runtime nem deploy); padrão mais baixo não é. Entrega melhor que o projeto que a executa é dívida, não qualidade.

## Mapa: onde cada informação mora

Cada componente tem **uma** fonte de verdade, o próprio arquivo. Os outros documentos apontam para ela com uma linha e um link, nunca copiam o comportamento.

| O quê | Onde |
|---|---|
| Fluxo de entrega, passos, regras do manager | [`plugins/pipeline/skills/manager/SKILL.md`](plugins/pipeline/skills/manager/SKILL.md); o que vale só numa situação (modo autônomo, pausa e uso do plano, telas, execução em paralelo, várias sessões, varredura de segurança), em [`references/`](plugins/pipeline/skills/manager/references/), um arquivo por situação |
| Validar as decisões tomadas em nome do usuário; pedido de feedback ao plugin | [`skills/validar/SKILL.md`](plugins/pipeline/skills/validar/SKILL.md), [`skills/feedback-plugin/SKILL.md`](plugins/pipeline/skills/feedback-plugin/SKILL.md) |
| Preparação de um projeto e de uma máquina nova, allowlist de comandos, template do `CLAUDE.md` dos projetos | [`plugins/pipeline/skills/kickoff/SKILL.md`](plugins/pipeline/skills/kickoff/SKILL.md) e [`templates/`](plugins/pipeline/skills/kickoff/templates/) |
| Papel, escopo e relatório de cada agente | [`plugins/pipeline/agents/`](plugins/pipeline/agents/) (`dev`, `reviewer`, `qa`, `discovery`); o que `dev` e `qa` têm em comum (servidor de dev, processos), em [`checklists/agents-shared.md`](plugins/pipeline/checklists/agents-shared.md) |
| Princípios gerais de qualidade (Invariants, acesso, testes, auth, UI, auditoria) | [`plugins/pipeline/checklists/general.md`](plugins/pipeline/checklists/general.md), o índice, e as fatias que ele lista, lidas quando o produto tem o que os itens delas tratam ([`access-and-data.md`](plugins/pipeline/checklists/access-and-data.md), [`auth-and-sessions.md`](plugins/pipeline/checklists/auth-and-sessions.md), [`web-and-ui.md`](plugins/pipeline/checklists/web-and-ui.md)) |
| O que spec e plano respondem (pré-mortem, premissas, domínio) | [`plugins/pipeline/skills/manager/templates/spec-checklist.md`](plugins/pipeline/skills/manager/templates/spec-checklist.md) |
| Regras exatas do ledger (ciclos, pendências, métricas) | docstring de [`ledger.py`](plugins/pipeline/skills/manager/ledger.py) |
| Checagens do gate e relatório de qualidade | docstring de [`gate.py`](plugins/pipeline/skills/manager/gate.py) |
| Scan de segredos, UTF-8, caracteres invisíveis, allowlist e falso positivo | docstring de [`hooks/pre-commit-secret-scan.py`](plugins/pipeline/hooks/pre-commit-secret-scan.py) |
| Hooks de sessão e de ferramenta (retomada após compactação, `pipeline.home` na versão em uso, atualização pela metade, pular o `pre-commit`, branch principal (negada no modo autônomo, perguntada fora dele), servidor de dev solto, entrega iniciada fora do modo auto) | docstrings de [`hooks/session-start.py`](plugins/pipeline/hooks/session-start.py) e [`hooks/bash-guard.py`](plugins/pipeline/hooks/bash-guard.py), registrados em [`hooks/hooks.json`](plugins/pipeline/hooks/hooks.json); a escolha entre `python` e `python3`, no topo de [`hooks/python.sh`](plugins/pipeline/hooks/python.sh) |
| Linha de andamento, painel `/andamento` e o uso da conta em `usage.json` (mod) | comentário do topo de [`hooks/andamento.js`](plugins/pipeline/hooks/andamento.js), listado em `modules` no `hooks.json` |
| Testes dos scripts | `plugins/pipeline/skills/manager/tests/`, `plugins/pipeline/hooks/tests/` (o do mod é `andamento.test.ts`) |
| O que o CI roda a cada push e PR | [`.github/workflows/testes.yml`](.github/workflows/testes.yml) |
| Ideias (não triadas, backlog, em espera, recusadas) | [`docs/roadmap.md`](docs/roadmap.md) |
| Análise de uma entrega real que virou item do backlog | [`docs/analises/`](docs/analises/), um arquivo por entrega, no slug dela |
| Histórico das versões, com as notas de atualização (vai com a versão instalada) | [`plugins/pipeline/UPGRADING.md`](plugins/pipeline/UPGRADING.md), aplicadas pela skill [`atualizar`](plugins/pipeline/skills/atualizar/SKILL.md) |
| Apresentação, começo rápido, componentes em uma linha | [`README.md`](README.md) |
| Uma entrega passo a passo, para quem chega ao repositório | [`docs/como-e-uma-entrega.md`](docs/como-e-uma-entrega.md) |
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

  Toda ideia passa pelo roadmap e termina na seção da versão que a entregou, no histórico (`plugins/pipeline/UPGRADING.md`), em "Em espera" com o sinal que a traz de volta, ou em "Recusado" com o motivo em uma linha; a que veio de um projeto sai do arquivo de atritos dele na rodada seguinte do `feedback-plugin` lá, porque o destino fica aqui. Antes de fechar cada versão, uma revisão por outro modelo, com base nos ledgers e relatórios das entregas, e uma revisão do diff inteiro e dos arquivos que ele toca tiram o que ficou repetido, específico de stack, impossível de conferir ou sem uso, e conferem que a documentação e o repositório continuam organizados: cada informação no arquivo que o mapa diz, links válidos, nenhum arquivo solto ou sem uso. Uma lição que se repete em dois projetos é candidata a princípio em `checklists/general.md`.
- **Fonte única por componente.** Comportamento novo vai para o arquivo do componente; README e este `CLAUDE.md` ganham no máximo uma linha com link. Ao mudar um componente, conferir que README, `CLAUDE.md`, `docs/roadmap.md`, o histórico e os outros componentes que o citam continuam consistentes (mesmos termos, nenhuma cópia). Única cópia permitida: os três princípios acima, idênticos palavra por palavra na seção "Propósito e princípios" do README; as duas cópias mudam juntas, no mesmo commit. Uma regra que um agente precisa e que mora num arquivo que ele não lê vai também no arquivo dele (cada agente lê o próprio e o que ele nomeia): é o caso do texto de fonte como dado, no `qa` e no `discovery`, e do teste instável, no `qa` e no manager.
- **Enxugar ao tocar.** Ao editar um arquivo, remover o que ficou obsoleto, duplicado ou sem uso, e listar o que saiu no PR.
- **Teste primeiro** para `ledger.py`, `gate.py`, os hooks e o mod: o teste novo falha antes da mudança. Ledgers de versões anteriores continuam legíveis, ou a quebra vai para o "Ao atualizar" da versão no histórico (`plugins/pipeline/UPGRADING.md`).
- Sem datas no texto dos documentos: o git registra quando cada coisa mudou. A origem vai como versão, PR ou "decisão do usuário".
- Arquivos em UTF-8 e LF (`.gitattributes`). Prompts de skills e agentes em inglês; README, este arquivo, o roadmap e o histórico em português, e também os moldes do kickoff e os rótulos que os scripts leem no `CLAUDE.md` dos projetos ("Comandos", "Testes", "Versão"), na língua dos projetos do dono.
- Nunca `git commit --no-verify`.

## Testar e validar

```bash
for t in plugins/pipeline/hooks/tests/test_*.py plugins/pipeline/skills/manager/tests/test_*.py; do sh plugins/pipeline/hooks/python.sh "$t"; done
(cd plugins/pipeline && claude plugin test)
claude plugin validate plugins/pipeline
claude plugin validate .
```

Cada arquivo de teste Python roda sozinho com o Python 3 (sem pytest) e imprime `ALL PASS`; o `claude plugin test` roda os testes `.test.ts` do mod. Cada um sai com código diferente de zero quando um assert falha, e o CI roda esses mesmos quatro comandos a cada push e PR, no Linux e no Windows, e a varredura de segredos de cada commit do PR (`pre-commit-secret-scan.py --range`), a mesma que o gate faz nos projetos ([`.github/workflows/testes.yml`](.github/workflows/testes.yml)).

Num clone novo, instale aqui o mesmo `pre-commit` que o `kickoff` instala em qualquer projeto (a premissa "o plugin não entrega o que não cumpre"), porque um hook mora em `.git/hooks` e não viaja no clone: `python plugins/pipeline/hooks/pre-commit-secret-scan.py --install-pre-commit`. Ele lê só linhas adicionadas, então os fixtures de teste já commitados não barram nada; um commit que adicione linha parecida com segredo é barrado com o fingerprint, e só o dono assina o `.pipeline-secrets-allow`. As regras de permissão que o kickoff escreve em qualquer projeto valem aqui também, em `.claude/settings.json`: o `deny` do `--no-verify`, do `core.hooksPath`, do `sudo`, do force push e da edição da allowlist; o push da branch principal pergunta pelo `bash-guard.py`.

## Versão e release

- Trabalho numa branch `feat/...` ou `fix/...` a partir da `main`, entregue por PR. Mudança só de documentação fora do que se instala (`docs/`, `README.md`, este arquivo) ou de limpeza do backlog vai numa branch `docs/...` e entra na `main` por merge `--no-ff`, sem PR e sem subir a versão (decisão do usuário).
- **Major, minor e patch.** Major só quando um ledger da versão anterior deixa de ser legível — a única quebra irreversível, e o teste do `ledger.py` a confere; minor quando há comportamento novo; patch quando é só correção, sem mudança de comportamento. A numeração voltou para 1.x por decisão do usuário, com o plugin usado só pelo dono (instalado do GitHub nos projetos dele), e a linha 1.x original virou 0.x (a conta está no `UPGRADING.md`): daqui para a frente, uma v2 significa exatamente essa quebra, nada mais.
- Cada release sobe a `version` de `plugin.json` (instalações do GitHub ficam fixas nela) e ganha uma seção no histórico (`plugins/pipeline/UPGRADING.md`) com os itens entregues, que saem de `docs/roadmap.md`, o número do PR e o parágrafo "Ao atualizar" ("nada muda" quando nada muda, para a skill `atualizar` saber).
- As lições de uma entrega acumulam na versão seguinte e saem num ponto de parada da entrega (nenhum agente rodando); correção de script quebrado (hook, gate, ledger) pode sair sozinha. Cada item do backlog diz se é **defeito** (o plugin não faz o que o arquivo dele diz) ou **melhoria**: defeito conferido não espera na fila, sai no próximo ponto de parada; melhoria espera a versão.
- Merge e instalação do plugin atualizado só com pedido explícito do dono.
