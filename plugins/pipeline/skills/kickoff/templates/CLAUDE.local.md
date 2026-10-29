# {{PROJECT_NAME}} — este computador

O Claude Code lê este arquivo junto com o `CLAUDE.md`, e ele fica fora do git: aqui vai só o que vale para esta máquina (outra máquina tem o seu). O que vale para o projeto em qualquer lugar fica no `CLAUDE.md`.

## Execução em paralelo

- Quanto uma cópia ocupa no pico, com a preparação, o armazenamento de dados e a verificação (build e suíte; a suíte inteira do `qa` à parte, se for maior): _(memória `X` GB, disco `Y` GB; ou "a medir")_
- Memória livre mínima para despachar uma cópia ou um `qa`: _(GB, entre crases; abaixo disso o `manager` espera)_
- Disco livre mínimo: _(GB, entre crases; abaixo disso o `status` avisa)_
- Com o usuário usando a máquina: _(quantas cópias pesadas ao mesmo tempo, entre crases, e a memória livre que já conta como falta)_

## Uso da conta

O mod do plugin grava o uso da assinatura (janela de 5 horas e semana) ao lado do ledger, e o `manager` economiza ou pausa por ele. Sem estas linhas valem os números padrão.

- Economia a partir de quanto uso, em %: _(padrão 60: o `reviewer` passa a sonnet e roda uma cópia por vez)_
- Pausa a partir de quanto uso da janela de 5 horas, em %: _(padrão 85: nada novo é despachado até o reset)_
- Pausa a partir de quanto uso da semana, em %: _(padrão 95)_
- Sempre econômico: _(sim, entre crases, numa conta Pro, para economizar desde o início; padrão não)_
