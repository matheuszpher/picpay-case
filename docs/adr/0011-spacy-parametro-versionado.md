# ADR-0011: Modelo spaCy como parâmetro versionado

**Status.** Aceito.

## Contexto

O case usa modelos spaCy (`en_core_web_sm/md/lg`) que trocam precisão por custo/latência.
Diferentes consumidores têm necessidades diferentes.

## Decisão

O modelo é parâmetro nas rotas (`/load/`, `/predict/`) e cada versão carregada é registrada. O
consumidor escolhe qual usar; o registry sabe qual é a versão ativa.

## Alternativas

- *Fixar um modelo único no serviço:* simples, mas tira do consumidor a escolha do ponto da curva
  precisão-vs-latência e impede rodar versões em paralelo.

## Consequências

- (+) Self-service de versão; permite comparar modelos e evoluir sem downtime.
- (−) Precisa gerenciar memória de múltiplos modelos carregados (mitigado pelo registry + limites).
