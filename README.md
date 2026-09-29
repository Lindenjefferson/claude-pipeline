# claude-pipeline

Plugin do [Claude Code](https://code.claude.com) para desenvolver projetos pessoais num fluxo curto e circular: planejar, implementar com testes, revisar, validar e só então deixar o código sair da máquina. Inspirado no [ECC](https://github.com/affaan-m/ecc) (o pipeline `orch-*`, o `code-reviewer` e o `verification-loop`), em versão enxuta.

O plugin é habilitado **por projeto**, nunca globalmente: onde não está ativo, nenhum agente ou skill dele é carregado.

## Como funciona

```
tamanho → (spec) → plano ✋ → por tarefa: dev → reviewer → qa ↺ → gate → merge/push ✋
```

1. **`pipeline:kickoff`** prepara o projeto: `CLAUDE.md`, `docs/`, `.gitignore`, o hook `pre-commit` de segredos, as permissões dos agentes e, conforme o stack, Playwright e a base de privilégios do Supabase.
2. **`pipeline:manager`** classifica o pedido como pequeno, padrão ou grande, e isso decide quantas etapas rodam. Nos grandes há spec (com `discovery` quando existem fontes brutas); nos padrões e grandes, um plano que você aprova (✋ 1).
3. Cada tarefa passa pelo laço **`dev` → `reviewer` → `qa`**. O `dev` implementa em TDD (red, green, refactor), atualiza a doc do módulo e commita na branch da feature. O `reviewer` revisa o diff da tarefa com os checklists do stack. O `qa` roda os testes e confere os critérios de aceite. Achados voltam ao `dev`; depois de 3 rodadas sem resolver, o `manager` pergunta a você.
4. O **`gate`** roda tudo localmente: ledger completo, build, tipos, lint, testes, scan de segredos em todo o histórico da branch e revisão do diff. Responde READY ou NOT READY e, se READY, grava o relatório de qualidade.
5. Você decide o merge e o push (✋ 2). Nada sai da máquina sem esse pedido.

## Componentes

| Componente | Função |
|---|---|
| `pipeline:kickoff` | Prepara um projeto novo ou existente para o fluxo. |
| `pipeline:manager` | Conduz a entrega e mantém o ledger (`ledger.py`). |
| `pipeline:discovery` | Extrai fatos das fontes brutas (planilhas, apps de referência, documentos) antes do design. |
| `pipeline:dev` | Implementa uma tarefa: código, migrations e a doc do módulo, sempre com o teste primeiro. |
| `pipeline:reviewer` | Revisa o diff da tarefa (ou o spec, antes do código): corretude, testes, segurança, banco/RLS, trilha de auditoria e UI. Só reporta o que consegue provar, com arquivo e linha e o cenário de falha; zero achados é um resultado válido. |
| `pipeline:qa` | Roda os testes de verdade e confere os critérios de aceite, no navegador quando há tela. |
| `pipeline:gate` | Checagem final local e relatório de qualidade. |
| Hook de segredos | `pre-commit` nativo do git, instalado pelo `kickoff`: bloqueia arquivos `.env` e linhas com cara de segredo (chaves de nuvem, tokens, chaves privadas, JWT que não seja a chave pública `anon`, `password`/`secret` com valor literal). É uma trava contra acidente: `git commit --no-verify` pula o hook, e o `kickoff` nega esse comando aos agentes. |

### Ledger

`.superpowers/ledger.jsonl` (fora do git) guarda uma linha por execução de agente: tarefa, agente, veredito, achados abertos, commit e rodada. `ledger.py status` mostra, por tarefa, o que falta: o reviewer ainda não viu o último commit do dev, o qa ainda não rodou depois da revisão, uma reprovação voltou para o dev, ou 3 rodadas sem resolver. `status --check` é o que o `gate` usa para saber se todas as tarefas fecharam. As decisões que o `manager` toma no seu lugar (um achado descartado, um Minor adiado) ficam como notas.

### Checklists e lições

`checklists/` tem as regras por stack (`auth`, `nextjs-react`, `postgres-supabase`, `general`), cada uma com os caminhos a que se aplica. O `dev` segue as que batem com os arquivos da tarefa e o `reviewer` confere. Quando um erro Critical ou Important vem de algo que uma regra escrita teria evitado, o `manager` acrescenta uma linha em `docs/lessons.md` do projeto, que o `dev` e o `reviewer` leem a cada tarefa.

### Hook de segredos no commit

- `python "<clone>/plugins/pipeline/hooks/pre-commit-secret-scan.py" --install-pre-commit` (o `kickoff` roda isso, com a sua permissão).
- Varre o índice que o git está commitando (`git diff --cached` com o `GIT_INDEX_FILE` que o git define), com a allowlist lida desse índice. Um `pre-commit` que já existia vira `pre-commit.pipeline-chained` e roda antes; se ele falhar, o commit para.
- É do lado do cliente e para acidentes: `--no-verify`, commits por encanamento (`commit-tree`, `rebase`) ou um script passam por fora. A última linha é a proteção do servidor: **ative o push protection do secret scanning do GitHub** (ou o equivalente do seu provedor) em cada repositório.
- O `gate` continua como etapa do `manager` (verificação final e relatório de qualidade), mas nada bloqueia o push: o `manager` só faz push quando você pede.

### Falso positivo no scan de segredos

O hook bloqueia o commit e lista cada achado com o arquivo e uma impressão digital (fingerprint), por exemplo:

```
- possible generic API key/secret/token assignment in supabase/seed.sql (fingerprint ed29c450272198d3fe54a8f66fa145022361507670c0ce8f2e0cac0cad46ca03)
```

Se aquela linha **não** é um segredo, libere só ela:

1. Copie o fingerprint da mensagem de bloqueio. Para listar os fingerprints das linhas sinalizadas, rode na raiz do repositório:
   ```
   git diff --cached | python "<clone>/plugins/pipeline/hooks/pre-commit-secret-scan.py" --fingerprint
   ```
   Para commits já feitos, use `git show <commit>`; para um arquivo inteiro, informe o caminho dele relativo à raiz do repositório: `python ... --fingerprint --path supabase/seed.sql < supabase/seed.sql`.
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

### Kickoff: complementos por stack e allowlist de comandos

O `kickoff` sempre instala o núcleo (hook de segredos, `.gitignore`, `docs/`, `CLAUDE.md`, grafo de conhecimento). Depois detecta o stack pelos arquivos do projeto e acrescenta convenções específicas só para o que encontrar, para o contexto dos agentes ficar pequeno:

- **Allowlist de comandos.** Junta os comandos do próprio projeto (seção "Comandos" do `CLAUDE.md` e scripts do `package.json`) em `permissions.allow` do `.claude/settings.json`, para os agentes não serem barrados pelo classificador do auto mode em lint, testes, build ou comandos de banco. Cada script vira uma entrada exata (`Bash(npm run db:types)`), nunca um curinga como `Bash(npm run db:*)`, que liberaria scripts futuros e qualquer argumento. Antes de liberar um script, o kickoff lê o corpo dele (e dos scripts que ele chama) e recusa se aparecer um termo proibido: `db push`, `db dump`, `--linked`, `--db-url`, `link`, `migration repair`, `secrets set`, `deploy`, `vercel`, `git push`, `rm -rf`. Rode o kickoff de novo sempre que os scripts mudarem. Também põe `Edit(.pipeline-secrets-allow)` e `Write(.pipeline-secrets-allow)` em `permissions.deny`. Nunca sobrescreve nem remove permissões existentes e mostra o diff antes.
- **Next.js 16 ou superior.** Põe `agentRules: false` para o `next dev` não reescrever o `CLAUDE.md`, registra que a interceptação vive em `proxy.ts` e, em projetos mobile-first, dá aos primitivos do shadcn alvos de toque de 44px no mobile (`h-11 md:h-N`). Propõe, como diff para você aprovar (igual à allowlist), o Playwright do próprio projeto: `@playwright/test` como devDependency na versão atual, o script `e2e:smoke` (`playwright test --grep @smoke`), um `playwright.config.ts` (testes em `e2e/`, só Chromium, `webServer` com `npm run dev` e `reuseExistingServer: true`; `E2E_BASE_URL=<url>` usa um `next dev` que já roda noutra porta sem subir outro), um spec de fumaça e as pastas de resultado no `.gitignore`. A allowlist ganha só a entrada exata `Bash(npm run e2e:smoke)`. O download do Chromium (`npx playwright install chromium`) fica com você. Se recusar, os "Comandos" do `CLAUDE.md` registram a verificação por script numa pasta temporária fora do projeto (`node <pasta>/check.mjs`) e nada entra no projeto.
- **Supabase.** Acrescenta uma migration base de privilégios (`anon` sem acesso a tabelas; `authenticated` sem truncate, references, trigger e maintain; sem privilégios em sequências; `EXECUTE` de funções revogado por padrão, inclusive para objetos futuros) e uma varredura pgTAP que falha se `anon` ou `authenticated` puderem executar função fora de uma allowlist por assinatura exata, se alguma tabela estiver sem RLS, se alguma view não tiver `security_invoker=true`, ou se `anon`/`authenticated` tiverem qualquer privilégio em materialized views ou foreign tables (o RLS não vale nelas). Os schemas verificados ficam no topo do arquivo, junto do marcador `ALLOWLIST` (padrão `public`; acrescente todo schema exposto pela API).
- **Versões atuais.** Antes de escrever comandos de scaffold, o kickoff e os planos conferem as versões e flags atuais (`npm view`, documentação) em vez de confiar na memória.

O kickoff é idempotente: rode de novo depois do scaffold de um projeto novo para aplicar os complementos.

### Relatórios de qualidade

Cada entrega que o `gate` aprova gera `docs/quality-reports/<data>-<slug>.md`: o que foi entregue, as tarefas e suas rodadas de revisão, o resultado de cada checagem, os Minors adiados e os alertas de custo (um cron novo, uma tabela grande, uma API paga).

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
- peça uma entrega, por exemplo "implementar o módulo de relatórios" ou "corrigir o bug do login", e o **manager** conduz do tamanho ao gate.

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
  agents/                           discovery, dev, reviewer, qa, gate
  skills/kickoff/                   skill e templates do kickoff
  skills/manager/                   skill, ledger.py, templates/spec-checklist.md e testes
  checklists/                       regras por stack (auth, nextjs-react, postgres-supabase, general)
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
- A 2.0.0 trocou o fluxo: um ledger iniciado por uma versão anterior não é lido pelo `ledger.py` novo. Termine a entrega em andamento antes de atualizar, ou comece um ledger novo.
- Instalações feitas a partir do GitHub ficam fixas na `version` de `plugin.json`: aumente a versão a cada release para que `claude plugin update` traga as mudanças.
- Os arquivos são mantidos em LF (`.gitattributes`).

## Licença

Projeto pessoal e privado. Todos os direitos reservados.
