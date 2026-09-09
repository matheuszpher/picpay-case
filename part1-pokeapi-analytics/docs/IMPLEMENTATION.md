# Registro de Implementação — Parte 1 (PokeAPI Analytics)

> **Regra permanente:** a partir deste documento, nenhuma etapa nova da Parte 1 é
> considerada concluída sem a sua seção correspondente aqui, no mesmo nível de detalhe
> das seções abaixo (o quê/onde, como, por quê, edge cases, bugs corrigidos, estratégia
> de testes, gotchas de ambiente). Documentar é parte da definição de "pronto", não um
> acréscimo opcional depois.

## O que este documento é (e o que não é)

Os [ADRs](../../docs/adr/) registram **decisões de arquitetura** — a escolha entre
opções de alto nível e o tradeoff que a justifica (ex.: "por que ingestão assíncrona
fora do Spark", ADR-0006). Este documento registra o **COMO da implementação**: as
estruturas de código, bibliotecas, assinaturas de função, edge cases tratados e bugs
encontrados no caminho — o nível de detalhe que alguém precisa para entender o código
sem reler todo o histórico de commits. Um ADR muda pouco; este documento cresce a cada
módulo novo.

Convenção: cada seção abaixo corresponde a um módulo de `src/` e segue a mesma
estrutura fixa (O que/onde → Como → Por quê → Edge cases → Bugs → Testes → Gotchas de
ambiente → ADRs relacionados).

---

## 1. Ingestão — `src/ingest.py`

### O que faz e onde

Coleta assíncrona da PokeAPI com cache em disco (camada bronze), sem tocar em Spark.
Implementa os 4 contratos do mini-spec:

| Função | Assinatura | Responsabilidade |
|---|---|---|
| `fetch_index` | `(page_size=100, max_items=None) -> list[dict]` | Pagina `GET /pokemon` até esgotar (ou até `max_items`), retorna `[{name, url}, ...]` |
| `extract_id` | `(url: str) -> int` | Extrai o id numérico do final de uma URL `/pokemon/{id}/` |
| `fetch_detail` | `async (client, url, cache_dir) -> dict` | Detalhe de 1 pokémon: cache-first, senão busca com retry e grava |
| `fetch_all` | `(urls, concurrency=10, cache_dir="data/bronze") -> list[dict]` | Coleta concorrente de todos os detalhes, idempotente |

Funções privadas de suporte: `_get_with_retry_sync` (retry para `fetch_index`),
`_get_with_retry` (retry async para `fetch_detail`), `_fetch_all_async` (corpo
assíncrono de `fetch_all`), `_main` (CLI mínima para `python -m src.ingest`, glue que
não faz parte do contrato do mini-spec).

### Como foi implementado

- **Paginação (`fetch_index`):** `httpx.Client` síncrono; a primeira requisição usa
  `params={"limit": page_size, "offset": 0}`, as seguintes seguem o campo `next` da
  resposta (que já vem com querystring completa, por isso `params=None` depois da
  primeira chamada). Corta a coleta assim que `len(results) >= max_items`, sem seguir
  para a próxima página.
- **Concorrência (`fetch_all`):** `httpx.AsyncClient` + `asyncio.Semaphore(concurrency)`
  dentro de `_fetch_all_async`; cada URL vira uma corrotina `_bound_fetch` que adquire o
  semáforo antes de chamar `fetch_detail`; `asyncio.gather` preserva a ordem dos
  resultados na mesma ordem da lista de entrada, independente da ordem de conclusão.
- **Retry/backoff:** manual, não usa `tenacity`. Duas implementações quase idênticas
  coexistem — `_get_with_retry` (async, usa `await asyncio.sleep`) para `fetch_detail`,
  e `_get_with_retry_sync` (usa `time.sleep`) para `fetch_index`. Backoff exponencial
  `backoff_base * 2**attempt` com `BACKOFF_BASE_SECONDS = 0.5` e `MAX_RETRIES = 5`
  (6 tentativas no total). `RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}`; qualquer
  outro `HTTPStatusError` (ex.: 404) propaga na hora, sem retry.
- **Cache bronze:** um arquivo `{cache_dir}/{id}.json` por pokémon. `fetch_detail`
  verifica `cache_file.exists()` antes de qualquer chamada de rede.
- **User-Agent:** setado explicitamentde (`USER_AGENT` constante) em ambos os clientes
  httpx — API pública, é educado se identificar.

### Por quê (tradeoffs de implementação)

- **Retry manual vs `tenacity`:** escolhido manual para não adicionar uma dependência
  externa só para ~20 linhas de lógica, e porque o backoff manual é trivialmente
  testável via `monkeypatch.setattr(asyncio, "sleep", ...)` / `monkeypatch.setattr(time,
  "sleep", ...)`, sem precisar entender a API de retry de uma biblioteca de terceiros
  nos testes.
- **Duas implementações de retry (sync/async) em vez de uma:** `fetch_index` não é
  `async` no mini-spec (só `fetch_detail` é), então manter `fetch_index` síncrono e
  duplicar a lógica de retry (em vez de forçar tudo para async, ou envolver a versão
  síncrona numa chamada `asyncio.run` por página) foi a opção mais simples e mais fiel
  ao contrato pedido. O custo é ~15 linhas duplicadas — aceitável dado o tamanho do
  módulo.
- **Escrita atômica do cache (tmp + replace) vs escrita direta:** decisão de
  confiabilidade adicionada depois da primeira versão (ver "Bugs" abaixo não se aplica
  aqui — foi um pedido explícito, não um bug encontrado). Escrever direto em
  `{id}.json` deixaria um JSON truncado/corrompido no disco se o processo fosse
  interrompido no meio da escrita; com `tmp.write_text(...)` seguido de
  `tmp.replace(cache_file)`, o rename é atômico no sistema de arquivos — ou o cache
  final existe inteiro, ou não existe (o `.tmp` órfão nunca é lido como cache válido).
- **`fetch_all` não expõe parâmetros de retry:** os parâmetros `max_retries`/
  `backoff_base` existem em `_get_with_retry`/`_get_with_retry_sync` mas não são
  propagados até `fetch_detail`/`fetch_all`/`fetch_index` porque o mini-spec fixa essas
  assinaturas exatamente (`fetch_all(urls, concurrency=10, cache_dir=...)`); os defaults
  de módulo (`MAX_RETRIES`, `BACKOFF_BASE_SECONDS`) cobrem o caso de uso real e ficam
  ajustáveis só por quem edita o código, não por parâmetro de chamada.

### Edge cases tratados

- **Fim de paginação:** `next: null` encerra o loop (`url = payload.get("next")` vira
  `None`).
- **`max_items` corta no meio de uma página:** retorna `results[:max_items]` sem
  disparar a requisição da página seguinte.
- **URL sem barra final:** `extract_id` trata tanto `/pokemon/1/` quanto `/pokemon/1`
  (usa `rstrip("/")` antes do `rsplit`).
- **Cache hit nunca toca a rede:** verificado explicitamente em teste com um handler
  que levanta `AssertionError` se for chamado.
- **Escrita interrompida:** se só o `.tmp` existir (processo morreu no meio de uma
  escrita anterior), `fetch_detail` não o enxerga como cache (só olha para
  `{id}.json`), então refaz a busca — nunca lê um JSON parcial.
- **Ordem preservada em coleta concorrente:** mesmo com respostas chegando fora de
  ordem, `fetch_all` devolve os resultados na mesma ordem da lista `urls` de entrada.
- **Idempotência entre execuções:** rodar `fetch_all` duas vezes com os mesmos `urls`
  não gera novas requisições na segunda vez (tudo já está em cache).

### Bugs encontrados e corrigidos

- **Recursão infinita nos helpers de teste (`_client_factory`/`_async_client_factory`).**
  Causa raiz: os helpers faziam `monkeypatch.setattr(httpx, "Client", factory)` e, dentro
  do próprio `factory`, chamavam `httpx.Client(...)` — mas nesse ponto `httpx.Client` já
  **era** o `factory` (o patch já tinha sido aplicado ao atributo do módulo), então cada
  chamada reinvocava a si mesma infinitamente (`RecursionError: maximum recursion depth
  exceeded`). Correção: capturar `_RealClient = httpx.Client` e `_RealAsyncClient =
  httpx.AsyncClient` **antes** de qualquer `monkeypatch.setattr`, e usar essas
  referências guardadas dentro dos factories, nunca o atributo do módulo (que pode já
  estar substituído).

### Estratégia de testes

Toda a rede é mockada via `httpx.MockTransport` (nativo do `httpx`, sem dependência
extra) — nenhum teste bate na PokeAPI real. Grupos de teste em `tests/test_ingest.py`:

- **`extract_id`:** casos com e sem barra final.
- **`fetch_index`:** paginação até `next: null`; corte por `max_items`; header
  `User-Agent` presente; retry em erro transiente (503→503→200) e sucesso; erro
  não-retryable (404) propaga sem retry.
- **`fetch_detail`:** cache hit (rede nunca chamada); cache miss (busca e grava);
  escrita atômica (nenhum `.tmp` sobra depois de um sucesso); `.tmp` órfão de escrita
  interrompida é ignorado como cache (refaz a busca); retry em erro transiente até
  sucesso; erro não-retryable propaga na hora; esgotamento de todas as tentativas
  propaga o `HTTPStatusError` final.
- **`fetch_all`:** ordem dos resultados preservada e idempotência (segunda chamada não
  gera requisições novas); limite real de concorrência (contador de requisições
  simultâneas em voo, usando um `asyncio.Lock` + contador dentro do handler mock,
  garantindo que nunca excede o `concurrency` passado); header `User-Agent` presente.

### Gotchas de ambiente

Nenhum específico deste módulo — é Python + `httpx` puro, sem dependência de JVM/Spark.

### ADRs relacionados

[ADR-0006](../../docs/adr/0006-ingestao-async-cache-bronze.md) — ingestão assíncrona
com cache bronze, fora do Spark.

---

## 2. Transformação — `src/transform.py`

### O que faz e onde

Bronze → silver: transforma a lista de detalhes brutos (JSON da PokeAPI, já em memória
como `list[dict]`) nas 4 tabelas do dicionário de dados, com schema Spark **explícito**
em todas elas — proibido `inferSchema`.

| Função | Assinatura | Responsabilidade |
|---|---|---|
| `build_pokemon` | `(details) -> DataFrame` | `[pokemon_id, name, height, weight, base_experience]` |
| `build_pokemon_type` | `(details) -> DataFrame` | `[pokemon_id, type_name]`, explode de `types` |
| `build_pokemon_stats` | `(details) -> DataFrame` | `[pokemon_id, stat_name, base_stat]`, explode de `stats` |
| `build_pokemon_ability` | `(details) -> DataFrame` | `[pokemon_id, ability_name, is_hidden]`, explode de `abilities` |
| `write_silver` | `(df, name, base_path="data") -> None` | Grava Parquet em `{base_path}/silver/{name}` |

Suporte privado: `RAW_DETAIL_SCHEMA` (constante de módulo, o `StructType` do JSON cru),
`_get_spark()` (obtém/cria a `SparkSession`), `_details_to_df(details)` (aplica o
schema explícito sobre a lista de dicts).

### Como foi implementado

- **`RAW_DETAIL_SCHEMA`:** um único `StructType` aninhado que espelha exatamente a
  forma do JSON de detalhe da PokeAPI — `types`/`stats`/`abilities` são
  `ArrayType(StructType([...]))`, cada um com a sub-estrutura aninhada
  (`type.name`, `stat.name`, `ability.name`) e `is_hidden` declarado como
  `BooleanType()` desde a raiz do schema (não como `StringType` para depois converter).
  Esse schema é passado direto para `spark.createDataFrame(details, schema=...)` —
  Spark nunca infere nada a partir dos dados.
- **Uma conversão por chamada:** cada `build_*` chama `_details_to_df(details)`
  internamente, ou seja, os `details` (Python puro) são convertidos para `DataFrame`
  uma vez por função, não uma vez só e reaproveitada entre as 4. Ver tradeoff abaixo.
- **Explode + select em duas etapas:** por exemplo em `build_pokemon_type`, primeiro
  `select(pokemon_id, explode(types).alias(type_entry))`, depois um segundo `select`
  que extrai `type_entry.type.name`. Mesma receita para `stats` e `abilities`.
- **`SparkSession` obtida via singleton (`getOrCreate`):** `_get_spark()` não recebe
  `spark` como parâmetro — chama `SparkSession.builder.appName(...).master(...)
  .getOrCreate()`, que reaproveita uma sessão já ativa na JVM se existir (é assim que
  os testes conseguem plugar uma `SparkSession` de teste com `master("local[1]")`,
  criada antes, e o código de produção simplesmente a reutiliza).
- **`write_silver`:** `df.write.mode("overwrite").parquet(...)` — sobrescreve o
  diretório de destino inteiro a cada chamada (reprocessável, não acumula).

### Por quê (tradeoffs de implementação)

- **Schema explícito vs `inferSchema`:** exigência do mini-spec, mas também justificada
  tecnicamente — `inferSchema` faria Spark ler os dados duas vezes (uma para inferir
  tipos, outra para carregar) e o tipo inferido pode variar entre execuções se algum
  campo aparecer `null` em todas as amostras de uma rodada. Com `StructType` fixo, o
  schema é sempre o mesmo, independente do conteúdo.
- **`_get_spark()` sem parâmetro `spark` explícito vs injeção de dependência:** o
  mini-spec fixa a assinatura `build_pokemon(details)` — sem lugar para passar uma
  `SparkSession`. A alternativa mais "pura" (testável sem estado global) seria
  `build_pokemon(spark, details)`, mas isso quebraria o contrato. O tradeoff aceito:
  as funções dependem implicitamente de uma `SparkSession` ativa/criável no processo,
  o que é o padrão de fato em código PySpark de produção (raramente se passa `spark`
  explicitamente entre módulos).
- **Reconverter `details` em `DataFrame` a cada `build_*` (4x) vs converter uma vez e
  reaproveitar:** também decorre de seguir a assinatura do mini-spec ao pé da letra —
  cada função recebe `details` (a lista Python), não um `DataFrame` já pronto. O custo
  de chamar `createDataFrame` 4 vezes sobre os mesmos ~1300 registros é pequeno nessa
  escala (não é a etapa que o mini-spec pede para otimizar — as otimizações de
  `broadcast`/`cache` são para a etapa de *análise*, não para o transform). Documentado
  aqui para não parecer descuido.
- **Semântica de `base_path` em `write_silver`:** o mini-spec dá o exemplo literal
  `data/silver/{name}`. Em vez de `base_path` já ser a raiz do silver (o que exigiria
  passar `"data/silver"` toda vez), `write_silver` recebe `base_path="data"` por
  default e concatena `"silver"/name` internamente. É uma escolha de nomenclatura que
  vale a pena checar antes de reusar a função em outro contexto — passar
  `base_path="data/silver"` por engano duplicaria o `"silver"` no caminho final.

### Edge cases tratados

- **Pokémon sem tipos/stats/abilities:** `explode()` sobre uma lista vazia
  simplesmente não gera nenhuma linha para aquele pokémon na tabela explodida (não
  lança erro, não gera `null`) — comportamento padrão do Spark, sem tratamento
  especial no código, mas vale saber que esse pokémon "some" da tabela derivada.
- **`is_hidden` como boolean real:** validado explicitamente em teste
  (`isinstance(df.schema["is_hidden"].dataType, BooleanType)` e filtros
  `df.is_hidden == True` / `== False`) — proteção contra uma regressão comum em
  pipelines que leem JSON: acabar com `"true"`/`"false"` como string.
- **`write_silver` com `mode("overwrite")`:** reprocessar com um dataset menor
  **substitui** o conteúdo anterior inteiro (não faz merge/append) — comportamento
  esperado e coberto por teste (`test_write_silver_overwrites_on_rerun`).

### Bugs encontrados e corrigidos

- **`python:3.11-slim` mudou de base e passou a trazer só OpenJDK 21 via `apt`,
  incompatível com `pyspark==3.5.3`.** Causa raiz: a tag `slim` (sem qualificador de
  release) segue a versão mais recente do Debian — em algum momento passou a apontar
  para `trixie`, cujo repositório não tem mais `openjdk-17-jre-headless` disponível
  (só `openjdk-21-*`), e o Spark 3.5.x não suporta oficialmente Java 21. Isso também
  se manifestou localmente antes do Docker: `pip install pyspark` (sem pin de versão)
  trouxe `pyspark==4.2.0`, que exige Java 17+, e travou indefinidamente contra o JDK 8
  instalado neste ambiente Windows. Correção: (1) pinar `pyspark==3.5.3` em
  `pyproject.toml` (suporta Java 8/11/17); (2) fixar a imagem base do Dockerfile em
  `python:3.11-slim-bookworm` (Debian 12, ainda empacota `openjdk-17-jre-headless`) em
  vez de `python:3.11-slim`.
- **Comparação de `StructType` completo falhando no round-trip de Parquet.** Causa
  raiz: `read_back.schema == df.schema` comparava também a flag `nullable` de cada
  campo — e o leitor de Parquet do Spark marca **todas** as colunas como
  `nullable=True` ao ler de volta, independente do que foi declarado na escrita
  (`nullable=False` em `pokemon_id`/`name`, por exemplo, não sobrevive ao round-trip).
  Esse teste só falhava em Linux/Docker porque no Windows local ele ficava `skip` (ver
  Gotchas abaixo) — só apareceu quando validamos a execução real no ambiente oficial.
  Correção: comparar apenas `(nome, tipo)` de cada campo, não o `StructType` inteiro:
  `[(f.name, f.dataType) for f in schema.fields]`.

### Estratégia de testes

`tests/conftest.py` define uma fixture `spark` de escopo `session` (`local[1]`, UI
desligada, `spark.sql.shuffle.partitions=1` para execução rápida e determinística —
sem isso, o número default de partições de shuffle geraria dezenas de tasks vazias
para um dataset de 3 linhas). `tests/test_transform.py` usa uma fixture de 3 pokémons
lavrados à mão (bulbasaur multi-tipo com uma hidden ability, charmander e squirtle
mono-tipo, squirtle também com hidden ability) cobrindo:

- **Schema explícito por tabela:** comparação campo a campo do `StructType` retornado
  contra o esperado — pega qualquer drift acidental de tipo (ex.: um `IntegerType` que
  vire `LongType`, ou perda do `BooleanType` em `is_hidden`).
- **Grão de cada tabela:** contagem de linhas esperada por explode (ex.:
  `pokemon_type` deve ter 4 linhas — 2 do bulbasaur + 1 + 1 — não 3, uma por pokémon).
- **`is_hidden` booleano real:** filtro por `== True`/`== False` retornando os nomes
  certos de habilidade.
- **`write_silver`:** grava e lê de volta (round-trip), e confirma que uma segunda
  escrita com dataset menor sobrescreve (não acumula).

### Gotchas de ambiente

- **Windows local sem `hadoop.dll`:** a escrita de Parquet passa pelo
  `FileOutputCommitter` do Hadoop, que no Windows chama `NativeIO$Windows.access0` via
  JNI — isso falha com `UnsatisfiedLinkError` se só existir `winutils.exe` sem o
  `hadoop.dll` correspondente (era exatamente o caso deste ambiente: `HADOOP_HOME`
  estava setado, mas só com `winutils.exe`). Os 2 testes de `write_silver` detectam
  isso checando a existência real do arquivo `%HADOOP_HOME%\bin\hadoop.dll` (não só a
  variável de ambiente) e usam `pytest.mark.skipif` com motivo explícito — o ambiente
  que efetivamente valida essa escrita é o Docker/CI (Linux), onde não há essa
  limitação. Validado manualmente: `docker build` + `docker run pytest` no container
  rodou os 27 testes da Parte 1 (na época, antes do `quality.py`) sem nenhum skip.
- **Versão do JDK:** precisa ser 8, 11 ou 17 (não 21) para `pyspark==3.5.3`. O
  Dockerfile fixa Java 17 (`openjdk-17-jre-headless` no `python:3.11-slim-bookworm`); o
  CI usa `actions/setup-java` com `distribution: temurin, java-version: "17"` para
  garantir o mesmo JDK no `ubuntu-latest` do GitHub Actions.

### ADRs relacionados

[ADR-0007](../../docs/adr/0007-medallion-bronze-silver-gold.md) — camadas medallion
(bronze/silver/gold). [ADR-0015](../../docs/adr/0015-spark-local-notebook-portavel.md)
— Spark local dockerizado + notebook portátil (justifica por que o ambiente oficial de
validação é o Docker/Linux, não o host Windows).

---

## 3. Qualidade — `src/quality.py`

### O que faz e onde

Checks de qualidade sobre as tabelas silver, com **fail loud**: o pipeline para
(exceção levantada) se uma invariante crítica for violada, em vez de só logar um aviso.

| Função/Classe | Assinatura | Responsabilidade |
|---|---|---|
| `DataQualityError` | `Exception` | Levantada quando uma invariante crítica é violada |
| `check_not_null` | `(df, cols) -> dict` | Conta nulos por coluna |
| `check_unique` | `(df, cols) -> dict` | Verifica se `cols` combinadas formam chave única |
| `check_referential` | `(child, parent, key="pokemon_id") -> dict` | Zero órfãos: toda chave de `child` deve existir em `parent` |
| `run_quality_report` | `(dfs) -> None` | Orquestra os 6 checks, imprime relatório, levanta se algo crítico falhar |

Suporte privado: `_print_report(checks)` (formata e imprime a tabela de resultados).

### Como foi implementado

- **Tipo de retorno "report":** um `dict` simples `{"check": str, "passed": bool,
  "details": str}` — não uma `dataclass`/classe própria. Ver tradeoff abaixo.
- **`check_not_null`:** `df.filter(F.col(col).isNull()).count()` por coluna;
  `passed = all(count == 0 ...)`.
- **`check_unique`:** `df.groupBy(*cols).count().filter(F.col("count") > 1).count()` —
  conta quantos *grupos* de chave aparecem mais de uma vez (não quantas linhas
  duplicadas no total).
- **`check_referential`:** anti-join — `child.join(parent.select(key).distinct(),
  on=key, how="left_anti").count()` — retorna as linhas de `child` cuja chave não
  existe em `parent`; a contagem dessas linhas é o número de órfãos.
- **`run_quality_report`:** monta uma lista de tuplas `(resultado_do_check,
  is_critico: bool)`:
  1. `check_not_null(pokemon, ["pokemon_id"])` — **crítico**
  2. `check_unique(pokemon, ["pokemon_id"])` — **crítico**
  3. `check_unique(pokemon_type, ["pokemon_id", "type_name"])` — **não crítico**
  4. `check_referential(pokemon_type, pokemon)` — **crítico**
  5. `check_referential(pokemon_stats, pokemon)` — **crítico**
  6. `check_referential(pokemon_ability, pokemon)` — **crítico**

  Imprime o relatório completo **antes** de decidir se levanta (ou seja, mesmo numa
  falha crítica, todos os 6 resultados aparecem no relatório — não para no primeiro
  erro). Depois, coleta **todos** os checks críticos que falharam (não só o primeiro) e
  levanta um único `DataQualityError` com o resumo de todos eles concatenado.

### Por quê (tradeoffs de implementação)

- **Criticidade decidida em `run_quality_report`, não nas funções `check_*`:** o
  mini-spec fixa as assinaturas `check_not_null(df, cols)`, `check_unique(df, cols)`,
  `check_referential(child, parent, key="pokemon_id")` — sem espaço para um parâmetro
  `critical=`. Em vez de quebrar essas assinaturas, "o que é crítico" foi tratado como
  uma decisão de negócio que pertence só ao orquestrador (`run_quality_report`): as
  funções `check_*` são primitivas genéricas e reaproveitáveis, e não sabem (nem
  precisam saber) em que contexto estão sendo usadas.
- **`dict` em vez de `dataclass` para o "report":** uma primeira versão usava uma
  `dataclass CheckResult`; foi simplificada para `dict` puro porque o mini-spec não
  pede um tipo específico, e `dict` mantém o módulo sem uma classe extra só para
  carregar 3 campos — mais simples de inspecionar em teste (`result["passed"]`) e de
  logar/serializar no futuro, se necessário.
- **Fail loud (exceção) vs log-only:** requisito explícito do usuário para este
  módulo — a checagem existe justamente para **impedir** que uma camada silver
  inconsistente vire uma camada gold (análises) enganosa. Combina com a filosofia de
  medallion do ADR-0007 ("reprocessável a partir da camada anterior"): é preferível
  parar aqui, no silver, a propagar um erro para a análise e descobrir tarde.
- **Quais invariantes são críticas:** PK nula/duplicada em `pokemon` e órfãos nas 3
  tabelas-filhas foram as invariantes explicitamente apontadas como "quebra o
  pipeline". A unicidade composta `(pokemon_id, type_name)` em `pokemon_type` fica
  **não crítica** de propósito — uma linha duplicada nesse par não corrompe a
  integridade referencial nem, sozinha, invalida as agregações das análises (que usam
  `countDistinct`); ainda assim ela aparece como `FAIL` no relatório impresso, visível
  para quem revisar, só não derruba o pipeline. Se isso mudar de ideia mais adiante
  (ex.: uma análise futura passar a somar sem `distinct`), é só mover essa entrada para
  `critical=True` na lista de `run_quality_report`.
- **Reportar todos os checks críticos falhos de uma vez, não parar no primeiro:** evita
  o cenário de corrigir uma invariante, rodar de novo, descobrir uma segunda invariante
  quebrada que estava escondida atrás da primeira exceção — o relatório e a mensagem de
  erro já mostram o quadro completo na primeira tentativa.

### Edge cases tratados

- **DataFrames vazios:** todo check passa trivialmente (0 nulos, 0 duplicatas, 0
  órfãos) — não é um caso especial no código, é consequência natural das agregações
  usadas (`count()` sobre um DataFrame vazio é `0`).
- **Múltiplas invariantes críticas quebradas ao mesmo tempo:** `run_quality_report`
  levanta uma única exceção cujo texto lista **todas** as falhas críticas (join por
  `"; "`), não só a primeira encontrada.

### Bugs encontrados e corrigidos

Nenhum bug novo neste módulo durante a implementação — construído sobre os contratos
de `transform.py` já validados no Docker/CI na etapa anterior. A validação
Docker/Linux do passo anterior (fix do JDK e da comparação de `StructType`) foi um
pré-requisito para poder confiar nos testes de `quality.py`, que também sobem uma
`SparkSession` real.

### Estratégia de testes

`tests/test_quality.py` **não** reaproveita `transform.py` para gerar os DataFrames de
teste — define seus próprios `StructType` locais (`POKEMON_SCHEMA`, `TYPE_SCHEMA`,
`STATS_SCHEMA`, `ABILITY_SCHEMA`), todos com `nullable=True` em todas as colunas. Isso
é deliberado: os testes de `quality.py` precisam conseguir construir DataFrames
**inválidos de propósito** (ex.: um `pokemon_id` nulo) para exercitar os checks, e o
schema de produção do `transform.py` declara `pokemon_id`/`name` como `nullable=False`
— usar esse schema aqui misturaria "testar a checagem de qualidade" com "testar se o
Spark aceita ou rejeita valores nulos contra um schema estrito" (pergunta diferente,
já coberta implicitamente pelos testes de `transform.py`). Cobertura:

- **Cada `check_*` isoladamente:** caso feliz + caso de violação —
  `check_not_null` (sem nulos / com PK nula), `check_unique` (chave simples e chave
  composta, ambas com e sem duplicata), `check_referential` (sem órfão / com órfão).
- **`run_quality_report`, uma invariante crítica por vez:** PK nula, PK duplicada,
  órfão em `pokemon_type`, órfão em `pokemon_stats`, órfão em `pokemon_ability` — cada
  um em um teste dedicado que afirma `pytest.raises(DataQualityError)`.
- **Caso feliz de `run_quality_report`:** não levanta, e a saída capturada
  (`capsys`) contém o cabeçalho do relatório e nenhum `"FAIL"`.
- **Violação não crítica:** duplicata em `(pokemon_id, type_name)` aparece como
  `"FAIL"` na saída capturada, mas `run_quality_report` **não** levanta — trava a
  decisão de design de "isso é reportado, não é fatal" num teste, não só num comentário.

### Gotchas de ambiente

Nenhum novo além dos já descritos na seção de `transform.py` (mesma fixture `spark` de
`conftest.py`, mesmas exigências de JDK). Validado de ponta a ponta em Docker/Linux:
**42/42 testes da Parte 1 passam** (`ingest` + `transform` + `quality`), incluindo os 2
testes de Parquet que no Windows local ficam `skip`.

### ADRs relacionados

[ADR-0007](../../docs/adr/0007-medallion-bronze-silver-gold.md) — o quality check é o
portão entre silver e gold que garante que a camada gold só é gerada a partir de dados
consistentes.
