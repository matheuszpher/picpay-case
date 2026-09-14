# Detalhes técnicos: Parte 1 (PokeAPI Analytics)

Este documento reúne o "por quê" das coisas: por que Docker é obrigatório aqui, o
que quebra se você tentar rodar sem ele, e detalhes do relatório gerencial gerado
a cada execução. Para o como/por quê de cada módulo de código (ingestão,
transformação, qualidade, análises, notebook), ver
[`docs/IMPLEMENTATION.md`](IMPLEMENTATION.md). Para decisões de arquitetura
formais, ver os [ADRs do projeto](../../docs/adr/).

## Índice

- [Por que Docker é obrigatório, não só recomendado](#por-que-docker-é-obrigatório-não-só-recomendado)
- [O que quebra se você rodar sem Docker](#o-que-quebra-se-você-rodar-sem-docker)
- [O relatório gerencial em HTML](#o-relatório-gerencial-em-html)
- [Cache bronze: idempotência entre execuções](#cache-bronze-idempotência-entre-execuções)

## Por que Docker é obrigatório, não só recomendado

Este projeto depende de uma combinação específica de versões (PySpark 3.5.3,
Java 8/11/17, matplotlib, ipykernel, papermill) mais uma biblioteca nativa do
Hadoop para escrever Parquet. O Dockerfile fixa tudo isso numa imagem já
testada; sem ele, cada máquina precisaria reproduzir manualmente esse ambiente
exato, e pequenas diferenças de versão já quebraram a execução real durante o
desenvolvimento (detalhe em [`docs/IMPLEMENTATION.md`](IMPLEMENTATION.md)).

## O que quebra se você rodar sem Docker

Se você tentar rodar localmente (Jupyter célula por célula, sem o
docker-compose), isto vai dar problema:

- **Import falha ou "meio funciona".** Sem `pip install -e ".[dev]"` a partir
  desta pasta, `from src import ingest, transform, quality, analysis, report`
  falha. Se você tiver algumas dependências instaladas por acaso e outras não,
  o notebook roda até a metade e quebra de forma confusa.
- **Gráficos (`%matplotlib inline`) quebram com `ModuleNotFoundError: No module
  named 'matplotlib'`** se o kernel do Jupyter que você selecionou não for o
  mesmo ambiente Python onde as dependências do projeto foram instaladas. É
  comum o Jupyter abrir com o Python global do sistema em vez do venv do
  projeto.
- **Criar a `SparkSession` falha ou trava** sem Java 8, 11 ou 17 instalado e
  `JAVA_HOME` configurado corretamente. PySpark 3.5.3 não suporta Java 21; se
  o `pip install` da sua máquina puxar uma versão diferente do PySpark (sem o
  pin do `pyproject.toml`), o problema piora.
- **Escrever Parquet (`write_silver`) falha no Windows** com
  `UnsatisfiedLinkError: NativeIO$Windows.access0`, porque a escrita passa
  pelo `FileOutputCommitter` do Hadoop, que exige um `hadoop.dll` nativo no
  `PATH`. Esse arquivo não vem com o PySpark nem com o Python; é preciso
  baixar manualmente a versão certa (Hadoop 3.3.x) de um repositório de
  terceiros e configurar `HADOOP_HOME`. No Linux (dentro do Docker) esse
  problema não existe.
- **Caminhos relativos quebram** se o Jupyter não abrir com o diretório de
  trabalho em `part1-pokeapi-analytics/` (comum em editores que abrem a partir
  da raiz do repo). O notebook assume que `data/bronze`, `data/silver` etc.
  são relativos a esta pasta.

Nenhum desses pontos tem solução automatizada fora do Docker. Se mesmo assim
quiser rodar localmente, precisa replicar manualmente tudo que o Dockerfile
faz: instalar as dependências do `pyproject.toml`, instalar Java 8/11/17,
registrar o kernel certo do Jupyter, e (no Windows) instalar o `hadoop.dll`.

## O relatório gerencial em HTML

Cada execução grava um relatório em `data/reports/` (fora do git), com a logo,
as cores e a fonte do PicPay, mais os 2 gráficos gerados na hora a partir dos
dados daquela execução (nada estático, nada pré-renderizado):

- `report-apipokemon-latest.html`: sempre sobrescrito, é o "resultado mais
  recente".
- `report-apipokemon-{DDMMYY}-{HHMMSS}.html`: um arquivo por execução, para
  manter histórico.

Os dados que alimentam o relatório ficam em `data/results/latest.json`,
sobrescrito a cada run. Detalhe de implementação (layout, geração dos
gráficos, tratamento de erro se a logo estiver ausente) em
[Seção 5 de `docs/IMPLEMENTATION.md`](IMPLEMENTATION.md#5-notebook-notebookipynb).

## Cache bronze: idempotência entre execuções

O cache bronze (`data/bronze/`, fora do git) persiste entre execuções. Um
segundo `docker compose up` reaproveita os JSONs já baixados e roda bem mais
rápido, sem bater na PokeAPI de novo. O `notebook.ipynb` já está commitado com
as saídas de uma execução completa, então dá para ver as 3 respostas e os
gráficos sem rodar nada. Detalhe da estratégia de cache e retry/backoff em
[Seção 1 de `docs/IMPLEMENTATION.md`](IMPLEMENTATION.md#1-ingestão-srcingestpy).
