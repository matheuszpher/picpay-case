# ADR-0017: Sem autenticação na Parte 2 neste MVP (API key fica em backlog)

**Status.** Aceito.

## Contexto

Hoje `/load/`, `/predict/`, `/list/` e `DELETE /models/{version}` estão
completamente abertos: qualquer um que alcance a porta 8000 usa a API sem
restrição nenhuma. Isso é uma lacuna real de "pronto para produção": em um
deploy exposto de verdade, isso permitiria abuso de CPU via `/predict/`,
download arbitrário de modelos via `/load/`, remoção do modelo ativo de outros
consumidores via `DELETE`, e leitura do histórico completo (potencialmente
sensível, no cenário do PIX por WhatsApp) via `/list/`.

A pergunta concreta que motivou este ADR: vale a pena adicionar uma API key
simples agora, dado que quem vai rodar este projeto primeiro é um recrutador
avaliando o case, na própria máquina dele?

## Decisão

Não implementar autenticação nesta entrega. Documentar a lacuna e o caminho de
solução (API key simples, nunca um sistema de usuários completo) como
backlog, não como trabalho em andamento.

## Alternativas

- *API key simples agora (header `X-API-Key` + `Depends` do FastAPI):* é
  pouco código (~20-30 linhas), mas muda a experiência de quem avalia: o
  Swagger UI hoje deixa clicar em "Try it out" e testar na hora, sem nenhum
  passo prévio. Com uma chave obrigatória, o recrutador precisaria primeiro
  descobrir/copiar a chave (de uma variável de ambiente, de um `.env`, de
  algum lugar do README) antes de conseguir testar qualquer rota. Isso
  adiciona fricção exatamente no momento em que o objetivo é reduzir
  fricção (ADR-0013, self-service).
- *Sistema de usuários completo (login, roles, JWT):* claramente
  desproporcional para o escopo de um case de backend/plataforma; nem chegou
  a ser cogitado como opção real.

## Consequências

- (+) Mantém o fluxo de avaliação sem atrito: cloná, `docker compose up
  --build`, abrir o Swagger, testar. Nenhum segredo para descobrir antes de
  usar.
- (+) A decisão fica registrada e defensável ("por que não tem
  autenticação?"), em vez de parecer uma lacuna não percebida.
- (−) O serviço, hoje, não é seguro o suficiente para ser exposto além de
  `localhost`/uma rede confiável. Isso é aceitável para o critério de
  avaliação deste case (rodar localmente), mas precisaria ser resolvido antes
  de qualquer deploy real.

