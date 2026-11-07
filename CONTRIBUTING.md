# Contribuir

O caminho mínimo para mudar o plugin e abrir um PR. As premissas e as regras completas estão no [`CLAUDE.md`](CLAUDE.md); o mapa de onde cada coisa mora, na seção [Mapa](CLAUDE.md#mapa-onde-cada-informação-mora) dele.

## Preparar o clone

```bash
git clone https://github.com/Lindenjefferson/foreman.git
cd foreman

# o hook de segredos mora em .git/hooks e não viaja no clone: instale-o uma vez
python plugins/foreman/hooks/pre-commit-secret-scan.py --install-pre-commit
```

Você precisa de Python 3, git e o [Claude Code](https://code.claude.com) no `PATH` (no Windows, os comandos rodam no Git Bash). As suítes criam repositórios git de teste, então o git precisa de identidade configurada (`git config user.email` e `user.name`).

Para testar o plugin de verdade, carregue o clone do disco num projeto de teste: `claude plugin marketplace add ./foreman` e `claude plugin install foreman@foreman --scope local`. As edições valem na próxima sessão (ou depois de `/reload-plugins`).

## Testar e validar

Os cinco comandos do `CLAUDE.md`, rodados antes de abrir o PR (não há CI):

```bash
for t in plugins/foreman/hooks/tests/test_*.py plugins/foreman/skills/manager/tests/test_*.py; do sh plugins/foreman/hooks/python.sh "$t"; done
(cd plugins/foreman && claude plugin test)
claude plugin validate plugins/foreman
claude plugin validate .
python plugins/foreman/hooks/pre-commit-secret-scan.py --range main..HEAD
```

Cada suíte Python roda sozinha, sem pytest, e termina em `ALL PASS`. As dos hooks levam pouco mais de um minuto no total (`test_bash_guard.py` é a mais longa); as do manager demoram mais, porque criam repositórios e rodam comandos de verdade: `test_gate.py` uns dois minutos e `test_ledger.py` uns quatro. O laço inteiro fica em torno de sete a oito minutos. O `claude plugin test` roda os testes do mod em cerca de um segundo, e os dois `validate` conferem o manifesto e o marketplace.

## Mudar

- Branch `feat/...` ou `fix/...` a partir da `main`, entregue por PR. Mudança só de documentação (`docs/`, `README.md`, `CLAUDE.md`, este arquivo) vai numa branch `docs/...` e não sobe a versão.
- **Teste primeiro** para `ledger.py`, `gate.py`, os hooks e o mod: o teste novo falha antes da mudança, e os ledgers de versões anteriores continuam legíveis.
- Cada componente tem uma fonte de verdade, o próprio arquivo (skill, agente, docstring do script). O README e o `CLAUDE.md` ganham no máximo uma linha com link.
- Ao tocar um arquivo, remova o que ficou obsoleto ou duplicado e liste no PR o que saiu.
- Arquivos em UTF-8 e LF. Prompts de skills e agentes em inglês; README, `CLAUDE.md`, roadmap e histórico em português.
- Nunca `git commit --no-verify`: o hook de segredos barra linhas com cara de segredo, e só o dono assina a allowlist (`.foreman-secrets-allow`).
- Uma ideia nova passa pelo filtro do `CLAUDE.md` (problema conferido no código ou num ledger, de preferência com um teste que falha) e pelo [roadmap](docs/roadmap.md) antes de virar PR.

## Versão

A `version` de [`plugin.json`](plugins/foreman/.claude-plugin/plugin.json) sobe a cada release, com uma seção nova no [histórico](plugins/foreman/UPGRADING.md) que diz o que entrou, o número do PR e o parágrafo "Ao atualizar" (ou "nada muda"). Minor quando há comportamento novo; patch quando é só correção; major só quando um ledger da versão anterior deixa de ser legível. Mudança só de documentação não sobe a versão. Quem sobe a versão e faz o merge é o dono.
