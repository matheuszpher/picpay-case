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
├── assets/
│   └── picpay-logo.png    # logo usada no relatório gerencial (versionada no git)
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

Só Docker Desktop instalado e rodando, mais internet para uma primeira ingestão (sem
cache bronze). Não precisa instalar Python, Java ou nenhuma biblioteca na sua máquina.

**Por que Docker é obrigatório aqui, não só recomendado:** este projeto depende de uma
combinação específica de versões (PySpark 3.5.3, Java 8/11/17, matplotlib, ipykernel,
papermill) mais uma biblioteca nativa do Hadoop para escrever Parquet. O Dockerfile fixa
tudo isso numa imagem testada; sem ele, cada máquina precisaria reproduzir manualmente
esse ambiente exato, e pequenas diferenças de versão já quebraram a execução real
durante o desenvolvimento (ver `docs/IMPLEMENTATION.md`).

**Se você rodar sem Docker (Jupyter local, célula por célula), isto vai dar problema:**

- **Import falha ou "meio funciona".** Sem `pip install -e ".[dev]"` a partir desta
  pasta, `from src import ingest, transform, quality, analysis, report` falha. Se você
  tiver algumas dependências instaladas por acaso e outras não, o notebook roda até a
  metade e quebra de forma confusa.
- **Gráficos (`%matplotlib inline`) quebram com `ModuleNotFoundError: No module named
  'matplotlib'`** se o kernel do Jupyter que você selecionou não for o mesmo ambiente
  Python onde as dependências do projeto foram instaladas. É comum o Jupyter abrir com
  o Python global do sistema em vez do venv do projeto.
- **Criar a `SparkSession` falha ou trava** sem Java 8, 11 ou 17 instalado e
  `JAVA_HOME` configurado corretamente. PySpark 3.5.3 não suporta Java 21; se o
  `pip install` da sua máquina puxar uma versão diferente do PySpark (sem o pin do
  `pyproject.toml`), o problema piora.
- **Escrever Parquet (`write_silver`) falha no Windows** com
  `UnsatisfiedLinkError: NativeIO$Windows.access0`, porque a escrita passa pelo
  `FileOutputCommitter` do Hadoop, que exige um `hadoop.dll` nativo no `PATH`. Esse
  arquivo não vem com o PySpark nem com o Python; é preciso baixar manualmente a versão
  certa (Hadoop 3.3.x) de um repositório de terceiros e configurar `HADOOP_HOME`. No
  Linux (dentro do Docker) esse problema não existe.
- **Caminhos relativos quebram** se o Jupyter não abrir com o diretório de trabalho em
  `part1-pokeapi-analytics/` (comum em editores que abrem a partir da raiz do repo). O
  notebook assume que `data/bronze`, `data/silver` etc. são relativos a esta pasta.

Nenhum desses pontos tem solução automatizada fora do Docker. Se mesmo assim quiser
rodar localmente, precisa replicar manualmente tudo que o Dockerfile faz: instalar as
dependências do `pyproject.toml`, instalar Java 8/11/17, registrar o kernel certo do
Jupyter, e (no Windows) instalar o `hadoop.dll`.

## Como rodar

Pipeline completo (ingest, transform, quality e as 3 análises), a partir desta pasta
(`part1-pokeapi-analytics/`). Roda o dataset completo (~1350 pokémons) e imprime as 3
respostas no terminal:

```bash
docker compose up --build
```

A partir da raiz do repositório, o equivalente é `make up-p1` (ou `make analysis-p1`,
alias do mesmo comando, nome usado no mini-spec da Parte 1).

O cache bronze (`data/bronze/`, fora do git) persiste entre execuções. Um segundo
`docker compose up` reaproveita os JSONs já baixados e roda bem mais rápido, sem bater
na PokeAPI de novo. O `notebook.ipynb` já está commitado com as saídas de uma execução
completa, então dá para ver as 3 respostas e os gráficos sem rodar nada.

Cada execução também grava um relatório gerencial em HTML (logo, cores e fonte do
PicPay, mais os 2 gráficos da Seção 5 do notebook, gerados na hora a partir dos dados
desta execução, nada estático) em `data/reports/`: `report-apipokemon-latest.html`
(sempre sobrescrito) e `report-apipokemon-{DDMMYY}-{HHMMSS}.html` (um por execução, com
histórico). Os dados que alimentam o relatório ficam em `data/results/latest.json`,
sobrescrito a cada run.

Só os testes:

```bash
docker build -t picpay-part1 .
docker run --rm picpay-part1 python -m pytest tests/ -v
```

A partir da raiz, `make test-p1`.

## Status

Ingestão, transformação, qualidade, análises, relatório gerencial e notebook
implementados e testados (67/67 testes passando no Docker/Linux, o ambiente oficial,
ver [ADR-0015](../docs/adr/0015-spark-local-notebook-portavel.md)). `docker compose up`
roda o pipeline completo de ponta a ponta, imprime as 3 respostas e gera o relatório
HTML: o critério de pronto da Parte 1 está fechado. Detalhe completo em
[`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md).
