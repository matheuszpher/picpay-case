# ADR-0007: Processamento em camadas medallion (bronze/silver/gold)

**Status.** Aceito.

## Contexto

Preciso ir do JSON cru da API até as 4 tabelas modeladas e às 3 análises, de forma rastreável e
reprocessável.

## Decisão

Adotar medallion: **bronze** (JSON cru cacheado), **silver** (as 4 tabelas do dicionário, com
schema explícito no Spark), **gold** (as análises, em Parquet).

## Alternativas

- *Transformar tudo num passo só (JSON → resultado):* menos arquivos, mas nada rastreável;
  qualquer erro obriga a rebater a API e refazer tudo.

## Consequências

- (+) Cada camada é reprocessável a partir da anterior; fácil de depurar e testar por etapa.
- (+) Schema explícito no silver evita inferência frágil de tipos.
- (−) Mais artefatos intermediários em disco.
