"""Observabilidade da API: logs JSON estruturados e métricas Prometheus (ADR-0009,
ADR-0014).

Mede o SERVIÇO (latência, throughput, taxa de erro, cache hit/miss), não o modelo:
drift ou qualidade de predição é outro nível de observabilidade, fora do escopo aqui
(distinção explícita da defesa oral do ADR-0009).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("ner_serving")

# Atributos que todo logging.LogRecord já tem por padrão; qualquer chave em
# record.__dict__ fora desta lista veio de `extra={...}` e deve aparecer no JSON.
_STANDARD_LOG_RECORD_ATTRS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
        "message",
    }
)


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOG_RECORD_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


HTTP_REQUESTS_TOTAL = Counter(
    "ner_http_requests_total",
    "Requisicoes HTTP recebidas, por metodo, rota e status",
    ["method", "path", "status_code"],
)
PREDICTIONS_TOTAL = Counter(
    "ner_predictions_total", "Total de predicoes atendidas, por modelo", ["model"]
)
PREDICT_LATENCY_SECONDS = Histogram(
    "ner_predict_latency_seconds", "Latencia de /predict/ em segundos", ["model"]
)
CACHE_REQUESTS_TOTAL = Counter(
    "ner_cache_requests_total",
    "Lookups de cache de predicao, por modelo e resultado (hit/miss)",
    ["model", "result"],
)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log JSON + métrica de contagem HTTP para toda requisição (ADR-0009).

    O `request_id` fica em `request.state.request_id`: rotas que querem correlacionar
    um log de negócio (por exemplo, o de `/predict/` em `api/main.py`) com este log
    de acesso podem lê-lo de lá, sem que este middleware precise conhecer nada sobre
    predição, modelo ou cache.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        path = request.url.path
        HTTP_REQUESTS_TOTAL.labels(
            method=request.method, path=path, status_code=str(response.status_code)
        ).inc()
        logger.info(
            "http_request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
            },
        )
        response.headers["X-Request-ID"] = request_id
        return response


def record_prediction(model: str, cached: bool, duration_seconds: float) -> None:
    PREDICTIONS_TOTAL.labels(model=model).inc()
    PREDICT_LATENCY_SECONDS.labels(model=model).observe(duration_seconds)
    CACHE_REQUESTS_TOTAL.labels(model=model, result="hit" if cached else "miss").inc()


def metrics_response() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
