# ADR-0008: FastAPI como framework do serviço

**Status.** Aceito.

## Contexto

O microserviço precisa de rotas HTTP, validação de payload e boa documentação. O case sugere
FastAPI ou Flask.

## Decisão

FastAPI.

## Alternativas

- *Flask:* maduro e simples, mas sem async nativo, sem validação de tipo embutida e sem OpenAPI
  automático, eu teria que colar Marshmallow/Swagger à mão.

## Consequências

- (+) Validação via Pydantic, I/O assíncrono, e Swagger UI (`/docs`) de graça, que é a "interface
  web" sem custo (ver [ADR-0013](0013-sem-frontend-custom.md)).
- (−) Um pouco mais de mágica implícita (injeção de dependência, lifespan) a dominar.
