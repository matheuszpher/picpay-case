# Parte 1 — PokeAPI Analytics (plano batch)

Pipeline batch em camadas medallion (bronze/silver/gold) sobre a PokeAPI: ingestão assíncrona,
4 tabelas do dicionário de dados modeladas via PySpark, 3 análises e checks de qualidade de
dados. Projeto autossuficiente — roda sozinho, sem depender da Parte 2.

Racional de arquitetura e diagramas: ver [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) e os
ADRs [0006](../docs/adr/0006-ingestao-async-cache-bronze.md),
[0007](../docs/adr/0007-medallion-bronze-silver-gold.md) e
[0015](../docs/adr/0015-spark-local-notebook-portavel.md).

Detalhe de implementação (como/por quê de cada módulo, edge cases, bugs corrigidos,
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
│   └── analysis.py     # gold: as 3 análises                              [pendente]
├── notebook.ipynb       # entregável exigido: extração + tabelas + análises
├── tests/
├── data/                # bronze cache (gitignore no volumoso)
├── Dockerfile
└── docker-compose.yml   # sobe PySpark local
```

## Modelo de dados

- `pokemon(pokemon_id, name, height, weight, base_experience)`
- `pokemon_type(pokemon_id, type_name)`
- `pokemon_stats(pokemon_id, stat_name, base_stat)`
- `pokemon_ability(pokemon_id, ability_name, is_hidden)`

## As 3 análises

1. Multi-tipo + força acima da média.
2. Abilities exclusivas de multi-tipo.
3. Top 5 versatilidade.

Fórmulas e passo a passo de cada análise serão detalhados em
[`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md) quando `analysis.py` for implementado.

## Como rodar

```bash
docker build -t picpay-part1 .
docker run --rm picpay-part1 python -m pytest tests/ -v
```

> `docker-compose.yml` (subir o pipeline completo via `docker compose up`) ainda não
> está atualizado para a implementação atual — cobre a etapa de análises (pendente).

## Status

Ingestão, transformação e qualidade implementadas e testadas (42/42 testes passando
no Docker/Linux — ambiente oficial, ver [ADR-0015](../docs/adr/0015-spark-local-notebook-portavel.md)).
Análises (`analysis.py`) e notebook ainda pendentes. Detalhe completo em
[`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md).
