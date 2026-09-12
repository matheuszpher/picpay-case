# Sem dependência nativa (nada de Java/Hadoop como na Parte 1): python:3.11-slim puro
# já basta. en-core-web-sm é dependência normal do pyproject.toml (pinada por URL de
# wheel, ver docs/IMPLEMENTATION.md seção 1), então "pip install" já pré-baixa o
# modelo default no build. Container sobe usável e /health fica pronto sem rede em
# runtime; outros modelos (via /load/, ou trocar DEFAULT_MODEL) exigem rede.
FROM python:3.11-slim

WORKDIR /app
COPY . .
# "demo" (gradio) é instalado aqui, na imagem final, mas fora do "[dev]" que o CI
# instala (ADR-0013: o playground não pode roubar tempo de CI). Um único
# Dockerfile/imagem serve api, mcp_server e o gradio_app opcional, trocando só o
# comando (ver docker-compose.yml).
RUN pip install --no-cache-dir -e ".[dev,demo]"

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
