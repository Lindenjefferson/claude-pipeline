# Operação

Como o produto é publicado, guardado e recuperado. Quem executa é uma pessoa: o plugin diz o que publicar e nunca publica. Cada procedimento é provado no ambiente de teste antes de valer para produção, e a data da última prova fica no próprio procedimento. Enquanto o produto não é publicado, cada seção diz "ainda não publicado".

## Publicar

_(os comandos, a ordem, o que confere que a publicação deu certo, e o que cada canal (loja, provedor de login, hospedagem) exige antes da primeira publicação, cada exigência com a prova)_

## Backup e restauração

_(o que entra no backup, onde fica, de quanto em quanto tempo; um backup só vale depois de uma restauração provada)_

## Reverter

_(como voltar para a versão anterior, migrations incluídas)_

## Onde ler os logs

_(onde ficam os logs que [`arquitetura.md`](arquitetura.md) descreve, como filtrar uma falha relatada e por quanto tempo ficam)_

## Saber que caiu

_(a checagem de fora do servidor que nota o produto fora do ar ou os erros acumulando, e quem ela avisa)_

## Dados pessoais

_(se o produto guarda dados de pessoas reais: como atender um pedido de exportar, corrigir ou apagar, o que fica no backup e até quando, e o que fazer num vazamento: quem avisar e em quanto tempo; se não guarda, "não se aplica" e por quê)_
