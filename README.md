# PicPay ML Case

<img src="part1-pokeapi-analytics/assets/picpay-logo.png" alt="PicPay" width="180">

> Dois projetos independentes, construídos com o mesmo padrão de engenharia. O serviço de
> serving reflete pensamento de plataforma de ML; a análise de dados reflete batch de
> engenharia de dados.

## Por que dois projetos, não uma "plataforma única"

Analytics em batch (PokeAPI + Spark) e serving online de NER (spaCy) têm domínios, runtimes e
lifecycles diferentes: não compartilham dado nem contrato. Forçá-los numa plataforma única
seria over-engineering. Em vez disso, os dois projetos são **independentes e autossuficientes**,
no mesmo repositório, construídos com a **mesma régua de engenharia** (CI, testes,
observabilidade, docs, IaC). O que os unifica não é runtime, é padrão de qualidade.

O discurso de "plataforma de ML" mora onde é honesto: a **Parte 2** (serving que abstrai o
fornecedor, versiona modelo, expõe REST + MCP) já é, por si só, uma peça de tooling de plataforma.
A **Parte 1** é engenharia de dados excelente, sem fingir ser parte de uma plataforma. Detalhe e
tradeoffs em [ADR-0012](docs/adr/0012-sem-plataforma-unica.md).

## Estrutura do repositório

```
picpay-ml-case/
├── README.md                      # este arquivo
├── docs/
│   ├── ARCHITECTURE.md            # system design + diagramas (fonte da verdade)
│   ├── adr/                       # decisões de arquitetura (uma por arquivo)
│   └── diagrams/                  # fontes .mmd, se separadas do ARCHITECTURE.md
├── part1-pokeapi-analytics/       # PROJETO 1: plano batch (autossuficiente)
├── part2-ner-serving/             # PROJETO 2: plano online (autossuficiente)
├── infra/                         # Terraform (AWS)
└── .github/workflows/             # CI/CD
```

## Os dois projetos

### Parte 1: [`part1-pokeapi-analytics/`](part1-pokeapi-analytics/README.md)

Pipeline batch em camadas medallion (bronze/silver/gold): ingestão assíncrona da PokeAPI, 4
tabelas do dicionário de dados via PySpark, 3 análises e checks de qualidade de dados. Ver
README do projeto para como rodar.

### Parte 2: [`part2-ner-serving/`](part2-ner-serving/README.md)

Serviço de NER com spaCy atrás de um provider abstrato, um core reutilizável (`nercore`) exposto
por dois transportes finos (REST via FastAPI e MCP), cache de predição, registry de versões de
modelo e histórico persistido. Observabilidade com logs estruturados, `/health`, `/metrics` e
dashboards Grafana. Ver README do projeto para como rodar.

## Como rodar

Cada projeto sobe sozinho via Docker Compose, sem precisar de nada além do Docker Desktop
instalado e rodando (mesmos passos em Linux, macOS e Windows):

1. Tenha o Docker Desktop instalado e rodando.
2. Entre na pasta do projeto que quer subir:
   ```bash
   cd part1-pokeapi-analytics
   ```
   ou
   ```bash
   cd part2-ner-serving
   ```
3. Suba com Docker Compose:
   ```bash
   docker compose up --build
   ```
   Na Parte 2, use `docker compose --profile demo up --build` para incluir também o
   playground Gradio opcional.

Ver o README de cada projeto (seção "Como executar") para os comandos completos por
sistema operacional, endpoints e comandos de teste.

## CI (GitHub Actions)

[![CI Parte 1](https://github.com/matheuszpher/picpay-case/actions/workflows/ci-part1.yml/badge.svg)](https://github.com/matheuszpher/picpay-case/actions/workflows/ci-part1.yml)
[![CI Parte 2](https://github.com/matheuszpher/picpay-case/actions/workflows/ci-part2.yml/badge.svg)](https://github.com/matheuszpher/picpay-case/actions/workflows/ci-part2.yml)

Cada projeto tem seu próprio pipeline ([`ci-part1.yml`](.github/workflows/ci-part1.yml),
[`ci-part2.yml`](.github/workflows/ci-part2.yml)), rodando lint (`ruff`), formatação
(`black --check`) e a suíte de testes (`pytest`). Os workflows são filtrados por path: um
commit que só mexe em `part1-pokeapi-analytics/` roda só a CI da Parte 1, e vice-versa, sem
disparar o pipeline da parte que não mudou. Ver a execução em andamento ou o histórico completo
na aba [Actions do repositório](https://github.com/matheuszpher/picpay-case/actions).

## Documentação

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): diagramas de contexto, contêineres, modelo de
  dados e sequência.
- [`docs/adr/`](docs/adr/README.md): cada decisão relevante de arquitetura, com contexto,
  alternativas consideradas e tradeoffs.

## Escopo: o que fica de fora (proposital)

- Treinar/fine-tunar modelo de NER próprio (usa spaCy pré-treinado).
- Front-end/UI custom: consumo via Swagger, MCP e notebook (Gradio é opcional, só ao final).
- Autenticação completa de usuários (no máximo API key simples no serving).
- Suporte a português no NER (documentado como evolução via provider).

Ver [ADR-0013](docs/adr/0013-sem-frontend-custom.md) para o racional de não ter frontend custom.

## Status

Os dois projetos estão fechados e testados no Docker (ambiente oficial de validação de cada um,
ver [ADR-0015](docs/adr/0015-spark-local-notebook-portavel.md) e
[ADR-0016](docs/adr/0016-docker-compose-ambiente-oficial-parte2.md)).

- **Parte 1**: pipeline completo (ingestão, transformação, qualidade, 3 análises, relatório
  gerencial), 67/67 testes passando. `docker compose up --build` roda de ponta a ponta.
- **Parte 2**: provider abstrato, registry, cache (LRU e Redis), histórico, orquestração, API
  REST, servidor MCP, playground Gradio opcional e observabilidade (logs JSON, `/health`,
  `/metrics`, Prometheus + Grafana provisionados), 98 testes no total. `docker compose up
  --build` sobe os 4 serviços centrais de ponta a ponta, já com Redis em uso; `--profile demo`
  soma o Gradio.

Detalhe de implementação de cada um em `part1-pokeapi-analytics/docs/IMPLEMENTATION.md` e
`part2-ner-serving/docs/IMPLEMENTATION.md`.
