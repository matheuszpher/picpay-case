"""Transporte REST (FastAPI): fino, reusa nercore.service (ADR-0003, ADR-0008).

Endpoints: /load/, /predict/, /list/, /models/, /health/, DELETE /models/{version},
/metrics. Nenhuma regra de negócio vive aqui: cada rota só chama `NERService` e
traduz o resultado (ou a exceção) para HTTP.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from src.api.observability import (
    RequestLoggingMiddleware,
    configure_logging,
    metrics_response,
    record_prediction,
)
from src.nercore.cache import InMemoryLRUCache
from src.nercore.config import settings
from src.nercore.history import PredictionHistory
from src.nercore.providers.base import ModelLoadError
from src.nercore.providers.spacy_provider import SpacyNERProvider
from src.nercore.registry import ModelNotFoundError, ModelRegistry
from src.nercore.schemas import (
    LoadRequest,
    ModelInfo,
    PredictionRecord,
    PredictRequest,
    PredictResult,
)
from src.nercore.service import EmptyTextError, NERService, NoActiveModelError

configure_logging(settings.LOG_LEVEL)
logger = logging.getLogger(__name__)


def _build_service() -> NERService:
    registry = ModelRegistry(provider_factory=SpacyNERProvider)
    history = PredictionHistory(settings.HISTORY_DB_PATH)
    cache = InMemoryLRUCache()
    return NERService(registry=registry, history=history, cache=cache)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.service = _build_service()
    try:
        app.state.service.load(settings.DEFAULT_MODEL)
    except ModelLoadError:
        # Não derruba a aplicação por falta de rede ou modelo default não
        # pré-instalado: /health reporta active_model=None, e /predict/ com um
        # `model` explícito ainda funciona via lazy-load (decisão de design nº 5).
        logger.exception(
            "falha ao pré-carregar o modelo default '%s' no startup",
            settings.DEFAULT_MODEL,
        )
    yield


app = FastAPI(title="PicPay ML Case: NER Serving", lifespan=lifespan)
app.add_middleware(RequestLoggingMiddleware)


def get_service(request: Request) -> NERService:
    return request.app.state.service


class LoadResponse(BaseModel):
    model: str
    loaded: bool
    active: bool


class ModelsResponse(BaseModel):
    active: str | None
    models: list[ModelInfo]


class HealthResponse(BaseModel):
    status: str
    active_model: str | None
    models_loaded: int


class DeleteResponse(BaseModel):
    removed: str


def _error_response(status_code: int, error: str, detail: object) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"error": error, "detail": detail}
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return _error_response(422, "validation_error", jsonable_encoder(exc.errors()))


@app.exception_handler(EmptyTextError)
async def handle_empty_text(request: Request, exc: EmptyTextError) -> JSONResponse:
    return _error_response(422, "empty_text", str(exc))


@app.exception_handler(NoActiveModelError)
async def handle_no_active_model(
    request: Request, exc: NoActiveModelError
) -> JSONResponse:
    return _error_response(409, "no_active_model", str(exc))


@app.exception_handler(ModelLoadError)
async def handle_model_load_error(
    request: Request, exc: ModelLoadError
) -> JSONResponse:
    return _error_response(400, "model_load_error", str(exc))


@app.exception_handler(ModelNotFoundError)
async def handle_model_not_found(
    request: Request, exc: ModelNotFoundError
) -> JSONResponse:
    return _error_response(404, "model_not_found", str(exc))


@app.post("/load/", response_model=LoadResponse)
def load_model(
    payload: LoadRequest, service: NERService = Depends(get_service)
) -> LoadResponse:
    service.load(payload.model)
    return LoadResponse(
        model=payload.model,
        loaded=True,
        active=service.active_model == payload.model,
    )


@app.post("/predict/", response_model=PredictResult)
def predict(
    payload: PredictRequest, service: NERService = Depends(get_service)
) -> PredictResult:
    start = time.perf_counter()
    result = service.predict(payload.text, model=payload.model)
    duration_seconds = time.perf_counter() - start
    record_prediction(
        model=result.model, cached=result.cached, duration_seconds=duration_seconds
    )
    return result


@app.get("/list/", response_model=list[PredictionRecord])
def list_predictions(
    limit: int = 100,
    offset: int = 0,
    service: NERService = Depends(get_service),
) -> list[PredictionRecord]:
    return service.list_predictions(limit=limit, offset=offset)


@app.get("/models/", response_model=ModelsResponse)
def list_models(service: NERService = Depends(get_service)) -> ModelsResponse:
    return ModelsResponse(active=service.active_model, models=service.list_models())


@app.get("/health/", response_model=HealthResponse)
def health(service: NERService = Depends(get_service)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        active_model=service.active_model,
        models_loaded=len(service.list_models()),
    )


@app.delete("/models/{version}", response_model=DeleteResponse)
def delete_model(
    version: str, service: NERService = Depends(get_service)
) -> DeleteResponse:
    service.delete_model(version)
    return DeleteResponse(removed=version)


@app.get("/metrics")
def metrics() -> Response:
    return metrics_response()
