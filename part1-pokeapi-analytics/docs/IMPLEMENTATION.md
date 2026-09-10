# Registro de Implementação: Parte 1 (PokeAPI Analytics)

> **Regra permanente:** a partir deste documento, nenhuma etapa nova da Parte 1 é
> considerada concluída sem a sua seção correspondente aqui, no mesmo nível de detalhe
> das seções abaixo (o quê/onde, como, por quê, edge cases, bugs corrigidos, estratégia
> de testes, gotchas de ambiente). Documentar é parte da definição de "pronto", não um
> acréscimo opcional depois.

## O que este documento é (e o que não é)

Os [ADRs](../../docs/adr/) registram decisões de arquitetura: a escolha entre opções
de alto nível e o tradeoff que a justifica (por exemplo, por que a ingestão é
assíncrona e roda fora do Spark, ADR-0006). Este documento registra o como da
implementação: estruturas de código, bibliotecas, assinaturas de função, edge cases
tratados e bugs encontrados no caminho. É o nível de detalhe que alguém precisa para
entender o código sem reler todo o histórico de commits. Um ADR muda pouco; este
documento cresce a cada módulo novo.

Convenção: cada seção abaixo corresponde a um módulo de `src/` e segue a mesma
estrutura fixa (o que/onde, como, por quê, edge cases, bugs, testes, gotchas de
ambiente, ADRs relacionados).

---

## 1. Ingestão: `src/ingest.py`

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
assíncrono de `fetch_all`) e `_main` (CLI mínima para `python -m src.ingest`; é glue
de execução, não faz parte do contrato do mini-spec).

### Como foi implementado

- **Paginação (`fetch_index`).** Usa `httpx.Client` síncrono. A primeira requisição
  usa `params={"limit": page_size, "offset": 0}`; as seguintes seguem o campo `next`
  da resposta, que já vem com querystring completa, por isso `params=None` depois da
  primeira chamada. A coleta corta assim que `len(results) >= max_items`, sem
  disparar a requisição da próxima página.
- **Concorrência (`fetch_all`).** `httpx.AsyncClient` combinado com
  `asyncio.Semaphore(concurrency)` dentro de `_fetch_all_async`. Cada URL vira uma
  corrotina `_bound_fetch` que adquire o semáforo antes de chamar `fetch_detail`.
  `asyncio.gather` preserva a ordem dos resultados na mesma ordem da lista de
  entrada, independente da ordem de conclusão.
- **Retry/backoff manual, sem `tenacity`.** Duas implementações quase idênticas
  coexistem: `_get_with_retry` (async, usa `await asyncio.sleep`) para
  `fetch_detail`, e `_get_with_retry_sync` (usa `time.sleep`) para `fetch_index`.
  Backoff exponencial `backoff_base * 2**attempt`, com `BACKOFF_BASE_SECONDS = 0.5`
  e `MAX_RETRIES = 5` (6 tentativas no total). `RETRYABLE_STATUS_CODES = {429, 500,
  502, 503, 504}`; qualquer outro `HTTPStatusError` (por exemplo 404) propaga na
  hora, sem retry.
- **Cache bronze.** Um arquivo `{cache_dir}/{id}.json` por pokémon. `fetch_detail`
  verifica `cache_file.exists()` antes de qualquer chamada de rede.
- **User-Agent.** Setado explicitamente (`USER_AGENT` constante) em ambos os
  clientes httpx. É boa prática se identificar ao consumir uma API pública.

### Por quê (tradeoffs de implementação)

- **Retry manual em vez de `tenacity`.** Uma dependência externa não se justifica
  para ~20 linhas de lógica, e o backoff manual é trivialmente testável via
  `monkeypatch.setattr(asyncio, "sleep", ...)` ou `monkeypatch.setattr(time, "sleep",
  ...)`, sem exigir conhecer a API de retry de uma biblioteca de terceiros nos
  testes.
- **Duas implementações de retry (sync/async) em vez de uma.** O mini-spec não
  declara `fetch_index` como `async` (só `fetch_detail` é), então manter
  `fetch_index` síncrono e duplicar a lógica de retry foi a opção mais simples e
  mais fiel ao contrato pedido, em vez de forçar tudo para async ou envolver a
  versão síncrona numa chamada `asyncio.run` por página. O custo é ~15 linhas
  duplicadas, aceitável dado o tamanho do módulo.
- **Escrita atômica do cache (tmp + replace) em vez de escrita direta.** Foi um
  pedido explícito de confiabilidade, não a correção de um bug encontrado. Escrever
  direto em `{id}.json` deixaria um JSON truncado no disco se o processo fosse
  interrompido no meio da escrita. Com `tmp.write_text(...)` seguido de
  `tmp.replace(cache_file)`, o rename é atômico no sistema de arquivos: ou o cache
  final existe inteiro, ou não existe. O `.tmp` órfão nunca é lido como cache
  válido.
- **`fetch_all` não expõe parâmetros de retry.** Os parâmetros `max_retries` e
  `backoff_base` existem em `_get_with_retry`/`_get_with_retry_sync`, mas não são
  propagados até `fetch_detail`/`fetch_all`/`fetch_index`, porque o mini-spec fixa
  essas assinaturas exatamente (`fetch_all(urls, concurrency=10, cache_dir=...)`).
  Os defaults de módulo (`MAX_RETRIES`, `BACKOFF_BASE_SECONDS`) cobrem o caso de uso
  real e ficam ajustáveis só por quem edita o código, não por parâmetro de chamada.

### Edge cases tratados

- **Fim de paginação.** `next: null` encerra o loop (`url = payload.get("next")`
  vira `None`).
- **`max_items` corta no meio de uma página.** Retorna `results[:max_items]` sem
  disparar a requisição da página seguinte.
- **URL sem barra final.** `extract_id` trata tanto `/pokemon/1/` quanto
  `/pokemon/1` (usa `rstrip("/")` antes do `rsplit`).
- **Cache hit nunca toca a rede.** Verificado explicitamente em teste, com um
  handler que levanta `AssertionError` se for chamado.
- **Escrita interrompida.** Se só o `.tmp` existir (o processo morreu no meio de
  uma escrita anterior), `fetch_detail` não o enxerga como cache (só olha para
  `{id}.json`) e refaz a busca. Nunca lê um JSON parcial.
- **Ordem preservada em coleta concorrente.** Mesmo com respostas chegando fora de
  ordem, `fetch_all` devolve os resultados na mesma ordem da lista `urls` de
  entrada.
- **Idempotência entre execuções.** Rodar `fetch_all` duas vezes com os mesmos
  `urls` não gera novas requisições na segunda vez, porque tudo já está em cache.

### Bugs encontrados e corrigidos

- **Recursão infinita nos helpers de teste (`_client_factory`/
  `_async_client_factory`).** Causa raiz: os helpers faziam
  `monkeypatch.setattr(httpx, "Client", factory)` e, dentro do próprio `factory`,
  chamavam `httpx.Client(...)`. Nesse ponto `httpx.Client` já era o `factory` (o
  patch já tinha sido aplicado ao atributo do módulo), então cada chamada
  reinvocava a si mesma infinitamente (`RecursionError: maximum recursion depth
  exceeded`). Correção: capturar `_RealClient = httpx.Client` e `_RealAsyncClient =
  httpx.AsyncClient` antes de qualquer `monkeypatch.setattr`, e usar essas
  referências guardadas dentro dos factories, nunca o atributo do módulo, que pode
  já estar substituído.
- **`fetch_all` quebrava ao rodar dentro do notebook (kernel Jupyter/IPython).**
  Descoberto só na Seção 5, ao executar `notebook.ipynb` de ponta a ponta pela
  primeira vez. Todos os testes, que rodam fora de um kernel, continuavam verdes.
  Causa raiz: `fetch_all` chamava `asyncio.run(...)` incondicionalmente. Um kernel
  Jupyter/IPython já mantém seu próprio event loop rodando o tempo todo, e
  `asyncio.run()` recusa ser chamado quando já existe um loop ativo no thread
  atual (`RuntimeError: asyncio.run() cannot be called from a running event
  loop`). Correção: `fetch_all` agora detecta se já há um loop rodando
  (`asyncio.get_running_loop()`); se houver, executa `_fetch_all_async` numa
  `ThreadPoolExecutor` de uma thread, com seu próprio `asyncio.run()` isolado
  nessa thread nova. Funciona tanto chamada de um script/teste comum quanto de
  dentro de um kernel. Teste de regressão:
  `test_fetch_all_works_when_called_from_a_running_event_loop`, que chama
  `fetch_all` de dentro de uma coroutine já rodando via `asyncio.run()`, simulando
  a situação de um kernel.

### Estratégia de testes

Toda a rede é mockada via `httpx.MockTransport` (nativo do `httpx`, sem dependência
extra). Nenhum teste bate na PokeAPI real. Grupos de teste em `tests/test_ingest.py`:

- **`extract_id`:** casos com e sem barra final.
- **`fetch_index`:** paginação até `next: null`; corte por `max_items`; header
  `User-Agent` presente; retry em erro transiente (503, 503, 200) e sucesso; erro
  não-retryable (404) propaga sem retry.
- **`fetch_detail`:** cache hit, onde a rede nunca é chamada; cache miss, onde busca
  e grava; escrita atômica, sem `.tmp` sobrando depois de um sucesso; `.tmp` órfão
  de escrita interrompida é ignorado como cache e a busca é refeita; retry em erro
  transiente até sucesso; erro não-retryable propaga na hora; esgotamento de todas
  as tentativas propaga o `HTTPStatusError` final.
- **`fetch_all`:** ordem dos resultados preservada e idempotência (a segunda
  chamada não gera requisições novas); limite real de concorrência, com um
  contador de requisições simultâneas em voo (um `asyncio.Lock` mais um contador
  dentro do handler mock) garantindo que nunca excede o `concurrency` passado;
  header `User-Agent` presente; regressão do bug do event loop, confirmando que
  chamar `fetch_all` de dentro de uma coroutine já rodando não levanta mais
  `RuntimeError`.

### Gotchas de ambiente

Nenhum específico deste módulo. É Python e `httpx` puros, sem dependência de
JVM/Spark.

### ADRs relacionados

[ADR-0006](../../docs/adr/0006-ingestao-async-cache-bronze.md): ingestão assíncrona
com cache bronze, fora do Spark.

---

## 2. Transformação: `src/transform.py`

### O que faz e onde

Bronze para silver: transforma a lista de detalhes brutos (JSON da PokeAPI, já em
memória como `list[dict]`) nas 4 tabelas do dicionário de dados, com schema Spark
explícito em todas elas. `inferSchema` é proibido.

| Função | Assinatura | Responsabilidade |
|---|---|---|
| `build_pokemon` | `(details) -> DataFrame` | `[pokemon_id, name, height, weight, base_experience]` |
| `build_pokemon_type` | `(details) -> DataFrame` | `[pokemon_id, type_name]`, explode de `types` |
| `build_pokemon_stats` | `(details) -> DataFrame` | `[pokemon_id, stat_name, base_stat]`, explode de `stats` |
| `build_pokemon_ability` | `(details) -> DataFrame` | `[pokemon_id, ability_name, is_hidden]`, explode de `abilities` |
| `write_silver` | `(df, name, base_path="data") -> None` | Grava Parquet em `{base_path}/silver/{name}` |

Suporte privado: `RAW_DETAIL_SCHEMA` (constante de módulo, o `StructType` do JSON
cru), `_get_spark()` (obtém ou cria a `SparkSession`) e `_details_to_df(details)`
(aplica o schema explícito sobre a lista de dicts).

### Como foi implementado

- **`RAW_DETAIL_SCHEMA`.** Um único `StructType` aninhado que espelha exatamente a
  forma do JSON de detalhe da PokeAPI. `types`, `stats` e `abilities` são
  `ArrayType(StructType([...]))`, cada um com a sub-estrutura aninhada
  (`type.name`, `stat.name`, `ability.name`), e `is_hidden` já declarado como
  `BooleanType()` na raiz do schema, não como `StringType` para converter depois.
  Esse schema é passado direto para `spark.createDataFrame(details, schema=...)`;
  o Spark nunca infere nada a partir dos dados.
- **Uma conversão por chamada.** Cada `build_*` chama `_details_to_df(details)`
  internamente, ou seja, os `details` (Python puro) são convertidos para
  `DataFrame` uma vez por função, não uma vez só e reaproveitada entre as 4. Ver o
  tradeoff correspondente abaixo.
- **Explode seguido de select, em duas etapas.** Em `build_pokemon_type`, por
  exemplo, primeiro `select(pokemon_id, explode(types).alias(type_entry))`, depois
  um segundo `select` que extrai `type_entry.type.name`. A mesma receita se
  repete para `stats` e `abilities`.
- **`SparkSession` obtida via singleton (`getOrCreate`).** `_get_spark()` não
  recebe `spark` como parâmetro: chama
  `SparkSession.builder.appName(...).master(...).getOrCreate()`, que reaproveita
  uma sessão já ativa na JVM se existir. É assim que os testes conseguem plugar
  uma `SparkSession` de teste com `master("local[1]")`, criada antes, e o código
  de produção simplesmente a reutiliza.
- **`write_silver`.** `df.write.mode("overwrite").parquet(...)` sobrescreve o
  diretório de destino inteiro a cada chamada, o que torna a etapa reprocessável
  sem acumular dados.

### Por quê (tradeoffs de implementação)

- **Schema explícito em vez de `inferSchema`.** É uma exigência do mini-spec, mas
  também se justifica tecnicamente: `inferSchema` faria o Spark ler os dados duas
  vezes (uma para inferir tipos, outra para carregar), e o tipo inferido pode
  variar entre execuções se algum campo aparecer `null` em todas as amostras de
  uma rodada. Com `StructType` fixo, o schema é sempre o mesmo, independente do
  conteúdo.
- **`_get_spark()` sem parâmetro `spark` explícito, em vez de injeção de
  dependência.** O mini-spec fixa a assinatura `build_pokemon(details)`, sem lugar
  para passar uma `SparkSession`. A alternativa mais pura e testável sem estado
  global seria `build_pokemon(spark, details)`, mas isso quebraria o contrato. O
  tradeoff aceito é que as funções dependem implicitamente de uma `SparkSession`
  ativa ou criável no processo, o que é o padrão de fato em código PySpark de
  produção: raramente se passa `spark` explicitamente entre módulos.
- **Reconverter `details` em `DataFrame` a cada `build_*` (4 vezes), em vez de
  converter uma vez e reaproveitar.** Decorre de seguir a assinatura do mini-spec
  ao pé da letra: cada função recebe `details` (a lista Python), não um
  `DataFrame` já pronto. O custo de chamar `createDataFrame` 4 vezes sobre os
  mesmos ~1300 registros é pequeno nessa escala, e essa não é a etapa que o
  mini-spec pede para otimizar (as otimizações de `broadcast`/`cache` são para a
  etapa de análise, não para o transform). Fica documentado aqui para não passar
  a impressão de descuido.
- **Semântica de `base_path` em `write_silver`.** O mini-spec dá o exemplo literal
  `data/silver/{name}`. Em vez de `base_path` já ser a raiz do silver, o que
  exigiria passar `"data/silver"` toda vez, `write_silver` recebe `base_path="data"`
  por default e concatena `"silver"/name` internamente. É uma escolha de
  nomenclatura que vale a pena checar antes de reusar a função em outro contexto:
  passar `base_path="data/silver"` por engano duplicaria o `"silver"` no caminho
  final.

### Edge cases tratados

- **Pokémon sem tipos, stats ou abilities.** `explode()` sobre uma lista vazia
  simplesmente não gera nenhuma linha para aquele pokémon na tabela explodida (não
  lança erro nem gera `null`). É o comportamento padrão do Spark, sem tratamento
  especial no código, mas vale saber que esse pokémon some da tabela derivada.
- **`is_hidden` como boolean real.** Validado explicitamente em teste
  (`isinstance(df.schema["is_hidden"].dataType, BooleanType)` e filtros
  `df.is_hidden == True` / `== False`), como proteção contra uma regressão comum
  em pipelines que leem JSON: acabar com `"true"`/`"false"` como string.
- **`write_silver` com `mode("overwrite")`.** Reprocessar com um dataset menor
  substitui o conteúdo anterior inteiro, sem merge nem append. É o comportamento
  esperado, coberto por teste (`test_write_silver_overwrites_on_rerun`).

### Bugs encontrados e corrigidos

- **`python:3.11-slim` mudou de base e passou a trazer só OpenJDK 21 via `apt`,
  incompatível com `pyspark==3.5.3`.** Causa raiz: a tag `slim`, sem qualificador
  de release, segue a versão mais recente do Debian. Em algum momento passou a
  apontar para `trixie`, cujo repositório não tem mais `openjdk-17-jre-headless`
  disponível (só `openjdk-21-*`), e o Spark 3.5.x não suporta oficialmente Java
  21. O mesmo problema se manifestou localmente antes do Docker: `pip install
  pyspark` sem pin de versão trouxe `pyspark==4.2.0`, que exige Java 17+, e travou
  indefinidamente contra o JDK 8 instalado neste ambiente Windows. Correção: (1)
  pinar `pyspark==3.5.3` em `pyproject.toml`, que suporta Java 8/11/17; (2) fixar a
  imagem base do Dockerfile em `python:3.11-slim-bookworm` (Debian 12, que ainda
  empacota `openjdk-17-jre-headless`) em vez de `python:3.11-slim`.
- **Comparação de `StructType` completo falhando no round-trip de Parquet.** Causa
  raiz: `read_back.schema == df.schema` comparava também a flag `nullable` de cada
  campo, e o leitor de Parquet do Spark marca todas as colunas como
  `nullable=True` ao ler de volta, independente do que foi declarado na escrita
  (`nullable=False` em `pokemon_id`/`name`, por exemplo, não sobrevive ao
  round-trip). Esse teste só falhava em Linux/Docker, porque no Windows local ele
  ficava `skip` (ver Gotchas abaixo), e só apareceu quando validamos a execução
  real no ambiente oficial. Correção: comparar apenas `(nome, tipo)` de cada
  campo, não o `StructType` inteiro: `[(f.name, f.dataType) for f in
  schema.fields]`.

### Estratégia de testes

`tests/conftest.py` define uma fixture `spark` de escopo `session` (`local[1]`, UI
desligada, `spark.sql.shuffle.partitions=1` para execução rápida e determinística;
sem isso, o número default de partições de shuffle geraria dezenas de tasks vazias
para um dataset de 3 linhas). `tests/test_transform.py` usa uma fixture de 3
pokémons lavrados à mão (bulbasaur multi-tipo com uma hidden ability, charmander e
squirtle mono-tipo, squirtle também com hidden ability) cobrindo:

- **Schema explícito por tabela:** comparação campo a campo do `StructType`
  retornado contra o esperado, pegando qualquer drift acidental de tipo (por
  exemplo um `IntegerType` que vire `LongType`, ou perda do `BooleanType` em
  `is_hidden`).
- **Grão de cada tabela:** contagem de linhas esperada por explode (`pokemon_type`
  deve ter 4 linhas: 2 do bulbasaur, 1 do charmander e 1 do squirtle, não 3, uma
  por pokémon).
- **`is_hidden` booleano real:** filtro por `== True`/`== False` retornando os
  nomes certos de habilidade.
- **`write_silver`:** grava e lê de volta em round-trip, e confirma que uma
  segunda escrita com dataset menor sobrescreve em vez de acumular.

### Gotchas de ambiente

- **Windows local sem `hadoop.dll`.** A escrita de Parquet passa pelo
  `FileOutputCommitter` do Hadoop, que no Windows chama
  `NativeIO$Windows.access0` via JNI. Isso falha com `UnsatisfiedLinkError` se só
  existir `winutils.exe` sem o `hadoop.dll` correspondente, exatamente o caso
  deste ambiente (`HADOOP_HOME` estava setado, mas só com `winutils.exe`). Os 2
  testes de `write_silver` detectam isso checando a existência real do arquivo
  `%HADOOP_HOME%\bin\hadoop.dll`, não só a variável de ambiente, e usam
  `pytest.mark.skipif` com motivo explícito. O ambiente que efetivamente valida
  essa escrita é o Docker/CI (Linux), onde essa limitação não existe. Validado
  manualmente: `docker build` mais `docker run pytest` no container rodou os 27
  testes da Parte 1 (na época, antes do `quality.py`) sem nenhum skip.
- **Versão do JDK.** Precisa ser 8, 11 ou 17, não 21, para `pyspark==3.5.3`. O
  Dockerfile fixa Java 17 (`openjdk-17-jre-headless` no
  `python:3.11-slim-bookworm`); o CI usa `actions/setup-java` com `distribution:
  temurin, java-version: "17"` para garantir o mesmo JDK no `ubuntu-latest` do
  GitHub Actions.

### ADRs relacionados

[ADR-0007](../../docs/adr/0007-medallion-bronze-silver-gold.md): camadas medallion
(bronze/silver/gold). [ADR-0015](../../docs/adr/0015-spark-local-notebook-portavel.md):
Spark local dockerizado com notebook portátil, o que justifica por que o ambiente
oficial de validação é o Docker/Linux, não o host Windows.

---

## 3. Qualidade: `src/quality.py`

### O que faz e onde

Checks de qualidade sobre as tabelas silver, com fail loud: o pipeline para
(exceção levantada) se uma invariante crítica for violada, em vez de só logar um
aviso.

| Função/Classe | Assinatura | Responsabilidade |
|---|---|---|
| `DataQualityError` | `Exception` | Levantada quando uma invariante crítica é violada |
| `check_not_null` | `(df, cols) -> dict` | Conta nulos por coluna |
| `check_unique` | `(df, cols) -> dict` | Verifica se `cols` combinadas formam chave única |
| `check_referential` | `(child, parent, key="pokemon_id") -> dict` | Zero órfãos: toda chave de `child` deve existir em `parent` |
| `run_quality_report` | `(dfs) -> None` | Orquestra os 6 checks, imprime relatório, levanta se algo crítico falhar |

Suporte privado: `_print_report(checks)` (formata e imprime a tabela de
resultados).

### Como foi implementado

- **Tipo de retorno "report".** Um `dict` simples `{"check": str, "passed": bool,
  "details": str}`, não uma `dataclass` ou classe própria. Ver o tradeoff
  correspondente abaixo.
- **`check_not_null`:** `df.filter(F.col(col).isNull()).count()` por coluna;
  `passed = all(count == 0 ...)`.
- **`check_unique`:** `df.groupBy(*cols).count().filter(F.col("count") >
  1).count()` conta quantos grupos de chave aparecem mais de uma vez, não quantas
  linhas duplicadas no total.
- **`check_referential`:** um anti-join, `child.join(parent.select(key).distinct(),
  on=key, how="left_anti").count()`, retorna as linhas de `child` cuja chave não
  existe em `parent`; a contagem dessas linhas é o número de órfãos.
- **`run_quality_report`:** monta uma lista de tuplas `(resultado_do_check,
  is_critico: bool)`:
  1. `check_not_null(pokemon, ["pokemon_id"])`, crítico
  2. `check_unique(pokemon, ["pokemon_id"])`, crítico
  3. `check_unique(pokemon_type, ["pokemon_id", "type_name"])`, não crítico
  4. `check_referential(pokemon_type, pokemon)`, crítico
  5. `check_referential(pokemon_stats, pokemon)`, crítico
  6. `check_referential(pokemon_ability, pokemon)`, crítico

  O relatório completo é impresso antes de decidir se levanta: mesmo numa falha
  crítica, todos os 6 resultados aparecem no relatório, sem parar no primeiro
  erro. Depois, todos os checks críticos que falharam (não só o primeiro) são
  coletados e um único `DataQualityError` é levantado com o resumo de todos eles
  concatenado.

### Por quê (tradeoffs de implementação)

- **Criticidade decidida em `run_quality_report`, não nas funções `check_*`.** O
  mini-spec fixa as assinaturas `check_not_null(df, cols)`, `check_unique(df,
  cols)` e `check_referential(child, parent, key="pokemon_id")`, sem espaço para
  um parâmetro `critical=`. Em vez de quebrar essas assinaturas, "o que é
  crítico" foi tratado como uma decisão de negócio que pertence só ao
  orquestrador (`run_quality_report`): as funções `check_*` são primitivas
  genéricas e reaproveitáveis, e não precisam saber em que contexto estão sendo
  usadas.
- **`dict` em vez de `dataclass` para o "report".** Uma primeira versão usava uma
  `dataclass CheckResult`, simplificada depois para `dict` puro porque o
  mini-spec não pede um tipo específico. `dict` mantém o módulo sem uma classe
  extra só para carregar 3 campos, é mais simples de inspecionar em teste
  (`result["passed"]`) e mais fácil de logar ou serializar no futuro, se
  necessário.
- **Fail loud (exceção) em vez de log-only.** Foi um requisito explícito do
  usuário para este módulo. A checagem existe justamente para impedir que uma
  camada silver inconsistente vire uma camada gold enganosa, e combina com a
  filosofia de medallion do ADR-0007 ("reprocessável a partir da camada
  anterior"): é preferível parar aqui, no silver, a propagar um erro para a
  análise e descobrir tarde.
- **Quais invariantes são críticas.** PK nula ou duplicada em `pokemon`, e
  órfãos nas 3 tabelas-filhas, foram as invariantes explicitamente apontadas
  como capazes de quebrar o pipeline. A unicidade composta `(pokemon_id,
  type_name)` em `pokemon_type` fica não crítica de propósito: uma linha
  duplicada nesse par não corrompe a integridade referencial nem, sozinha,
  invalida as agregações das análises, que usam `countDistinct`. Ainda assim ela
  aparece como `FAIL` no relatório impresso, visível para quem revisar, só não
  derruba o pipeline. Se isso mudar (por exemplo, se uma análise futura passar a
  somar sem `distinct`), basta mover essa entrada para `critical=True` na lista
  de `run_quality_report`.
- **Reportar todos os checks críticos falhos de uma vez, sem parar no
  primeiro.** Evita o cenário de corrigir uma invariante, rodar de novo e só
  então descobrir uma segunda invariante quebrada que estava escondida atrás da
  primeira exceção. O relatório e a mensagem de erro já mostram o quadro
  completo na primeira tentativa.

### Edge cases tratados

- **DataFrames vazios.** Todo check passa trivialmente (0 nulos, 0 duplicatas, 0
  órfãos). Não é um caso especial no código, é consequência natural das
  agregações usadas (`count()` sobre um DataFrame vazio é `0`).
- **Múltiplas invariantes críticas quebradas ao mesmo tempo.**
  `run_quality_report` levanta uma única exceção cujo texto lista todas as
  falhas críticas (join por `"; "`), não só a primeira encontrada.

### Bugs encontrados e corrigidos

Nenhum bug novo neste módulo durante a implementação. Foi construído sobre os
contratos de `transform.py` já validados no Docker/CI na etapa anterior. A
validação Docker/Linux do passo anterior, com o fix do JDK e da comparação de
`StructType`, foi um pré-requisito para poder confiar nos testes de
`quality.py`, que também sobem uma `SparkSession` real.

### Estratégia de testes

`tests/test_quality.py` não reaproveita `transform.py` para gerar os DataFrames
de teste: define seus próprios `StructType` locais (`POKEMON_SCHEMA`,
`TYPE_SCHEMA`, `STATS_SCHEMA`, `ABILITY_SCHEMA`), todos com `nullable=True` em
todas as colunas. Isso é deliberado. Os testes de `quality.py` precisam
conseguir construir DataFrames inválidos de propósito (por exemplo, um
`pokemon_id` nulo) para exercitar os checks, e o schema de produção do
`transform.py` declara `pokemon_id`/`name` como `nullable=False`. Usar esse
schema aqui misturaria "testar a checagem de qualidade" com "testar se o Spark
aceita ou rejeita valores nulos contra um schema estrito", uma pergunta
diferente, já coberta implicitamente pelos testes de `transform.py`. Cobertura:

- **Cada `check_*` isoladamente:** caso feliz e caso de violação para
  `check_not_null` (sem nulos e com PK nula), `check_unique` (chave simples e
  chave composta, ambas com e sem duplicata) e `check_referential` (sem órfão e
  com órfão).
- **`run_quality_report`, uma invariante crítica por vez:** PK nula, PK
  duplicada, órfão em `pokemon_type`, órfão em `pokemon_stats` e órfão em
  `pokemon_ability`, cada um em um teste dedicado que afirma
  `pytest.raises(DataQualityError)`.
- **Caso feliz de `run_quality_report`:** não levanta, e a saída capturada
  (`capsys`) contém o cabeçalho do relatório e nenhum `"FAIL"`.
- **Violação não crítica:** a duplicata em `(pokemon_id, type_name)` aparece
  como `"FAIL"` na saída capturada, mas `run_quality_report` não levanta. Isso
  trava a decisão de design de que essa violação é reportada, não fatal, num
  teste, não só num comentário.

### Gotchas de ambiente

Nenhum novo além dos já descritos na seção de `transform.py` (mesma fixture
`spark` de `conftest.py`, mesmas exigências de JDK). Validado de ponta a ponta em
Docker/Linux: 42/42 testes da Parte 1 passam (`ingest`, `transform` e
`quality`), incluindo os 2 testes de Parquet que no Windows local ficam `skip`.

### ADRs relacionados

[ADR-0007](../../docs/adr/0007-medallion-bronze-silver-gold.md): o quality check
é o portão entre silver e gold que garante que a camada gold só é gerada a
partir de dados consistentes.

---

## 4. Análises: `src/analysis.py`

### O que faz e onde

Silver para gold: as 3 análises do mini-spec, como funções puras sobre
`DataFrame`s. Recebem os DFs do silver já carregados, nunca leem Parquet
diretamente, e são determinísticas (mesma entrada, mesma saída, sem estado
global além do cache do Spark).

| Função | Assinatura | Responsabilidade |
|---|---|---|
| `forca` | `(stats) -> DataFrame` | `[pokemon_id, forca]` = soma de todos os `base_stat` por pokémon. Cacheada. |
| `q1_multitype_above_avg` | `(pokemon, types, stats) -> tuple[int, DataFrame]` | Quantos pokémons são multi-tipo e têm força acima da média? `(resultado, df_detalhe)` |
| `q2_abilities_exclusive_multitype` | `(types, abilities) -> DataFrame` | `[ability_name]`: abilities que nunca aparecem em pokémon mono-tipo |
| `q3_top5_versatility` | `(pokemon, types, stats, abilities) -> DataFrame` | `[pokemon_id, name, versatility_score]`: top 5 por versatilidade |

Suporte privado: `_n_types(types)` (contagem de tipos distintos por pokémon,
reaproveitada por Q1, Q2 e Q3).

### Como foi implementado

- **`forca(stats)`:** `stats.groupBy("pokemon_id").agg(F.sum("base_stat")...)`,
  seguido de `.cache()` antes de retornar. É chamada internamente por `q1` e por
  `q3` (cada uma recebe `stats`, não `forca` já pronta; ver "Por quê" abaixo).
- **`q1_multitype_above_avg`:** calcula `forca_df` e `n_types_df`. A média usada
  no filtro vem de `forca_df.agg(F.avg("forca")).first()[0]`, um valor escalar
  extraído do DataFrame de forças (uma linha por pokémon), não uma agregação
  sobre a tabela de stats crua. Filtra `n_types > 1 AND forca > media`, junta com
  `pokemon` só para trazer o `name` no detalhe, e conta o resultado final.
- **`q2_abilities_exclusive_multitype`:** cruza `n_types_df` com `abilities`,
  dando para cada linha de habilidade quantos tipos o pokémon dono tem. Filtra
  `n_types == 1` e extrai o conjunto distinto de `ability_name` (abilities que
  aparecem em algum mono-tipo). O resultado final é
  `abilities.distinct().subtract(abilities_em_mono)`.
- **`q3_top5_versatility`:** monta `forca_df`, `n_types_df` e `n_abilities_df`
  (`countDistinct("ability_name")` por pokémon, contando também as com
  `is_hidden=true`, um contrato explícito do mini-spec), junta os três por
  `pokemon_id`, calcula a coluna `versatility_score = n_types*2 + n_abilities +
  forca/100`, ordena por `(score desc, pokemon_id asc)`, corta em 5 e só então
  junta com `pokemon` para trazer o `name` das 5 linhas finais.
- **Broadcast.** Todo join de uma tabela grande (`forca_df`, `abilities`) contra
  uma agregação derivada de dimensão pequena (`n_types_df`, `n_abilities_df`, ou
  o `pokemon.select("pokemon_id", "name")` reduzido) usa `F.broadcast(...)` do
  lado pequeno, evitando shuffle nessas junções.

### Por quê (tradeoffs de implementação)

- **A pegadinha da média em Q1, explícita no código.** "Média geral da força" é
  a média das forças por pokémon, uma linha por pokémon no `forca_df`, não a
  média linha-a-linha da tabela `pokemon_stats`, que tem uma linha por
  combinação pokémon-stat e pesaria errado pokémons com mais stats registrados.
  O código calcula `forca_df.agg(F.avg("forca"))`, ou seja, a média é tirada
  depois de já ter agregado por pokémon, nunca direto sobre
  `stats.select("base_stat")`. Isso está comentado explicitamente no docstring
  de `q1_multitype_above_avg`, não só aqui, para quem ler o código não repetir o
  erro numa mudança futura. O teste
  `test_q1_uses_average_of_forca_per_pokemon_not_average_of_raw_base_stat`
  documenta e trava numericamente essa diferença (ver "Estratégia de testes").
- **`forca(stats)` chamada de forma independente por `q1` e `q3`, em vez de
  passada como parâmetro entre elas, e por que isso não quebra o `cache()`.** O
  mini-spec fixa as assinaturas de `q1`/`q3` recebendo `stats` (a tabela crua),
  não `forca` já pronta, o que significa que na prática `q1_multitype_above_avg`
  e `q3_top5_versatility` cada uma chama `forca(stats)` por conta própria: dois
  objetos Python de `DataFrame` diferentes. Isso é seguro porque o `cache()` do
  Spark não é indexado pela instância Python do objeto, e sim pelo plano lógico
  analisado da consulta. Se as duas chamadas recebem o mesmo `stats` de entrada
  e aplicam exatamente a mesma transformação
  (`groupBy("pokemon_id").agg(sum(...))`), o `CacheManager` do Spark reconhece
  os planos como equivalentes e reaproveita os dados já materializados na
  segunda chamada, sem recomputar. Na prática isso só funciona se as duas
  chamadas realmente recebem o mesmo objeto `stats`, e é assim que uma futura
  orquestração (notebook) deve chamar `q1`/`q3`: passando o `stats` lido uma
  única vez do Parquet.
- **`_n_types` extraído como função privada compartilhada.** Q1, Q2 e Q3
  precisam da mesma contagem de tipos por pokémon. Extrair evita reescrever a
  mesma `groupBy`/`countDistinct` três vezes e garante que as três análises usam
  exatamente a mesma definição de quantos tipos um pokémon tem.
- **Q2 segue os passos literais do mini-spec (join com `n_types` completo,
  depois filtra `== 1`) em vez de já juntar só com os mono-tipo
  pré-filtrados.** As duas formas dão o mesmo resultado, já que juntar com
  `n_types_df` inteiro e filtrar depois equivale a filtrar `n_types_df` para
  mono-tipo antes do join. A primeira foi escolhida por ser exatamente a receita
  descrita no mini-spec, mais fácil de auditar linha a linha contra o
  enunciado; o `broadcast()` no join compensa qualquer custo extra de trazer o
  `n_types` completo, que é uma tabela pequena de qualquer forma.
- **Tiebreaker determinístico em Q3 (`pokemon_id` asc).** Sem uma chave de
  desempate explícita, `orderBy(score.desc()).limit(5)` não garante ordem
  estável entre linhas com o mesmo `versatility_score`; o resultado do top 5
  poderia variar entre execuções, ou entre um plano de 1 partição local e um
  cluster com várias partições, quando há empate na borda do corte. Ordenar por
  `(score desc, pokemon_id asc)` antes do `limit(5)` fixa qual dos empatados
  entra.
- **`q1`/`q3` recebem `pokemon` só para anexar o `name`.** O cálculo de
  contagem ou score em si não depende de nenhuma coluna de `pokemon` além do
  `pokemon_id`, que já vem de `forca`/`n_types`. `pokemon` é usado
  exclusivamente para tornar o resultado legível (nome em vez de só id), por
  isso o join com `pokemon` é sempre o último passo, depois de já ter reduzido
  as linhas ao mínimo necessário: o `.filter(...)` em Q1, o `.limit(5)` em Q3.

### Edge cases tratados

- **Empate exatamente na borda do top 5.** Coberto explicitamente no fixture de
  teste (dois pokémons com o mesmo `versatility_score`, um deles posicionado
  como o 5º ou 6º colocado). Sem o tiebreaker, esse caso teria resultado
  ambíguo. Ver "Estratégia de testes".
- **Pokémon sem nenhuma ability, tipo ou stat.** Não aparece nos DataFrames
  agregados correspondentes (`_n_types`, `n_abilities_df`, `forca`). Como os
  joins entre essas agregações e `forca_df`/`abilities` são `inner join`
  (default), um pokémon faltando em uma das três dimensões simplesmente não
  entra no resultado de Q1/Q3, sem gerar `null` nem erro. Não há pokémon assim
  no dicionário de dados real, já que todo pokémon tem pelo menos 1 tipo, 1 stat
  e 1 ability, mas vale registrar o comportamento caso o dado de entrada um dia
  tenha uma lacuna.
- **`n_abilities` conta habilidades escondidas.** `is_hidden=true` participa da
  contagem normalmente (`countDistinct("ability_name")` não filtra por
  `is_hidden`), uma decisão explícita do mini-spec, testada indiretamente pelo
  fixture (bulbasaur tem uma ability hidden e uma não-hidden, `n_abilities=2`).

### Bugs encontrados e corrigidos

Nenhum bug de implementação encontrado nesta etapa. Foi construído diretamente
sobre os contratos de `transform.py`/`quality.py` já validados nas etapas
anteriores, e a suíte de testes com valores calculados à mão (ver abaixo)
pegaria qualquer erro de lógica antes de chegar ao Docker.

### Estratégia de testes

`tests/test_analysis.py` usa o mesmo padrão de `test_quality.py` (schemas
locais `nullable=True`, independentes de `transform.py`) com um fixture de 6
pokémons desenhado para que as 3 respostas sejam calculáveis à mão e
verificáveis exatamente. Não é um teste de "rodou sem lançar exceção":

- **`forca`:** valores exatos por pokémon (`{1: 94, 2: 122, 3: 91, 4: 92, 5: 85,
  6: 92}`) e um teste dedicado que confirma `storageLevel.useMemory is True`,
  prova de que o `.cache()` foi de fato chamado.
- **Q1, a pegadinha travada numericamente.** A soma total de `base_stat` é 576
  nos dois cenários (o mesmo número, já que a soma não muda com o agrupamento),
  mas a média certa, das 6 forças, é `576/6 = 96.0`, enquanto a média errada,
  das 12 linhas de stat, seria `576/12 = 48.0`. Com o divisor certo, só
  `ivysaur` (forca 122) supera a média e é multi-tipo, então `resultado == 1`.
  Com o divisor errado, `bulbasaur` (94), `ivysaur` (122) e `pidgey` (85)
  passariam do limiar (48), e `resultado` seria `3`. O teste
  `test_q1_uses_average_of_forca_per_pokemon_not_average_of_raw_base_stat`
  afirma `resultado == 1` e documenta no docstring por que `3` seria o valor de
  uma implementação errada. Qualquer regressão nessa conta muda o resultado
  observável do teste, não só um detalhe interno.
- **Q2, as 3 categorias pedidas, todas no mesmo fixture.** `overgrow` (só em
  bulbasaur e ivysaur, ambos multi-tipo) e `keen-eye` (só em pidgey, multi-tipo)
  têm que entrar. `chlorophyll` (aparece no bulbasaur e no charmander, mono-tipo)
  tem que ficar de fora: é o caso mais traiçoeiro, porque uma implementação que
  verificasse só "aparece em algum multi-tipo", em vez de "nunca aparece em
  mono-tipo", incluiria `chlorophyll` erradamente. `blaze`, `torrent` e
  `run-away` (só em mono-tipo) ficam de fora de forma trivial. Um teste final
  (`test_q2_exact_result_set`) confere o conjunto exato `{"overgrow",
  "keen-eye"}`, além dos testes que isolam cada categoria.
- **Q3, ranking e tiebreaker.** `squirtle` (id 4) e `rattata` (id 6) têm
  `versatility_score` idêntico (3.92) de propósito, posicionados exatamente na
  fronteira do corte entre o 5º e o 6º lugar. O teste confere a lista ordenada
  completa de `pokemon_id`, `name` e `versatility_score` (com `pytest.approx`
  para a divisão fracionária de `forca/100`) e, separadamente, confirma que
  `squirtle` (id menor) entra e `rattata` (id maior) fica de fora. Sem o
  `orderBy` com a chave de desempate, esse teste seria instável, podendo passar
  ou falhar dependendo da ordem física dos dados no plano do Spark.

### Gotchas de ambiente

Nenhum novo além dos já descritos nas seções de `transform.py`/`quality.py`
(mesma fixture `spark` de `conftest.py`, mesmas exigências de JDK 8/11/17).
Validado de ponta a ponta em Docker/Linux: 52/52 testes da Parte 1 passam
(`ingest`, `transform`, `quality` e `analysis`).

### ADRs relacionados

[ADR-0007](../../docs/adr/0007-medallion-bronze-silver-gold.md): a camada gold
(estas 3 análises) só é gerada depois do portão de qualidade do silver.
`cache()`/`broadcast()` aqui são as otimizações citadas no blueprint original
para esta etapa; a etapa de transform, por contraste, não teve otimização de
performance como objetivo (ver seção 2).

---

## 5. Notebook: `notebook.ipynb`

### O que faz e onde

`notebook.ipynb`, na raiz de `part1-pokeapi-analytics/`, é o entregável oficial
da Parte 1: a camada de orquestração, narrativa e apresentação. Importa e chama,
em sequência, as funções já implementadas e testadas em `src/`. Não reimplementa
nenhuma lógica de ingestão, transformação, qualidade ou análise.

Fluxo das 22 células (11 de código, 11 de markdown intercaladas):

1. Setup: `sys.path`, imports de `src.ingest`, `src.transform`, `src.quality`,
   `src.analysis` e `src.report`, criação da `SparkSession` (`local[*]`).
2. Ingestão: `ingest.fetch_index()` mais `ingest.fetch_all(...)` com o cache
   bronze.
3. Transformação: as 4 `build_*` de `transform.py` e `write_silver` de cada
   uma.
4. Qualidade: `quality.run_quality_report(...)`.
5. As 3 análises: `analysis.q1_multitype_above_avg`,
   `q2_abilities_exclusive_multitype` e `q3_top5_versatility`, cada uma
   precedida de uma célula markdown com a pergunta, a fórmula ou lógica e, para
   Q1 e Q2, a pegadinha explicada em prosa, seguida de `print()`s claros da
   resposta.
6. Visualização: bar chart do top 5 (Q3) e histograma da distribuição de força
   com a linha da média (Q1, reforçando a pegadinha visualmente), via
   `report.build_top5_chart`/`report.build_forca_distribution_chart` (Seção 6),
   exibidos com `IPython.display.Image`.
7. Relatório gerencial: persiste os resultados e gera o HTML com logo, cores
   e os mesmos dois gráficos (Seção 6).
8. Conclusão: link para este documento.

### Como foi implementado

- **PySpark vanilla.** Nenhuma célula usa `display()`, `dbutils`, sessão
  pré-provida ou Delta: só `SparkSession.builder...getOrCreate()` explícito e
  `print()`/`.show()` para saída. Os gráficos (Seção 5) não usam nenhuma magic
  do IPython (nem `%matplotlib inline`): são gerados por
  `report.build_top5_chart`/`report.build_forca_distribution_chart` (Seção 6),
  que devolvem PNG em base64, exibido via
  `IPython.display.Image`/`display()` (funções padrão do `IPython.display`,
  disponíveis em qualquer kernel Jupyter, Colab ou Databricks).
- **Execução e prova via `papermill`, não `nbconvert`.** O notebook é executado
  de ponta a ponta via `papermill notebook.ipynb notebook.ipynb --log-output`, o
  mesmo arquivo de entrada e saída, rodando in place. A flag `--log-output` faz
  o papermill transmitir ao vivo, para o stdout do processo, o texto que cada
  célula imprime, além de gravar os outputs no JSON do notebook. Isso resolve
  dois requisitos ao mesmo tempo: o notebook commitado fica com as respostas e
  os gráficos embutidos, e `docker compose up`/`make up-p1` mostram as 3
  respostas no terminal do avaliador, sem precisar abrir o Jupyter.
  `jupyter nbconvert --execute` sozinho não atende ao segundo requisito: grava
  os outputs no JSON, mas não espelha o `print()` das células no stdout do
  processo pai enquanto executa. O ADR-0015 já cotava o papermill como
  ferramenta de prova de reprodutibilidade; aqui ele também vira o mecanismo de
  execução de produção.
- **Dataset completo por padrão.** `MAX_ITEMS = None` na célula de ingestão
  coleta os ~1350 pokémons reais (ver números exatos abaixo). Trocar para um
  inteiro, por exemplo `50`, faz um smoke test rápido em desenvolvimento, sem
  editar nenhuma outra célula.
- **Uma única `SparkSession` para o notebook inteiro.** Criada uma vez na
  célula 2 (`master("local[*]")`) e reaproveitada por todas as chamadas de
  `src/` via o mesmo mecanismo de `getOrCreate()` documentado na Seção 2. O
  notebook não precisa, e não deve, recriar uma sessão por etapa.
- **Docker.** O `Dockerfile` ganhou `matplotlib`, `ipykernel` e `papermill`
  como dependências (via `pyproject.toml`) e um passo de build `python -m
  ipykernel install --sys-prefix --name python3`; sem isso, o papermill não
  encontra o kernel `"python3"` referenciado nos metadados do notebook. O `CMD`
  da imagem e o `command` do `docker-compose.yml` chamam exatamente o comando
  de execução acima.

### Por quê (tradeoffs de implementação)

- **`papermill` em vez de `jupyter nbconvert --execute` para a execução de
  produção.** Os dois usam o mesmo motor de execução por baixo (`nbclient`, via
  um kernel Jupyter real), mas só o papermill tem a flag de log ao vivo que o
  critério de pronto exige: imprimir as 3 respostas no terminal de quem roda
  `docker compose up`. `jupyter nbconvert --to script` converteria as células
  de código para um `.py` executável direto, mas perderia o texto das células
  markdown (a narrativa) e não teria vantagem sobre o papermill nesse ponto,
  já que os gráficos hoje não dependem de nenhuma magic do IPython (Seção 5)
  para funcionar dentro de um kernel real.
- **Dataset completo por padrão, não uma amostra.** O objetivo do notebook é
  responder as 3 perguntas de verdade. Uma amostra por padrão obrigaria o
  avaliador a lembrar de trocar `MAX_ITEMS` antes de confiar nos números; o
  parâmetro existe para desenvolvimento rápido, não é o caminho de entrega.
- **Notebook não é bind-mounted no `docker-compose.yml`.** O volume monta só
  `./data` (o cache bronze), não o próprio `notebook.ipynb`. É uma decisão
  deliberada: se o notebook fosse montado, cada `docker compose up` do
  avaliador sobrescreveria o arquivo local com uma nova execução, sujando o
  `git status` a cada rodada. Sem o mount, `docker compose up` sempre mostra as
  3 respostas no terminal (via `--log-output`), e o `.ipynb` commitado, com as
  saídas desta sessão, continua sendo a referência de "olhe sem rodar nada". As
  duas formas de consumir o resultado ficam desacopladas.
- **Uma célula de código por etapa, com markdown antes de cada pergunta.** A
  granularidade fina, 10 células de código em vez de 3 ou 4 maiores, deixa o
  log do `--log-output` legível: cada `Executing Cell N` no terminal corresponde
  a uma etapa nomeável do pipeline, o que ajuda a depurar se algo falhar no
  meio.

### Edge cases tratados

- **Empate real no dataset de produção.** Rodando com os ~1350 pokémons reais,
  a Q3 tem um empate genuíno de 4 vias em `score=13.00` na fronteira do top 5
  (`kommo-o`, `dragapult`, `archaludon`, `kommo-o-totem`). O tiebreaker
  determinístico de `q3_top5_versatility` (Seção 4) não é só um cenário de
  teste hipotético: resolve um empate que realmente acontece nos dados reais.
- **Falha de qualidade interrompe o notebook, por design (fail loud).** A
  célula de `run_quality_report` não está envolvida em `try/except`. Se uma
  invariante crítica falhar, a exceção propaga e a execução do notebook para
  ali, sem gerar as análises a partir de um silver ruim. É o comportamento
  desejado (ver Seção 3), não um bug a esconder.
- **Reprocessamento idempotente.** Rodar o notebook duas vezes seguidas não
  duplica nada: `write_silver` sobrescreve (Seção 2) e o cache bronze evita
  repetir a coleta da API (Seção 1).

### Bugs encontrados e corrigidos

- **`fetch_all` quebrava dentro do kernel Jupyter/IPython**
  (`RuntimeError: asyncio.run() cannot be called from a running event loop`).
  Só apareceu na primeira execução real do notebook, porque é o primeiro lugar
  em que `ingest.fetch_all` é chamado de dentro de um processo que já tem um
  event loop próprio rodando; nenhum teste roda dentro de um kernel. Causa raiz
  e correção documentadas na Seção 1 (o fix é em `src/ingest.py`, não no
  notebook; o notebook continuou só chamando `fetch_all` normalmente).
- **Bind mount silencioso e vazio com Git Bash e Docker Desktop no Windows.**
  Ao validar a execução com `docker run -v "$(pwd):/app" ...` fora do
  `docker-compose.yml`, só para depuração manual, o container recebia um `/app`
  inexistente. O MSYS/Git Bash reescreve automaticamente argumentos que
  parecem paths estilo Unix antes de repassá-los ao Docker Desktop, corrompendo
  o `-v "$(pwd):/app"`. O sintoma era enganoso: o comando não dava erro nenhum,
  o papermill "executava com sucesso" (exit code 0) e imprimia as respostas
  corretamente, só que gravando o notebook executado dentro do container
  efêmero, descartado no `--rm`. O arquivo no host nunca era tocado. Só foi
  percebido ao inspecionar o `notebook.ipynb` do host depois e ver
  `outputs: []` em toda célula. Correção: prefixar o comando com
  `MSYS_NO_PATHCONV=1`, que desliga a reescrita de path do MSYS, ao rodar
  `docker run -v` manualmente neste ambiente. Isso não afeta `docker compose
  up`: o volume do `docker-compose.yml` é declarado em YAML, não passa pelo
  parser de argumentos do shell, então não sofre esse problema. Só comandos
  `docker run -v ...` digitados direto no Git Bash precisam do workaround.

### Estratégia de execução e prova

Executado de ponta a ponta em Docker/Linux com `papermill notebook.ipynb
notebook.ipynb --log-output`, dataset completo (sem `MAX_ITEMS`), duas vezes:
uma coletando do zero, outra reaproveitando o cache bronze. Depois, uma
terceira vez através do `docker compose up` real, o comando que o avaliador de
fato roda. Resultado, com dados reais da PokeAPI nesta execução:

- Ingestão: 1351 pokémons coletados (43,9s do zero; 19,1s com cache bronze
  quente).
- Silver: `pokemon` com 1351 linhas, `pokemon_type` com 2116, `pokemon_stats`
  com 8106 e `pokemon_ability` com 2941.
- Qualidade: todos os 6 checks `PASS`. Nenhuma invariante violada; o dataset
  real da PokeAPI é consistente.
- Q1: 510 pokémons multi-tipo com força acima da média.
- Q2: 94 abilities exclusivas de multi-tipo.
- Q3, top 5: `eternatus-eternamax` (16.25), `kommo-o` (13.00), `dragapult`
  (13.00), `archaludon` (13.00) e `kommo-o-totem` (13.00). Os 4 últimos
  empatados, com a ordem decidida pelo tiebreaker `pokemon_id asc`.
- Os dois gráficos, top 5 e distribuição de força, foram inspecionados
  visualmente após a execução: barras e histograma corretos, linha da média em
  452,2.

`notebook.ipynb` foi commitado com esses outputs, texto e as duas imagens PNG,
embutidos no JSON. O avaliador vê as respostas abrindo o arquivo, sem precisar
rodar nada. `data/`, incluindo o cache bronze gerado, fica fora do git.

### Gotchas de ambiente

- **Kernel `python3` precisa estar registrado na imagem** para papermill ou
  nbconvert encontrarem o kernel referenciado nos metadados do `.ipynb`
  (`python -m ipykernel install --sys-prefix --name python3` no Dockerfile).
  Sem isso, a execução falha com "No such kernel: python3" antes mesmo de
  rodar a primeira célula.
- **`MSYS_NO_PATHCONV=1`** é necessário só para comandos `docker run -v ...`
  digitados manualmente no Git Bash (Windows); ver "Bugs encontrados e
  corrigidos" acima. `docker compose up`/`make up-p1` não precisam disso.
- Mesmas exigências de JDK 8/11/17 das seções anteriores, já que o notebook
  cria a mesma `SparkSession` que os testes e os módulos usam.

### ADRs relacionados

[ADR-0015](../../docs/adr/0015-spark-local-notebook-portavel.md): notebook
vanilla, sem APIs exclusivas de Databricks. O próprio ADR já cotava o
papermill como ferramenta de prova de reprodutibilidade; aqui ele também virou
o mecanismo de execução via `docker compose up`.
[ADR-0006](../../docs/adr/0006-ingestao-async-cache-bronze.md) e
[ADR-0007](../../docs/adr/0007-medallion-bronze-silver-gold.md): o notebook é
só a orquestração visível dessas decisões, não uma nova decisão de
arquitetura.

---

## 6. Persistência e relatório gerencial: `src/report.py`

### O que faz e onde

Persiste as respostas de cada execução do notebook e gera um relatório
gerencial em HTML, com a logo, as cores e a fonte do PicPay, incluindo dois
gráficos montados na hora a partir dos dados recebidos. É lógica de
apresentação, mas segue a mesma régua do resto do projeto: vive em `src/`,
testada isoladamente, e o notebook só chama (inclusive para os próprios
gráficos que aparecem na Seção 5 do notebook: são a mesma função, chamada
duas vezes, uma para o notebook e outra para o HTML).

| Função | Assinatura | Responsabilidade |
|---|---|---|
| `build_results` | `(*, generated_at, ingest_seconds, dataset_counts, q1_resultado, q2_abilities, q3_top5, forca_values) -> dict` | Monta o dict de resultados de uma execução |
| `save_results_json` | `(results, path="data/results/latest.json") -> Path` | Grava os resultados em JSON, sobrescrevendo a cada execução |
| `build_top5_chart` | `(top5: list[dict]) -> str` | Bar chart do top 5 de versatilidade, PNG em base64 |
| `build_forca_distribution_chart` | `(forca_values: list[float]) -> str` | Histograma da força com linha da média, PNG em base64 |
| `build_html_report` | `(results) -> str` | Monta o HTML do relatório gerencial, com logo e os dois gráficos embutidos |
| `save_html_report` | `(html, generated_at, reports_dir="data/reports") -> tuple[Path, Path]` | Salva o HTML em dois arquivos: `latest` e um com timestamp |

Constantes públicas: `PICPAY_GREEN`, `PICPAY_GREEN_LIGHT`, `PICPAY_DARK`,
`PICPAY_FONT` (paleta e tipografia) e `LOGO_PATH` (caminho do arquivo da
logo, resolvido a partir de `__file__`, não do diretório de trabalho).

### Como foi implementado

- **`build_results`** recebe só argumentos nomeados (todos `*` keyword-only)
  com os números e listas já calculados pelo notebook (contagens do silver,
  resultado de Q1, lista de abilities de Q2, lista de dicts do top 5 de Q3, e
  agora também a lista completa de forças por pokémon, usada pelo histograma).
  Não recalcula nada, só empacota.
- **A logo** foi fornecida pelo usuário (`.webp`, convertida uma única vez
  para `assets/picpay-logo.png` com fundo transparente) e vive em
  `part1-pokeapi-analytics/assets/`, versionada no git como um asset normal
  do projeto (não é cache de dado, não fica em `data/`). `PICPAY_GREEN` foi
  recalibrado para `#00C356`, a cor dominante amostrada diretamente dos
  pixels da logo (a estimativa anterior, `#21C25E`, era uma aproximação sem
  a logo em mãos).
- **`build_top5_chart`/`build_forca_distribution_chart`** usam
  `matplotlib.figure.Figure` diretamente (não `matplotlib.pyplot`) e
  renderizam via `fig.savefig(buf, format="png")` num `io.BytesIO`, retornando
  o PNG em base64. Nenhuma das duas toca no backend global do matplotlib nem
  em `plt.show()`/`%matplotlib inline`: por isso o notebook pôde parar de usar
  a magic do IPython (ver Seção 5) sem perder nada.
- **`build_html_report`** monta uma string HTML única via f-string, com CSS
  inline num `<style>` no `<head>`. Usa a fonte Poppins carregada via Google
  Fonts (link no `<head>`) com fallback para fontes de sistema, o verde de
  marca no cabeçalho e nos números em destaque, a logo embutida como
  `<img src="data:image/png;base64,...">`, e os dois gráficos (também
  base64) dentro das seções de Q1 e Q3.
- **`save_html_report`** escreve o mesmo conteúdo HTML em dois arquivos: um
  de nome fixo (`report-apipokemon-latest.html`) e um com o padrão de nome
  pedido, `report-apipokemon-{DDMMYY}-{HHMMSS}.html` (por exemplo
  `report-apipokemon-140926-000707.html` para 14/09/2026 às 00:07:07).

### Por quê (tradeoffs de implementação)

- **`Figure`/`Agg` em vez de `pyplot` para os gráficos do relatório.** O
  notebook já usava `matplotlib.pyplot` com `%matplotlib inline` pra exibir
  gráficos inline (Seção 5, versão anterior). Gerar os gráficos do relatório
  com esse mesmo `pyplot` global criaria uma dependência de qual backend
  está ativo no processo no momento da chamada (frágil: o resultado mudaria
  dependendo se `build_html_report` roda antes ou depois de alguma célula
  configurar o backend). Usar `Figure` diretamente, sem tocar em nenhum
  estado global do matplotlib, elimina essa dependência de ordem de
  execução; a função funciona igual dentro de um notebook Jupyter, num
  script batch ou dentro de um teste do pytest.
- **Notebook reaproveita `build_top5_chart`/`build_forca_distribution_chart`
  em vez de ter seu próprio código de plot.** Antes da logo/gráficos do
  relatório, o notebook desenhava os dois gráficos com `matplotlib.pyplot`
  direto na célula, em azul/vermelho, cores que não tinham relação com o
  relatório em HTML. Manter os dois códigos seria: (1) duplicação da mesma
  lógica de plot em dois lugares, indo contra a régua do projeto; e (2) uma
  inconsistência visual real, o notebook mostrando um gráfico e o relatório
  mostrando outro, de cores diferentes, para o mesmo dado. Trocar o notebook
  para chamar as mesmas funções de `report.py` resolve as duas coisas de
  uma vez: zero duplicação e os dois lugares mostram exatamente a mesma
  imagem.
- **Dois arquivos de saída para o mesmo HTML, não um só.** O pedido original
  tinha duas exigências que, à letra, se contradizem: "overwrite no que já
  existe" e, ao mesmo tempo, um nome de arquivo com data e hora (que por
  definição não se repete, então não haveria o que sobrescrever). A leitura
  adotada: o dado bruto (`data/results/latest.json`) é o que sempre
  sobrescreve, é o "insumo" citado no pedido; o relatório em si ganha as duas
  formas, uma fixa para abrir "o mais recente" sem precisar procurar o nome, e
  uma com timestamp para preservar o histórico de execuções (o que também é
  útil num relatório gerencial: comparar a execução de hoje com a de ontem).
- **JSON separado do HTML, em vez de o HTML ser a única persistência.** O
  `data/results/latest.json` existe porque o relatório em si (apresentação)
  não é um bom formato para reconsumo por outro processo (parsing de HTML
  para extrair números é frágil, e ainda mais frágil com gráficos embutidos
  em base64 no meio). O JSON é o dado; o HTML é a leitura humana dele.
- **Sem `try/except` na célula do notebook que chama `report.*`.** Se algo
  falhar na geração do relatório (por exemplo, permissão de escrita, ou o
  arquivo da logo não existir), é melhor a exceção propagar e o notebook
  terminar com erro visível do que mascarar uma falha de persistência com um
  `except: pass` silencioso.
- **Logo fornecida pelo usuário, não baixada de um kit de imprensa por
  conta própria.** Logos são ativos de marca registrada; usar o arquivo que
  o próprio usuário forneceu (dono do case, aplicando pra vaga no PicPay)
  evita depender de uma URL externa não verificada e mantém o relatório
  autocontido (a logo vira base64 dentro do HTML, não uma referência a um
  arquivo remoto).

### Edge cases tratados

- **Execuções em sequência não acumulam lixo no `latest.json`/
  `latest.html`.** Cada chamada de `save_results_json`/`save_html_report`
  sobrescreve o arquivo de nome fixo inteiro, sem merge com o conteúdo
  anterior.
- **Diretórios criados sob demanda.** `save_results_json` e
  `save_html_report` chamam `mkdir(parents=True, exist_ok=True)` antes de
  escrever, então funcionam tanto num clone novo (sem `data/results/` ou
  `data/reports/` ainda) quanto em reruns.
- **Nomes de arquivo com timestamp nunca colidem em uso normal.** A
  resolução de `%H%M%S` é de 1 segundo; duas execuções do pipeline completo
  (que leva dezenas de segundos) não geram o mesmo nome. Rodar a função duas
  vezes no mesmo segundo (só em teste, não no fluxo real) geraria uma
  colisão e uma sobrescreveria a outra; não tratado, porque não acontece no
  uso real do notebook.
- **`LOGO_PATH` resolvido a partir de `__file__`, não do diretório de
  trabalho.** Se resolvesse a partir de um caminho relativo tipo
  `"assets/picpay-logo.png"`, quebraria caso alguém chamasse `report.*` de
  um `cwd` diferente da raiz de `part1-pokeapi-analytics/`. Resolver a
  partir de `Path(__file__).resolve().parent.parent` torna a localização do
  asset independente de onde o processo foi iniciado.
- **Gráficos com lista vazia não quebram.** `build_forca_distribution_chart`
  só desenha a linha da média e a legenda se `forca_values` não estiver
  vazio; com dataset vazio (não acontece no uso real, mas é o tipo de
  entrada que um teste pode passar), a função ainda devolve um PNG válido,
  só que sem histograma.

### Bugs encontrados e corrigidos

Nenhum bug de implementação neste módulo. Foi construído depois de já ter os
outros 4 módulos validados; a única coisa nova (escrita de arquivo simples e
geração de imagem via matplotlib, sem Spark) não tem as armadilhas de
ambiente dos módulos anteriores.

### Estratégia de testes

`tests/test_report.py` não usa Spark (o módulo não depende de `SparkSession`),
só monta dicts, gera imagem e escreve arquivo em `tmp_path`:

- **`build_results`:** confirma o formato do dict de saída, incluindo que
  `q2_abilities_exclusive_multitype.count` é derivado de `len(q2_abilities)`,
  não de um valor passado à parte (impossível divergir).
- **`save_results_json`:** grava e lê de volta; e um teste dedicado confirma
  que uma segunda chamada com dados diferentes sobrescreve o arquivo por
  completo (não sobra número da execução anterior).
- **`build_top5_chart`/`build_forca_distribution_chart`:** confirmam que o
  retorno, decodificado de base64, começa com a assinatura binária real de
  um PNG (`\x89PNG\r\n\x1a\n`); e, crucial pro requisito de "nada estático ou
  chumbado", um teste dedicado para cada função gera o gráfico duas vezes
  com dados diferentes e afirma que os dois PNGs resultantes são diferentes
  (`chart_a != chart_b`), o que trava que os gráficos realmente refletem o
  dado de entrada, não uma imagem fixa reaproveitada.
- **`build_html_report`:** confirma que os números-chave (resultado de Q1,
  nomes do top 5 de Q3) aparecem no HTML gerado, que a cor de marca
  (`PICPAY_GREEN`) e a fonte (`Poppins`) estão presentes, que o documento
  começa com `<!doctype html>` e tem `<html>`/`</html>` balanceados, e que
  há exatamente 3 imagens embutidas em base64 (1 logo + 2 gráficos), nenhuma
  carregada de uma URL externa.
- **`test_logo_asset_exists_and_is_a_real_png`:** confirma que o arquivo em
  `LOGO_PATH` existe e começa com a assinatura binária de PNG, pegando o caso
  de alguém commitar um arquivo corrompido ou renomear o asset sem atualizar
  o caminho.
- **`save_html_report`:** confirma os dois arquivos gerados (nome fixo e
  nome com timestamp), que o nome com timestamp bate no formato
  `report-apipokemon-DDMMYY-HHMMSS.html` via regex, e, com duas chamadas
  seguidas com timestamps diferentes, que o arquivo de nome fixo é
  sobrescrito com o conteúdo da segunda execução enquanto o arquivo com
  timestamp da primeira execução continua intacto no disco.

### Gotchas de ambiente

Nenhum. Não depende de Spark, Java ou rede; roda igual em qualquer ambiente
com Python 3.11 e as dependências do `pyproject.toml` instaladas (a única
nova é `matplotlib`, já listada desde a Seção 5).

### ADRs relacionados

Nenhum ADR novo. É uma decisão de implementação (como apresentar e persistir
resultados), não uma decisão de arquitetura de plataforma; por isso vive só
aqui, não em `docs/adr/`.
