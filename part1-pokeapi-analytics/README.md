# Parte 1 — PokeAPI Analytics (plano batch)

Pipeline batch em camadas medallion (bronze/silver/gold) sobre a PokeAPI: ingestão assíncrona,
4 tabelas do dicionário de dados modeladas via PySpark, 3 análises e checks de qualidade de
dados. Projeto autossuficiente — roda sozinho, sem depender da Parte 2.

Racional de arquitetura e diagramas: ver [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) e os
ADRs [0006](../docs/adr/0006-ingestao-async-cache-bronze.md) e
[0007](../docs/adr/0007-medallion-bronze-silver-gold.md).

## Estrutura

```
part1-pokeapi-analytics/
├── pyproject.toml / requirements.txt
├── src/
│   ├── ingest.py       # coleta async + cache bronze + retry/backoff
│   ├── transform.py    # bronze -> silver (4 tabelas) com schema explícito
│   ├── analysis.py     # gold: as 3 análises
│   └── quality.py      # checks: schema, not-null, integridade referencial
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

Detalhe das fórmulas no [BLUEPRINT](../docs-uso-interno/BLUEPRINT_PicPay_ML_Case.md), seção 6.

## Como rodar

> Ainda não implementado — esqueleto do projeto (Fase 0).

```bash
docker compose up
```

## Status

Esqueleto — sem lógica implementada ainda.
