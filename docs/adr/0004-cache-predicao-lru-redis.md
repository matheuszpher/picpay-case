# ADR-0004: Cache de predição (LRU em processo → Redis)

**Status.** Aceito.

## Contexto

Inferência de NER consome CPU e, sob carga, vira gargalo. No cenário do PIX por WhatsApp, muitas
mensagens se repetem. A predição é **determinística** para um dado `(versão do modelo, texto)`.

## Decisão

Cachear o resultado de `/predict/` com chave `hash(model_version + text)`. Começar com um cache
LRU em processo (barato, sem dependência) e permitir Redis via configuração para quando houver
múltiplas réplicas.

## Alternativas

- *Sem cache:* toda chamada recomputa no spaCy, p95 e CPU crescem com o tráfego.
- *Só Redis desde o início:* adiciona dependência de infra mesmo quando roda em uma instância só.

## Consequências

- (+) Corta latência e CPU em inputs repetidos.
- (+) Invalidação trivial: a versão do modelo está na chave e cada versão é imutável, então não
  existe o problema clássico de cache stale.
- (−) Memória extra; e o LRU em processo não é compartilhado entre réplicas (por isso o Redis
  quando escala).
