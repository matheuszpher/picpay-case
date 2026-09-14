# Detalhes técnicos: Parte 2 (NER Serving)

Este documento reúne o "por quê" das coisas: decisões de design, limitações
conhecidas e passo a passo de exploração manual (MCP, observabilidade). Para
como/por quê de cada módulo de código, ver
[`docs/IMPLEMENTATION.md`](IMPLEMENTATION.md). Para decisões de arquitetura
formais, ver os [ADRs do projeto](../../docs/adr/).

## Índice

- [Idioma: por que texto em português não extrai nada por padrão](#idioma-por-que-texto-em-português-não-extrai-nada-por-padrão)
- [Segurança: sem autenticação neste MVP](#segurança-sem-autenticação-neste-mvp)
- [As três formas de consumir o serviço](#as-três-formas-de-consumir-o-serviço)
- [MCP: cenário e como testar manualmente](#mcp-cenário-e-como-testar-manualmente)
- [Playground Gradio: detalhes](#playground-gradio-detalhes)
- [Docker: pré-download do modelo default](#docker-pré-download-do-modelo-default)
- [Observabilidade: Prometheus e Grafana](#observabilidade-prometheus-e-grafana)
- [Redis: para que serve, e o que ele realmente muda aqui](#redis-para-que-serve-e-o-que-ele-realmente-muda-aqui)

## Idioma: por que texto em português não extrai nada por padrão

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
Ver [ADR-0011](../../docs/adr/0011-spacy-parametro-versionado.md).

## Segurança: sem autenticação neste MVP

Todas as rotas estão abertas, sem nenhuma chave ou login. Decisão consciente,
não lacuna esquecida: quem roda este projeto primeiro é um avaliador, na
própria máquina, sem exposição de rede: uma API key obrigatória só
adicionaria fricção ao fluxo de testar direto pelo Swagger. Backlog e
raciocínio completo (o que mudaria antes de qualquer deploy real) em
[ADR-0017](../../docs/adr/0017-sem-autenticacao-no-mvp.md).

## As três formas de consumir o serviço

Todas reusam a mesma `NERService` (ADR-0003), nenhuma lógica duplicada entre
elas:

| Interface | Para quem | Quando usar |
|---|---|---|
| **API REST** (terminal/Swagger) | integrações automatizadas, scripts, o próprio avaliador testando | é a superfície "de produção" de verdade; tudo passa por aqui na prática |
| **MCP** (`extract_entities`) | um agente/LLM (ex.: assistente de PIX por WhatsApp) | quando quem chama é outro programa de IA, não um humano |
| **Gradio** (navegador) | uma pessoa explorando visualmente, sem escrever `curl`/JSON | demo opcional, não é a forma "oficial" de produção |

Ver [ADR-0013](../../docs/adr/0013-sem-frontend-custom.md) para o racional de não
ter frontend custom (o Gradio é a única exceção, e é condicional).

## MCP: cenário e como testar manualmente

O `mcp_server` expõe uma única tool, `extract_entities(text, model=None)`, que
reusa exatamente a mesma `NERService` da API REST (nenhuma lógica duplicada,
ADR-0003).

O caso de uso pensado é o assistente de PIX do PicPay por WhatsApp: um usuário
manda uma mensagem em linguagem natural ("manda 50 pra Maria amanhã de manhã") e
o agente (LLM) chama `extract_entities` para identificar as entidades relevantes
(PERSON, MONEY, DATE) antes de montar a transação. O agente decide o que fazer
com cada entidade extraída; a tool só extrai, nunca interpreta intenção de
pagamento.

Cache, histórico e lazy-load de modelo funcionam da mesma forma que na REST. O
que NÃO é compartilhado entre os dois transportes: o modelo carregado em
memória e o cache de predição são por processo (REST e MCP rodam em processos
separados); só o histórico em SQLite é compartilhado, porque é o mesmo arquivo
em disco.

### Testando o MCP manualmente

O servidor MCP não sobe junto do `docker compose up` (ele fala stdio, não HTTP;
não faz sentido como container de longa duração da mesma forma que a API). Para
testar fora dos testes automatizados, há três opções, todas a partir do `.venv`
local (`pip install -e ".[dev]"`).

**Opção 1: `scripts/test_mcp.py` (recomendada: funciona igual em qualquer terminal)**

Chama a tool `extract_entities` direto em processo, via `fastmcp.Client(mcp)`
(cliente em memória, sem subir um subprocesso via stdio). O único argumento na
linha de comando é o texto puro, sem JSON nem aspas aninhadas:

**Linux:**

```bash
./.venv/bin/python scripts/test_mcp.py 'Can you send $45 to Michael on June 3?'
```

**macOS:**

```bash
./.venv/bin/python scripts/test_mcp.py 'Can you send $45 to Michael on June 3?'
```

**Windows (PowerShell):**

```powershell
.\.venv\Scripts\python.exe scripts\test_mcp.py 'Can you send $45 to Michael on June 3?'
```

Esse comando existe justamente por causa da Opção 2 abaixo: `fastmcp call
--input-json` exige aspas aninhadas na linha de comando (`{"text": "..."}`), e o
Windows PowerShell escapa essas aspas de forma diferente entre a versão 5.1 e a
7.x (variável interna `$PSNativeCommandArgumentPassing`), então o mesmo comando
pode funcionar numa máquina e falhar em outra com um erro de parsing de JSON.
Como não dá para garantir qual versão de PowerShell quem for rodar este projeto
vai ter, a Opção 1 evita o problema inteiro: só passa um argumento de texto
simples, sem aspas internas, para qualquer versão de shell.

**Opção 2: CLI do `fastmcp` (mais rápida para explorar, mas frágil no Windows)**

Útil para listar as tools e ver o schema, sem instalar nada extra:

**Linux:**

```bash
./.venv/bin/fastmcp list --command "$(pwd)/.venv/bin/python -m src.mcp_server.server" --input-schema
```

**macOS:**

```bash
./.venv/bin/fastmcp list --command "$(pwd)/.venv/bin/python -m src.mcp_server.server" --input-schema
```

**Windows (PowerShell):**

```powershell
$py = "$(Get-Location)\.venv\Scripts\python.exe" -replace '\\','/'
.\.venv\Scripts\fastmcp.exe list --command "$py -m src.mcp_server.server" --input-schema
```

(o `-replace '\\','/'` é necessário: o parser de `--command` do fastmcp não lida bem com
barras invertidas do Windows nesse argumento específico, então convertemos para barras
normais antes de montar o comando. Isso é estável entre versões de PowerShell; o problema
de aspas descrito acima é só no `--input-json` do `call`, por isso a Opção 1 existe para
chamar a tool de verdade.)

Cada chamada da CLI sobe um processo novo (não é um servidor persistente): o modelo é
recarregado a cada `call` (~1s de warm-up), e cache/registry não sobrevivem entre
chamadas separadas. Só `data/history.db` persiste de verdade, porque é arquivo em
disco. Isso vale igualmente para `scripts/test_mcp.py` (Opção 1).

**Opção 3: MCP Inspector (UI visual no navegador)**

Exige `uv` (gerenciador de pacotes Python) e Node.js/`npx` instalados (o Inspector
em si é um pacote npm, baixado automaticamente na primeira execução).

**Linux:**

```bash
# instalar uv uma vez, no próprio .venv do projeto
./.venv/bin/python -m pip install uv

# subir o Inspector (adiciona o .venv/bin ao PATH desta sessão, pra o
# fastmcp achar o uv sem precisar instalar globalmente)
PATH="$(pwd)/.venv/bin:$PATH" ./.venv/bin/fastmcp dev inspector -m src.mcp_server.server
```

**macOS:**

```bash
# instalar uv uma vez, no próprio .venv do projeto
./.venv/bin/python -m pip install uv

# subir o Inspector (adiciona o .venv/bin ao PATH desta sessão, pra o
# fastmcp achar o uv sem precisar instalar globalmente)
PATH="$(pwd)/.venv/bin:$PATH" ./.venv/bin/fastmcp dev inspector -m src.mcp_server.server
```

**Windows (PowerShell):**

```powershell
# instalar uv uma vez, no próprio .venv do projeto
.\.venv\Scripts\python.exe -m pip install uv

# subir o Inspector (adiciona o .venv\Scripts ao PATH desta sessão, pra o
# fastmcp achar o uv sem precisar instalar globalmente)
$env:PATH = "$(Get-Location)\.venv\Scripts;$env:PATH"
.\.venv\Scripts\fastmcp.exe dev inspector -m src.mcp_server.server
```

O terminal imprime uma URL do tipo
`http://127.0.0.1:6274?MCP_INSPECTOR_API_TOKEN=<token>`. Abra essa URL completa
(com o token) no navegador: ela já vem conectada ao servidor MCP, com
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

## Playground Gradio: detalhes

O Gradio chama `NERService.predict()` diretamente, em processo, sem passar pela
rota `/predict/` da API, mas compartilha as três coisas que importam: histórico
(`GET /list/` mostra predições feitas no Gradio, mesmo `data/history.db`),
cache (mesmo Redis) e métricas. O serviço `gradio` também expõe seu próprio
`/metrics`, e o `prometheus.yml` faz scrape dos dois (`api:8000` e
`gradio:7860`) sob o mesmo `job_name`. Como os painéis do Grafana somam as
séries sem filtrar por instância, uma predição feita na tela do Gradio aparece
nos mesmos gráficos que uma predição feita via `curl` na API.

Como usar:
1. Abra [localhost:7860](http://localhost:7860)
2. Digite um texto no campo "Texto" (em inglês, ver seção de idioma acima)
3. Deixe o campo "Modelo" em branco (usa o modelo ativo) ou informe um nome
   explícito
4. Clique em **Submit**: as entidades aparecem destacadas com cores
   diferentes por tipo, direto em cima do texto

`docker compose down` liso não derruba o serviço `gradio`, que sobe atrás de um
profile (`--profile demo`); é preciso `docker compose --profile demo down` para
derrubar tudo, incluindo ele.

## Docker: pré-download do modelo default

`en_core_web_sm` é dependência normal do `pyproject.toml` (pinada por URL de wheel),
não uma etapa manual extra: `pip install` durante o build já o baixa, então o
container sobe usável e `/health/` já reporta o modelo ativo, sem precisar de rede
em tempo de execução. Trocar `DEFAULT_MODEL` para outro modelo (`en_core_web_md`,
por exemplo) ou chamar `/load/` com um modelo diferente em runtime exige rede
naquele momento, porque só o `en_core_web_sm` vem embutido na imagem. Tradeoff
documentado: imagem maior (modelo embutido) em troca de a API já subir pronta,
offline.

**Por que Docker é obrigatório aqui, não só recomendado:** `en_core_web_sm` já
vem pinado como dependência normal do `pyproject.toml`, mas `spacy==3.7.5`
também exige `click` disponível em tempo de import, algo que uma resolução de
dependências diferente (por exemplo, uma versão mais nova de `typer` puxada
por acaso) pode deixar faltando de forma nada óbvia. O Dockerfile fixa uma
combinação de versões já validada; sem ele, cada máquina precisaria reproduzir
manualmente esse ambiente exato. Sem os pins exatos do `pyproject.toml`,
`import spacy` pode quebrar com `ModuleNotFoundError: No module named 'click'`,
um erro que não aponta para nenhuma linha do seu código. Detalhe completo em
[`docs/IMPLEMENTATION.md`](IMPLEMENTATION.md#2-provider-de-ner-srcnercoreprovidersbasepy-srcnercoreprovidersspacy_providerpy).

## Observabilidade: Prometheus e Grafana

### API vs. Gradio nos gráficos

Vale reforçar essa distinção porque os dois aparecem juntos nos gráficos: a
**api** (`:8000`) é o serviço de produção de verdade, pensado para ser chamado
por outros programas (a REST oficial, ADR-0008). O **gradio** (`:7860`) é um
playground opcional (ADR-0013) para uma pessoa testar visualmente, rodando o
mesmo código (`NERService`) num processo separado. Nos gráficos, cada um
aparece como uma métrica com um label `instance` diferente (`api:8000` ou
`gradio:7860`), mas os painéis somam os dois juntos por padrão.

### Passo a passo: vendo os dashboards no Grafana

1. Suba a stack (`docker compose --profile demo up --build`).
2. Faça algumas predições primeiro (via `curl`, Swagger ou Gradio): os
   painéis não têm nada para mostrar antes disso.
3. Abra [localhost:3000](http://localhost:3000), login `admin` / `admin`.
4. Menu lateral → **Dashboards** → **NER Serving** (já provisionado sozinho,
   não precisa importar nada).

O dashboard tem 4 painéis (definidos em
[`grafana/dashboards/ner.json`](../grafana/dashboards/ner.json), versionado como
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

## Redis: para que serve, e o que ele realmente muda aqui

`RedisCache` (ADR-0004) guarda o resultado de uma predição
(`{modelo, texto} -> entidades`), para não rodar o spaCy de novo quando a
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
