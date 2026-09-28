# pipeline-marketplace

Marketplace local com um plugin, `pipeline`: o fluxo multiagente pessoal. Ele é habilitado **por repo**, nunca globalmente, então projetos que não o habilitam não carregam agentes, skills nem hook dele.

## O que o plugin `pipeline` traz

| Parte | Local | Função |
|---|---|---|
| Agentes | `plugins/pipeline/agents/` | `discovery`, `dev`, `db`, `security`, `audit`, `design`, `code-review`, `qa`, `docs`, `gate`. Chamados como `pipeline:<nome>`. |
| Skill `manager` | `plugins/pipeline/skills/manager/` | Orquestra uma entrega e mantém o ledger (`ledger.py`, `package.py`). |
| Skill `kickoff` | `plugins/pipeline/skills/kickoff/` | Prepara um projeto (CLAUDE.md, docs/, gitignore, grafo). |
| Hook | `plugins/pipeline/hooks/` | Escaneia segredos em `git commit` e `git push` e exige aprovação do `gate` onde há `docs/quality-reports/`. |

## Isolamento

A única chave é o plugin habilitado no repo. Sem isso, nada do plugin existe na sessão: nem agentes, nem skills, nem o hook.

## O que é garantido e o que não é

- **Garantido pelo hook** (em sessões com o plugin ativo): commit e push feitos pelo Claude pelas ferramentas Bash e PowerShell passam pelo scan de segredos, e o push exige a aprovação do `gate` onde há `docs/quality-reports/`. O hook entende comandos encadeados e aninhados, `bash -c` / `powershell -Command`, prefixos de variável, `command`/`env`, caminho completo do git e opções globais (`-c`, `--no-pager`, `-C`). Custa ~40 ms por comando.
- **Garantido pelo git** (onde o `kickoff` instalou o `pre-push`): nenhum push com segredo sai da máquina, por qualquer caminho.
- **Não garantido**: um script que chama git por dentro, e comandos digitados por você no terminal (só o `pre-push` os cobre). A aprovação do `gate` é uma linha em `.git/gate-approved` que qualquer sessão consegue escrever: o bloqueio impede esquecer o gate, não burlá-lo de propósito. O processo do `manager` (ordem dos agentes, rodadas, rotas) depende de o modelo segui-lo; o ledger valida o que recebe, mas não o que deixou de ser registrado.

## Usar em um projeto novo ou existente

Na pasta do projeto (uma vez):

```bash
claude plugin install pipeline@linde-local --scope local
```

Abrir uma sessão nessa pasta e pedir o `kickoff`. Ele cria a estrutura, e pergunta antes de instalar hooks persistentes.

`--scope local` grava em `.claude/settings.local.json` do projeto (ignorado pelo git). Para desligar: `claude plugin uninstall pipeline@linde-local --scope local`.

## Manutenção

- Fonte única: esta pasta. `${CLAUDE_PLUGIN_ROOT}` aponta para `plugins/pipeline/` aqui, então editar os arquivos vale na próxima sessão.
- Validar: `claude plugin validate <pasta>`.
- Testes (cada arquivo imprime `ALL PASS`): `python plugins/pipeline/hooks/tests/test_<nome>.py` (cinco arquivos, o hook) e `python plugins/pipeline/skills/manager/tests/test_<nome>.py` (`ledger` e `package`).
- Não mover nem renomear esta pasta sem reinstalar: o hook `pre-push` que o `kickoff` instala nos repos aponta para o script aqui e, se não o achar, sai sem escanear (`[ -f ... ] || exit 0`). Depois de mover, rodar `claude plugin marketplace add <novo caminho>` e, em cada repo, `python <novo caminho>/plugins/pipeline/hooks/pre-commit-secret-scan.py --install-pre-push`.
- Versionado com git: commitar cada mudança no fluxo. `.gitattributes` mantém tudo em LF.
- Depende do plugin `superpowers@claude-plugins-official` (declarado em `plugin.json`; `marketplace.json` libera a dependência de outro marketplace). Sem ele ativo, o `pipeline` não carrega, em vez de quebrar no meio de uma entrega.
- Marketplace registrado com `claude plugin marketplace add <esta pasta>` (nome `linde-local`).