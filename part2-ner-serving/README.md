# Parte 2: NER Serving

<img src="assets/picpay-logo.png" alt="PicPay" width="180">

Microsserviço de reconhecimento de entidades nomeadas (NER) com spaCy, rodando
localmente via Docker. Documentação técnica completa (decisões de arquitetura,
limitações conhecidas, observabilidade em detalhe) em
[`docs/DETALHES_TECNICOS.md`](docs/DETALHES_TECNICOS.md).

## 1. Estrutura de pastas

```
part2-ner-serving/
├── docs/
│   ├── IMPLEMENTATION.md      # registro de implementação (como/por quê por módulo)
│   └── DETALHES_TECNICOS.md   # por quês, limitações, passo a passo de exploração
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
├── scripts/
│   └── test_mcp.py          # chama extract_entities via MCP em processo, sem aspas na linha de comando
├── prometheus/
│   └── prometheus.yml
├── grafana/
│   ├── dashboards/ner.json          # dashboard versionado como código
│   └── provisioning/                # datasource + dashboard provisionados sozinhos
├── Dockerfile
└── docker-compose.yml       # api + redis + prometheus + grafana (+ gradio opcional)
```

## 2. O que foi entregue

### Requisitos obrigatórios do case

| Endpoint | Descrição |
|---|---|
| `POST /load/` | Carrega (baixa se preciso) um modelo e o marca como ativo |
| `POST /predict/` | Extrai entidades de um texto (ex.: `"Can you send $45 to Michael on June 3?"` → `MONEY: 45`, `PERSON: Michael`, `DATE: June 3`) |
| `GET /list/` | Histórico de predições já feitas |

### Requisitos sugeridos do case

| Endpoint | Descrição |
|---|---|
| `GET /models/` | Modelo ativo + lista de modelos carregados |
| `GET /health/` | Liveness + qual modelo está ativo |
| `DELETE /models/{version}` | Descarrega um modelo |

### Boas práticas pedidas pelo case

- **Organização e separação de responsabilidades**: lógica de negócio isolada numa lib (`nercore`), reutilizada por dois transportes finos (REST e MCP), sem duplicação.
- **Tratamento de erros**: hierarquia de exceções de domínio mapeada para respostas HTTP consistentes (`{error, detail}`), inclusive erros de validação.
- **Logs estruturados**: logging em JSON, com id de requisição.
- **Versionamento claro**: registry de modelos carregados, com um modelo ativo por vez, troca explícita via `/load/`.
- **README**: este documento + documentação técnica detalhada.

### Extras entregues (além do case)

- **Docker Compose completo**: sobe API, cache, métricas e dashboards com um único comando.
- **Servidor MCP** (`extract_entities`): a mesma lógica de NER exposta como tool para um agente/LLM, não só como API REST.
- **Playground Gradio** (opcional): interface web para testar sem escrever `curl`/JSON.
- **Observabilidade com Prometheus e Grafana**: métricas de latência, throughput, taxa de erro e cache hit rate, com dashboard já provisionado.
- **Cache de predição em Redis**, com fallback em memória (LRU) selecionável por variável de ambiente.
- **Suite de testes automatizados** (unitários e de integração) e pipeline de CI (lint, format, testes).
- **ADRs**: decisões de arquitetura documentadas (ver [`docs/adr/`](../docs/adr/)).

## 3. Como executar

Pré-requisito único: Docker Desktop instalado e rodando (não precisa instalar Python nem nenhuma biblioteca na sua máquina). A partir desta pasta (`part2-ner-serving/`):

**Linux:**

```bash
docker compose --profile demo up --build
```

**macOS:**

```bash
docker compose --profile demo up --build
```

**Windows (PowerShell):**

```powershell
docker compose --profile demo up --build
```

Esse comando sobe todos os 5 serviços de uma vez, incluindo o playground Gradio (que fica atrás de um profile do compose e não sobe com um `docker compose up --build` sem o `--profile demo`).

Serviços e links (com a stack no ar):

| Serviço | Link |
|---|---|
| API: Swagger interativo | [localhost:8000/docs](http://localhost:8000/docs) |
| API: health check | [localhost:8000/health/](http://localhost:8000/health/) |
| API: métricas Prometheus | [localhost:8000/metrics](http://localhost:8000/metrics) |
| Prometheus (UI) | [localhost:9090](http://localhost:9090) |
| Grafana (dashboard) | [localhost:3000](http://localhost:3000) (login `admin`/`admin`) |
| Gradio (playground) | [localhost:7860](http://localhost:7860) |

No Prometheus, a tela inicial vem vazia (é normal): digite `up` na caixa de busca e clique
em **Execute** para ver os alvos monitorados.

Forma mais fácil de testar: é aconselhável começar pelo
[playground Gradio](http://localhost:7860), sem escrever nenhum comando. Basta abrir o
link, digitar um texto e clicar em **Submit** para ver as entidades reconhecidas
destacadas direto na tela.

Testando `/predict/` pelo terminal (com a API no ar):

**Linux:**

```bash
curl -X POST http://localhost:8000/predict/ \
  -H "Content-Type: application/json" \
  -d '{"text": "Can you send $45 to Michael on June 3?"}'
```

**macOS:**

```bash
curl -X POST http://localhost:8000/predict/ \
  -H "Content-Type: application/json" \
  -d '{"text": "Can you send $45 to Michael on June 3?"}'
```

**Windows (PowerShell):**

```powershell
curl.exe -X POST http://localhost:8000/predict/ `
  -H "Content-Type: application/json" `
  -d '{"text": "Can you send $45 to Michael on June 3?"}'
```

Ou, sem decorar nenhum comando, abra [localhost:8000/docs](http://localhost:8000/docs) (Swagger) e teste cada rota direto pelo navegador, em qualquer sistema operacional.

### Testando o MCP

O servidor MCP não sobe junto do `docker compose up` (ele fala stdio, não HTTP). Para testar
manualmente, a partir de um `.venv` local (`pip install -e ".[dev]"`), use o script
[`scripts/test_mcp.py`](scripts/test_mcp.py): ele chama a tool `extract_entities` direto em
processo (sem depender de escapar JSON na linha de comando, algo que varia entre versões do
PowerShell no Windows):

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

Passo a passo completo de outras formas de testar (CLI do `fastmcp`, MCP Inspector: uma UI
visual no navegador) em
[`docs/DETALHES_TECNICOS.md`](docs/DETALHES_TECNICOS.md#testando-o-mcp-manualmente).

Para rodar os testes automatizados (mesma imagem usada para servir a API):

**Linux:**

```bash
docker build -t picpay-part2 .
docker run --rm picpay-part2 python -m pytest tests/ -v
```

**macOS:**

```bash
docker build -t picpay-part2 .
docker run --rm picpay-part2 python -m pytest tests/ -v
```

**Windows (PowerShell):**

```powershell
docker build -t picpay-part2 .
docker run --rm picpay-part2 python -m pytest tests/ -v
```

Para derrubar a stack (todos os 5 serviços, incluindo o Gradio):

**Linux:**

```bash
docker compose --profile demo down
```

**macOS:**

```bash
docker compose --profile demo down
```

**Windows (PowerShell):**

```powershell
docker compose --profile demo down
```

---

Para entender o porquê de cada decisão (idioma, segurança, observabilidade em
detalhe, o cenário do MCP, testes manuais do MCP, Redis), ver
[`docs/DETALHES_TECNICOS.md`](docs/DETALHES_TECNICOS.md). Para o registro de
implementação módulo a módulo, ver [`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md).
