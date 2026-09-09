# Arquitetura — PicPay ML Case

> Fonte da verdade do system design. Decisões e tradeoffs por trás de cada escolha estão em
> [`docs/adr/`](adr/README.md).

## 1. Contexto (C4 nível 1) — dois projetos independentes, mesmo repo

```mermaid
flowchart LR
    EVAL[Avaliador PicPay] -->|roda local / le docs| REPO
    subgraph REPO["Repositorio unico (mesma regua de engenharia)"]
        P1[["Projeto 1<br/>Analytics batch (PokeAPI + Spark)"]]
        P2[["Projeto 2<br/>NER serving (tooling de plataforma)"]]
    end
    P1 -->|ingestao| POKE[(PokeAPI)]
    P2 -->|carrega modelos| SPACY[(spaCy models)]
    AGENT[Agente LLM / Assistente PIX] -->|extract_entities via MCP| P2
    CONS[Cientista de Dados / time] -->|load / predict / list| P2
    %% sem seta entre P1 e P2: desacoplamento proposital
```

## 2. Contêineres (C4 nível 2)

```mermaid
flowchart TB
    subgraph P1["Parte 1 - Plano batch"]
        ING[Ingestao async] --> BRZ[(Bronze cache JSON)]
        BRZ --> SPK[Spark medallion] --> GLD[(Gold Parquet + analises)]
    end
    subgraph P2["Parte 2 - Plano online (independente)"]
        REST[FastAPI REST] --> SVC
        MCP[MCP server] --> SVC
        GRADIO[Gradio demo - opcional] --> SVC
        SVC[nercore.service] --> PROV[NERProvider - spaCy]
        SVC --> REG[Model registry]
        SVC --> CACHE[(Redis / LRU)]
        SVC --> HIST[(SQLite historico)]
        REST --> METRICS["/metrics"]
    end
    subgraph OBS["Observabilidade"]
        PROM[Prometheus] --> GRAF[Grafana dashboards]
    end
    subgraph INFRA["Infra (Terraform / AWS)"]
        ECR[ECR] --> ECS[ECS Fargate] --> ALB[ALB]
        ELASTIC[(ElastiCache Redis)]
    end
    METRICS -.scrape.-> PROM
    REST -.deploy.-> ECS
```

## 3. Modelo de dados (ERD — Parte 1)

```mermaid
erDiagram
    POKEMON ||--o{ POKEMON_TYPE : tem
    POKEMON ||--o{ POKEMON_STATS : tem
    POKEMON ||--o{ POKEMON_ABILITY : tem
    POKEMON {
        int pokemon_id PK
        string name
        int height
        int weight
        int base_experience
    }
    POKEMON_TYPE {
        int pokemon_id FK
        string type_name
    }
    POKEMON_STATS {
        int pokemon_id FK
        string stat_name
        int base_stat
    }
    POKEMON_ABILITY {
        int pokemon_id FK
        string ability_name
        boolean is_hidden
    }
```

## 4. Sequência — `/predict/` com cache

```mermaid
sequenceDiagram
    participant C as Cliente / Agente
    participant A as API/MCP (transporte)
    participant S as nercore.service
    participant K as Cache
    participant P as spaCy Provider
    participant H as Historico
    C->>A: predict(text, model)
    A->>S: predict(text, model)
    S->>K: get(hash(model+text))
    alt cache hit
        K-->>S: entities
    else cache miss
        S->>P: predict(text)
        P-->>S: entities
        S->>K: set(...)
    end
    S->>H: registra (input, output, ts, versao)
    S-->>A: entities
    A-->>C: entities
```
