# Proposta 2.7.0: o que a etapa 2 (retomada) e a etapa 3 ensinaram

**Status: aprovada pelo usuário em 2026-10-16, os 16 itens como escritos** (revisão um a um), **mais os itens 17 (isolamento para várias instâncias) e 18 (segurança), pedidos pelo usuário no mesmo dia.** Implementação numa branch `feat/2.7.0-...` do repositório do plugin, com PR e aprovação de merge.

Rascunho original para decisão do usuário. Origem: a entrega da etapa 2 (correções visuais) e da etapa 3 inteira do controle-financeiro com o plugin 2.6.1, boa parte em modo autônomo (usuário ausente). Toda regra abaixo é geral, sem stack; o que é de stack ficou no `docs/lessons.md` do projeto.

## Números da entrega

| | Etapa 2 (retomada) | Etapa 3 |
|---|---|---|
| Tarefas | 6 rodadas de correção (fix-6..fix-11) | 23 tarefas em 4 ciclos + 5 rodadas de correção + limpeza |
| Revisões do plano | — | 3 (FAIL, FAIL, PASS) |
| Achados Important | 6 (reviewer 4, qa 2) | 5 no plano (um deles: fatura paga mudando de valor) e 4 no código |
| Origem dos achados | execução | execução > plano > desenho |

O tempo foi para as rodadas de correção de bordas (foco, vãos, limites, quebra de palavra) e para três revisões do plano. O paralelismo da 2.3 (worktrees, reviewer ∥ qa, próximo ciclo em segundo plano) funcionou, com os atritos da seção B.

## A. Bugs do plugin

1. **`gate.py` não acha os testes com o glob natural.** A linha "Arquivos de teste" é casada com `fnmatch`, onde `**/` exige ao menos uma subpasta: `e2e/**/*.spec.ts` não casa `e2e/x.spec.ts`. A checagem de rastreabilidade fica cega sem erro nenhum.
   - Correção: casar com semântica de glob (`**/` = zero ou mais pastas) e o gate avisar quando um glob da linha não casa nenhum arquivo rastreado. Teste em `test_gate.py` com arquivo na raiz da pasta e em subpasta.
2. **Worktree do Agent nasce de um commit antigo**, não do HEAD da branch da entrega. Em todas as tarefas paralelas o dev teve de conferir e fazer `reset`.
   - Correção: o brief de tarefa paralela traz o commit de origem; `agents/dev.md` manda conferir `git log -1` contra ele antes de tocar em qualquer coisa e parar com NEEDS_CONTEXT se a worktree tiver commits que não são dele.
3. **Remover a worktree falha enquanto o agente ainda está vivo** (lock "claude agent ... pid"). O manager tentou integrar na primeira notificação e a sequência de comandos quebrou no meio.
   - Correção (manager): integrar e remover a worktree só depois da notificação de término do agente; comandos de integração um por vez, sem encadear o registro no ledger depois do `worktree remove`.

## B. Execução em paralelo

4. **Dependências por worktree.** O guard de isolamento nega PowerShell/cmd na worktree, então a junction para o `node_modules` do projeto não sai, e o servidor de dev não acha o framework pela pasta-mãe. Cada worktree com servidor precisou de instalação própria (lenta).
   - Correção: o manager prepara a worktree antes de despachar (junction ou instalação, cópia do arquivo de ambiente) fora do guard; o template "Execução em paralelo" do kickoff ganha a linha "como preparar as dependências de uma cópia".
5. **Saídas de teste compartilhadas.** Duas execuções do runner de e2e ao mesmo tempo apagam os artefatos uma da outra (ENOENT).
   - Correção: o template "Execução em paralelo" pede uma pasta de saída por execução (variável de ambiente), e o brief de qa e reviewer a usa sempre.
6. **Servidor de dev subido à mão difere do subido pelo runner** (ferramenta de dev por cima da tela só é desligada quando o runner sobe o servidor).
   - Correção: o template pede que o comando de subir o servidor para e2e esteja escrito no `CLAUDE.md`, com as variáveis do ambiente de teste.

17. **Várias instâncias só rendem com o ambiente isolado.** Nas etapas medidas, o gargalo não foi o número de agentes, e sim o que todas as cópias dividem: um banco local único (reset, testes do banco e e2e que gravam rodam um por vez), o limite de login do serviço de autenticação local (por endereço, somado entre as cópias) e a suíte e2e longa. Mais instâncias sem isolamento trocam espera por conflito.
    - **Template "Execução em paralelo" do kickoff** ganha, além de porta e pasta de saída: (a) como dar um armazenamento de dados próprio a cada cópia (outra instância do banco com portas próprias, ou um esquema por cópia), ou declará-lo compartilhado; (b) os limites do ambiente de teste que atrapalham execuções simultâneas (taxa de login, por exemplo) e como afrouxá-los só no ambiente local; (c) testes que reaproveitam uma sessão autenticada pronta em vez de autenticar a cada teste.
    - **Manager:** antes de despachar mais de uma tarefa que usa o recurso compartilhado, confere se o projeto declarou o isolamento; sem ele, paraleliza só a codificação e serializa a verificação (o que já faz), e sugere a tarefa de infraestrutura de isolamento como primeira tarefa da próxima entrega quando a espera pelo recurso for o maior tempo nas métricas.
    - **Várias sessões (terminais) no mesmo projeto:** uma frente por sessão, dividida por fronteira de módulo (nenhum arquivo em comum), cada uma na sua worktree, branch e ledger; uma só sessão integra (merge na branch da entrega e gate); números sequenciais reservados no plano. Frentes em repositórios diferentes rodam em sessões separadas sem coordenação.

## C. Planejamento

7. **Regra transversal aplicada numa função e esquecida nas irmãs.** O plano trouxe o código de várias funções que listam ou somam a mesma coisa (instâncias de recorrência, recebíveis por pessoa); a regra de encerramento e a de "venda quitada sai do total" estavam numa e não nas outras. Os dois Important do ciclo 1 vieram do plano.
   - Regra nova no checklist (Invariantes) e no modo plano do reviewer: **toda regra que filtra ou soma um conjunto vale em todas as funções que listam ou somam esse conjunto; o plano lista essas funções e cada uma tem um teste da regra.**
8. **A ordem "validar antes de escrever" precisa estar no plano.** A primeira versão do pagamento confirmava itens e só depois validava a data; um pagamento recusado deixava o total errado.
   - Regra no questionário de pré-mortem (spec-checklist §1): **"o que já foi gravado se a validação seguinte recusar?" — validação e permissão vêm antes de qualquer escrita; o que tem de acontecer junto é uma operação atômica.**
9. **Rascunho do plano por subagente funcionou** (5.000+ linhas sem gastar o contexto do manager) e três revisões em modo plano pegaram 1 erro de dinheiro e 8 Important antes de qualquer código.
   - Formalizar no passo 2 do manager: o plano pode ser escrito por um subagente com o mesmo brief do `writing-plans`; o manager aplica as decisões de produto e roda o reviewer em modo plano até PASS (no máximo 3 rodadas, depois pergunta).

## D. Revisão e testes

10. **Checagem de layout só no elemento apontado.** Corrigir a coluna de descrição empurrou a quebra de palavra para as colunas vizinhas, e o teste novo não viu.
    - Ampliar o item de layout do checklist: **a checagem de uma tabela ou lista mede toda célula de toda coluna e todos os cabeçalhos (texto dentro da célula, sem palavra partida, sem encostar no vizinho), em cada largura da faixa onde aquele layout vale, e o vão interno de cards em grade.**
11. **Formulário pré-preenchido com dados de quando a tela abriu.** Um diálogo guardava a sugestão da primeira renderização e salvava valores velhos depois de uma mudança na mesma tela; a resposta do servidor trazia erro para um campo que a tela não tinha, e nada aparecia.
    - Ampliar o item "A form bound to a selected record...": **o pré-preenchimento vem dos dados no momento de abrir, e erro do servidor para campo que a tela não mostra aparece como mensagem geral, com recarga.**
12. **Valor acima do limite de armazenamento dizia "formato inválido".**
    - Exemplo novo no item "A predictable failure never becomes a generic error": acima do limite, a mensagem diz o limite.

## E. Lições

13. **Lição em texto não segurou; a regra de lint segurou.** "Conta derivada não mora em componente" foi escrita num ciclo e quebrada no seguinte.
    - `agents/dev.md`: antes do commit, conferir o próprio diff contra cada linha de `docs/lessons.md` e citar no relatório as que se aplicaram.
    - `manager` 4.6: lição quebrada uma segunda vez vira checagem automática na mesma rodada, sem nova chance em texto.
14. **Seções do `CLAUDE.md` que outra ferramenta reescreve.** O dev escreveu regras do projeto dentro de uma seção gerada por ferramenta (sobrescrita na reinstalação).
    - `agents/dev.md` e kickoff: só escrever em seções do projeto; uma seção gerada por ferramenta é identificada pelo cabeçalho e nunca recebe conteúdo.

## F. Modo autônomo (usuário ausente)

15. **A regra "uma rodada de correção e depois pergunte" para tudo quando o usuário não está.** Foram necessárias até 6 rodadas numa etapa; o usuário pediu para seguir decidindo e anotando.
    - Modo autônomo explícito no manager, ligado pelo usuário: as aprovações viram registro; o plano passa pelo reviewer em modo plano no lugar da aprovação 1; rodadas de correção continuam até PASS; **merge e push nunca** (a entrega seguinte sai numa branch empilhada); toda decisão tomada vai para uma lista "VALIDAR" mostrada na volta, junto com os itens adiados.
    - `ledger.py note --validar` para marcar a decisão; `status` e o relatório do gate listam as marcadas.

## G. Revisão visual

16. **Capturas perdidas.** As capturas da revisão visual ficaram no scratchpad da sessão e a página publicada ficou ilegível depois de uma troca de conta.
    - O qa guarda o script e as capturas da entrega numa pasta persistente ignorada pelo git (ex.: `.superpowers/telas/<entrega>/`), com opção de recapturar só as telas que mudaram, e espera os avisos temporários sumirem antes de capturar.
    - O manager publica a página de telas a partir dessa pasta (um arquivo por entrega).

## H. Segurança

18. **Revisão de segurança por entrega e veto a extensões de terceiros.** Origem: leitura de sete skills de "security audit" de terceiros (2026-10-16). Nenhuma valia instalar: OWASP genérico, pentest fora do escopo, binário remoto sem versão fixa que altera dependências sozinho, ou cópia do revisor nativo com filtro que descarta rate limit, redirect, auditoria e corrida. Três trouxeram ideias que viram regra própria.
    - **Manager, passo 6 (antes do gate):** rodar a revisão de segurança nativa da ferramenta sobre a branch da entrega uma vez; achados entram como `fix-N` ou como item adiado com decisão, como os do reviewer.
    - **Checklist geral, "Web and UI":** cabeçalhos de segurança da resposta (política de conteúdo, transporte estrito, enquadramento, referenciador) configurados e testados; artefatos de depuração (mapas de código-fonte, erros detalhados, rotas de diagnóstico) desligados no build de produção; tokens e identificadores secretos gerados só por fonte criptográfica.
    - **Regra de veto antes de instalar qualquer skill, plugin, servidor MCP ou hook de terceiros** (no manager e no kickoff; vale também para o usuário): ler todos os arquivos, não só o principal, incluindo hooks, manifesto do plugin, configuração de MCP, arquivos de instrução para agentes (`AGENTS.md`, `CLAUDE.md` do repositório) e scripts de ciclo de vida de pacotes (`postinstall`); recusar quem baixa e roda código sem versão fixa (`npx` sem versão, `curl | sh`), altera dependências ou configuração sozinho, envia conteúdo para fora sem estar claro, pede ferramentas além do que descreve ou tenta mudar o comportamento do agente fora do próprio escopo; conferir licença e procedência (cópia sem atribuição é sinal de alerta). O resultado é um de três: não instalar, copiar a ideia para regra própria, ou instalar com versão fixa.

## Para a 2.8 (decisão do usuário, 2026-10-16)

- **Mods do Claude Code para o modo multi-instância:** painel com o status do ledger de cada frente (worktree ou sessão), aviso quando outra sessão termina uma tarefa ou o gate, e um comando para listar as sessões abertas e mandar mensagem a uma delas. A conversa entre sessões já é nativa; o mod a torna visível. Começa por um protótipo pequeno do painel antes de virar item.

## Fora desta proposta (fica no projeto)

Regras de stack que surgiram e já estão no `docs/lessons.md` do controle-financeiro: o padrão de foco depois do sucesso com o diálogo do framework de UI, o seletor de lint contra lista de módulos montada à mão, `items-start` em grades de cards.

## Ordem sugerida

1. A1 (glob do gate), A2/A3 (worktree), B4–B6 (template de paralelo): correções, versão de patch se preferir separar.
2. C7, C8, D10–D12, E13–E14: checklist e agentes, sem código.
3. F15 (modo autônomo) e G16 (capturas persistentes): mudam o manager e o ledger, com testes em `test_ledger.py`.
