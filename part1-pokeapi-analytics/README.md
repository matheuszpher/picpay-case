# Parte 1: PokeAPI Analytics (plano batch)

<img src="assets/picpay-logo.png" alt="PicPay" width="180">

Pipeline batch em camadas medallion (bronze/silver/gold) sobre a PokeAPI, rodando
localmente via Docker. Documentação técnica completa (por que Docker é
obrigatório, o que quebra sem ele, detalhes do relatório gerado) em
[`docs/DETALHES_TECNICOS.md`](docs/DETALHES_TECNICOS.md).

## 1. Estrutura de pastas

```
part1-pokeapi-analytics/
├── assets/
│   └── picpay-logo.png    # logo usada no relatório gerencial (versionada no git)
├── docs/
│   ├── IMPLEMENTATION.md      # registro de implementação (como/por quê por módulo)
│   └── DETALHES_TECNICOS.md   # por quês, gotchas de ambiente, relatório HTML
├── pyproject.toml
├── src/
│   ├── ingest.py       # coleta async + cache bronze + retry/backoff
│   ├── transform.py    # bronze -> silver (4 tabelas) com schema explícito
│   ├── quality.py      # checks: not-null, unicidade, integridade ref.
│   ├── analysis.py     # gold: as 3 análises
│   └── report.py       # persistência dos resultados + relatório HTML
├── notebook.ipynb       # entregável: orquestra ingest->transform->quality->analysis->report
├── tests/
├── data/                # bronze cache, resultados e relatórios (fora do git)
├── Dockerfile
└── docker-compose.yml   # sobe PySpark local
```

## 2. O que foi entregue

### Requisitos obrigatórios do case

| Etapa | Descrição |
|---|---|
| Extração de dados | Consome `GET /pokemon` da PokeAPI com paginação, e uma requisição por pokémon para os detalhes (`types`, `stats`, `abilities`) |
| Modelagem dos dados | 4 tabelas conforme o dicionário de dados do case: `pokemon`, `pokemon_type`, `pokemon_stats`, `pokemon_ability` |
| Análises com Spark | As 3 perguntas do case respondidas via PySpark (ver abaixo) |
| Entregável | `notebook.ipynb`, orquestrando extração, construção das tabelas e as 3 análises |

Tabelas entregues (schema explícito via `StructType`, sem `inferSchema`):

- `pokemon(pokemon_id, name, height, weight, base_experience)`
- `pokemon_type(pokemon_id, type_name)`
- `pokemon_stats(pokemon_id, stat_name, base_stat)`
- `pokemon_ability(pokemon_id, ability_name, is_hidden)`

As 3 análises pedidas:

1. Quantos pokémons têm mais de um tipo e força acima da média geral.
2. Quais abilities não aparecem em nenhum pokémon de tipo único.
3. Os 5 pokémons mais versáteis (`versatility_score = tipos*2 + abilities + soma_stats/100`).

Fórmulas, passo a passo e a pegadinha da média em Q1 estão detalhados na
[Seção 4 de `docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md#4-análises-srcanalysispy).

### Boas práticas pedidas pelo case

- **Ingestão de dados a partir de API REST**, com tratamento de paginação e de dados aninhados (JSON).
- **Modelagem relacional**: as 4 tabelas do dicionário de dados, com chaves primária/estrangeira coerentes.
- **Manipulação e agregação de dados com Spark**: `groupBy`, `join`, `explode`, `broadcast`, `cache`.
- **Clareza na organização e documentação do código**: módulos separados por responsabilidade (`ingest`, `transform`, `quality`, `analysis`, `report`), com testes e documentação por módulo.

### Extras entregues (além do case)

- **Checks de qualidade de dados** (`quality.py`): not-null, unicidade e integridade referencial entre as 4 tabelas, com relatório impresso e falha explícita em invariante crítica.
- **Cache bronze idempotente**: reexecuções reaproveitam os JSONs já baixados, sem bater de novo na PokeAPI.
- **Relatório gerencial em HTML**, com identidade visual do PicPay e gráficos gerados a partir dos dados de cada execução.
- **Suite de testes automatizados** (67 testes) e pipeline de CI (lint, format, testes).
- **ADRs**: decisões de arquitetura documentadas (ver [`docs/adr/`](../docs/adr/)).

## 3. Como executar

Pré-requisito único: Docker Desktop instalado e rodando, mais internet para uma primeira ingestão (sem cache bronze). Não precisa instalar Python, Java ou nenhuma biblioteca na sua máquina.

Pipeline completo (ingest, transform, quality e as 3 análises), a partir desta pasta (`part1-pokeapi-analytics/`). Roda o dataset completo (~1350 pokémons) e imprime as 3 respostas no terminal:

**Linux:**

```bash
docker compose up --build
```

**macOS:**

```bash
docker compose up --build
```

**Windows (PowerShell):**

```powershell
docker compose up --build
```

A partir da raiz do repositório, o equivalente é `make up-p1` (ou `make analysis-p1`, alias do mesmo comando).

Só os testes:

**Linux:**

```bash
docker build -t picpay-part1 .
docker run --rm picpay-part1 python -m pytest tests/ -v
```

**macOS:**

```bash
docker build -t picpay-part1 .
docker run --rm picpay-part1 python -m pytest tests/ -v
```

**Windows (PowerShell):**

```powershell
docker build -t picpay-part1 .
docker run --rm picpay-part1 python -m pytest tests/ -v
```

A partir da raiz, `make test-p1`.

---

Para entender o porquê de cada decisão (Docker obrigatório, gotchas de
ambiente, detalhes do relatório HTML), ver
[`docs/DETALHES_TECNICOS.md`](docs/DETALHES_TECNICOS.md). Para o registro de
implementação módulo a módulo, ver [`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md).
