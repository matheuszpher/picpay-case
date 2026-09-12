# Architecture Decision Records: PicPay ML Case

Cada ADR segue o formato: **Contexto** (o problema) → **Decisão** (o que foi escolhido) →
**Alternativas** (o que foi considerado e descartado) → **Consequências** (o tradeoff real, bom
e ruim).

## Índice

| # | Decisão | Status |
|---|---|---|
| [0001](0001-repositorio-unico.md) | Um único repositório Git | Aceito |
| [0002](0002-provider-abstrato-ner.md) | Abstração do fornecedor de NER (provider pattern) | Aceito |
| [0003](0003-core-lib-transportes-finos.md) | Core como lib; REST e MCP como transportes finos | Aceito |
| [0004](0004-cache-predicao-lru-redis.md) | Cache de predição (LRU → Redis) | Aceito |
| [0005](0005-historico-sqlite.md) | Histórico em SQLite (Postgres-ready) + índice | Aceito |
| [0006](0006-ingestao-async-cache-bronze.md) | Ingestão async + cache bronze (fora do Spark) | Aceito |
| [0007](0007-medallion-bronze-silver-gold.md) | Medallion (bronze/silver/gold) | Aceito |
| [0008](0008-fastapi.md) | FastAPI | Aceito |
| [0009](0009-observabilidade-aplicacao.md) | Observabilidade de aplicação (logs/health/metrics) | Aceito |
| [0010](0010-terraform-aws-ecs-fargate.md) | Terraform → AWS ECS Fargate | Aceito |
| [0011](0011-spacy-parametro-versionado.md) | Modelo spaCy como parâmetro versionado | Aceito |
| [0012](0012-sem-plataforma-unica.md) | Sem plataforma única (desacoplamento proposital) | Aceito |
| [0013](0013-sem-frontend-custom.md) | Sem frontend custom (+ Gradio opcional) | Aceito |
| [0014](0014-prometheus-grafana.md) | Prometheus + Grafana | Aceito |
| [0015](0015-spark-local-notebook-portavel.md) | Ambiente Spark: local dockerizado + notebook portável | Aceito |
| [0016](0016-docker-compose-ambiente-oficial-parte2.md) | Docker Compose como ambiente oficial da Parte 2 | Aceito |
| [0017](0017-sem-autenticacao-no-mvp.md) | Sem autenticação neste MVP (API key fica em backlog) | Aceito |
