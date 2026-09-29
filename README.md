# claude-pipeline

Plugin do [Claude Code](https://code.claude.com) que conduz entregas de software (módulos, features e correções) por uma equipe de agentes especializados, com revisão independente, registro de progresso e um gate final antes de qualquer código sair da máquina.

O plugin é habilitado **por projeto**, nunca globalmente: onde não está ativo, nenhum agente, skill ou hook dele é carregado.

## Como funciona

```
discovery → brainstorming → revisão do spec → plano → dev / db → docs + revisores → gate
```

1. **`pipeline:kickoff`** prepara o projeto: `CLAUDE.md`, convenção de documentação em `docs/`, `.gitignore`, grafo de conhecimento opcional e o hook `pre-push` de segredos.
2. **`pipeline:manager`** conduz cada entrega: planeja, despacha os agentes, encaminha cada problema ao dono do arquivo e registra tudo em um ledger.
3. Na **revisão do spec**, antes do plano, os revisores leem o spec aprovado pelo brainstorming (ainda sem código) e ele é corrigido até todos aprovarem.
4. Os **revisores** analisam cada tarefa em paralelo, cada um no seu domínio.
5. O **`gate`** confere se todos os revisores exigidos aprovaram os commits atuais, varre o histórico em busca de segredos e, ao aprovar, grava um relatório de qualidade com nota.

## Componentes

| Componente | Função |
|---|---|
| `pipeline:kickoff` | Prepara um projeto novo ou existente para o fluxo. |
| `pipeline:manager` | Orquestra uma entrega e mantém o ledger (`ledger.py`) e os pacotes de revisão (`package.py`). |
| `pipeline:discovery` | Extrai e estrutura fatos das fontes brutas antes do design. |
| `pipeline:dev` | Implementa uma tarefa do plano. |
| `pipeline:db` | Schema, migrations e políticas de acesso; também revisa essas mudanças. |
| `pipeline:docs` | Mantém a documentação viva em `docs/`. |
| `pipeline:code-review` | Corretude, duplicação, testes e complexidade. |
| `pipeline:security` | Autenticação, autorização, segredos e validação de entrada. |
| `pipeline:audit` | Rastreabilidade de escritas sensíveis e erros silenciados. |
| `pipeline:design` | Consistência de UI e acessibilidade. |
| `pipeline:qa` | Roda os testes e valida os critérios de aceite de ponta a ponta. |
| `pipeline:gate` | Verificação final e relatório de qualidade. |
| Hook de segredos | Bloqueia `git commit` e `git push` do Claude que contenham segredos e exige a aprovação do `gate` para o push em projetos com `docs/quality-reports/`. No commit, considera também o que o mesmo comando adiciona (`git add ... && git commit`), os arquivos passados ao commit e o `-a`; no push, os refs enviados (refspecs, tags, `--all`), não só o `HEAD`. Entende aliases do git. |

### Revisão do spec

Um erro de design (uma política de acesso no escopo errado, um convite que atravessa a fronteira entre contas, uma escrita financeira sem rastro) pego no spec custa uma edição; pego depois do código, custa uma migration nova e retrabalho. Por isso, depois que o brainstorming aprova o spec e antes do `writing-plans`, o `manager` despacha em paralelo os revisores do domínio do spec, em **modo spec** (somente leitura, entrada é o documento, não um diff):

| O spec toca | Revisor |
|---|---|
| Auth, permissões, sessões, segredos, RLS | `security` |
| Schema, migrations, RLS, queries | `db` (modo revisor) |
| Escrita de dados sensíveis ou financeiros | `audit` |
| Telas e fluxos de UI | `design` |
| Contratos e interfaces complexos | `code-review` (opcional) |

- **Obrigatória** quando o spec toca auth, permissões, RLS, schema/migrations, segredos ou dados sensíveis/financeiros; nos demais casos o `manager` pergunta ao usuário. Quando não roda, o motivo fica registrado como nota `ruling` da tarefa `spec`.
- Cada achado aponta a seção do spec, o cenário concreto e a correção proposta no design. Achados Critical/Important são corrigidos no spec pela sessão principal (decisões de produto vão ao usuário) e os mesmos revisores rodam de novo até aprovar, com no máximo 5 rodadas. Minors são aplicados ou registrados como `deferred`.
- Evidência: relatórios em `.superpowers/reports/spec-<agente>-r<rodada>.md` e entradas no ledger com a tarefa `spec` e o caminho do spec revisado. Esses achados ficam fora das notas de qualidade (foram pegos antes do código) e aparecem à parte no relatório do `gate`.
- O `gate` bloqueia a entrega que toca esses domínios sem revisão de spec aprovada nem nota explicando a ausência, e pede nova revisão se o spec mudou depois dela.

O spec responde, antes da revisão, às seções de [`skills/manager/templates/spec-checklist.md`](plugins/pipeline/skills/manager/templates/spec-checklist.md): trilha de auditoria das escritas sensíveis, estados de UI, concorrência e invariantes, auth (oráculos de conta, pré-cadastro, confirmar ≠ logar, sessões), privilégios padrão, tabela de códigos de erro e plano de testes com alvos de mutação. Seção sem resposta no domínio de um revisor é achado.

### Ledger

Cada entrega tem um ledger em `.superpowers/ledger.jsonl`, escrito só pelo `ledger.py`. Ele registra, por tarefa e agente, o intervalo de commits revisado, o veredito, os problemas encontrados e em aberto e as decisões tomadas. Linhas inválidas são recusadas na entrada, e `status --head HEAD` aponta revisões que ficaram para trás de commits novos (para a tarefa `spec`, só quando o próprio spec mudou).

- `save-report` grava o relatório do agente, sem transcrição à mão, em `.superpowers/reports/<tarefa>-<agente>-r<N>.md` (rodada automática contada por tarefa, agente e papel, como no `append`; nunca sobrescreve) e imprime o caminho para o `append`. O `db` exige `--role implementer|reviewer`, e a revisão dele vai para `<tarefa>-db-review-r<N>.md`.
- `--head`/`--from` aceitam qualquer ref (`HEAD`) e gravam o SHA.
- O `append` valida o relatório de `dev`, `db` e `docs`: recusa relatório sem linha `LEDGER`, curto demais (200 caracteres em `DONE`/`DONE_WITH_CONCERNS`; motivo de 40 nos demais vereditos) ou "placeholder", relatório de `dev`/`db` sem o SHA do commit, e arquivo citado que não está em `git diff FROM..HEAD` (`--allow-unlisted '<motivo>'` para exceções; o motivo é obrigatório e vira nota de decisão).

### Briefs, adendos e lições

- `package.py brief` aceita ids como `T1.2`, `3` e `A-1`, e anexa ao texto da tarefa os adendos de `.superpowers/briefs/<tarefa>.addenda/*.md` e `.superpowers/briefs/all.addenda/*.md`. O manager nunca edita um brief gerado, então reextrair não perde nada.
- **Lições**: regras atômicas (até 280 caracteres) que teriam evitado um achado. As globais ficam versionadas no plugin, em `plugins/pipeline/lessons/<stack>.jsonl` (`postgres-supabase`, `nextjs-react`, `auth`, `general`), e as da entrega em `.superpowers/lessons.jsonl`, escritas só por `ledger.py lesson add|mark|list|promote|sync`. O `brief` injeta até 6 lições (8000 caracteres) cujos `paths` casam com os arquivos da tarefa, ordenadas por relevância (quantos arquivos da tarefa casam e quão específico é o glob), depois `priority` (opcional, nas lições centrais de RLS, `security definer` e `revoke`), depois `held - 2*recurred` com bônus para as da entrega. Cada lição conta `injected`, `held` (preveniu) e `recurred` (reincidiu); regerar um brief que já existe não reconta. Os contadores das lições globais ficam numa linha de override na entrega, e só vão para os arquivos globais com `lesson sync`. No fechamento, o manager mostra cada lição da entrega e só promove para o global as que o usuário aprovar, uma a uma, e só sincroniza os contadores se o usuário aprovar.

### Checklists por stack

`plugins/pipeline/checklists/{postgres-supabase,nextjs-react,auth}.md`, cada um com frontmatter `stack`, `paths` e `agents`. O `package.py review` lista no cabeçalho do pacote os checklists cujos `paths` casam com os arquivos alterados (lockfiles ficam fora do diff, com as linhas de nome, versão, `resolved` e `integrity` alteradas numa seção `## Dependency changes`), e cada revisor abre os que citam o seu papel. Item não atendido é achado como outro qualquer.

### Revisores e implementadores

- Revisores (`code-review`, `security`, `db` revisor, `audit`, `design`) passam por um *pre-report gate*: Critical/Important exigem prova (arquivo:linha e cenário concreto ou reprodução), zero achados é resultado válido, sem enchimento de estilo.
- O `code-review` sempre roda mutação independente em tarefas com migrations, funções SQL ou módulos de regra pura (NULL, fronteira `>=`/`>`, janela de tempo, filtro de escopo, auditoria em laço, checagem de permissão) e relata as sobreviventes.
- `dev` e `db` seguem RED primeiro (o teste rodou e falhou pelo motivo certo antes da correção), listam os arquivos a partir de `git show --stat`, gravam só UTF-8, sobem servidores só em background ou com `timeout`, e o `db` entrega a tabela mutação → teste que falhou.

### Falso positivo no scan de segredos

O hook bloqueia o commit (ou o push) e lista cada achado com o arquivo e uma impressão digital (fingerprint), por exemplo:

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
- A entrada só vale depois de estar no stage: o commit lê o `.pipeline-secrets-allow` do índice, e o push lê o de cada commit enviado. Uma entrada que existe só no arquivo de trabalho é ignorada.
- O fingerprint é o sha256 do caminho do arquivo mais a linha com os espaços normalizados. Mudar o conteúdo da linha, ou a mesma linha em outro arquivo, exige uma nova entrada; só reindentar não exige.
- Cada entrada libera só aquela linha exata daquele arquivo. As outras continuam sendo verificadas.
- Não existe supressão por comentário no código.
- Quem adiciona entradas é você, não o agente. O hook do plugin nega ao agente editar o arquivo (Write/Edit/MultiEdit/NotebookEdit) e qualquer comando Bash/PowerShell que o altere, coloque no stage, mova ou restaure (ler com `git diff`, `git show` ou `cat` continua permitido); o `kickoff` também põe `Edit(.pipeline-secrets-allow)` e `Write(.pipeline-secrets-allow)` em `permissions.deny`. O arquivo é versionado: mudanças nele exigem a revisão de `security`, e o `gate` lista cada entrada nova no relatório com a linha que ela cobre.
- Um segredo de verdade nunca vai para a allowlist: remova-o e troque-o (rotacione).

O scan já não sinaliza auto-atribuição de uma coluna a ela mesma, nomes qualificados (`t.col`, `excluded.col`), palavras-chave SQL, identificadores escritos (`new_password_value`, `DEFAULT_API_KEY_NAME`, `hashedPasswordValue`: com `_`, ou camelCase em que cada parte tem ao menos duas minúsculas e uma vogal, até 40 caracteres) e referências a variáveis de ambiente (`process.env.X`, `${VAR}`, `$VAR`, `os.environ[...]`, `os.getenv(...)`, `import.meta.env.X`, `%VAR%`). Continuam bloqueando: valores literais entre aspas com cara de segredo (um placeholder só é aceito quando é o valor inteiro, como `changeme`, `example`, `xxxx...`, ou começa com `your_`, `your-` ou `<`); sequências sem `_` de 16 caracteres ou mais em uma só caixa ou com caixa alternada (`xKqPz...`); valores em que quase todo caractere aparece uma vez só (entropia de Shannon de 3,5 bits/caractere ou mais e perto do máximo para o tamanho); e, sob chaves `password`/`passwd`/`secret`, frases com `_` que não citam nenhuma palavra de código (`correct_horse_battery_staple` bloqueia, `user_input_value` passa).

### Kickoff: complementos por stack e allowlist de comandos

O `kickoff` sempre instala o núcleo (hooks, `.gitignore`, `docs/`, `CLAUDE.md`, grafo de conhecimento). Depois detecta o stack pelos arquivos do projeto e acrescenta convenções específicas só para o que encontrar, para o contexto dos agentes ficar pequeno:

- **Allowlist de comandos.** Junta os comandos do próprio projeto (seção "Comandos" do `CLAUDE.md` e scripts do `package.json`) em `permissions.allow` do `.claude/settings.json`, para os agentes não serem barrados pelo classificador do auto mode em lint, testes, build ou comandos de banco. Cada script vira uma entrada exata (`Bash(npm run db:types)`), nunca um curinga como `Bash(npm run db:*)`, que liberaria scripts futuros e qualquer argumento. Antes de liberar um script, o kickoff lê o corpo dele (e dos scripts que ele chama) e recusa se aparecer um termo proibido: `db push`, `db dump`, `--linked`, `--db-url`, `link`, `migration repair`, `secrets set`, `deploy`, `vercel`, `git push`, `rm -rf`. Rode o kickoff de novo sempre que os scripts mudarem. Também põe `Edit(.pipeline-secrets-allow)` e `Write(.pipeline-secrets-allow)` em `permissions.deny`. Nunca sobrescreve nem remove permissões existentes e mostra o diff antes.
- **Next.js 16 ou superior.** Põe `agentRules: false` para o `next dev` não reescrever o `CLAUDE.md`, registra que a interceptação vive em `proxy.ts` e, em projetos mobile-first, dá aos primitivos do shadcn alvos de toque de 44px no mobile (`h-11 md:h-N`).
- **Supabase.** Acrescenta uma migration base de privilégios (`anon` sem acesso a tabelas; `authenticated` sem truncate, references, trigger e maintain; sem privilégios em sequências; `EXECUTE` de funções revogado por padrão, inclusive para objetos futuros) e uma varredura pgTAP que falha se `anon` ou `authenticated` puderem executar função fora de uma allowlist por assinatura exata, se alguma tabela estiver sem RLS, se alguma view não tiver `security_invoker=true`, ou se `anon`/`authenticated` tiverem qualquer privilégio em materialized views ou foreign tables (o RLS não vale nelas). Os schemas verificados ficam no topo do arquivo, junto do marcador `ALLOWLIST` (padrão `public`; acrescente todo schema exposto pela API).
- **Versões atuais.** Antes de escrever comandos de scaffold, o kickoff e os planos conferem as versões e flags atuais (`npm view`, documentação) em vez de confiar na memória.

O kickoff é idempotente: rode de novo depois do scaffold de um projeto novo para aplicar os complementos.

### Relatórios de qualidade

Toda entrega aprovada gera `docs/quality-reports/<data>-<slug>.md` e uma linha em `docs/quality-reports/history.jsonl`, com notas por dimensão (segurança, auditoria, design, code review, banco de dados e testes) calculadas a partir do ledger. Isso permite acompanhar a evolução da qualidade do projeto ao longo do tempo.

## Requisitos

- Claude Code com suporte a plugins.
- Python 3 (como `python` ou `python3`) e git no `PATH`. Sem Python 3, o hook do Claude avisa no stderr e deixa passar, e o `pre-push` bloqueia.
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
- peça uma entrega, por exemplo "implementar o módulo de relatórios", e o **manager** conduz do plano ao gate.

Nada é enviado ao repositório remoto sem pedido explícito: os commits ficam em uma branch de worktree, e o merge e o push só acontecem depois da aprovação do `gate`.

Para desabilitar em um projeto:

```bash
claude plugin uninstall pipeline@linden-plugins --scope local
```

## Estrutura

```
.claude-plugin/marketplace.json     marketplace linden-plugins
plugins/pipeline/
  .claude-plugin/plugin.json        manifesto e dependências
  agents/                           os 10 agentes
  skills/kickoff/                   skill e templates do kickoff
  skills/manager/                   skill, ledger.py, package.py, templates/spec-checklist.md e testes
  checklists/                       checklists por stack, listados no pacote de revisão
  lessons/                          lições globais por stack (JSONL), injetadas nos briefs
  hooks/                            hooks.json, scanner de segredos e testes
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

- O hook `pre-push` que o `kickoff` instala em cada projeto não guarda caminho: ele localiza o scanner pela variável `CLAUDE_PIPELINE_HOME` ou por `git config pipeline.home` (raiz do plugin, isto é, `<clone>/plugins/pipeline`). Configure uma vez por máquina com `git config --global pipeline.home "<clone>/plugins/pipeline"`. Se o clone mudar de lugar, só esse valor muda, sem reinstalar o hook nos projetos. Se o scanner não for encontrado, o push é bloqueado com uma mensagem, nunca liberado em silêncio.
- Projetos com o `pre-push` instalado antes da 1.2.0 chamam `python` fixo: rode de novo `python "<clone>/plugins/pipeline/hooks/pre-commit-secret-scan.py" --install-pre-push` em cada um para trocar pelo shim novo (ele só sobrescreve o hook que ele mesmo instalou).
- O registro de aprovação (`<git-common-dir>/gate-approved`) protege contra acidentes, não contra um agente mal-intencionado: qualquer processo com shell no repositório pode escrever nele. Quem garante a aprovação é o fluxo do `manager`, não o arquivo.
- Instalações feitas a partir do GitHub ficam fixas na `version` de `plugin.json`: aumente a versão a cada release para que `claude plugin update` traga as mudanças.
- Os arquivos são mantidos em LF (`.gitattributes`).

## Licença

Projeto pessoal e privado. Todos os direitos reservados.
