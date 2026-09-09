# ADR-0005: Histórico de predições em SQLite (pronto para Postgres) com índice

**Status.** Aceito.

## Contexto

O `GET /list/` precisa devolver o histórico (input, output, timestamp, versão) e esse histórico
deve sobreviver a um restart do container.

## Decisão

Persistir em SQLite, atrás de uma interface de repositório, com índice em
`(timestamp, model_version)`. A interface permite trocar por Postgres sem tocar no service.

## Alternativas

- *Guardar em memória (lista):* simples, mas perde tudo no restart.
- *Postgres desde já:* robusto, mas exige subir um banco, peso desnecessário para o escopo local.
- *Append em arquivo (JSONL):* simples, mas consulta e ordenação ficam ruins.

## Consequências

- (+) Zero-config, roda local, sobrevive a restart, consulta ordenada rápida por causa do índice.
- (+) Trocar por Postgres é só outra implementação do repositório.
- (−) SQLite não aguenta escrita concorrente alta; o índice deixa a escrita um pouco mais lenta.
