# Parte 2 — NER Serving (plano online)

Serviço de NER com spaCy atrás de um provider abstrato. Toda a lógica vive numa lib
reutilizável (`nercore`), exposta por dois transportes finos — REST (FastAPI) e MCP — sem
duplicação. Cache de predição, registry de versões de modelo e histórico persistido.
Observabilidade com logs estruturados, `/health`, `/metrics` e dashboards Grafana. Projeto
autossuficiente — roda sozinho, sem depender da Parte 1.

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
├── pyproject.toml
├── src/
│   ├── nercore/            # a LIB (core reutilizável)
│   │   ├── providers/
│   │   │   ├── base.py         # interface NERProvider (abstrata)
│   │   │   └── spacy_provider.py
│   │   ├── registry.py     # versões carregadas + versão ativa
│   │   ├── history.py      # persistência do histórico (SQLite)
│   │   ├── cache.py        # LRU -> Redis (mesma interface)
│   │   ├── service.py      # orquestra provider + registry + cache + history
│   │   └── schemas.py      # Pydantic (Entity, PredictRequest, ...)
│   ├── api/                 # transporte REST (FastAPI) — fino
│   │   └── main.py
│   └── mcp_server/          # transporte MCP — fino, reusa nercore.service
│       └── server.py
├── tests/
├── Dockerfile
└── docker-compose.yml       # api + redis
```

## Endpoints

Obrigatórios: `POST /load/`, `POST /predict/`, `GET /list/`.
Sugeridos: `GET /models/`, `GET /health/`, `DELETE /models/{version}`.
Extra de produção: `GET /metrics` (Prometheus).

## Consumo (self-service, sem frontend custom)

Swagger UI (`/docs`), MCP (para agentes — cenário do assistente de PIX por WhatsApp),
notebook/curl e, opcionalmente ao final, um playground Gradio. Ver
[ADR-0013](../docs/adr/0013-sem-frontend-custom.md).

## Como rodar

> Ainda não implementado — esqueleto do projeto (Fase 0).

```bash
docker compose up
```

## Status

Esqueleto — sem lógica implementada ainda.
