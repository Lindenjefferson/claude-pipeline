# Arquitetura e padrões

Os padrões que todo código deste projeto segue, para o projeto crescer sem que cada entrega, de uma pessoa ou de um agente, invente o seu. O `dev` lê este arquivo antes de cada tarefa, o `reviewer` aponta o código que diverge dele, e um padrão novo entra aqui na mesma entrega que o adota. O `gate.py` recusa a entrega enquanto houver módulo e este arquivo ainda tiver um campo por preencher; "n/a" com o motivo é uma resposta.

## Mapa dos módulos

Um nó por documento de módulo de [`docs/`](README.md), uma seta por dependência; refeito na limpeza de cada entrega.

```mermaid
flowchart LR
  %% exemplo: cadastro --> banco
```

## Camadas e onde mora cada coisa

_(as camadas do código, o que cada uma pode chamar e a pasta de cada coisa: tela, regra, acesso a dados, integração)_

## Nomes e arquivos

_(como se nomeiam arquivos, funções, tabelas e rotas; um arquivo por quê)_

## Erros

_(como um erro sobe, o que o usuário vê e o que nunca é engolido)_

## Logs

_(o que cada falha que o usuário pode relatar registra, com que contexto, e onde o operador lê; o detalhe da operação fica em [`operacao.md`](operacao.md))_

## Testes

_(onde ficam, como se nomeiam (o id do critério primeiro), e como cada teste cria os próprios dados)_

## Decisões

| Decisão | Por quê | Entrega |
|---|---|---|
| _(uma linha por escolha de arquitetura que um dev novo perguntaria)_ | | |
