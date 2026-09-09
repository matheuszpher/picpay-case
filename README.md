# PicPay ML Case

> Dois projetos independentes, construídos com o mesmo padrão de engenharia. O serviço de
> serving reflete pensamento de plataforma de ML; a análise de dados reflete disciplina de
> engenharia de dados.

## Por que dois projetos, não uma "plataforma única"

Analytics em batch (PokeAPI + Spark) e serving online de NER (spaCy) têm domínios, runtimes e
lifecycles diferentes — não compartilham dado nem contrato. Forçá-los numa plataforma única
seria over-engineering. Em vez disso, os dois projetos são **independentes e autossuficientes**,
no mesmo repositório, construídos com a **mesma régua de engenharia** (CI, testes,
observabilidade, docs, IaC). O que os unifica não é runtime — é padrão de qualidade.

O discurso de "plataforma de ML" mora onde é honesto: a **Parte 2** (serving que abstrai o
fornecedor, versiona modelo, expõe REST + MCP) já é, por si só, uma peça de tooling de plataforma.
A **Parte 1** é engenharia de dados excelente, sem fingir ser parte de uma plataforma. Detalhe e
tradeoffs em [ADR-0012](docs/adr/0012-sem-plataforma-unica.md).

## Estrutura do repositório

```
picpay-ml-case/
├── README.md                      # este arquivo
├── Makefile                       # atalhos: make up / make test / make ingest / make api
├── docs/
│   ├── ARCHITECTURE.md            # system design + diagramas (fonte da verdade)
│   ├── adr/                       # decisões de arquitetura (uma por arquivo)
│   └── diagrams/                  # fontes .mmd, se separadas do ARCHITECTURE.md
├── part1-pokeapi-analytics/       # PROJETO 1 — plano batch (autossuficiente)
├── part2-ner-serving/             # PROJETO 2 — plano online (autossuficiente)
├── infra/                         # Terraform (AWS)
└── .github/workflows/             # CI/CD
```

## Os dois projetos

### Parte 1 — [`part1-pokeapi-analytics/`](part1-pokeapi-analytics/README.md)

Pipeline batch em camadas medallion (bronze/silver/gold): ingestão assíncrona da PokeAPI, 4
tabelas do dicionário de dados via PySpark, 3 análises e checks de qualidade de dados. Ver
README do projeto para como rodar.

### Parte 2 — [`part2-ner-serving/`](part2-ner-serving/README.md)

Serviço de NER com spaCy atrás de um provider abstrato, um core reutilizável (`nercore`) exposto
por dois transportes finos — REST (FastAPI) e MCP —, cache de predição, registry de versões de
modelo e histórico persistido. Observabilidade com logs estruturados, `/health`, `/metrics` e
dashboards Grafana. Ver README do projeto para como rodar.

## Como rodar

Cada projeto sobe sozinho via Docker Compose — ver o README de cada um. Atalhos comuns no
[`Makefile`](Makefile) da raiz: `make up`, `make test`, `make ingest`, `make api`.

## Documentação

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — diagramas de contexto, contêineres, modelo de
  dados e sequência.
- [`docs/adr/`](docs/adr/README.md) — cada decisão relevante de arquitetura, com contexto,
  alternativas consideradas e tradeoffs.

## Escopo — o que fica de fora (proposital)

- Treinar/fine-tunar modelo de NER próprio (usa spaCy pré-treinado).
- Front-end/UI custom — consumo via Swagger, MCP e notebook (Gradio é opcional, só ao final).
- Autenticação completa de usuários (no máximo API key simples no serving).
- Suporte a português no NER (documentado como evolução via provider).

Ver [ADR-0013](docs/adr/0013-sem-frontend-custom.md) para o racional de não ter frontend custom.

## Status

Esqueleto do repositório (Fase 0 do roadmap). Lógica ainda não implementada — ver plano da Parte 1
na conversa de setup.
