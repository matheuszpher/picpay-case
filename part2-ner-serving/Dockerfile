# Stub — Fase 0 (esqueleto). Base e etapas reais entram na Fase 3.
FROM python:3.11-slim

WORKDIR /app

# COPY pyproject.toml .
# RUN pip install --no-cache-dir .

COPY . .

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
