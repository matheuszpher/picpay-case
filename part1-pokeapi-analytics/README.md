# Parte 1: PokeAPI Analytics (plano batch)

Pipeline batch em camadas medallion (bronze/silver/gold) sobre a PokeAPI: ingestão assíncrona,
4 tabelas do dicionário de dados modeladas via PySpark, 3 análises e checks de qualidade de
dados. Projeto autossuficiente, roda sozinho, sem depender da Parte 2.

Racional de arquitetura e diagramas: ver [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) e os
ADRs [0006](../docs/adr/0006-ingestao-async-cache-bronze.md),
[0007](../docs/adr/0007-medallion-bronze-silver-gold.md) e
[0015](../docs/adr/0015-spark-local-notebook-portavel.md).

Detalhe de implementação (como e por quê de cada módulo, edge cases, bugs corrigidos,
estratégia de testes): [`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md).

## Estrutura

```
part1-pokeapi-analytics/
├── docs/
│   └── IMPLEMENTATION.md  # registro de implementação (como/por quê por módulo)
├── pyproject.toml
├── src/
│   ├── ingest.py       # coleta async + cache bronze + retry/backoff       [pronto]
│   ├── transform.py    # bronze -> silver (4 tabelas) com schema explícito [pronto]
│   ├── quality.py      # checks: not-null, unicidade, integridade ref.     [pronto]
│   ├── analysis.py     # gold: as 3 análises                              [pronto]
│   └── report.py       # persistência dos resultados + relatório HTML      [pronto]
├── notebook.ipynb       # entregável: orquestra ingest->transform->quality->analysis->report [pronto]
├── tests/
├── data/                # bronze cache, resultados e relatórios (fora do git)
├── Dockerfile
└── docker-compose.yml   # sobe PySpark local
```

## Modelo de dados

- `pokemon(pokemon_id, name, height, weight, base_experience)`
- `pokemon_type(pokemon_id, type_name)`
- `pokemon_stats(pokemon_id, stat_name, base_stat)`
- `pokemon_ability(pokemon_id, ability_name, is_hidden)`

## As 3 análises

1. Multi-tipo e força acima da média.
2. Abilities exclusivas de multi-tipo.
3. Top 5 versatilidade.

Fórmulas, passo a passo e a pegadinha da média em Q1 estão detalhados na
[Seção 4 de `docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md#4-análises-srcanalysispy).

## Pré-requisitos

Só Docker instalado e rodando. Internet é necessária apenas para uma primeira ingestão
(sem cache bronze); os testes automatizados não tocam a rede real.

## Como rodar

Pipeline completo (ingest, transform, quality e as 3 análises), a partir desta pasta
(`part1-pokeapi-analytics/`). Roda o dataset completo (~1350 pokémons) e imprime as 3
respostas no terminal:

```bash
docker compose up
```

A partir da raiz do repositório, o equivalente é `make up-p1` (ou `make analysis-p1`,
alias do mesmo comando, nome usado no mini-spec da Parte 1).

O cache bronze (`data/bronze/`, fora do git) persiste entre execuções. Um segundo
`docker compose up` reaproveita os JSONs já baixados e roda bem mais rápido, sem bater
na PokeAPI de novo. O `notebook.ipynb` já está commitado com as saídas de uma execução
completa, então dá para ver as 3 respostas e os gráficos sem rodar nada.

Cada execução também grava um relatório gerencial em HTML (cores e fonte do PicPay) em
`data/reports/`: `report-apipokemon-latest.html` (sempre sobrescrito) e
`report-apipokemon-{DDMMYY}-{HHMMSS}.html` (um por execução, com histórico). Os dados
que alimentam o relatório ficam em `data/results/latest.json`, sobrescrito a cada run.

Só os testes:

```bash
docker build -t picpay-part1 .
docker run --rm picpay-part1 python -m pytest tests/ -v
```

A partir da raiz, `make test-p1`.

## Status

Ingestão, transformação, qualidade, análises, relatório gerencial e notebook
implementados e testados (61/61 testes passando no Docker/Linux, o ambiente oficial,
ver [ADR-0015](../docs/adr/0015-spark-local-notebook-portavel.md)). `docker compose up`
roda o pipeline completo de ponta a ponta, imprime as 3 respostas e gera o relatório
HTML: o critério de pronto da Parte 1 está fechado. Detalhe completo em
[`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md).
