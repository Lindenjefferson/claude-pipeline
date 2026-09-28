# pipeline-marketplace

Marketplace local com um plugin, `pipeline`: o fluxo multiagente pessoal. Ele é habilitado **por repo**, nunca globalmente, então projetos que não o habilitam (trabalho, eDevize) não carregam agentes, skills nem hook dele.

## O que o plugin `pipeline` traz

| Parte | Local | Função |
|---|---|---|
| Agentes | `plugins/pipeline/agents/` | `discovery`, `dev`, `db`, `security`, `audit`, `design`, `code-review`, `qa`, `docs`, `gate`. Chamados como `pipeline:<nome>`. |
| Skill `manager` | `plugins/pipeline/skills/manager/` | Orquestra uma entrega e mantém o ledger (`ledger.py`, `package.py`). |
| Skill `kickoff` | `plugins/pipeline/skills/kickoff/` | Prepara um projeto (CLAUDE.md, docs/, gitignore, grafo). |
| Hook | `plugins/pipeline/hooks/` | Escaneia segredos em `git commit` e `git push` e exige aprovação do `gate` onde há `docs/quality-reports/`. |

## Isolamento

A única chave é o plugin habilitado no repo. Sem isso, nada do plugin existe na sessão: nem agentes, nem skills, nem o hook. Os repos da eDevize não o habilitam.

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
- Testar o hook: `python plugins/pipeline/hooks/tests/test_<nome>.py` (quatro arquivos; todos imprimem `ALL PASS`).
- Não mover nem renomear esta pasta sem reinstalar: o hook `pre-push` que o `kickoff` instala nos repos aponta para o script aqui e, se não o achar, sai sem escanear (`[ -f ... ] || exit 0`). Depois de mover, rodar `claude plugin marketplace add <novo caminho>` e, em cada repo, `python <novo caminho>/plugins/pipeline/hooks/pre-commit-secret-scan.py --install-pre-push`.
- Versionado com git: commitar cada mudança no fluxo.
- Marketplace registrado com `claude plugin marketplace add <esta pasta>` (nome `linde-local`).