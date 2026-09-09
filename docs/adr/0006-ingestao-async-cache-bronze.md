# ADR-0006: Ingestão da PokeAPI assíncrona com cache bronze (fora do Spark)

**Status.** Aceito.

## Contexto

Modelar as tabelas exige buscar o detalhe de ~1300 pokémons (`/pokemon/{id}`). Fazer isso
sequencialmente é o gargalo óbvio da Parte 1.

## Decisão

Coletar com concorrência limitada (httpx + asyncio + semáforo) e retry/backoff, e salvar o JSON
cru em disco (camada bronze). O Spark só entra depois, na transformação/análise.

## Alternativas

- *Coleta sequencial:* simples, mas minutos viram dezenas de minutos.
- *Paralelizar a coleta com o próprio Spark:* acopla ingestão ao cluster e polui o job de análise
  com responsabilidade de rede.

## Consequências

- (+) Coleta rápida com pressão controlada sobre a API pública (semáforo + backoff = educado).
- (+) Cache bronze = reprodutibilidade e reprocessamento sem rebater a API.
- (−) Complexidade de asyncio; precisa tratar limite de taxa/erros transitórios.
