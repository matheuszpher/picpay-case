# ADR-0014: Stack de observabilidade com Prometheus + Grafana

**Status.** Aceito.

## Contexto

Além dos logs e do `/metrics` (ver [ADR-0009](0009-observabilidade-aplicacao.md)), quero uma
visão operacional visível e próxima de produção.

## Decisão

Subir Prometheus (scrape do `/metrics`) e Grafana via docker-compose, com um dashboard
versionado como código (JSON) mostrando latência p95, throughput, taxa de erro e cache hit/miss.

## Alternativas

- *Só expor `/metrics` sem stack:* mostra instrumentação, mas não a visão agregada.
- *Serviço gerenciado (Datadog/CloudWatch):* fora do escopo local e custo.

## Consequências

- (+) Visão de produção de verdade, reproduzível localmente, dashboard como código (versionável).
- (+) Fala a língua de operação, reaproveita experiência real de MLOps.
- (−) Mais dois contêineres no compose; dashboard a manter.
