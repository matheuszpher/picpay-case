# ADR-0013: Sem frontend custom; consumo via Swagger/MCP/notebook (+ Gradio opcional)

**Status.** Aceito.

## Contexto

A vaga é de ML Engineer (backend/plataforma). Uma UI custom não é pedida nem avaliada, e mal
feita sinaliza prioridade errada e consome tempo dos itens que contam.

## Decisão

Não construir frontend custom. As superfícies de consumo são: Swagger UI (grátis do FastAPI), MCP
(para agentes), notebook/curl (exemplos) e, **opcionalmente e por último**, um playground em
Gradio/Streamlit: Python puro, ~40 linhas, reusando `nercore.service`, marcado como demo, sob
três condições: só depois de tudo pronto e testado, claramente opcional, e sem roubar tempo de
CI/IaC/testes. Alternativa de custo zero: um GIF de demo no README.

## Alternativas

- *SPA em React/Vue:* fora do escopo da vaga, alto custo, expõe a julgamento de frontend.

## Consequências

- (+) Tempo concentrado no que a vaga avalia; consumo coberto por canais padrão e profissionais.
- (+) Gradio (se entrar) reforça self-service com esforço mínimo e on-brand para ML.
- (−) Sem "tela bonita" própria, compensado pelo Swagger e por um possível GIF.
