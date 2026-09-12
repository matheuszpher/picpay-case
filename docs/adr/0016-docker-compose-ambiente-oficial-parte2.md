# ADR-0016: Docker Compose como ambiente oficial de validação da Parte 2

**Status.** Aceito.

## Contexto

A Parte 2 depende de spaCy (com um modelo pré-baixado), FastAPI/uvicorn, fastmcp e,
para a stack de observabilidade completa, Prometheus e Grafana. Cada uma dessas
peças tem sua própria cadeia de dependências (por exemplo, `spacy==3.7.5` exige
`click` disponível em tempo de import, algo que só apareceu ao testar a instalação
de verdade, ver `docs/IMPLEMENTATION.md` fase 2.1). Preciso de um ambiente único e
reprodutível para considerar a Parte 2 validada, análogo ao papel do
[ADR-0015](0015-spark-local-notebook-portavel.md) na Parte 1.

## Decisão

Docker Compose é o ambiente oficial de validação: `docker compose up --build` sobe
os 4 serviços (api, redis, prometheus, grafana) com um único comando, sem exigir
Java, GPU ou conta em serviço externo. `docker build` + `docker run <imagem>
python -m pytest tests/` roda a suíte de testes na mesma imagem usada para servir a
API, o mesmo padrão já usado na Parte 1. Testes locais fora do Docker (`.venv`) são
usados só para iteração rápida durante o desenvolvimento, nunca como critério final
de "pronto".

## Alternativas

- *Só documentar `pip install` local:* mais rápido de escrever, mas reproduz o
  mesmo risco já visto na Parte 1 (PySpark/Java): pequenas diferenças de versão
  entre máquinas (aqui, entre versões de `spacy`/`typer`/`click`) quebram a
  instalação de forma não óbvia.
- *Kubernetes/Helm local (kind, minikube):* mais próximo de produção real, mas peso
  de setup desproporcional ao escopo de um case, e exigiria que o avaliador instale
  ferramentas extras além do Docker.

## Consequências

- (+) Reprodutível de verdade: quem clona o repositório só precisa de Docker
  Desktop instalado e rodando, mesma exigência já feita na Parte 1.
- (+) A mesma imagem serve dois propósitos (rodar a API e rodar os testes),
  eliminando divergência entre "o que roda em produção" e "o que foi testado".
- (−) Build da imagem inclui as dependências de desenvolvimento (`pytest`, etc.),
  deixando a imagem maior do que uma imagem de produção enxuta multi-stage teria;
  aceitável no escopo de um case, onde simplicidade e um único Dockerfile pesam
  mais do que otimizar o tamanho da imagem.

