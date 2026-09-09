# PySpark 3.5.3 exige Java 8/11/17 (ADR-0015: Spark local dockerizado, reprodutível).
# Pinado em bookworm (não "slim" simples): trixie só empacota OpenJDK 21, não suportado pelo 3.5.3.
FROM python:3.11-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV PATH="${JAVA_HOME}/bin:${PATH}"

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e ".[dev]"

CMD ["python", "-m", "src.ingest"]
