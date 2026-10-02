# claude-pipeline

Plugin do [Claude Code](https://code.claude.com) para desenvolver projetos pessoais num fluxo curto e circular: planejar, implementar com testes, revisar, validar e só então deixar o código sair da máquina. Inspirado no [ECC](https://github.com/affaan-m/ecc) (o pipeline `orch-*`, o `code-reviewer` e o `verification-loop`), em versão enxuta.

O plugin é habilitado **por projeto**, nunca globalmente: onde não está ativo, nenhum agente ou skill dele é carregado.

## Como funciona

```
tamanho → (spec) → plano ✋ → ciclo: dev por tarefa → reviewer 1× → qa 1× → correção 1× ↺ → gate.py → merge/push ✋
```

1. **`pipeline:kickoff`** prepara o projeto com a estrutura que não depende de stack: `CLAUDE.md` (com a seção "Comandos" que o `gate.py` lê), `docs/` com `lessons.md`, `.gitignore`, o hook `pre-commit` de segredos, as permissões dos agentes e o grafo de conhecimento. O setup do stack é do projeto.
2. **`pipeline:manager`** classifica o pedido como pequeno, padrão ou grande, e isso decide quantas etapas rodam. Nos grandes há spec (com `discovery` quando existem fontes brutas); nos padrões e grandes, um plano que você aprova (✋ 1).
3. O trabalho anda em **ciclos curtos** de até ~6 tarefas. Em cada tarefa só o `dev` roda: implementa em TDD (red, green, refactor), atualiza a doc do módulo, roda a suíte e commita na branch da feature. No fim do ciclo, **um** `reviewer` revisa o diff do ciclo inteiro com o checklist geral e as regras do projeto e **um** `qa` confere os critérios de aceite. O `dev` corrige todos os achados numa rodada só (tarefa `fix-N`, que fica no mesmo ciclo), e o reviewer confere só a correção; se ainda sobrar algo, o `manager` pergunta a você. Ciclo pequeno quer dizer diff pequeno, poucos achados e uma correção, e o que deu errado vira uma checagem automática (ou, se não der, uma linha em `docs/lessons.md`) para o ciclo seguinte não repetir.
4. O **`gate.py`** é um script, não um agente: confere o ledger e a árvore limpa, roda os comandos Build, Typecheck, Lint e Testes do `CLAUDE.md` e o scan de segredos em todo o histórico da branch. Responde READY ou NOT READY em segundos ou minutos e, se READY, grava o relatório de qualidade.
5. Você decide o merge e o push (✋ 2). Nada sai da máquina sem esse pedido.

## Componentes

| Componente | Função |
|---|---|
| `pipeline:kickoff` | Prepara um projeto novo ou existente para o fluxo. |
| `pipeline:manager` | Conduz a entrega em ciclos, mantém o ledger (`ledger.py`) e roda o `gate.py`. |
| `pipeline:discovery` | Extrai fatos das fontes brutas (planilhas, apps de referência, documentos) antes do design. |
| `pipeline:dev` | Implementa uma tarefa: código, migrations e a doc do módulo, sempre com o teste primeiro. |
| `pipeline:reviewer` | Revisa o diff do ciclo (ou o spec, antes do código): corretude, testes, segurança, acesso a dados, trilha de auditoria e UI, com as Invariantes (também no modo spec). Só reporta o que consegue provar, com arquivo e linha e o cenário de falha; zero achados é um resultado válido. |
| `pipeline:qa` | Roda os testes de verdade e confere os critérios de aceite do ciclo, no navegador quando há tela. |
| Hook de segredos | `pre-commit` nativo do git, instalado pelo `kickoff`: bloqueia arquivos `.env` e linhas com cara de segredo (chaves de nuvem, tokens, chaves privadas, JWT que não seja a chave pública `anon`, `password`/`secret` com valor literal). É uma trava contra acidente: `git commit --no-verify` pula o hook, e o `kickoff` nega esse comando aos agentes. |

### Ledger

`.superpowers/ledger.jsonl` (fora do git) guarda uma linha por execução de agente: agente, tarefa, veredito, achados (Critical, Important, Minor) e commit, agrupadas em ciclos. `ledger.py status` mostra o que falta no ciclo atual: uma tarefa do dev sem concluir, o reviewer que ainda não viu as últimas mudanças, o qa que ainda não rodou depois da revisão, uma reprovação que voltou para o dev, ou uma correção que não resolveu. O ciclo fecha quando o qa aprova, e `status --check` é o que o `gate.py` usa para saber disso.

- Uma rodada de correção (`add --agent dev --task fix-N`) fica no ciclo corrente, mesmo num ciclo já fechado: exige um reviewer sobre a correção, e o qa de novo só quando o último qa do ciclo reprovou.
- `start --archive` move uma entrega anterior para `ledger-<slug-antigo>.jsonl` ao lado e começa outra; sem a flag, o `start` recusa e diz isso.
- As decisões que o `manager` toma no seu lugar (um achado descartado, um Minor adiado) ficam como notas (`note`), e cada lição como `lesson`, com `--check` quando virou checagem automática.
- `status --json` traz as métricas da entrega (achados por ciclo e severidade, rodadas de correção, lições e quantas viraram checagem), que o relatório de qualidade publica.
- A saída é sempre UTF-8, inclusive no console do Windows.

### Checklist, Invariantes e lições

O plugin carrega só princípios gerais, que valem para qualquer stack: `checklists/general.md` (Invariantes, acesso e dados, testes, auth e sessões, web e UI, auditoria) e a seção Invariantes do `reviewer`, aplicada também ao revisar a spec. As regras do stack e do projeto ficam no `CLAUDE.md` e no `docs/lessons.md` de cada projeto, que o `dev` e o `reviewer` leem a cada tarefa.

Quando um erro Critical ou Important vem de algo que uma regra teria evitado, o `manager` pergunta primeiro "isso pode ser uma checagem?" (teste, helper de teste, regra de lint); só o que não dá para automatizar vira uma linha em `docs/lessons.md`. Uma lição que se repete em dois projetos é proposta para o plugin, como princípio geral, no relatório de fechamento.

### Plano vivo

O plano traz código completo só nas regras puras e nas migrations e camada de dados; as tarefas de tela levam interfaces, critérios de aceite e testes, e o `dev` segue o padrão que já existe no código. Quando o código diverge do plano com razão (migration renumerada, contagem de testes, um padrão adotado), o `manager` acrescenta uma linha na seção `## Errata` no fim do plano, a única parte que ele edita, e todo brief do `dev` manda ler a errata.

### Hook de segredos no commit

- `python "<clone>/plugins/pipeline/hooks/pre-commit-secret-scan.py" --install-pre-commit` (o `kickoff` roda isso, com a sua permissão).
- Varre o índice que o git está commitando (`git diff --cached` com o `GIT_INDEX_FILE` que o git define), com a allowlist lida desse índice. Um `pre-commit` que já existia vira `pre-commit.pipeline-chained` e roda antes; se ele falhar, o commit para.
- É do lado do cliente e para acidentes: `--no-verify`, commits por encanamento (`commit-tree`, `rebase`) ou um script passam por fora. A última linha é a proteção do servidor: **ative o push protection do secret scanning do GitHub** (ou o equivalente do seu provedor) em cada repositório.
- O `gate.py` é a checagem final antes do merge, mas nada bloqueia o push: o `manager` só faz push quando você pede.

### Falso positivo no scan de segredos

O hook bloqueia o commit e lista cada achado com o arquivo e uma impressão digital (fingerprint), por exemplo:

```
- possible generic API key/secret/token assignment in db/seed.sql (fingerprint ed29c450272198d3fe54a8f66fa145022361507670c0ce8f2e0cac0cad46ca03)
```

Se aquela linha **não** é um segredo, libere só ela:

1. Copie o fingerprint da mensagem de bloqueio. Para listar os fingerprints das linhas sinalizadas, rode na raiz do repositório:
   ```
   git diff --cached | python "<clone>/plugins/pipeline/hooks/pre-commit-secret-scan.py" --fingerprint
   ```
   Para commits já feitos, use `git show <commit>`; para um arquivo inteiro, informe o caminho dele relativo à raiz do repositório: `python ... --fingerprint --path db/seed.sql < db/seed.sql`.
2. Acrescente você mesmo uma linha em `.pipeline-secrets-allow` na raiz do repositório, com o motivo:
   ```
   ed29c450272198d3fe54a8f66fa145022361507670c0ce8f2e0cac0cad46ca03  # seed de teste, não é credencial
   ```
3. Coloque o arquivo no stage: `git add .pipeline-secrets-allow`. Depois peça ao agente para fazer o commit de novo (o `.pipeline-secrets-allow` entra junto).

Regras:
- A entrada só vale depois de estar no stage: o commit lê o `.pipeline-secrets-allow` do índice. Uma entrada que existe só no arquivo de trabalho é ignorada.
- O fingerprint é o sha256 do caminho do arquivo mais a linha com os espaços normalizados. Mudar o conteúdo da linha, ou a mesma linha em outro arquivo, exige uma nova entrada; só reindentar não exige.
- Cada entrada libera só aquela linha exata daquele arquivo. As outras continuam sendo verificadas.
- Não existe supressão por comentário no código.
- Quem adiciona entradas é você, não o agente: o `kickoff` põe `Edit(.pipeline-secrets-allow)` e `Write(.pipeline-secrets-allow)` em `permissions.deny`. O arquivo é versionado, e o `gate` confere que cada entrada nova da branch cobre uma linha que não é credencial de verdade.
- Um segredo de verdade nunca vai para a allowlist: remova-o e troque-o (rotacione).

O scan já não sinaliza auto-atribuição de uma coluna a ela mesma, nomes qualificados (`t.col`, `excluded.col`), palavras-chave SQL, identificadores escritos (`new_password_value`, `DEFAULT_API_KEY_NAME`, `hashedPasswordValue`: com `_`, ou camelCase em que cada parte tem ao menos duas minúsculas e uma vogal, até 40 caracteres) e referências a variáveis de ambiente (`process.env.X`, `${VAR}`, `$VAR`, `os.environ[...]`, `os.getenv(...)`, `import.meta.env.X`, `%VAR%`). Continuam bloqueando: valores literais entre aspas com cara de segredo (um placeholder só é aceito quando é o valor inteiro, como `changeme`, `example`, `xxxx...`, ou começa com `your_`, `your-` ou `<`); sequências sem `_` de 16 caracteres ou mais em uma só caixa ou com caixa alternada (`xKqPz...`); valores em que quase todo caractere aparece uma vez só (entropia de Shannon de 3,5 bits/caractere ou mais e perto do máximo para o tamanho); e, sob chaves `password`/`passwd`/`secret`, frases com `_` que não citam nenhuma palavra de código (`correct_horse_battery_staple` bloqueia, `user_input_value` passa).

### Kickoff: núcleo e allowlist de comandos

O `kickoff` instala só o que não depende de stack: hook de segredos, `.gitignore`, `docs/` (com `lessons.md`), `CLAUDE.md` e grafo de conhecimento. Não detecta stack nem instala configuração de framework, banco ou testes de interface: o setup do stack é desenhado pelo projeto, conferindo antes as versões e flags atuais no gerenciador de pacotes, no `--help` e na documentação atual, nunca de memória.

- **Allowlist de comandos.** Cada comando completo da seção "Comandos" do `CLAUDE.md` vira uma entrada exata em `permissions.allow` do `.claude/settings.json`, para os agentes não serem barrados pelo classificador do auto mode em lint, testes ou build. Nunca um curinga (`:*`), que liberaria comandos futuros e qualquer argumento. Antes de liberar um comando, o kickoff lê o corpo dele (e dos scripts que ele chama) e recusa se aparecer um termo proibido: `db push`, `db dump`, `--linked`, `--db-url`, `link`, `migration repair`, `secrets set`, `deploy`, `publish`, `vercel`, `git push`, `rm -rf`. Também põe `Edit(.pipeline-secrets-allow)`, `Write(.pipeline-secrets-allow)` e `git commit --no-verify`/`-n` em `permissions.deny`. Nunca sobrescreve nem remove permissões existentes e mostra o diff antes.

O kickoff é idempotente: rode de novo depois do scaffold do stack (ou quando os comandos mudarem) para preencher os "Comandos" e a allowlist.

### Relatórios de qualidade

Cada entrega que o `gate.py` aprova gera `docs/quality-reports/<data>-<slug>.md`: o resultado de cada checagem, os commits da branch, o número de ciclos, as notas do ledger (Minors adiados, decisões) e as métricas da entrega (achados por ciclo e severidade, rodadas de correção, lições adicionadas e automatizadas), para ver as lições reduzindo achados de uma entrega para outra.

## Requisitos

- Claude Code com suporte a plugins.
- Python 3 (como `python` ou `python3`) e git no `PATH`. Sem Python 3, o `pre-commit` bloqueia o commit e diz por quê.
- Plugin [`superpowers`](https://github.com/obra/superpowers), instalado do marketplace oficial (`superpowers@claude-plugins-official`) e declarado como dependência.
- Opcional: [graphify](https://github.com/Graphify-Labs/graphify) (`pip install graphifyy`) para o grafo de conhecimento do projeto.

## Instalação

Adicione o marketplace uma vez por máquina. Para desenvolver o plugin, use um clone local: um marketplace de pasta local é carregado direto do disco, então as edições valem na próxima sessão.

```bash
git clone https://github.com/Lindenjefferson/claude-pipeline.git
claude plugin marketplace add ./claude-pipeline
```

Para só usar, sem editar, o marketplace pode vir direto do GitHub (repositório privado: exige acesso configurado no git):

```bash
claude plugin marketplace add Lindenjefferson/claude-pipeline
```

O marketplace se chama `linden-plugins` e contém o plugin `pipeline`.

## Uso

Habilite o plugin na pasta do projeto. O escopo `local` grava em `.claude/settings.local.json`, que não vai para o git:

```bash
claude plugin install pipeline@linden-plugins --scope local
```

Em uma sessão nessa pasta:

- peça o **kickoff** para preparar a estrutura (ele pergunta antes de instalar hooks persistentes);
- peça uma entrega, por exemplo "implementar o módulo de relatórios" ou "corrigir o bug do login", e o **manager** conduz do tamanho ao `gate.py`.

Nada é enviado ao repositório remoto sem pedido explícito: os commits ficam numa branch `feat/...` ou `fix/...`, e o merge e o push só acontecem depois do READY do `gate` e da sua aprovação.

Para desabilitar em um projeto:

```bash
claude plugin uninstall pipeline@linden-plugins --scope local
```

## Estrutura

```
.claude-plugin/marketplace.json     marketplace linden-plugins
plugins/pipeline/
  .claude-plugin/plugin.json        manifesto e dependências
  agents/                           discovery, dev, reviewer, qa
  skills/kickoff/                   skill e templates do kickoff
  skills/manager/                   skill, ledger.py, gate.py, templates/spec-checklist.md e testes
  checklists/general.md             princípios gerais (Invariantes, acesso, testes, auth, UI, auditoria)
  hooks/                            scanner de segredos (pre-commit) e testes
```

## Desenvolvimento

Validar o plugin e o marketplace:

```bash
claude plugin validate plugins/pipeline
claude plugin validate .
```

Rodar os testes (cada arquivo imprime `ALL PASS`):

```bash
for t in plugins/pipeline/hooks/tests/test_*.py plugins/pipeline/skills/manager/tests/test_*.py; do python "$t"; done
```

Observações:

- O `pre-commit` que o `kickoff` instala em cada projeto não guarda caminho: localiza o scanner pela variável `CLAUDE_PIPELINE_HOME` ou por `git config pipeline.home` (raiz do plugin, isto é, `<clone>/plugins/pipeline`). Configure uma vez por máquina com `git config --global pipeline.home "<clone>/plugins/pipeline"`. Se o clone mudar de lugar, só esse valor muda. Se o scanner não for encontrado, o commit é bloqueado com uma mensagem, nunca liberado em silêncio.
- Projetos preparados antes da 1.6.0 têm também um `pre-push` do plugin: ele passou a não fazer nada. Rode em cada um `python "<clone>/plugins/pipeline/hooks/pre-commit-secret-scan.py" --install-pre-commit`, que atualiza o `pre-commit` e remove esse `pre-push` (um `pre-push` de outra origem fica). O `git config pipeline.gate` e o arquivo `gate-approved` deixaram de ser usados e podem ser apagados.
- A 2.0.0 e a 2.1.0 trocaram o formato do ledger: um ledger iniciado por uma versão anterior não é lido pelo `ledger.py` novo. Termine a entrega em andamento antes de atualizar, ou comece um ledger novo. A 2.2.0 lê os ledgers da 2.1.0: um `fix-N` gravado depois de um ciclo fechado passa a contar nesse ciclo, e as entradas antigas só com `--open` aparecem nas métricas como achados bloqueantes sem divisão.
- A 2.2.0 tirou os templates de stack do `kickoff` e os checklists de stack (`auth`, `nextjs-react`, `postgres-supabase`). Projetos preparados antes continuam com os arquivos que o kickoff já instalou; as regras de stack que ainda valem devem ir para o `CLAUDE.md` ou o `docs/lessons.md` do projeto.
- Instalações feitas a partir do GitHub ficam fixas na `version` de `plugin.json`: aumente a versão a cada release para que `claude plugin update` traga as mudanças.
- Os arquivos são mantidos em LF (`.gitattributes`).

## Licença

Projeto pessoal e privado. Todos os direitos reservados.
