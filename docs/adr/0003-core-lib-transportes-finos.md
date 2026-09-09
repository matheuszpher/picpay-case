# ADR-0003: Core como biblioteca; REST e MCP como transportes finos

**Status.** Aceito.

## Contexto

O serviço precisa ser consumível como API REST e, segundo o contexto do PicPay, também como MCP
(para um agente/LLM, ex.: o assistente de PIX). O risco é duplicar a lógica em dois lugares.

## Decisão

Toda a lógica vive em uma biblioteca (`nercore`: service, providers, registry, cache, history).
REST (FastAPI) e MCP (fastmcp) são apenas *transportes* finos que chamam o mesmo `nercore.service`.

## Alternativas

- *Implementar a lógica dentro da API e o MCP chamar a API por HTTP:* adiciona um salto de rede,
  acopla o MCP à disponibilidade do servidor HTTP e duplica validação.
- *Dois serviços independentes:* duplicação de código e de manutenção.

## Consequências

- (+) Zero duplicação: uma correção no core vale para REST e MCP.
- (+) Responde ao "microserviço e/ou lib" do enunciado, é os dois: uma lib exposta por dois
  canais.
- (−) Exige desenhar bem a fronteira do core (o que é domínio vs o que é transporte).
