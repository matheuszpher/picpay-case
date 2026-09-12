# Registro de Implementação: Parte 2 (NER Serving)

> **Regra permanente:** a partir deste documento, nenhuma etapa nova da Parte 2 é
> considerada concluída sem a sua seção correspondente aqui, no mesmo nível de detalhe
> das seções abaixo (o quê/onde, como, por quê, edge cases, bugs corrigidos, estratégia
> de testes, gotchas de ambiente). Documentar é parte da definição de "pronto", não um
> acréscimo opcional depois.

## O que este documento é (e o que não é)

Os [ADRs](../../docs/adr/) registram decisões de arquitetura: a escolha entre opções
de alto nível e o tradeoff que a justifica (por exemplo, por que existe uma abstração
de provider, ADR-0002). Este documento registra o como da implementação: estruturas de
código, bibliotecas, assinaturas de função, edge cases tratados e bugs encontrados no
caminho. É o nível de detalhe que alguém precisa para entender o código sem reler todo
o histórico de commits.

Convenção: cada seção abaixo corresponde a um módulo de `src/` (ou a um arquivo de
suporte de teste com peso arquitetural, como `tests/fakes.py`) e segue a mesma
estrutura fixa (o que/onde, como, por quê, edge cases, bugs, testes, gotchas de
ambiente, ADRs relacionados).

---

## 1. Schemas e configuração: `src/nercore/schemas.py`, `src/nercore/config.py`

### O que faz e onde

`schemas.py` define os modelos de domínio Pydantic compartilhados por REST e MCP:
`Entity`, `PredictResult`, `ModelInfo`, `PredictionRecord`, `LoadRequest`,
`PredictRequest`. `config.py` centraliza configuração via variáveis de ambiente com
`pydantic-settings`: `DEFAULT_MODEL`, `CACHE_BACKEND`, `REDIS_URL`,
`HISTORY_DB_PATH`, `LOG_LEVEL`.

### Como foi implementado

- Os seis modelos de `schemas.py` seguem exatamente os campos do mini-spec, sem campos
  extras. `PredictRequest.model` é opcional (`str | None = None`), refletindo a regra
  de negócio de que `/predict/` sem `model` usa o modelo ativo.
- `config.py` expõe uma instância pronta `settings = Settings()` a nível de módulo,
  para ser importada diretamente por quem precisar (`from src.nercore.config import
  settings`), em vez de cada módulo instanciar `Settings()` de novo.

### Por quê (tradeoffs de implementação)

- **`config.py` é um arquivo novo**, não fazia parte da árvore original do esqueleto
  da Fase 0. `history.py` (fase 2.2, `HISTORY_DB_PATH`) e `cache.py` (fase 2.2,
  `CACHE_BACKEND`/`REDIS_URL`) dependem de um lugar central pra ler essas variáveis, e
  criá-lo só quando o primeiro consumidor precisasse teria adiado uma decisão que é
  mais barata de tomar cedo (nomes das variáveis, defaults).
- **`pydantic-settings` em vez de `os.environ.get` espalhado.** Os defaults ficam
  documentados em um único lugar, tipados, e o override por variável de ambiente é
  testável sem montar cenários de integração.

### Edge cases

- `PredictRequest` com `model=None` é o caminho normal (usa o ativo), não um erro de
  validação.
- `LoadRequest` sem `model` é erro de validação (`model` é obrigatório lá), o que
  `test_load_request_requires_model` confirma.

### Bugs encontrados e corrigidos

Nenhum nesta etapa.

### Estratégia de testes

`tests/test_schemas.py`: construção de cada modelo com dados válidos, mais o caso de
erro de `LoadRequest` sem `model`. `tests/test_config.py`: valores default de
`Settings()` e override via `monkeypatch.setenv`, usando `Settings(_env_file=None)`
para não depender de um `.env` acidental no ambiente de teste.

### Gotchas de ambiente

Nenhum.

### ADRs relacionados

Nenhum ADR específico; `schemas.py` é o modelo de dados que sustenta ADR-0002 e
ADR-0003 (provider e camadas), sem ser, ele mesmo, uma decisão de arquitetura.

---

## 2. Provider de NER: `src/nercore/providers/base.py`, `src/nercore/providers/spacy_provider.py`

### O que faz e onde

`base.py` define a interface `NERProvider` (ADR-0002): `load(model_name)`,
`predict(text)`, `is_loaded(model_name)`. `spacy_provider.py` implementa essa
interface usando spaCy (`SpacyNERProvider`) e define `ModelLoadError`, a exceção de
domínio levantada quando um modelo não instalado falha ao ser baixado.

### Como foi implementado

- **Uma instância de provider representa no máximo um modelo carregado.**
  `SpacyNERProvider` guarda `self._nlp` (o pipeline spaCy) e `self._model_name`. Essa
  escolha resolve uma ambiguidade do contrato do mini-spec: `predict(text)` não recebe
  parâmetro de modelo. Quem decide QUAL modelo usar não é o provider, é a camada
  acima: a fase 2.2 (`ModelRegistry`) vai manter uma instância de `NERProvider` por
  modelo registrado (um dicionário `{model_name: provider}`) e chamar `predict()` na
  instância certa. Isso é consistente com a decisão de design nº 5 do mini-spec
  ("modelo fica carregado em memória; nunca recarrega por request"): quem guarda os
  objetos `nlp` carregados, na prática, é essa coleção de providers dentro do
  registry.
- **`load(model_name)`** verifica `spacy.util.is_package(model_name)`; se o modelo não
  estiver instalado, chama `spacy.cli.download(model_name)`. Se o download falhar
  (nome inválido, sem rede), a chamada pode levantar `SystemExit` (comportamento
  interno do spaCy) ou uma exceção comum; ambos os casos são convertidos em
  `ModelLoadError`, para quem chama `load()` não precisar conhecer detalhes internos
  do spaCy. Depois do download (ou se já estava instalado), `spacy.load(model_name)`
  carrega o pipeline em memória.
- **`predict(text)`** roda `self._nlp(text)` e mapeia cada `ent` do `doc.ents` para um
  `Entity(label=ent.label_, text=ent.text, start_char=ent.start_char,
  end_char=ent.end_char)`, sem nenhuma normalização do texto da entidade (o texto
  retornado é exatamente o que o spaCy extraiu).
- **`is_loaded(model_name)`** compara `self._model_name == model_name`, sem tentar
  carregar nada.

### Por quê (tradeoffs de implementação)

- **Um provider por modelo, em vez de um provider que guarda vários `nlp` num
  dicionário interno.** A interface `NERProvider` do mini-spec não tem um parâmetro de
  modelo em `predict()`, o que sugere fortemente essa forma: o provider é "burro" (um
  wrapper fino de UM pipeline), e a responsabilidade de gerência de múltiplos modelos
  é do registry, uma camada acima, que já existe pra isso.
- **Erro de download convertido em `ModelLoadError`, não propagado como
  `SystemExit`.** `SystemExit` encerraria o processo se não fosse pego em algum lugar;
  numa API rodando com uvicorn, deixar isso vazar significaria derrubar o worker
  inteiro por causa de um nome de modelo errado num request. Convertê-lo cedo, dentro
  do provider, evita que cada chamador (`registry`, depois `service`, depois os
  handlers da API) precise lembrar de tratar `SystemExit` especificamente.
- **Sem normalização do texto da entidade**, como o mini-spec pede explicitamente
  (edge case: "não normalizar magicamente"). Retornar exatamente `ent.text` mantém o
  provider previsível e testável por igualdade direta de string.

### Edge cases

- `predict()` chamado antes de qualquer `load()` levanta `RuntimeError` (estado
  inválido de uso, não um erro de negócio a ser tratado pela API).
- Modelo já instalado: `load()` pula o download e vai direto para `spacy.load()`.
- Modelo cujo download falha: `ModelLoadError`, mensagem inclui o nome do modelo.
- **Texto em português com o modelo default (`en_core_web_sm`) não extrai
  entidade nenhuma.** Não é bug de mapeamento: `en_core_web_sm` é treinado só em
  inglês, então `doc.ents` volta vazio para qualquer texto em outro idioma.
  Confirmado manualmente carregando `pt_core_news_sm` via `provider.load()` (o
  mesmo caminho de lazy-load, sem nenhuma mudança de código): o texto "Envie
  R$100 para Matheus amanhã" rendeu `PER "Envie R$"` (limite de entidade errado)
  e `PER "Matheus"` (correto), sem reconhecer nem o valor (`MONEY`) nem a data
  (`DATE`), qualidade bem abaixo do que `en_core_web_sm` dá em inglês para a
  mesma frase. Prova que a abstração de provider já permite trocar de idioma sem
  tocar código, mas que "suporte a português" hoje é só mecanicamente possível,
  não pronto para uso: fica documentado como evolução (ADR-0011), não como
  capacidade entregue.

### Bugs encontrados e corrigidos

- **`click` ausente na resolução de dependências, mesmo sendo exigido por
  `spacy.cli` em tempo de import.** `spacy==3.7.5` importa `from click import
  NoSuchOption` dentro de `spacy/cli/_util.py`, mas a versão mais recente de `typer`
  resolvida pelo pip (0.27.2) não declara mais `click` como dependência direta
  (`pip show typer` não lista `click` em `Requires`). Resultado:
  `ModuleNotFoundError: No module named 'click'` só ao importar `spacy` (não é
  específico do nosso código). Corrigido adicionando `click>=8.1,<9` como dependência
  explícita do projeto em `pyproject.toml`, em vez de depender de uma cadeia
  transitiva que mudou de comportamento entre versões de `typer`. Reproduzido e
  corrigido tanto no `.venv` do Windows quanto no container Docker (`python:3.11-slim`),
  então não é uma particularidade de plataforma.

### Estratégia de testes

`tests/test_spacy_provider.py`, usando a fixture `spacy_provider` (`conftest.py`,
escopo de sessão, carrega `en_core_web_sm` uma única vez por execução da suíte):

- `NERProvider` não pode ser instanciada diretamente (é uma ABC).
- `load()`/`is_loaded()` refletem o modelo carregado (e não outro).
- `predict()` mapeia entidades reais do spaCy para `Entity`, e os offsets
  (`start_char`/`end_char`) batem com o texto original.
- `predict()` antes de `load()` levanta `RuntimeError`.
- O caminho de download é testado com `monkeypatch` em `is_package` e
  `spacy.cli.download` (sem rede real): tanto o caso de sucesso quanto o de falha
  (`SystemExit` capturado e convertido em `ModelLoadError`).

`en_core_web_sm` é dependência normal do `pyproject.toml` (pinada por URL de wheel,
ver decisão de design nº 2 do plano), não uma dependência só de teste: carregar o
pacote local dentro de um teste é leitura de disco, não uma chamada de rede, então não
quebra a convenção da Parte 1 de "testes nunca tocam rede" (`tests/test_ingest.py`).
Só `SpacyNERProvider.load()` baixando um modelo NÃO instalado seria uma chamada de
rede real, e esse caminho é sempre mockado nos testes.

### Gotchas de ambiente

`click` precisa estar pinado explicitamente (ver bug acima); sem isso, `import spacy`
falha de forma não óbvia (o traceback aponta para dentro do próprio pacote spacy, não
para o código deste projeto).

### ADRs relacionados

ADR-0002 (abstração de provider), ADR-0011 (modelo versionado por nome).

---

## 3. Provider fake para testes: `tests/fakes.py`

### O que faz e onde

`FakeProvider` implementa `NERProvider` sem depender de spaCy: `load()` registra a
chamada e marca o modelo como carregado (ou levanta `ModelLoadError`, se configurado
para simular falha), `predict()` devolve uma lista de `Entity` pré-configurada e
registra o texto recebido, `is_loaded()` reflete o último modelo carregado.

### Como foi implementado

- Construtor aceita `entities: list[Entity] | None` (o que `predict()` deve devolver)
  e `raise_on_load: bool` (simula falha de download).
- `load_calls` e `predict_calls` são listas públicas que acumulam os argumentos
  recebidos em cada chamada, para os testes de fases futuras (`registry`, `service`,
  `api`) poderem afirmar quantas vezes e com quais argumentos o provider foi
  invocado, sem precisar de um mock genérico.

### Por quê (tradeoffs de implementação)

- **Mora em `tests/fakes.py`, não em `src/nercore`.** O ADR-0002 já antecipa
  literalmente essa necessidade ("dá pra usar um provider fake nos testes, sem
  carregar modelo real"), mas um fake não tem valor de produção: colocá-lo dentro de
  `nercore` criaria o risco de alguém importar `FakeProvider` por engano em código de
  aplicação real, ou de um leitor externo (recrutador avaliando o código) confundir um
  helper de teste com uma implementação de fornecedor legítima.
- **Não mora em `conftest.py`.** Manter a classe importável diretamente (em vez de só
  disponível via fixture) permite instanciar variantes por teste
  (`FakeProvider(entities=[...])`, `FakeProvider(raise_on_load=True)`) sem multiplicar
  fixtures. `conftest.py` fica reservado para fixtures que de fato compartilham estado
  entre testes (como `spacy_provider`, que é cara de recriar).
- **Precisa nascer já na fase 2.1, antes da fase de `service.py` (2.3).** Os testes de
  `registry.py` (fase 2.2) também vão precisar de um provider fake, porque
  `ModelRegistry.register()` chama `provider.load()` internamente. Se o fake só
  existisse a partir da fase de serviço, os testes de registry ficariam sem
  alternativa a carregar spaCy de verdade.

### Edge cases

- `is_loaded()` chamado antes de qualquer `load()` retorna `False` (não levanta
  exceção), simetria com o uso esperado em `service.py` (checagem antes de decidir se
  precisa carregar).

### Bugs encontrados e corrigidos

Nenhum.

### Estratégia de testes

`tests/test_fakes.py` verifica que `FakeProvider` é de fato um `NERProvider`
(`isinstance`), que `load`/`is_loaded`/`predict` se comportam como esperado, e que
`raise_on_load=True` propaga `ModelLoadError` sem marcar o modelo como carregado.

### Gotchas de ambiente

Nenhum.

### ADRs relacionados

ADR-0002.

---

## Validação da fase 2.1

19/19 testes passando tanto no `.venv` local (Windows) quanto no Docker/Linux
(`python:3.11-slim`, ambiente oficial de validação, mesma convenção da Parte 1). Lint
(`ruff check .`) e formatação (`black --check .`) passando após adicionar o
per-file-ignore de `DTZ001` em `tests/test_schemas.py` (mesmo padrão já usado na Parte
1 para timestamps fixos de teste).

### Correção feita no início da fase 2.2

`ModelLoadError` foi movida de `providers/spacy_provider.py` para `providers/base.py`.
Na fase 2.1 ela nasceu junto da implementação concreta, mas é um erro de contrato da
interface `NERProvider` (qualquer implementação pode levantá-lo), e `tests/fakes.py`
já a importava de `spacy_provider.py` só porque não havia outro lugar. Relocada antes
de `registry.py` passar a depender dela, pra não formar uma dependência de um módulo
de provider concreto para outro.

---

## 4. Registro de modelos: `src/nercore/registry.py`

### O que faz e onde

`ModelRegistry` mantém, para cada modelo registrado neste processo, uma instância de
`NERProvider` já carregada, e sabe qual delas está ativa. Métodos: `register`,
`active` (propriedade), `set_active`, `list`, `is_registered`, `remove`,
`get_provider`.

### Como foi implementado

- **Uma instância de provider por modelo registrado**, guardada num dicionário
  `{model_name: NERProvider}`. Isso é a peça que fecha a decisão de design tomada na
  fase 2.1 (seção 2 acima): o registry é quem sabe qual provider usar para qual
  modelo, e `get_provider(model_name)` é o método que a fase 2.3 (`service.py`) vai
  chamar antes de `predict()`.
- **`provider_factory` é injetado no construtor** (`Callable[[], NERProvider]`), não
  fixado em `SpacyNERProvider`. Produção instancia `ModelRegistry(provider_factory=
  SpacyNERProvider)`; os testes usam `FakeProvider`.
- **`register()` é idempotente**: só chama `provider_factory()` + `provider.load()`
  se o modelo ainda não estiver no dicionário. Chamar `register()` de novo para um
  modelo já carregado apenas troca `active`, sem recarregar.
- **Falha em `register()` não deixa estado parcial.** Se `provider.load()` levanta
  (por exemplo `ModelLoadError`), a exceção propaga sem o modelo entrar no dicionário
  e sem mudar `active`.
- **`remove()` do modelo ativo zera `active` para `None`**, nunca troca implicitamente
  para outro modelo carregado (decisão de design nº 8 do plano de execução): evita que
  um cliente que não pediu nenhum modelo específico receba respostas de um modelo
  diferente do que esperava.
- **`ModelNotFoundError`** é levantada por `set_active`, `remove` e `get_provider`
  quando o nome não está registrado.

### Por quê (tradeoffs de implementação)

- **`ModelNotFoundError` definida aqui, não em `service.py`.** É o registry quem sabe
  quais modelos existem; a hierarquia de exceções da fase 2.3 (`NoActiveModelError`,
  etc, ver decisão de design nº 6 do plano) vai reusar esta classe para "modelo pedido
  não existe", em vez de duplicá-la.
- **`list()` reconstrói `ModelInfo` a cada chamada**, em vez de manter uma lista
  paralela sincronizada com o dicionário de providers. Menos estado para manter
  consistente, e o custo é irrelevante (poucos modelos, tipicamente um dígito).

### Edge cases

- Registrar o mesmo modelo duas vezes: idempotente, não recarrega.
- Remover o modelo ativo: `active` vira `None`.
- Remover um modelo inativo: `active` não muda.
- Operações (`set_active`, `remove`, `get_provider`) em modelo não registrado:
  `ModelNotFoundError`.

### Bugs encontrados e corrigidos

Nenhum nesta etapa (além da correção de `ModelLoadError` já descrita acima, que é
anterior a este módulo).

### Estratégia de testes

`tests/test_registry.py`, usando `FakeProvider` (nunca spaCy real, `ModelRegistry` não
sabe nem precisa saber que existe spaCy): idempotência de `register`, propagação de
falha de carga sem registrar nada, troca de ativo ao registrar um segundo modelo,
`list()` refletindo o ativo correto, e os três `ModelNotFoundError` (`set_active`,
`remove`, `get_provider`).

### Gotchas de ambiente

Nenhum.

### ADRs relacionados

ADR-0011 (modelo versionado por nome), ADR-0002 (provider).

---

## 5. Histórico de predições: `src/nercore/history.py`

### O que faz e onde

`PredictionHistory` persiste cada predição em SQLite (ADR-0005): `add(input, output,
model, timestamp) -> int` (devolve o id gerado) e `list(limit=100, offset=0) ->
list[PredictionRecord]`.

### Como foi implementado

- **Uma conexão SQLite por chamada** (`sqlite3.connect` dentro de cada método, nunca
  guardada como atributo de instância), em vez de uma conexão de longa duração. Evita
  compartilhar uma única conexão entre threads do servidor ASGI (fase 2.4), o que o
  `sqlite3` do stdlib não suporta com segurança por padrão.
- **Tabela `predictions`** com `id INTEGER PRIMARY KEY AUTOINCREMENT`, `input TEXT`,
  `output TEXT` (JSON serializado da lista de `Entity`), `model TEXT`, `timestamp
  TEXT` (ISO 8601 via `datetime.isoformat()`). Criada com `CREATE TABLE IF NOT
  EXISTS` no `__init__`, então instanciar `PredictionHistory` é seguro tanto na
  primeira execução quanto em restarts.
- **Índice em `(timestamp, model)`**, criado junto da tabela. `/list/` é read-heavy
  (ADR-0005) e ordena por timestamp; incluir `model` no índice também deixa
  preparado um futuro filtro por modelo sem precisar de outro índice.
- **`list()` ordena por `timestamp DESC`**: o histórico é consumido como um log do
  ponto de vista do cliente (decisão de design nº 4 do mini-spec), e o caso de uso
  natural de "ver o que aconteceu" é do mais recente para o mais antigo.
- **`output` é serializado com `entity.model_dump()` + `json.dumps`**, e
  desserializado de volta com `Entity(**entity)` na leitura. O schema Pydantic vale
  tanto para o corpo HTTP quanto para a forma persistida, sem um segundo formato de
  serialização.

### Por quê (tradeoffs de implementação)

- **SQLite, não Postgres, não uma lista em memória.** Já é a decisão do ADR-0005;
  aqui só materializa: zero-config, sobrevive a restart, e a interface exposta
  (`add`/`list`) é pequena o bastante para trocar por Postgres depois sem tocar
  `service.py`.
- **Conexão por chamada em vez de uma conexão persistente com lock manual.** Para o
  volume esperado (uma escrita por predição, escopo local/demo), abrir/fechar por
  chamada é mais simples que gerenciar um lock ou um pool, e o SQLite já serializa
  escritas no nível do arquivo.

### Edge cases

- Diretório do banco (`HISTORY_DB_PATH`) ainda não existe: `__init__` cria os
  diretórios pais (`Path.mkdir(parents=True, exist_ok=True)`) antes de conectar.
- `list()` numa base vazia devolve lista vazia, não erro.
- `output=[]` (predição sem nenhuma entidade encontrada) é serializado e
  desserializado normalmente como lista vazia.

### Bugs encontrados e corrigidos

Nenhum.

### Estratégia de testes

`tests/test_history.py`, sempre com `tmp_path` (arquivo SQLite real em disco,
descartável): ids incrementais, ordenação por mais recente primeiro, paginação
(`limit`/`offset`), e persistência ao reabrir o mesmo arquivo com uma nova instância
de `PredictionHistory` (prova que os dados sobrevivem a um restart do processo, não só
à instância em memória).

### Gotchas de ambiente

Nenhum (SQLite via stdlib, sem dependência nativa adicional, diferente do gotcha de
Parquet/Hadoop da Parte 1).

### ADRs relacionados

ADR-0005.

---

## 6. Cache de predição: `src/nercore/cache.py`

### O que faz e onde

`PredictionCache` (ABC) define `get(key)`/`set(key, value)`. `InMemoryLRUCache` é a
implementação default. `cache_key(model, text)` calcula a chave
(`sha256(f"{model}::{text}")`).

### Como foi implementado

- **`cache_key` é uma função do módulo, não um método de instância**, porque o
  cálculo da chave não depende de estado do cache (é puro: mesmo `model`+`text`,
  mesma chave sempre) e vai ser chamado por `service.py` (fase 2.3) antes de decidir
  hit ou miss.
- **O valor guardado é `list[Entity]`, não `PredictResult`.** `PredictResult` tem um
  campo `cached: bool` que descreve a chamada atual (foi hit ou miss), não uma
  propriedade do dado armazenado; guardar o `PredictResult` inteiro faria o cache
  "lembrar" um valor de `cached` que só faz sentido no momento em que foi escrito.
  Quem decide o valor de `cached` na resposta final é o `NERService`.
- **`InMemoryLRUCache`** usa `collections.OrderedDict`: `get()` mexe a chave lida para
  o fim (mais recentemente usada) via `move_to_end`; `set()` faz o mesmo antes de
  sobrescrever, e evita o item do início (`popitem(last=False)`, o menos
  recentemente usado) quando o tamanho passa de `max_size`.

### Por quê (tradeoffs de implementação)

- **`OrderedDict` em vez de `functools.lru_cache` ou uma lib de terceiros.** O cache
  aqui precisa de uma interface própria (`PredictionCache`) para ser substituível por
  Redis depois (ADR-0004); `lru_cache` decora funções e não se presta a essa troca.
  `OrderedDict` dá O(1) amortizado em `get`/`set`/evicção com só stdlib, mesma
  filosofia de "sem dependência nova quando o stdlib resolve" da Parte 1 (retry
  manual em vez de `tenacity`).
- **Chave inclui o modelo.** Já é a decisão do ADR-0004 (invalidação trivial: cada
  versão de modelo é imutável); `cache_key` só materializa isso.

### Edge cases

- `max_size <= 0` levanta `ValueError` na construção (nunca cria um cache que não
  guarda nada).
- Mesma string de texto com modelos diferentes: chaves diferentes, sempre miss entre
  si.
- Reescrever uma chave já existente (`set` duas vezes com a mesma key) atualiza o
  valor e marca como recém-usada, sem contar como uma segunda entrada para fins de
  evicção.

### Bugs encontrados e corrigidos

Nenhum.

### Estratégia de testes

`tests/test_cache.py`: determinismo e sensibilidade ao modelo de `cache_key`; hit
após `set`; miss para chave nunca vista; miss ao trocar o modelo com o mesmo texto;
evicção respeitando a ordem real de uso (não a ordem de inserção, o teste
deliberadamente lê a entrada mais antiga antes de inserir uma terceira, pra provar que
`get` conta como uso); `max_size` inválido.

### Gotchas de ambiente

Nenhum.

### ADRs relacionados

ADR-0004.

---

## Validação da fase 2.2

41/41 testes passando (19 da fase 2.1 + 22 novos) tanto no `.venv` local (Windows)
quanto no Docker/Linux (`python:3.11-slim`, ambiente oficial). Lint (`ruff check .`,
incluindo um auto-fix de `UP017` trocando `timezone.utc` por `datetime.UTC`) e
formatação (`black --check .`) passando sem exceções novas.

---

## 7. Orquestração: `src/nercore/service.py`

### O que faz e onde

`NERService` é o único ponto de entrada que REST (fase 2.4) e MCP (fase 2.5) vão
chamar (ADR-0003): `load(model)`, `predict(text, model=None) -> PredictResult`,
`list_predictions(limit, offset)`, `list_models()`, `delete_model(model)`. Recebe
`registry`, `history` e `cache` já construídos no construtor (injeção de dependência
simples, sem framework de DI).

### Como foi implementado

- **`predict()` resolve o modelo em três passos**: (1) usa `model` se veio explícito,
  senão usa `registry.active`, e levanta `NoActiveModelError` se nenhum dos dois
  existir; (2) se o modelo resolvido ainda não está registrado, chama
  `registry.register()` (mesmo caminho de `load()`, inclusive baixando se preciso);
  (3) calcula `cache_key(model, text)`, tenta o cache, e só chama
  `registry.get_provider(model).predict(text)` em caso de miss.
- **Histórico é gravado sempre**, depois da resolução de hit/miss, com o resultado
  final (seja ele vindo do cache ou do provider). Isso implementa literalmente a
  decisão de design nº 4 do mini-spec: o cache economiza inferência, não o registro.
- **`load()` é só `registry.register(model)`.** Não existe lógica extra aqui; o
  método existe para dar ao service (e por consequência à API) um verbo explícito de
  "pré-aquecer", separado de `predict()`.

### Por quê (tradeoffs de implementação)

- **Modelo explícito já carregado, mas não ativo, NÃO se torna o novo ativo.** O
  mini-spec diz "ativo = último carregado" (decisão de design nº 3), e "carregado" é
  um evento que só acontece dentro de `registry.register()`. Se o modelo já está no
  dicionário do registry, `predict()` não chama `register()` de novo, logo não há
  novo evento de carregamento, logo o ativo não muda. A alternativa (qualquer
  `predict()` com `model` explícito também vira o ativo) faria uma leitura pontual de
  um modelo secundário "sequestrar" o default de todo mundo que não especifica
  `model`, o que é um efeito colateral surpreendente para uma chamada que parece só
  de leitura. Coberto por
  `test_predict_with_already_loaded_non_active_model_does_not_switch_active`.
- **`NoActiveModelError` vive em `service.py`, não em `registry.py`.** "Não há modelo
  ativo" só é um erro no contexto de uma predição sem modelo explícito; o registry em
  si permite perfeitamente existir sem nenhum modelo ativo (por exemplo, logo depois
  de `remove()` do único modelo carregado), sem que isso seja um erro. É o `service`,
  ao tentar resolver um modelo para uma predição, que transforma esse estado em
  exceção.
- **Cache guarda `list[Entity]`, e é o `service` quem monta o `PredictResult` final
  com o `cached` correto** (decisão já tomada em `cache.py`, fase 2.2): aqui é onde
  essa decisão se paga, já que só o `service` sabe, no momento da chamada, se aquele
  resultado específico veio do cache ou não.

### Edge cases

- `predict()` sem `model` e sem nenhum modelo jamais carregado: `NoActiveModelError`.
- `predict()` com `model` explícito nunca antes visto: carrega (ou baixa, se
  necessário) e passa a ser o ativo.
- `predict()` repetido com o mesmo texto e mesmo modelo: primeira chamada é miss,
  segunda é hit, e o provider só é chamado uma vez (`predict_calls` do
  `FakeProvider` prova isso).
- Mesmo texto, modelos diferentes: entradas de cache independentes (miss para os
  dois na primeira vez de cada um).
- `delete_model` de um modelo não registrado: propaga `ModelNotFoundError` do
  registry, sem tradução.

### Bugs encontrados e corrigidos

Nenhum.

### Estratégia de testes

`tests/test_service.py`, com `FakeProvider` mas `ModelRegistry`, `PredictionHistory`
(SQLite real em `tmp_path`) e `InMemoryLRUCache` reais, para também testar a fiação
entre as camadas, não só o `service` isolado com tudo mockado: resolução de modelo
(explícito, ativo, nenhum dos dois), lazy-load e o efeito sobre o ativo, cache
hit/miss com contagem de chamadas reais ao provider (`predict_calls`), separação de
entradas de cache por modelo, histórico gravado em toda predição (inclusive hit), e
delegação simples de `list_predictions`/`list_models`/`delete_model`.

### Gotchas de ambiente

Nenhum.

### ADRs relacionados

ADR-0003 (core como lib, transportes finos), ADR-0002, ADR-0004, ADR-0005, ADR-0011.

---

## Validação da fase 2.3

53/53 testes passando (41 das fases 2.1/2.2 + 12 novos) tanto no `.venv` local
(Windows) quanto no Docker/Linux (`python:3.11-slim`, ambiente oficial). Lint (`ruff
check .`) e formatação (`black --check .`) passando sem exceções novas.

### Correção feita no início da fase 2.4

`EmptyTextError` foi adicionada a `service.py` (não à API): "texto vazio ou só
espaços é inválido" é uma regra de negócio, e o `NERService` é compartilhado por REST
e MCP (ADR-0003). Se essa checagem vivesse só no handler da rota REST, o transporte
MCP (fase 2.5) aceitaria texto vazio sem essa proteção, duplicando (ou pior,
esquecendo de duplicar) a validação. `predict()` agora rejeita texto vazio antes de
resolver o modelo. Também foi adicionada a propriedade `NERService.active_model`
(delega para `registry.active`): a API precisa expor "qual é o modelo ativo" em
`/models/` e `/health/`, e isso é estado do `registry`, não algo que a API deveria
acessar diretamente contornando o `service`.

---

## 8. API REST: `src/api/main.py`

### O que faz e onde

`FastAPI` app com as 6 rotas da fase 2.4: `POST /load/`, `POST /predict/`, `GET
/list/`, `GET /models/`, `GET /health/`, `DELETE /models/{version}` (`/metrics` fica
para a fase 2.6). Cada rota só chama `NERService` e traduz o resultado (ou a exceção)
para HTTP; nenhuma regra de negócio vive aqui (ADR-0003, ADR-0008).

### Como foi implementado

- **`NERService` é construído uma vez, no `lifespan` do FastAPI**, e guardado em
  `app.state.service`. `get_service(request) -> NERService` é a dependência
  (`Depends`) que toda rota usa para chegar nele; é essa indireção que permite
  substituir o service inteiro nos testes via `app.dependency_overrides[get_service]
  = lambda: service_de_teste`, sem tocar as rotas.
- **Warm-up do `DEFAULT_MODEL` acontece no `lifespan`**, chamando
  `service.load(settings.DEFAULT_MODEL)` antes do `yield`. Se isso levantar
  `ModelLoadError` (sem rede, nome inválido), o erro é só logado
  (`logger.exception`) e a aplicação sobe do mesmo jeito, com `active_model=None` até
  alguém chamar `/load/` ou `/predict/` com um `model` explícito. Verificado
  manualmente rodando `uvicorn` de verdade (não só via `TestClient`, que nunca
  exercita o `lifespan` nos testes, ver seção de testes abaixo): `/health/` reportou
  `active_model: "en_core_web_sm"` e `/predict/` sem `model` já funcionou na primeira
  chamada.
- **Handlers de exceção dedicados** traduzem cada exceção de domínio para o formato
  padronizado `{"error": <slug>, "detail": <mensagem>}`: `RequestValidationError`
  (Pydantic, 422, `error="validation_error"`), `EmptyTextError` (422,
  `"empty_text"`), `NoActiveModelError` (409, `"no_active_model"`), `ModelLoadError`
  (400, `"model_load_error"`), `ModelNotFoundError` (404, `"model_not_found"`). Sem
  isso, o 422 de validação do Pydantic sairia no formato default do FastAPI
  (`{"detail": [...]}`), diferente do formato das outras respostas de erro.
- **Trailing slashes seguem a tabela do mini-spec exatamente como especificada**,
  inconsistência incluída: `/load/`, `/predict/`, `/list/`, `/models/` com barra
  final, `DELETE /models/{version}` sem barra. Não foi "corrigido" silenciosamente
  (isso mudaria o contrato); os testes batem exatamente nesses paths.
- **Respostas com forma própria** (`LoadResponse`, `ModelsResponse`,
  `HealthResponse`, `DeleteResponse`) são modelos Pydantic locais deste arquivo, não
  de `nercore/schemas.py`: são formatos específicos do transporte REST (por exemplo,
  `{model, loaded, active}` de `/load/` não corresponde a nenhum objeto de domínio
  existente), então não pertencem ao core compartilhado com o MCP.

### Por quê (tradeoffs de implementação)

- **`get_service` como dependência injetável, não um singleton global importado
  direto.** Testar rotas FastAPI com um service real que grava em disco e carrega
  spaCy seria lento e não hermético; o padrão `Depends` + `dependency_overrides` é a
  forma oficialmente suportada pelo FastAPI de trocar toda a árvore de dependências
  de uma rota nos testes, sem duplicar as funções de rota.
- **`extend-immutable-calls = ["fastapi.Depends"]` no ruff, em vez de
  `# noqa: B008` rota por rota.** O padrão `param: Tipo = Depends(...)` é o jeito
  documentado de se fazer injeção de dependência no FastAPI; sinalizar `B008` (chamada
  de função em default de argumento) aqui é falso positivo, porque o FastAPI nunca
  reavalia esse valor por request, ele introspecciona a assinatura da função uma vez.
  Resolver via configuração do linter, não silenciando a regra arquivo a arquivo.

### Edge cases

- Todos os edge cases já cobertos pela tabela do mini-spec (texto vazio/só espaço,
  modelo inválido em `/load/`, `/predict/` sem modelo ativo e sem `model`, delete de
  modelo não carregado) estão implementados via a hierarquia de exceções e seus
  handlers.
- Startup sem rede e sem `DEFAULT_MODEL` pré-instalado: aplicação sobe mesmo assim
  (decisão de design nº 5 do plano de execução).
- `predict()` com `model` nunca antes registrado: lazy-load via `service.predict()`
  (já implementado na fase 2.3), a API só repassa o resultado.

### Bugs encontrados e corrigidos

Nenhum bug de execução; a correção de arquitetura (`EmptyTextError`/`active_model`
em `service.py`) está descrita acima, antes desta seção.

### Estratégia de testes

`tests/test_api.py`, com `TestClient(app)` usado **sem** o context manager `with`:
Starlette só roda `lifespan` (startup/shutdown) dentro de `with TestClient(app) as
client:`; sem o `with`, o `lifespan` nunca dispara, então o warm-up do
`DEFAULT_MODEL` (que usaria `SpacyNERProvider` real e o `HISTORY_DB_PATH` de
produção) nunca é acionado pelos testes. Cada teste constrói seu próprio
`NERService` (registry com `FakeProvider`, `PredictionHistory` num `tmp_path`,
`InMemoryLRUCache`) e o injeta via `app.dependency_overrides[get_service]`, com
`teardown_function` limpando o override entre testes. Cobertura: toda a tabela de
endpoints e códigos de erro (200, 400, 404, 409, 422 duas variantes), mais um teste
de fiação de ponta a ponta com `SpacyNERProvider` real (modelo já instalado, sem
rede) provando que a pilha completa (rota, `service`, provider real) funciona, não
só com o fake. O warm-up do `lifespan` em si foi validado manualmente subindo
`uvicorn` de verdade (ver seção "Como foi implementado" acima), não por um teste
automatizado: automatizar isso exigiria rodar o app com `with TestClient(app)`
contra o `HISTORY_DB_PATH`/spaCy reais de produção, o que reintroduziria
exatamente o acoplamento que a suíte inteira evita.

### Gotchas de ambiente

`Starlette` (dependência do `FastAPI`) emite um aviso de depreciação ao usar
`TestClient` com a versão do `httpx` instalada ("Using `httpx` with
`starlette.testclient` is deprecated; install `httpx2` instead"). Os testes passam
normalmente (é só aviso, não erro); registrado aqui para não ser confundido com uma
falha real numa leitura futura dos logs de CI, e para revisar se `httpx2` (ou uma
mudança de versão do Starlette) muda esse comportamento antes do fechamento da Parte
2.

### ADRs relacionados

ADR-0008 (FastAPI), ADR-0003, ADR-0002, ADR-0004, ADR-0005, ADR-0011.

---

## Validação da fase 2.4

71/71 testes passando (53 das fases 2.1-2.3 + 18 novos) tanto no `.venv` local
(Windows) quanto no Docker/Linux (`python:3.11-slim`, ambiente oficial). Lint (`ruff
check .`) e formatação (`black --check .`) passando. Warm-up do `lifespan` validado
manualmente com `uvicorn` real: `/health/` reportou o modelo default carregado e
`/predict/` sem `model` funcionou de primeira; `/predict/` gravou `data/history.db`
como esperado (removido depois, é artefato local).

---

## 9. Servidor MCP: `src/mcp_server/server.py`

### O que faz e onde

Expõe uma única tool via `fastmcp`: `extract_entities(text, model=None) ->
list[Entity]`. Reusa a mesma `NERService` que a API REST usa (ADR-0003); nenhuma
lógica de negócio vive neste arquivo.

### Como foi implementado

- **A API do `fastmcp` foi inspecionada empiricamente antes de escrever qualquer
  código** (o plano de execução já sinalizava essa biblioteca como instável entre
  versões): confirmado por experimento que `@mcp.tool` devolve a função Python
  original sem envolvê-la (só anexa metadados em `__fastmcp__`), que `fastmcp.Client`
  conecta a um `FastMCP` em memória (sem transporte real) para testes, e que
  exceções levantadas dentro de uma tool chegam ao cliente como
  `fastmcp.exceptions.ToolError`, automaticamente, sem precisar de handlers próprios
  (diferente da API REST, que precisou de handlers explícitos para o formato
  `{error, detail}`).
- **`_service` é um singleton de módulo, construído de forma preguiçosa** (só na
  primeira chamada de `_get_service()`, dentro de `extract_entities`), não no import
  do módulo. Isso evita que só importar `src.mcp_server.server` (o que os testes
  precisam fazer) já crie um `PredictionHistory` real apontando para
  `settings.HISTORY_DB_PATH` e carregue spaCy de verdade como efeito colateral.
- **Warm-up do `DEFAULT_MODEL`, com a mesma tolerância a falha da API (fase 2.4,
  decisão de design nº 5)**: na primeira chamada de `_get_service()`, tenta
  `service.load(settings.DEFAULT_MODEL)`; se falhar (`ModelLoadError`), só loga e
  segue, sem derrubar o processo. Quem chamar `extract_entities` sem `model` recebe
  o erro normal do `NERService` (`NoActiveModelError`), traduzido pelo `fastmcp` em
  `ToolError` no cliente.

### Por quê (tradeoffs de implementação)

- **Singleton de módulo com construção preguiçosa, em vez do `lifespan` do
  `FastMCP` + injeção via `Context`.** Foi verificado experimentalmente que o
  `FastMCP` tem um mecanismo de `lifespan` quase idêntico ao do FastAPI (dispara só
  quando um `Client` de verdade se conecta, não no import), com o valor do lifespan
  acessível dentro de uma tool via um parâmetro `ctx: Context` que o `fastmcp` some
  do schema exposto ao agente. Esse mecanismo funciona, mas é mais código, depende
  de mais detalhes internos do `fastmcp` (exatamente o ponto de instabilidade que o
  plano de execução já sinalizava) e exigiria simular um `Context` nos testes
  que chamam a tool diretamente como função Python. Um singleton de módulo com
  construção preguiçosa (padrão simples, só Python) entrega o mesmo resultado
  prático (nunca constrói no import, constrói e faz warm-up uma vez, antes do
  primeiro uso real) com muito menos superfície de acoplamento à biblioteca.
- **`_build_service()` duplicada aqui e em `api/main.py`, não extraída para um
  módulo compartilhado.** As duas funções são idênticas (~5 linhas: registry com
  `SpacyNERProvider`, `PredictionHistory` em `settings.HISTORY_DB_PATH`,
  `InMemoryLRUCache`), mas REST e MCP são processos independentes de verdade (podem
  rodar em máquinas diferentes, com ciclos de vida diferentes); importar uma função
  de `api/main.py` dentro de `mcp_server/server.py` (ou vice-versa) criaria uma
  dependência entre transportes que a arquitetura (ADR-0003) deliberadamente evita.
  Extrair para um terceiro módulo só para essas 5 linhas seria uma camada de
  indireção sem ganho real, dado o tamanho do projeto.
- **Sem handlers de exceção customizados, ao contrário da API REST.** O `fastmcp`
  já traduz qualquer exceção da tool em `ToolError` para o cliente MCP; replicar o
  formato `{error, detail}` da REST aqui não faria sentido, porque o protocolo MCP
  não é HTTP e o consumidor (um agente/LLM) já recebe uma mensagem de erro
  estruturada o bastante para decidir o que fazer (por exemplo, pedir mais contexto
  ao usuário).

### Edge cases

- `extract_entities` sem `model` e sem modelo ativo: `NoActiveModelError`, vira
  `ToolError` no cliente MCP.
- Texto vazio ou só espaço: `EmptyTextError` (a mesma regra de negócio da REST,
  fase 2.4, vive em `service.py`), também vira `ToolError`.
- `model` explícito nunca antes carregado: lazy-load, igual ao comportamento da
  REST (mesmo `NERService`).
- Cache e modelo carregado em memória NÃO são compartilhados entre os processos
  REST e MCP; só o SQLite do histórico é (mesmo arquivo em disco). Documentado no
  README (seção "MCP: o cenário do assistente de PIX por WhatsApp").

### Bugs encontrados e corrigidos

- **Faltava `mcp.run()`: o arquivo nunca era executável como processo
  standalone.** Encontrado ao tentar validar manualmente o servidor MCP com o CLI
  do próprio `fastmcp` (`fastmcp list`/`call --command "python -m
  src.mcp_server.server"`): o processo era criado e encerrava na hora, sem nunca
  falar o protocolo MCP, porque o módulo só definia `mcp` e a tool, sem nenhum
  bloco `if __name__ == "__main__": mcp.run()`. Os testes automatizados (fase 2.5)
  nunca pegaram isso porque usam `fastmcp.Client(mcp)` (conecta direto no objeto
  Python em memória, sem nunca precisar rodar o arquivo como script) ou chamam
  `extract_entities()` como função direta. Corrigido adicionando o bloco de
  entrypoint padrão. Reforça um limite real da suíte: testes em memória provam a
  lógica da tool, mas não provam que o servidor é executável como processo, e só
  a tentativa de uso manual revelou isso.

### Estratégia de testes

`tests/test_mcp_server.py`: a maioria dos testes chama `extract_entities()`
diretamente como função Python (confirmado que o decorador não a envolve),
substituindo o singleton `_service` do módulo via `monkeypatch.setattr` por um
`NERService` construído com `FakeProvider`, registry/history/cache reais (mesmo
padrão da fase 2.3). Dois testes adicionais usam `fastmcp.Client` conectado em
memória ao objeto `mcp` de verdade (`asyncio.run`, sem precisar da dependência
`pytest-asyncio`): um prova que o protocolo MCP real devolve as entidades
corretamente, outro prova que uma exceção de domínio (texto vazio) chega ao cliente
como `ToolError`.

### Gotchas de ambiente

Nenhum.

### ADRs relacionados

ADR-0003 (core como lib, transportes finos), ADR-0002, ADR-0013 (MCP como uma das
formas de consumo self-service, sem frontend custom).

---

## Validação da fase 2.5

77/77 testes passando (71 da fase 2.4 + 6 novos) tanto no `.venv` local (Windows)
quanto no Docker/Linux (`python:3.11-slim`, ambiente oficial). Lint (`ruff check .`)
e formatação (`black --check .`) passando.

### Validação manual adicional (pós-fase 2.7)

Ao validar manualmente o servidor MCP como processo real (não só em memória via
testes), usando o CLI do próprio `fastmcp`:

```bash
fastmcp list --command "<venv>/python.exe -m src.mcp_server.server" --input-schema
fastmcp call --command "<venv>/python.exe -m src.mcp_server.server" \
  --target extract_entities --input-json '{"text": "Elon Musk visited Brazil in 2024."}'
```

Encontrado e corrigido o bug do `mcp.run()` ausente (ver "Bugs encontrados e
corrigidos" acima). Depois da correção: `fastmcp list` mostra a tool
`extract_entities` com o schema esperado (`text`/`model`), `fastmcp call` devolve
as entidades corretas (`PERSON`/`GPE`/`DATE`), e o caminho de erro (texto vazio)
propaga como `ToolError` também pelo transporte stdio real, não só via
`fastmcp.Client` em memória. 86/86 testes automatizados continuam passando após a
correção, em Windows e Docker/Linux.

Observação de ambiente: o CLI do `fastmcp` (`list`/`call` apontando para um
arquivo `.py`) tenta, por padrão, rodar o servidor via `uv` (não instalado neste
ambiente de desenvolvimento); a alternativa que funciona sem instalar nada além
do que o projeto já usa é `--command "<python-do-venv> -m
src.mcp_server.server"`, que invoca o módulo diretamente com o Python do `.venv`
já criado nas fases anteriores.

---

## 10. Observabilidade: `src/api/observability.py`, `prometheus/`, `grafana/`

### O que faz e onde

`observability.py` reúne os três pilares do ADR-0009: `JSONFormatter` +
`configure_logging` (logs estruturados), `RequestLoggingMiddleware` (log de acesso +
métrica HTTP por requisição) e três métricas Prometheus (`PREDICTIONS_TOTAL`,
`PREDICT_LATENCY_SECONDS`, `CACHE_REQUESTS_TOTAL`) expostas via `/metrics`
(`metrics_response`). `prometheus/prometheus.yml` configura o scrape do serviço;
`grafana/provisioning/` e `grafana/dashboards/ner.json` provisionam o datasource e o
dashboard automaticamente, sem passo manual (ADR-0014).

### Como foi implementado

- **`JSONFormatter`** monta um dicionário com os quatro campos padrão
  (`timestamp`, `level`, `logger`, `message`) e adiciona qualquer atributo extra do
  `LogRecord` que não seja um dos atributos padrão do próprio `logging` (lista fixa
  em `_STANDARD_LOG_RECORD_ATTRS`). É assim que `logger.info("http_request",
  extra={"request_id": ..., "status_code": ...})` vira campos de primeira classe no
  JSON, em vez de ficar preso dentro de uma string de mensagem.
- **`RequestLoggingMiddleware`** (um `BaseHTTPMiddleware` do Starlette) gera um
  `request_id` (`uuid4`) por requisição, mede a duração com `time.perf_counter`,
  loga um evento `http_request` (request id, método, path, status, duração em ms) e
  devolve o mesmo id no header `X-Request-ID` da resposta. Incrementa também
  `HTTP_REQUESTS_TOTAL{method,path,status_code}`, a métrica usada no painel de taxa
  de erro do Grafana.
- **Log e métrica específicos de `/predict/`** vivem na própria rota
  (`api/main.py`), não no middleware: `record_prediction(model, cached,
  duration_seconds)` é chamado ali porque só a rota sabe, depois de chamar
  `service.predict()`, qual foi o modelo resolvido e se veio de cache. O middleware
  genérico não tem (nem deveria ter) esse conhecimento de domínio.
- **As três métricas de negócio são instanciadas uma única vez, a nível de módulo**
  (não dentro de uma função de fábrica), exatamente pela razão antecipada na fase
  2.1: recriar a mesma métrica do `prometheus_client` mais de uma vez no mesmo
  processo levanta `Duplicated timeseries`. Como `observability.py` só é importado
  uma vez por processo Python (comportamento padrão de módulos), isso nunca
  acontece mesmo com vários `TestClient(app)` criados em testes diferentes.
- **`configure_logging` substitui os handlers do logger raiz** por um único
  `StreamHandler` com `JSONFormatter`, chamado uma vez no import de `api/main.py`
  (antes da definição do `app`). Rodar isso no import (não dentro do `lifespan`) é
  seguro porque configurar logging não tem efeito colateral em disco/rede, ao
  contrário de `_build_service()`, que continua adiado para o `lifespan` (fase 2.4).
- **Provisionamento automático do Grafana**: `grafana/provisioning/datasources/`
  cadastra o Prometheus como datasource com `uid: prometheus` fixo;
  `grafana/provisioning/dashboards/` aponta para a pasta onde
  `grafana/dashboards/ner.json` é montada (`/var/lib/grafana/dashboards`). O
  dashboard referencia o datasource pelo mesmo `uid` fixo, então o painel já
  carrega funcionando assim que o container sobe, sem precisar importar nada pela
  UI.
- **`grafana/dashboards/ner.json`** tem os 4 painéis exigidos pelo ADR-0014:
  latência p95 (`histogram_quantile(0.95, ...)` sobre
  `ner_predict_latency_seconds_bucket`), throughput (`rate(ner_predictions_total)`),
  taxa de erro (`rate` de `ner_http_requests_total{status_code=~"5.."}` sobre o
  total) e cache hit rate (`rate` de `ner_cache_requests_total{result="hit"}` sobre
  o total).

### Por quê (tradeoffs de implementação)

- **Log de acesso genérico (middleware) separado do log de negócio de predição
  (rota).** Um único ponto tentando logar tudo (path, status, modelo, cache)
  obrigaria o middleware a inspecionar o corpo da resposta para extrair `model` e
  `cached`, algo mais frágil e mais acoplado ao formato de `PredictResult` do que
  simplesmente logar dentro da própria rota, que já tem esses valores à mão.
- **`X-Request-ID` na resposta, não só no log.** Sem isso, o request id só existiria
  do lado do servidor; devolvê-lo no header permite correlacionar um problema
  relatado pelo cliente (por exemplo, um erro 500) com a linha exata do log,
  prática padrão de operação.
- **Contador de HTTP por status (`HTTP_REQUESTS_TOTAL`), além do contador de
  predições (`PREDICTIONS_TOTAL`).** O ADR-0014 pede explicitamente um painel de
  taxa de erro; sem uma métrica que inclua o `status_code` de toda resposta
  (inclusive erros 4xx/5xx antes de chegar numa rota de negócio, como um 404 de
  rota inexistente), não haveria como montar esse painel com dado real. Foi
  adicionado no meio do middleware porque é exatamente ali que o status final de
  toda resposta já está disponível, sem duplicar lógica em cada rota.
- **Arquivos de provisionamento do Grafana (`grafana/provisioning/**`) não estavam
  na árvore do mini-spec** (que só citava `grafana/dashboards/ner.json`), mas sem
  eles o dashboard versionado como código exigiria um passo manual de import via
  UI toda vez que o Grafana subisse do zero, o que contradiz a própria justificativa
  do ADR-0014 ("dashboard versionado, reprodutível localmente"). Mesma lógica da
  adição de `config.py` na fase 2.1: um arquivo novo, fora da árvore original, mas
  necessário para a peça já planejada funcionar de verdade.

### Edge cases

- Log sem nenhum campo extra: o JSON final só tem os 4 campos padrão, nada de
  chaves vazias ou `null` supérfluos.
- Log de uma exceção (`exc_info`): o traceback formatado vai para a chave
  `exc_info` do JSON, não para a mensagem.
- `/metrics` chamado antes de qualquer predição: `PREDICTIONS_TOTAL`,
  `PREDICT_LATENCY_SECONDS` e `CACHE_REQUESTS_TOTAL` simplesmente não aparecem
  ainda no texto exposto (comportamento padrão do `prometheus_client`: uma série só
  existe depois do primeiro `.labels(...).inc()`/`.observe(...)` com aquela
  combinação de labels). `HTTP_REQUESTS_TOTAL` é incrementada só depois que
  `call_next` devolve a resposta, então a própria chamada a `/metrics` nunca se
  conta a si mesma; ela aparece no texto devolvido pela chamada seguinte.

### Bugs encontrados e corrigidos

- **Contexto de build do Docker sem `.dockerignore`.** Ao validar o
  `docker-compose.yml` com os novos serviços (`docker compose up prometheus
  grafana`), o Compose tentou reconstruir a imagem `api` (dependência declarada) e
  o passo de contexto de build ficou visivelmente lento, transferindo mais de
  300MB. Causa: sem `.dockerignore`, `COPY . .` no `Dockerfile` (ainda stub) inclui
  `.venv/` (centenas de MB com spaCy/numpy instalados), `__pycache__/`,
  `.pytest_cache/` e `data/`. Corrigido criando `part2-ner-serving/.dockerignore`
  excluindo esses diretórios. Não é um bug funcional (os testes continuavam
  passando), mas teria piorado bastante o tempo de build real na fase 2.7, quando o
  Dockerfile passar a de fato instalar dependências.

### Estratégia de testes

`tests/test_observability.py`: `JSONFormatter` testado diretamente (sem depender de
`caplog`, que usa seu próprio handler): construção manual de `logging.LogRecord`
com e sem campos extra, com e sem `exc_info`, verificando que a saída é sempre um
único JSON válido por linha e que nenhum atributo padrão do `LogRecord` vaza para o
payload quando não há `extra`. Métricas testadas via `metric.collect()` (API pública
do `prometheus_client`, não o atributo privado `_value`), com um nome de
modelo exclusivo por teste para não sofrer interferência de outros testes que
também chamam `record_prediction` (as métricas são singletons de módulo,
compartilhados por todo o processo de teste). `tests/test_api.py` ganhou um teste
de `/metrics` (verifica presença das 4 métricas no texto exposto, com um modelo de
nome exclusivo) e um teste confirmando que toda resposta carrega `X-Request-ID`.

A validação de que o Grafana e o Prometheus realmente carregam o datasource e o
dashboard provisionados foi feita manualmente subindo só esses dois serviços
(`docker compose up --no-deps prometheus grafana`, sem a `api`, cujo Dockerfile
ainda é stub até a fase 2.7): `curl` em `/-/healthy` do Prometheus confirmou o
target `ner-serving` configurado, e a API HTTP do Grafana
(`/api/datasources`, `/api/dashboards/uid/ner-serving`) confirmou o datasource
`Prometheus` e os 4 painéis do dashboard carregados automaticamente, sem nenhum
passo manual de import.

### Gotchas de ambiente

`docker compose up <serviço>` também sobe as dependências declaradas em
`depends_on` daquele serviço (aqui, `prometheus` depende de `api`). Para validar
Prometheus e Grafana isoladamente antes do Dockerfile da API estar pronto (fase
2.7), é preciso `--no-deps` explicitamente, senão o Compose tenta subir a `api`
(que ainda falha, por ser um stub) e aborta a subida dos outros serviços.

### ADRs relacionados

ADR-0009 (observabilidade da aplicação), ADR-0014 (Prometheus + Grafana).

---

## Validação da fase 2.6

86/86 testes passando (77 da fase 2.5 + 9 novos) tanto no `.venv` local (Windows)
quanto no Docker/Linux (`python:3.11-slim`, ambiente oficial). Lint (`ruff check .`)
e formatação (`black --check .`) passando. Prometheus e Grafana validados
manualmente via `docker compose up --no-deps prometheus grafana` (ver seção acima):
target configurado, datasource e dashboard (4 painéis) provisionados
automaticamente.

---

## 11. Docker/compose de ponta a ponta e fechamento (fase 2.7)

### O que faz e onde

`Dockerfile` real (substitui o stub da Fase 0), `docker-compose.yml` final com os 4
serviços (api, redis, prometheus, grafana), `.dockerignore` novo, `README.md`
reescrito com o fluxo real de execução, `ADR-0016` (Docker Compose como ambiente
oficial de validação da Parte 2, análogo ao ADR-0015 da Parte 1).

### Como foi implementado

- **`Dockerfile`** segue exatamente o padrão já usado na Parte 1: `FROM
  python:3.11-slim`, `COPY . .`, `RUN pip install --no-cache-dir -e ".[dev]"`, uma
  única imagem usada tanto para servir a API (`CMD uvicorn ...`) quanto para rodar a
  suíte de testes (`docker run <imagem> python -m pytest tests/`). Sem etapa
  especial de download do modelo default: como `en-core-web-sm` já é dependência
  normal do `pyproject.toml` desde a fase 2.1 (pinada por URL de wheel), `pip
  install` durante o build já o baixa. O tradeoff pedido pelo mini-spec (imagem
  maior vs. container já usável offline) foi decidido ali atrás, sem precisar de
  código novo aqui, só de documentação explicando a conexão.
- **`docker-compose.yml`**: `api` ganhou um volume `./data:/app/data`, para o
  `history.db` (SQLite) sobreviver a um `docker compose down`/`up` (mesmo padrão do
  bind mount de `data/` na Parte 1). `redis`, `prometheus` e `grafana` continuam
  como já estavam desde as fases 2.2/2.6.
- **`.dockerignore` novo** (fase 2.6 corrigiu o sintoma, aqui ele já está em vigor
  para a imagem de produção de verdade): sem ele, `COPY . .` levaria `.venv/`,
  `__pycache__/` e `data/` para dentro da imagem.
- **README reescrito**: pré-requisitos (por que Docker é obrigatório, com o gotcha
  real do `click`/`spacy` documentado, não hipotético), `docker compose up --build`
  como comando único, tabela de endpoints atualizada (a antiga distinção
  "obrigatório/sugerido" do mini-spec não faz mais sentido: tudo foi implementado),
  seção do tradeoff de pré-download do modelo, e status final com contagem de
  testes.
- **`ADR-0016`** documenta a decisão (implícita desde o início, mas nunca escrita)
  de que Docker Compose é o ambiente oficial de validação da Parte 2, espelhando o
  papel do ADR-0015 na Parte 1. Cita o próprio bug do `click`/`spacy` (fase 2.1)
  como evidência concreta de por que essa validação importa, não é só
  formalidade.

### Por quê (tradeoffs de implementação)

- **Uma imagem só, com dependências de dev incluídas, em vez de multi-stage build
  enxuto.** Mesma decisão já tomada (e documentada) na Parte 1: simplicidade e um
  único Dockerfile testável pesam mais do que otimizar o tamanho final da imagem,
  no escopo de um case. Documentado explicitamente como consequência negativa no
  ADR-0016, não escondido.
- **Bind mount de `data/` em vez de um named volume do Docker.** Um bind mount
  deixa o `history.db` visível e inspecionável diretamente no host (o mesmo
  racional já aplicado ao `data/` da Parte 1), o que importa para um avaliador que
  quer abrir o arquivo sem precisar entrar no container.

### Edge cases

- Primeira execução (`docker compose up --build`) sem `data/history.db` ainda
  existente: `PredictionHistory.__init__` cria o diretório e o arquivo sozinho (já
  implementado na fase 2.2); nada de setup manual necessário.
- `docker compose up <serviço>` sobe as dependências declaradas em `depends_on`
  daquele serviço (gotcha já registrado na fase 2.6); `docker compose up --build`
  sem argumento nenhum sobe todos os 4 de uma vez, sem essa armadilha.

### Bugs encontrados e corrigidos

Nenhum bug novo nesta fase (o do `.dockerignore` foi encontrado e corrigido ainda
na fase 2.6, antes do Dockerfile real existir).

### Estratégia de testes / validação

Sem testes novos de código nesta fase (não há lógica nova em `src/`). Validação
empírica de ponta a ponta, na ordem:

1. `docker compose up --build -d`: os 4 containers sobem.
2. `curl /health/`: `active_model: "en_core_web_sm"` já carregado, sem chamada
   prévia a `/load/` (warm-up funcionando dentro do container real, não só via
   `uvicorn` local como na fase 2.4).
3. `curl -X POST /predict/`: entidades corretas (`PERSON`, `GPE`, `DATE`) para um
   texto real, `cached: false` na primeira chamada.
4. `curl /docs`: Swagger UI responde 200.
5. Duas predições de mais, aguardando dois ciclos de scrape do Prometheus (15s
   cada): `curl` direto no Prometheus confirma o target `ner-serving` com `health:
   up`; consulta à API do Grafana (`/api/datasources/proxy/uid/prometheus/api/v1/query`)
   confirma `ner_predictions_total{model="en_core_web_sm"}` valendo `2`, prova de
   que o dado flui de verdade api → Prometheus → Grafana, não só que os serviços
   sobem.
6. `docker exec` no container da API + `sqlite3` confirmam as 2 predições
   persistidas em `/app/data/history.db`, e o mesmo arquivo aparece no host em
   `part2-ner-serving/data/history.db` (prova do bind mount).
7. `docker run <imagem> python -m pytest tests/ -v`: 86/86 passando dentro da
   mesma imagem que serve a API (não uma imagem de teste separada).
8. `docker compose -f part2-ner-serving/docker-compose.yml up --build -d`,
   repetido a partir da raiz do repositório (não só de dentro da pasta do
   projeto): mesmo resultado, confirma que o `make up-p2` da raiz (que roda esse
   exato comando) funciona.

### Gotchas de ambiente

Nenhum novo. `make` (usado pelos atalhos do `Makefile` da raiz) não está disponível
neste ambiente Git Bash específico usado durante o desenvolvimento; os comandos
`docker compose`/`docker run` equivalentes foram usados diretamente para validar, e
o comportamento é idêntico ao que o `Makefile` chama por trás. Isso não é uma
limitação do projeto, é uma característica do ambiente local de desenvolvimento
(mesma situação seria resolvida com `make` instalado, comum em macOS/Linux).

### ADRs relacionados

ADR-0016 (novo, ambiente oficial de validação), ADR-0004 (Redis, ainda inerte),
ADR-0009, ADR-0014.

---

## 12. Cache Redis: `src/nercore/cache.py::RedisCache` (fase 2.8, primeira parte)

### O que faz e onde

`RedisCache(PredictionCache)` implementa a mesma interface de `InMemoryLRUCache`
usando um Redis de verdade, via `redis-py`. `build_cache(cache_backend, redis_url)`
é a fábrica (nova, em `cache.py`) que escolhe entre as duas implementações; `api/main.py`
e `mcp_server/server.py` passaram a chamar essa fábrica em vez de instanciar
`InMemoryLRUCache()` direto. `docker-compose.yml` liga `CACHE_BACKEND=redis` na
`api`, então o container Redis (que subia ocioso desde a fase 2.6) passa a ser
usado de verdade na demo completa.

### Como foi implementado

- **`RedisCache.get`/`set` serializam `list[Entity]` como JSON** (`entity.model_dump()`
  + `json.dumps`/`json.loads`), o mesmo padrão já usado em `history.py` (fase 2.2)
  para persistir `output`. Nenhum formato de serialização novo no projeto.
- **Chaves com prefixo `ner:cache:`** (`RedisCache.KEY_PREFIX`), para não colidir
  com outros usos do mesmo Redis e para dar pra inspecionar/filtrar via `redis-cli
  keys 'ner:cache:*'` sem ambiguidade.
- **A política de evicção LRU não vive no cliente Python**, ao contrário de
  `InMemoryLRUCache` (que implementa a própria evicção com `OrderedDict`). Para
  `RedisCache`, quem evict a é o próprio servidor Redis, configurado no
  `docker-compose.yml` com `--maxmemory 64mb --maxmemory-policy allkeys-lru`. É a
  forma padrão de se ter LRU com Redis: deixar o servidor decidir, não reimplementar
  o algoritmo no cliente.
- **`build_cache` vive em `cache.py`, não em `service.py`.** `NERService` continua
  sem saber que Redis existe (recebe uma `PredictionCache` já pronta pelo
  construtor, decisão da fase 2.3); é a camada de transporte (`api/main.py`,
  `mcp_server/server.py`) que lê `settings.CACHE_BACKEND`/`settings.REDIS_URL` e
  monta a peça certa antes de passar para `NERService`.
- **`docker-compose.yml`: `REDIS_URL=redis://redis:6379/0` na `api`**, não
  `localhost` (esse é o default do `config.py`, correto para quem roda a API fora
  do compose). Dentro da rede do compose, o hostname resolvido é o nome do
  serviço (`redis`), não `localhost`; contêineres diferentes, redes diferentes.

### Por quê (tradeoffs de implementação)

- **`CACHE_BACKEND=memory` continua sendo o default do código** (`config.py`), não
  mudou. É o `docker-compose.yml` que liga `redis` explicitamente, de propósito,
  para a demo completa provar que a troca funciona de ponta a ponta. Quem roda a
  API fora deste compose (só `uvicorn`, por exemplo) continua caindo no LRU em
  processo, exatamente como o ADR-0004 recomenda como default.
- **Sem fallback automático para `InMemoryLRUCache` se o Redis cair.** Se
  `CACHE_BACKEND=redis` e o Redis está fora do ar, `RedisCache.get`/`set` propagam
  o erro de conexão do `redis-py`. Silenciar isso e cair para memória seria
  mascarar uma falha de infraestrutura real (o operador não saberia que o Redis
  caiu); não é o tipo de robustez que vale a pena adicionar sem ter sido pedida.

### Edge cases

- `build_cache` com um valor de `CACHE_BACKEND` desconhecido (nem `"memory"` nem
  `"redis"`): `ValueError` explícito, falha cedo em vez de silenciosamente cair
  num backend errado.
- `RedisCache(redis_url)` não conecta na hora da construção (`redis.Redis.from_url`
  é preguiçoso); só o primeiro `get`/`set` de fato abre a conexão. Isso permite
  testar `build_cache("redis", ...)` sem precisar de um Redis no ar (só verifica o
  tipo devolvido).

### Bugs encontrados e corrigidos

- **`tests/test_redis_cache.py` fixava a URL em `"redis://localhost:6379/0"`, em
  vez de ler `settings.REDIS_URL`.** Passava nos testes locais (Redis publicado em
  `localhost:6379` também fora do compose), mas ao rodar dentro de um container
  avulso na mesma rede do compose (`docker run --network
  part2-ner-serving_default -e REDIS_URL=redis://redis:6379/0 ...`), os testes
  continuavam tentando `localhost` e pulavam com "Redis não está acessível",
  mesmo com um Redis de verdade alcançável em `redis:6379`. Corrigido lendo
  `settings.REDIS_URL` (que já respeita a variável de ambiente) em vez de uma
  constante fixa no arquivo de teste.
- **Container `api` com código desatualizado após editar testes.** Ao investigar o
  bug acima, o primeiro `docker run` usou uma imagem construída ANTES da correção
  (`docker compose up --build` tinha rodado mais cedo; a edição no arquivo de
  teste veio depois, mas não há rebuild automático). Não é bug de código, mas um
  lembrete operacional: `COPY . .` no Dockerfile tira uma fotografia no momento do
  build, então qualquer edição posterior exige `docker compose build`/`--build`
  de novo antes de validar dentro do container.

### Estratégia de testes

`tests/test_cache.py` ganhou 3 testes de `build_cache` (memory, redis, backend
desconhecido) sem precisar de um Redis real (a instanciação de `RedisCache` não
conecta). `tests/test_redis_cache.py` é um arquivo novo, todo pulado
(`pytest.mark.skipif`) se `settings.REDIS_URL` não responder a `PING` dentro de
0.5s, mesmo padrão do skip de Parquet/hadoop.dll no Windows da Parte 1: hit/miss,
sobrevivência do valor a uma segunda instância de `RedisCache` (prova de que o
dado está no Redis, não num estado Python), separação por modelo, e o prefixo de
chave. Validado rodando de verdade em três cenários: `.venv` local com `docker
compose up -d redis`, container avulso na rede do compose apontando para
`redis://redis:6379/0`, e a suíte inteira dentro da imagem final da `api`.

### Validação manual de ponta a ponta

`docker compose up --build` com `CACHE_BACKEND=redis` já ativo: primeira chamada a
`/predict/` veio `cached: false`, segunda chamada com o mesmo texto veio `cached:
true`, e `docker exec ... redis-cli keys '*'` mostrou a chave
`ner:cache:<hash>` de verdade dentro do Redis do compose.
`redis-cli config get maxmemory-policy` confirmou `allkeys-lru` aplicado.

### Gotchas de ambiente

Editar um arquivo depois de já ter rodado `docker compose up --build` não afeta o
container em execução nem uma imagem já construída; é preciso reconstruir
(`docker compose build <serviço>` ou `up --build` de novo) antes de validar a
mudança dentro do Docker. Óbvio em retrospecto, mas custou uma investigação real
nesta fase (ver "Bugs encontrados e corrigidos" acima).

### ADRs relacionados

ADR-0004 (agora com as duas metades implementadas: LRU em processo e Redis).

---

## 13. Playground Gradio: `src/gradio_app/app.py` (fase 2.8, segunda parte)

### O que faz e onde

Interface web opcional (ADR-0013) com um campo de texto, um campo de modelo
opcional, e uma área `gr.HighlightedText` que mostra as entidades reconhecidas
destacadas dentro do próprio texto. `predict_and_highlight(text, model)` é a
única função de negócio do módulo: chama `NERService.predict` e traduz o
resultado para o formato que `gr.HighlightedText` espera.

### Como foi implementado

- **A API do `gradio` foi inspecionada empiricamente antes de escrever código**
  (mesma disciplina usada com `fastmcp` na fase 2.5): confirmado por experimento
  que `gr.HighlightedText.postprocess` aceita `{"text": ..., "entities": [{"entity",
  "start", "end"}, ...]}`, formato que mapeia direto para os campos de `Entity`
  (`label`/`start_char`/`end_char`), sem nenhuma tradução manual de spans.
- **Mesmo padrão de singleton preguiçoso do MCP (fase 2.5)**: `_service` só é
  construído no primeiro uso de `predict_and_highlight`, não no import do
  módulo, e tenta pré-carregar `DEFAULT_MODEL` uma vez, sem derrubar o processo
  se falhar.
- **`_build_service()` chama `build_cache()` (fase 2.8, primeira parte)**, então
  o Gradio herda automaticamente o mesmo backend de cache (`CACHE_BACKEND`) que
  API e MCP usam. Confirmado manualmente: uma predição feita pelo Gradio grava
  uma chave `ner:cache:...` no Redis do compose, igual à API.
- **Erros de negócio (`EmptyTextError`, `NoActiveModelError`, `ModelLoadError`)
  viram `gr.Error`**, a classe do próprio Gradio que mostra uma mensagem limpa na
  UI (sem traceback), em vez de deixar a exceção Python crua vazar para a tela.
  Mesmo espírito dos handlers de exceção da API REST (fase 2.4), adaptado para o
  mecanismo de erro específico do Gradio.
- **Dependência isolada num extra `demo`, não em `dev`** (`pyproject.toml`):
  ADR-0013 exige que o playground não roube tempo de CI. O `.github/workflows/ci.yml`
  só instala `.[dev]`, então nunca baixa `gradio`; só o `Dockerfile` (imagem
  final) instala `.[dev,demo]`.
- **`docker-compose.yml`: serviço `gradio` atrás de `profiles: ["demo"]`.** Não
  sobe com `docker compose up` puro, só com `docker compose --profile demo up
  --build`. Mesma imagem da `api` (`build: .`), só troca o `command` para
  `python -m src.gradio_app.app`; nenhum Dockerfile novo.

### Por quê (tradeoffs de implementação)

- **`gr.HighlightedText` em vez de devolver JSON cru.** O ADR-0013 justifica o
  Gradio como "on-brand para ML"; um textbox de saída com JSON não seria
  diferente de usar `curl`. Destacar as entidades no próprio texto é o que
  justifica ter uma UI em vez de só documentar mais um exemplo de `curl`.
  Confirmado que o formato de entrada certo existe nativamente no componente,
  sem precisar de HTML/CSS customizado.
- **Extra `demo` separado de `dev`, com `pytest.importorskip("gradio")` no
  arquivo de teste.** Sem isso, `tests/test_gradio_app.py` quebraria a coleta de
  testes inteira em qualquer ambiente sem `gradio` instalado (CI, por
  desenho). `importorskip` pula o arquivo inteiro com motivo claro nesse caso, e
  roda de verdade onde `demo` estiver instalado (`.venv` local com `pip install
  -e ".[dev,demo]"`, ou a imagem Docker).
- **Profile do compose em vez de mais um `docker-compose.yml`.** Manter um único
  arquivo de compose, com o serviço opcional atrás de `profiles`, é mais simples
  do que duas fontes de verdade (`docker-compose.yml` +
  `docker-compose.demo.yml`) para a mesma stack.

### Edge cases

- Campo de modelo em branco (`""`): tratado como `None` (`model.strip() or
  None`), usa o modelo ativo, mesmo comportamento de `payload.model` opcional na
  API REST.
- Texto vazio ou só espaço: `gr.Error`, não uma exceção Python crua.
- Sem nenhum modelo ativo (warm-up falhou e nenhum modelo foi carregado ainda):
  `gr.Error` também, com a mensagem de `NoActiveModelError`.
- Predições feitas no Gradio originalmente não apareciam nas métricas do
  Prometheus/Grafana (o Gradio chama `NERService.predict()` direto, sem passar
  pela rota `/predict/` da API, que era a única a chamar `record_prediction()`).
  Descoberto porque o usuário perguntou diretamente ("o que faço no Gradio não
  alimenta o Grafana?"); endereçado logo em seguida, ver seção 14.

### Bugs encontrados e corrigidos

- **Imagem `api` desatualizada depois de adicionar os arquivos do Gradio.**
  Mesmo bug de metodologia já documentado na fase 2.8 (primeira parte, seção
  12): `docker compose --profile demo up --build gradio redis` só reconstrói os
  serviços nomeados explicitamente (`gradio`, `redis`), não `api`. Rodar
  `python -m pytest tests/` dentro da imagem `api` (ainda não reconstruída)
  mostrou só 94 testes (o estado anterior ao Gradio), não 98. Corrigido com
  `docker compose build api` explícito antes de validar. Reforça a lição já
  registrada: `--build` seletivo por serviço não reconstrói o resto da stack.
- **`docker compose down` (sem `--profile demo`) não derruba um serviço que foi
  subido com `--profile demo up`.** Descoberto ao validar o teardown: o
  container `gradio` continuou rodando depois de um `docker compose down` liso,
  e um `docker compose up -d` seguinte reportou o `gradio` como "Up" sem
  nunca tê-lo criado nesse comando. É comportamento documentado do Compose (o
  profile precisa ser passado tanto para subir quanto para derrubar), não um
  bug deste projeto, mas fácil de não perceber. `docker compose --profile demo
  down` é a forma correta de limpar tudo, incluindo o `gradio`.

### Estratégia de testes

`tests/test_gradio_app.py`: só a função `predict_and_highlight` é testada
(FakeProvider, mesmo padrão dos outros transportes), nunca a renderização da UI
do Gradio em si, pelo mesmo motivo que a Parte 2 nunca testou o HTML gerado pelo
Swagger da API REST. Cobertura: formato de saída correto para
`gr.HighlightedText`, campo de modelo em branco usando o ativo, e os dois
caminhos de erro (`EmptyTextError`, `NoActiveModelError`) virando `gr.Error`.

### Validação manual de ponta a ponta

`docker compose --profile demo up --build gradio redis`: a UI subiu em
`localhost:7860` com o título e a descrição corretos (confirmado via `/config`
da própria aplicação). Chamada real via `gradio_client.Client.predict(...)`
(a mesma API que o navegador usa por trás) devolveu as entidades certas
("Send $100 to John tomorrow." → MONEY/PERSON/DATE; "Bill Gates works at
Microsoft." → PERSON/ORG), e `redis-cli keys` confirmou a chave de cache
gravada pelo Gradio no mesmo Redis que a API usa. Confirmado também que
`docker compose up` puro (sem `--profile demo`) sobe só os 4 serviços centrais,
sem o `gradio`.

### Gotchas de ambiente

Ver "Bugs encontrados e corrigidos" acima: reconstruir a imagem certa depois de
mudar código, e usar `--profile demo` tanto para subir quanto para derrubar o
serviço opcional.

### ADRs relacionados

ADR-0013 (sem frontend custom; Gradio como exceção opcional e condicionada),
ADR-0003 (reuso do core, zero lógica nova).

---

## 14. Métricas do Gradio no Prometheus/Grafana (fase 2.8, terceira parte)

### O que faz e onde

O serviço `gradio` passa a expor `/metrics` (mesmo formato Prometheus da API,
mesmo registro de métricas de `src/api/observability.py`) e a chamar
`record_prediction()` a cada predição. `prometheus/prometheus.yml` ganha um
segundo alvo (`gradio:7860`) sob o mesmo `job_name` da API.

### Como foi implementado

- **`predict_and_highlight` mede a duração com `time.perf_counter()` e chama
  `record_prediction(model=result.model, cached=result.cached,
  duration_seconds=...)`**, exatamente como a rota `/predict/` da API já
  fazia (fase 2.6). Nenhuma métrica nova foi criada; é a mesma
  `PREDICTIONS_TOTAL`/`PREDICT_LATENCY_SECONDS`/`CACHE_REQUESTS_TOTAL` de
  sempre, só que agora incrementada também a partir deste processo.
- **`gr.mount_gradio_app(app, demo, path="/")`** (API pública do próprio
  Gradio, verificada empiricamente antes de usar) monta a UI dentro de uma
  `FastAPI` criada por nós, o que abre espaço para registrar uma rota HTTP
  customizada (`/metrics`, via `app.get("/metrics")(metrics_response)`) no
  mesmo processo e porta. `demo.launch()` sozinho não permite isso: o
  processo passou a subir com `uvicorn.run(app, ...)` em vez de
  `demo.launch()`.
- **Mesmo `job_name` no `prometheus.yml` para `api` e `gradio`, dois
  `targets`.** Os painéis do dashboard (fase 2.6) somam com `sum(rate(...))`
  sem filtrar por `instance`; usar o mesmo job significa que nenhum painel
  precisou mudar para passar a incluir as duas fontes.

### Por quê (tradeoffs de implementação)

- **`record_prediction()` chamado direto de dentro do Gradio, não via uma
  segunda rota HTTP intermediária.** O Gradio já reusa `NERService` em
  processo (decisão original do ADR-0013); reusar também a função de métrica
  do mesmo jeito é consistente, e evita inventar uma chamada de rede
  desnecessária só para registrar uma métrica.
- **Um único `job_name` com dois `targets`, em vez de dois jobs
  separados** (`ner-serving-api`, `ner-serving-gradio`). A alternativa exigiria
  reescrever as queries do dashboard para somar entre jobs; manter um job só
  significa zero mudança nos painéis já existentes, ao custo de não conseguir
  filtrar "só API" ou "só Gradio" num painel sem usar o label `instance`
  (que continua disponível, só não é o que os painéis atuais agrupam).

### Edge cases

- `gradio:7860` aparece como target `down` no Prometheus sempre que o profile
  `demo` não está no ar (comportamento esperado, não erro de configuração,
  documentado desde a fase 2.8 segunda parte).
- A UI do Gradio e o `/metrics` compartilham porta e processo: um erro ao
  montar uma rota não derruba a outra (são registradas na mesma app FastAPI
  antes do `uvicorn.run`, então qualquer erro de import apareceria no boot,
  não em runtime).

### Bugs encontrados e corrigidos

Nenhum bug de código nesta parte. Um problema de ambiente (não deste projeto)
interrompeu a primeira tentativa de validação: o Docker Desktop travou no meio
dos testes manuais (provavelmente por causa do volume de rebuilds da sessão),
exigindo reinício antes de terminar a validação. Não deixou nenhum estado
inconsistente: depois do reinício, `docker compose --profile demo up -d`
subiu tudo limpo de novo, e a validação foi refeita do zero com sucesso.

### Estratégia de testes

Nenhum teste automatizado novo: a mudança em `predict_and_highlight` (chamar
`record_prediction`) já é exercitada pelos testes existentes de
`tests/test_gradio_app.py` (que não fazem asserção sobre métricas, mas
passariam a falhar se a chamada quebrasse alguma coisa). A montagem do
`/metrics` via `gr.mount_gradio_app` não tem teste automatizado dedicado,
porque testar isso exigiria subir um servidor HTTP de verdade (mesmo
raciocínio já aplicado ao warm-up do `lifespan` da API na fase 2.4: validado
manualmente, não em teste unitário).

### Validação manual de ponta a ponta

Com a stack completa no ar (`docker compose --profile demo up -d`):
1. `curl http://localhost:7860/metrics` confirmou `ner_predictions_total`,
   `ner_predict_latency_seconds` e `ner_cache_requests_total` presentes e
   incrementados depois de uma predição real via `gradio_client.Client`.
2. Prometheus reportou os dois alvos (`api:8000`, `gradio:7860`) como `up`.
3. Uma consulta via API do Grafana
   (`/api/datasources/proxy/uid/prometheus/api/v1/query`) por
   `ner_predictions_total` mostrou a série com `instance="gradio:7860"`.
4. Uma segunda predição feita via `curl` direto na API, seguida da mesma
   consulta agregando `sum(...) by (instance)`, mostrou as duas séries lado a
   lado (`api:8000` e `gradio:7860`), provando que os painéis (que somam sem
   filtrar por instância) já agregam as duas fontes sem nenhuma mudança
   no dashboard.

### Gotchas de ambiente

Docker Desktop pode travar sob uso intenso (muitos rebuilds seguidos na mesma
sessão); não é um problema deste projeto, mas vale reiniciar o Docker Desktop
se `docker ps` parar de responder ou devolver "Internal Server Error".

### ADRs relacionados

ADR-0009 (observabilidade), ADR-0014 (Prometheus/Grafana), ADR-0013 (Gradio).

---

## Fechamento da Parte 2 (atualizado)

As 7 fases do plano de execução (2.1 a 2.7) mais as três partes da fase 2.8
(`RedisCache` real, o playground Gradio, e suas métricas no Prometheus/Grafana)
estão implementadas, testadas e documentadas. 98 testes no total (93 passando +
5 pulados sem Redis local disponível) no Docker/Linux, o ambiente oficial
(ADR-0016); todos os 98 passam quando um Redis está acessível. `docker compose
up --build` sobe os 4 serviços centrais com `CACHE_BACKEND=redis` já ativo;
`docker compose --profile demo up --build` soma o playground Gradio, já
instrumentado. Uma predição real flui de ponta a ponta em todos os
consumidores (REST, MCP, Gradio): serviço → Redis (cache) → Prometheus →
Grafana, cada elo validado manualmente, incluindo a agregação de métricas de
múltiplas fontes no mesmo painel. Não resta nenhum item da lista original de
"fora do escopo/fase 2.8" além de infraestrutura AWS via Terraform (fora do
escopo desta entrega, ver discussão sobre custo real de nuvem) e suporte a
português de qualidade (documentado como evolução, ADR-0011).
