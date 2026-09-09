# ADR-0009: Observabilidade no nível da aplicação (logs estruturados, /health, /metrics)

**Status.** Aceito.

## Contexto

Um serviço "de produção" precisa ser operável: dá pra ver o que aconteceu, se está vivo e como
está performando. O case pede logs estruturados explicitamente.

## Decisão

Logs em JSON com request id, modelo e latência; `/health` (liveness + se o modelo está pronto);
`/metrics` no formato Prometheus (contador de predições, histograma de latência, cache hit/miss).
Monitorar o serviço é diferente de monitorar o modelo: esta ADR cobre o serviço; drift do modelo
é outro nível, fora de escopo aqui (ver [ADR-0014](0014-prometheus-grafana.md) para o detalhe de
Prometheus/Grafana).

## Alternativas

- *Só `print`/log de texto:* difícil de consultar e agregar.
- *Sem health/metrics:* o serviço vira caixa-preta; sem base para autoscaling ou alerta.

## Consequências

- (+) Operável e pronto para orquestradores (health para readiness/liveness; métricas para scrape).
- (−) Esforço inicial de instrumentação.
