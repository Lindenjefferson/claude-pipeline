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

### Ledger

Cada entrega tem um ledger em `.superpowers/ledger.jsonl`, escrito só pelo `ledger.py`. Ele registra, por tarefa e agente, o intervalo de commits revisado, o veredito, os problemas encontrados e em aberto e as decisões tomadas. Linhas inválidas são recusadas na entrada, e `status --head HEAD` aponta revisões que ficaram para trás de commits novos (para a tarefa `spec`, só quando o próprio spec mudou).

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
  skills/manager/                   skill, ledger.py, package.py e testes
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
