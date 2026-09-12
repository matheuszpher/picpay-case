# Parte 2: NER Serving (plano online)

Serviço de NER com spaCy atrás de um provider abstrato. Toda a lógica vive numa lib
reutilizável (`nercore`), exposta por dois transportes finos, REST (FastAPI) e MCP, sem
duplicação. Cache de predição, registry de versões de modelo e histórico persistido.
Observabilidade com logs estruturados, `/health`, `/metrics` e dashboards Grafana. Projeto
autossuficiente: roda sozinho, sem depender da Parte 1.

Racional de arquitetura e diagramas: ver [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) e os
ADRs [0002](../docs/adr/0002-provider-abstrato-ner.md),
[0003](../docs/adr/0003-core-lib-transportes-finos.md),
[0004](../docs/adr/0004-cache-predicao-lru-redis.md),
[0005](../docs/adr/0005-historico-sqlite.md),
[0011](../docs/adr/0011-spacy-parametro-versionado.md) e
[0014](../docs/adr/0014-prometheus-grafana.md).

## Estrutura

```
part2-ner-serving/
├── docs/
│   └── IMPLEMENTATION.md   # registro de implementação (como/por quê por módulo)
├── pyproject.toml
├── src/
│   ├── nercore/             # a LIB (core reutilizável, sem saber de HTTP/MCP)
│   │   ├── providers/
│   │   │   ├── base.py          # interface NERProvider (abstrata) + ModelLoadError
│   │   │   └── spacy_provider.py
│   │   ├── config.py       # settings via env (pydantic-settings)
│   │   ├── registry.py     # modelos carregados + versão ativa
│   │   ├── history.py      # persistência do histórico (SQLite)
│   │   ├── cache.py        # LRU em processo + Redis (build_cache escolhe por env)
│   │   ├── service.py      # orquestra provider + registry + cache + history
│   │   └── schemas.py      # Pydantic (Entity, PredictRequest, ...)
│   ├── api/                 # transporte REST (FastAPI), fino
│   │   ├── main.py
│   │   └── observability.py    # logs JSON + métricas Prometheus
│   ├── mcp_server/          # transporte MCP, fino, reusa nercore.service
│   │   └── server.py
│   └── gradio_app/          # playground opcional (ADR-0013), reusa nercore.service
│       └── app.py
├── tests/
├── prometheus/
│   └── prometheus.yml
├── grafana/
│   ├── dashboards/ner.json          # dashboard versionado como código
│   └── provisioning/                # datasource + dashboard provisionados sozinhos
├── Dockerfile
└── docker-compose.yml       # api + redis + prometheus + grafana (+ gradio opcional)
```

## Endpoints

| Método | Rota | Descrição |
|---|---|---|
| POST | `/load/` | Pré-carrega (baixa se preciso) um modelo e o marca como ativo |
| POST | `/predict/` | Extrai entidades de um texto; usa o modelo ativo se `model` não for informado |
| GET | `/list/` | Histórico de predições (paginado por `limit`/`offset`) |
| GET | `/models/` | Modelo ativo + lista de modelos carregados |
| GET | `/health/` | Liveness + qual modelo está ativo |
| DELETE | `/models/{version}` | Descarrega um modelo |
| GET | `/metrics` | Métricas no formato Prometheus |

Documentação interativa (Swagger UI) em `/docs` assim que a API estiver no ar.

### Idioma: por que texto em português não extrai nada por padrão

`en_core_web_sm` (o modelo default) foi treinado só em inglês; um texto em
português passa pelo pipeline normalmente, mas `doc.ents` volta vazio, porque o
modelo não reconhece nada daquele idioma. Não é um bug de mapeamento nosso, é uma
limitação do modelo carregado.

A arquitetura de provider já suporta trocar de idioma sem nenhuma mudança de
código: `POST /load/` com `{"model": "pt_core_news_sm"}` baixa e carrega o modelo
de português do spaCy (mesmo caminho de lazy-load usado para qualquer outro
modelo). Testado manualmente: funciona, mas a qualidade fica bem abaixo do
`en_core_web_sm` em texto informal (estilo mensagem de PIX). Exemplo real:

```
Texto:  "Envie R$100 para Matheus amanhã"
en_core_web_sm (em inglês equivalente "Send $100 to Matheus tomorrow"):
  MONEY "100", PERSON "Matheus", DATE "tomorrow"
pt_core_news_sm:
  PER "Envie R$"   (limite de entidade errado, devia ser só o valor em MONEY)
  PER "Matheus"    (correto)
  (nada de MONEY nem DATE: R$100 e amanhã não foram reconhecidos)
```

Suporte a português fica documentado como evolução (trocar para um modelo de PT
mais robusto, ou treinar/ajustar um pipeline próprio), não como algo pronto hoje.
Ver [ADR-0011](../docs/adr/0011-spacy-parametro-versionado.md).

### Segurança: sem autenticação neste MVP

Todas as rotas estão abertas, sem nenhuma chave ou login. Decisão consciente,
não lacuna esquecida: quem roda este projeto primeiro é um avaliador, na
própria máquina, sem exposição de rede: uma API key obrigatória só
adicionaria fricção ao fluxo de testar direto pelo Swagger. Backlog e
raciocínio completo (o que mudaria antes de qualquer deploy real) em
[ADR-0017](../docs/adr/0017-sem-autenticacao-no-mvp.md).

## Consumo (self-service, sem frontend custom)

Três formas de usar o mesmo serviço, todas reusando a mesma `NERService`
(ADR-0003), nenhuma lógica duplicada entre elas:

| Interface | Para quem | Quando usar |
|---|---|---|
| **API REST** (terminal/Swagger) | integrações automatizadas, scripts, o próprio recrutador testando | é a superfície "de produção" de verdade; tudo passa por aqui na prática |
| **MCP** (`extract_entities`) | um agente/LLM (ex.: assistente de PIX por WhatsApp) | quando quem chama é outro programa de IA, não um humano |
| **Gradio** (navegador) | uma pessoa explorando visualmente, sem escrever `curl`/JSON | demo opcional, não é a forma "oficial" de produção |

Ver [ADR-0013](../docs/adr/0013-sem-frontend-custom.md) para o racional de não
ter frontend custom (o Gradio é a única exceção, e é condicional).

### Usando pelo terminal (API REST)

Com a API no ar (`docker compose up --build`, porta `8000`):

```bash
# carregar/pré-aquecer um modelo (o default já vem carregado no boot)
curl -X POST http://localhost:8000/load/ \
  -H "Content-Type: application/json" \
  -d '{"model": "en_core_web_sm"}'

# extrair entidades (usa o modelo ativo se "model" não for informado)
curl -X POST http://localhost:8000/predict/ \
  -H "Content-Type: application/json" \
  -d '{"text": "Elon Musk visited Brazil in 2024."}'

# ver o histórico de predições já feitas (por qualquer interface: API, MCP, Gradio)
curl http://localhost:8000/list/

# ver qual modelo está ativo e quais estão carregados
curl http://localhost:8000/models/

# liveness + modelo ativo
curl http://localhost:8000/health/

# descarregar um modelo
curl -X DELETE http://localhost:8000/models/en_core_web_sm
```

Ou, sem decorar nenhum comando: abra
[localhost:8000/docs](http://localhost:8000/docs) (Swagger) e teste cada rota
clicando em "Try it out".

### Usando pelo Gradio (navegador)

Com o profile `demo` no ar (`docker compose --profile demo up --build`, porta
`7860`):

1. Abra [localhost:7860](http://localhost:7860)
2. Digite um texto no campo "Texto" (em inglês, ver seção "Idioma" acima)
3. Deixe o campo "Modelo" em branco (usa o modelo ativo) ou informe um nome
   explícito
4. Clique em **Submit**: as entidades aparecem destacadas com cores
   diferentes por tipo, direto em cima do texto

Cada predição feita aqui também aparece no `GET /list/` da API (mesmo
histórico) e nos dashboards do Grafana (mesmas métricas, ver seção de
observabilidade abaixo).

### MCP: o cenário do assistente de PIX por WhatsApp

O `mcp_server` expõe uma única tool, `extract_entities(text, model=None)`, que reusa
exatamente a mesma `NERService` da API REST (nenhuma lógica duplicada, ADR-0003).

O caso de uso pensado é o assistente de PIX do PicPay por WhatsApp: um usuário manda
uma mensagem em linguagem natural ("manda 50 pra Maria amanhã de manhã") e o agente
(LLM) chama `extract_entities` para identificar as entidades relevantes (PERSON,
MONEY, DATE) antes de montar a transação. O agente decide o que fazer com cada
entidade extraída; a tool só extrai, nunca interpreta intenção de pagamento.

Cache, histórico e lazy-load de modelo funcionam da mesma forma que na REST. O que
NÃO é compartilhado entre os dois transportes: o modelo carregado em memória e o
cache de predição são por processo (REST e MCP rodam em processos separados); só o
histórico em SQLite é compartilhado, porque é o mesmo arquivo em disco.

### Testando o MCP manualmente

O servidor MCP não sobe junto do `docker compose up` (ele fala stdio, não HTTP;
não faz sentido como container de longa duração da mesma forma que a API). Para
testar fora dos testes automatizados, há duas opções, ambas a partir do `.venv`
local (`pip install -e ".[dev]"` já criado nas fases anteriores):

**Opção 1: CLI do `fastmcp` (rápido, sem instalar nada extra)**

```bash
cd part2-ner-serving

# lista as tools disponíveis e o schema de cada uma
./.venv/Scripts/fastmcp.exe list --command "$(pwd)/.venv/Scripts/python.exe -m src.mcp_server.server" --input-schema

# chama extract_entities de verdade
./.venv/Scripts/fastmcp.exe call --command "$(pwd)/.venv/Scripts/python.exe -m src.mcp_server.server" \
  --target extract_entities --input-json '{"text": "Send $100 to John tomorrow."}'
```

Cada chamada sobe um processo novo (não é um servidor persistente): o modelo é
recarregado a cada `call` (~1s de warm-up), e cache/registry não sobrevivem entre
chamadas separadas. Só `data/history.db` persiste de verdade, porque é arquivo em
disco.

**Opção 2: MCP Inspector (UI visual no navegador)**

Exige `uv` (gerenciador de pacotes Python) e Node.js/`npx` instalados (o Inspector
em si é um pacote npm, baixado automaticamente na primeira execução).

```bash
# instalar uv uma vez, no próprio .venv do projeto
./.venv/Scripts/python.exe -m pip install uv

# subir o Inspector (adiciona o .venv/Scripts ao PATH desta sessão, pra o
# fastmcp achar o uv sem precisar instalar globalmente)
PATH="$(pwd)/.venv/Scripts:$PATH" ./.venv/Scripts/fastmcp.exe dev inspector -m src.mcp_server.server
```

O terminal imprime uma URL do tipo
`http://127.0.0.1:6274?MCP_INSPECTOR_API_TOKEN=<token>`. Abra essa URL completa
(com o token) no navegador: ela já vem conectada ao nosso servidor MCP, com
autenticação embutida na própria URL.

Como usar:
1. Na aba **Tools**, clique em `extract_entities`.
2. Preencha `text` (e opcionalmente `model`, ex.: `en_core_web_sm`) no formulário.
3. Clique em **Run Tool** e veja o resultado (entidades, labels, offsets)
   formatado na tela, sem precisar montar JSON na mão.

Esse processo fica rodando em background até você derrubá-lo (`Ctrl+C` no
terminal onde rodou, ou matar os processos `node` que o `npx` do Inspector
sobe). Serve só para exploração manual, não é parte do fluxo de deploy do
projeto.

## Pré-requisitos

Só Docker Desktop instalado e rodando, mais internet na primeira execução (para
baixar as imagens e o modelo spaCy, ver abaixo). Não precisa instalar Python nem
nenhuma biblioteca na sua máquina.

**Por que Docker é obrigatório aqui, não só recomendado:** `en_core_web_sm` (o
modelo spaCy usado por padrão) já vem pinado como dependência normal do
`pyproject.toml`, mas `spacy==3.7.5` também exige `click` disponível em tempo de
import, algo que uma resolução de dependências diferente (por exemplo, uma versão
mais nova de `typer` puxada por acaso) pode deixar faltando de forma nada óbvia. O
Dockerfile fixa uma combinação de versões já validada; sem ele, cada máquina
precisaria reproduzir manualmente esse ambiente exato.

**Se você rodar sem Docker (`pip install` local), isto vai dar problema:** sem os
pins exatos do `pyproject.toml`, o `pip` pode resolver uma versão de `typer` que não
traz mais `click` como dependência transitiva, e `import spacy` quebra com
`ModuleNotFoundError: No module named 'click'`, um erro que não aponta para nenhuma
linha do seu código. Detalhe completo em
[`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md#2-provider-de-ner-srcnercoreprovidersbasepy-srcnercoreprovidersspacy_providerpy).

## Como rodar

A partir desta pasta (`part2-ner-serving/`):

```bash
docker compose up --build
```

Sobe 4 serviços. Links locais (só funcionam com a stack no ar, na sua própria
máquina, não são endereços públicos):

| Serviço | Link | Observação |
|---|---|---|
| API: Swagger interativo | [localhost:8000/docs](http://localhost:8000/docs) | testar `/predict/`, `/load/` etc. direto pelo navegador |
| API: health check | [localhost:8000/health/](http://localhost:8000/health/) | reporta o modelo ativo |
| API: métricas Prometheus | [localhost:8000/metrics](http://localhost:8000/metrics) | texto cru, formato Prometheus |
| Prometheus (UI) | [localhost:9090](http://localhost:9090) | ver targets em Status → Targets, rodar queries PromQL |
| Grafana (dashboard) | [localhost:3000](http://localhost:3000) | login `admin` / `admin`; dashboard "NER Serving" já provisionado |
| Redis | `localhost:6379` | sem UI web; inspecionar via `redis-cli` dentro do container |

- **api**: `/health/` já reporta `en_core_web_sm` carregado (pré-baixado no
  build, ver seção "Docker" abaixo).
- **redis**: usado de verdade como backend de cache (`CACHE_BACKEND=redis` já
  ligado na `api` deste compose, com `maxmemory-policy allkeys-lru`
  configurado). Ver ADR-0004 e `docs/IMPLEMENTATION.md`.
- **prometheus**: já configurado para fazer scrape do `/metrics` da api (e do
  gradio, se o profile `demo` estiver no ar, ver abaixo).
- **grafana**: datasource do Prometheus e o dashboard "NER Serving" (latência
  p95, throughput, taxa de erro, cache hit rate) já provisionados sozinhos,
  sem import manual.

A partir da raiz do repositório, o equivalente é `make up-p2`.

Exemplo de uso (com a API já no ar):

```bash
curl -X POST http://localhost:8000/predict/ \
  -H "Content-Type: application/json" \
  -d '{"text": "Elon Musk visited Brazil in 2024."}'
```

O histórico de predições (`data/history.db`, fora do git) persiste entre execuções
via bind mount (`./data:/app/data`).

### Playground Gradio (opcional)

Um quinto serviço, **gradio: [localhost:7860](http://localhost:7860)**, fica
atrás de um profile do compose: não sobe com o `docker compose up --build`
normal, só com:

```bash
docker compose --profile demo up --build
```

Interface web simples (reusa a mesma `NERService`, ADR-0013) com um campo de
texto e outro de modelo opcional, mostrando as entidades reconhecidas destacadas
direto no texto. Para derrubar tudo, incluindo o `gradio`, use o mesmo profile:

```bash
docker compose --profile demo down
```

(`docker compose down` liso não derruba um serviço subido com `--profile demo`,
comportamento do próprio Docker Compose, não deste projeto.)

**O que o Gradio compartilha com a API REST.** O Gradio chama
`NERService.predict()` diretamente, em processo, sem passar pela rota
`/predict/` da API, mas compartilha as três coisas que importam: histórico
(`GET /list/` mostra predições feitas no Gradio, mesmo `data/history.db`),
cache (mesmo Redis) e métricas. O serviço `gradio` também expõe seu próprio
`/metrics`, e o `prometheus.yml` faz scrape dos dois (`api:8000` e
`gradio:7860`) sob o mesmo `job_name`. Como os painéis do Grafana somam as
séries sem filtrar por instância, uma predição feita na tela do Gradio aparece
nos mesmos gráficos que uma predição feita via `curl` na API.

Só os testes, na mesma imagem usada para servir a API:

```bash
docker build -t picpay-part2 .
docker run --rm picpay-part2 python -m pytest tests/ -v
```

A partir da raiz, `make test-p2`.

### Docker: pré-download do modelo default

`en_core_web_sm` é dependência normal do `pyproject.toml` (pinada por URL de wheel),
não uma etapa manual extra: `pip install` durante o build já o baixa, então o
container sobe usável e `/health/` já reporta o modelo ativo, sem precisar de rede
em tempo de execução. Trocar `DEFAULT_MODEL` para outro modelo (`en_core_web_md`,
por exemplo) ou chamar `/load/` com um modelo diferente em runtime exige rede
naquele momento, porque só o `en_core_web_sm` vem embutido na imagem. Tradeoff
documentado: imagem maior (modelo embutido) em troca de a API já subir pronta,
offline.

## Observabilidade: Prometheus e Grafana

### O que é a API e o que é o Gradio, na prática

Vale reforçar essa distinção porque os dois aparecem juntos nos gráficos: a
**api** (`:8000`) é o serviço de produção de verdade, pensado para ser chamado
por outros programas (a REST oficial, ADR-0008). O **gradio** (`:7860`) é um
playground opcional (ADR-0013) para uma pessoa testar visualmente, rodando o
mesmo código (`NERService`) num processo separado. Nos gráficos abaixo, cada
um aparece como uma métrica com um label `instance` diferente
(`api:8000` ou `gradio:7860`), mas os painéis somam os dois juntos por padrão.

### Passo a passo: vendo os dashboards no Grafana

1. Suba a stack (`docker compose up --build`, ou `--profile demo` para incluir
   o Gradio também).
2. Faça algumas predições primeiro (via `curl`, Swagger ou Gradio): os
   painéis não têm nada para mostrar antes disso.
3. Abra [localhost:3000](http://localhost:3000), login `admin` / `admin`.
4. Menu lateral → **Dashboards** → **NER Serving** (já provisionado sozinho,
   não precisa importar nada).

O dashboard tem 4 painéis (definidos em
[`grafana/dashboards/ner.json`](grafana/dashboards/ner.json), versionado como
código, ADR-0014):

| Painel | O que mostra | Como interpretar |
|---|---|---|
| **Latência p95 (/predict/)** | 95% das predições respondem em até X segundos | quanto menor, melhor; picos indicam modelo carregando ou CPU sob pressão |
| **Throughput (predições/s)** | quantas predições por segundo, por modelo | mostra volume de uso ao longo do tempo |
| **Taxa de erro HTTP (5xx)** | proporção de respostas com erro de servidor | deveria ficar em 0% na maior parte do tempo; um pico indica algo quebrando |
| **Cache hit rate** | proporção de predições respondidas pelo cache (Redis), sem rodar o spaCy de novo | mais alto é melhor (menos CPU gasta); sobe quando o mesmo texto se repete |

Os gráficos só mostram dado depois que o Prometheus faz pelo menos um scrape
(a cada 15s, ver `prometheus/prometheus.yml`) depois de uma predição real.

### Prometheus: a UI e a métrica `up`

Em [localhost:9090](http://localhost:9090), a caixa de busca no topo espera
uma query PromQL: a tela inicial ("No data queried yet") é normal, não é
erro. Duas queries úteis para começar:

- `up`: uma métrica que o próprio Prometheus cria para cada alvo que ele
  monitora. Valor `1` significa "consegui fazer scrape desse alvo agora
  mesmo"; `0` significa "não consegui" (alvo fora do ar, ou não existe ainda,
  como o `gradio` quando o profile `demo` não está no ar).
- `ner_predictions_total`: o contador bruto por trás do painel de throughput.

Menu **Status → Targets** mostra a mesma informação de forma visual: cada
linha é um alvo configurado (`api:8000`, `gradio:7860`), com o estado
`UP`/`DOWN` e quando foi o último scrape.

### Onde esses dados ficam guardados (e por que não persistem hoje)

Este é um MVP: só o histórico de predições foi projetado para sobreviver a um
restart. Métricas e cache, não, e isso é intencional, não esquecimento.

| Dado | Onde fica | Sobrevive a `docker compose down`? | Por quê |
|---|---|---|---|
| Histórico de predições | `data/history.db` (SQLite), bind mount `./data:/app/data` | **Sim** | é o único dado que faz sentido auditar depois; por isso ganhou um volume real desde a fase 2.2 |
| Métricas do Prometheus | dentro do container do `prometheus`, sem volume mapeado | **Não** | simplicidade de MVP: nenhum painel de histórico de longo prazo era exigido, só o dashboard "ao vivo" |
| Dashboards/datasource do Grafana | arquivos em `grafana/` (montados read-only) | Sim, mas porque são reconstruídos a cada boot a partir do código, não porque foram salvos em algum lugar | dashboard como código (ADR-0014): não precisa persistir estado, porque o estado é o próprio arquivo `.json` versionado no git |
| Cache (Redis) | memória do container `redis`, sem volume de disco (`--maxmemory`, sem RDB/AOF) | **Não** | é cache: perder o conteúdo ao reiniciar é esperado e correto, o dado real (a predição) já está no `history.db` |

**Em produção**, a peça que mudaria de verdade é o Prometheus: normalmente se
adiciona um volume (`prometheus_data:/prometheus`) para as métricas
sobreviverem a um restart do container, e a partir de um certo volume de
dados, uma solução de armazenamento de longo prazo (Thanos, Cortex, Mimir, ou
um Prometheus gerenciado) para reter meses de histórico em vez de só os dias
que cabem no disco de uma instância única. O Grafana continuaria sem precisar
de volume próprio (dashboard como código já é a prática recomendada mesmo em
produção); o Redis também continuaria sem persistência de disco, porque essa
é a natureza de um cache, com ou sem MVP.

### Redis: para que serve, e o que ele realmente muda aqui

`RedisCache` (ADR-0004) guarda o resultado de uma predição
(`{modelo, texto} → entidades`), para não rodar o spaCy de novo quando a
mesma combinação aparece de novo. Vale ser honesto sobre o impacto real: com
uma réplica só da API (este ambiente local), o Redis não traz ganho de
desempenho sobre o cache em memória que existia antes dele (`InMemoryLRUCache`):
na real é um pouco mais lento, por causa do round-trip de rede. O ganho real
apareceria com **múltiplas réplicas da API rodando atrás de um load
balancer**: cada réplica com cache em memória isolado recalcularia a mesma
predição de novo; com Redis compartilhado, um cache hit em qualquer réplica
beneficia todas as outras. Implementamos e validamos o Redis para provar que
essa evolução (documentada desde o início no ADR-0004) funciona de verdade,
não só no papel.

## Status

Ingestão de texto, provider abstrato (spaCy), registry de modelos, cache LRU e
Redis (as duas implementações de `PredictionCache`, selecionáveis por
`CACHE_BACKEND`), histórico em SQLite, orquestração (`NERService`), API REST
completa, servidor MCP (`extract_entities`), playground Gradio opcional e
observabilidade (logs JSON, `/health`, `/metrics`, Prometheus + Grafana
provisionados) implementados e testados (98 testes no total, 93 passando + 5
pulados sem Redis local, todos os 98 passam com Redis acessível; ambiente
oficial de validação é o Docker/Linux, ver
[ADR-0016](../docs/adr/0016-docker-compose-ambiente-oficial-parte2.md)). `docker
compose up --build` sobe os 4 serviços centrais de ponta a ponta com
`CACHE_BACKEND=redis` já ativo; `docker compose --profile demo up --build` soma
o playground Gradio. Validado manualmente com predições reais fluindo por REST,
MCP e Gradio até Redis (cache), Prometheus e Grafana: o critério de pronto da
Parte 2 está fechado. Terraform para a Parte 2 (ADR-0010) e suporte robusto a
português (ADR-0011) seguem como evolução futura documentada, fora do escopo
desta entrega.
Detalhe completo em [`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md).
