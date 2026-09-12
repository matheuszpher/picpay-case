"""Playground opcional em Gradio: reusa `nercore.service`, sem lógica nova (ADR-0013).

Marcado como demo, não como transporte oficial: REST (fase 2.4) e MCP (fase 2.5)
continuam sendo as superfícies de consumo reais; isto só existe para visualizar o
NER no navegador sem `curl`, Swagger ou o MCP Inspector. Construído só depois de
tudo (fases 2.1 a 2.8) já pronto e testado, conforme as condições do ADR-0013.

Expõe `/metrics` (ADR-0009) para o Prometheus também fazer scrape deste processo:
sem isso, predições feitas aqui nunca apareceriam no Grafana, porque cada
processo (api, gradio) tem sua própria contagem de métricas em memória, e o
Prometheus só visita os alvos configurados em `prometheus/prometheus.yml`.
"""

from __future__ import annotations

import logging
import time

import gradio as gr
from fastapi import FastAPI

from src.api.observability import metrics_response, record_prediction
from src.nercore.cache import build_cache
from src.nercore.config import settings
from src.nercore.history import PredictionHistory
from src.nercore.providers.base import ModelLoadError
from src.nercore.providers.spacy_provider import SpacyNERProvider
from src.nercore.registry import ModelRegistry
from src.nercore.service import EmptyTextError, NERService, NoActiveModelError

logger = logging.getLogger(__name__)

_service: NERService | None = None


def _build_service() -> NERService:
    registry = ModelRegistry(provider_factory=SpacyNERProvider)
    history = PredictionHistory(settings.HISTORY_DB_PATH)
    cache = build_cache(settings.CACHE_BACKEND, settings.REDIS_URL)
    return NERService(registry=registry, history=history, cache=cache)


def _get_service() -> NERService:
    """Mesmo padrão preguiçoso do MCP (fase 2.5): constrói só no primeiro uso, não
    no import do módulo, e tenta pré-carregar o modelo default uma única vez sem
    derrubar o processo se falhar.
    """
    global _service
    if _service is None:
        _service = _build_service()
        try:
            _service.load(settings.DEFAULT_MODEL)
        except ModelLoadError:
            logger.exception(
                "falha ao pré-carregar o modelo default '%s' no primeiro uso do Gradio",
                settings.DEFAULT_MODEL,
            )
    return _service


def predict_and_highlight(text: str, model: str) -> dict:
    """Chama `NERService.predict` e converte o resultado para o formato que
    `gr.HighlightedText` espera: `{"text": ..., "entities": [{"entity", "start",
    "end"}, ...]}`. Erros de negócio viram `gr.Error` (mensagem limpa na UI, sem
    traceback), o mesmo espírito dos handlers de exceção da API REST.
    """
    service = _get_service()
    start = time.perf_counter()
    try:
        result = service.predict(text, model=model.strip() or None)
    except (EmptyTextError, NoActiveModelError, ModelLoadError) as exc:
        raise gr.Error(str(exc)) from exc
    duration_seconds = time.perf_counter() - start

    record_prediction(
        model=result.model, cached=result.cached, duration_seconds=duration_seconds
    )

    return {
        "text": text,
        "entities": [
            {"entity": entity.label, "start": entity.start_char, "end": entity.end_char}
            for entity in result.entities
        ],
    }


demo = gr.Interface(
    fn=predict_and_highlight,
    inputs=[
        gr.Textbox(
            label="Texto", placeholder="Send $100 to John tomorrow.", lines=3
        ),
        gr.Textbox(
            label="Modelo (opcional, usa o ativo se vazio)",
            placeholder=settings.DEFAULT_MODEL,
        ),
    ],
    outputs=gr.HighlightedText(label="Entidades reconhecidas"),
    title="PicPay ML Case: NER Playground",
    description=(
        "Reusa a mesma NERService da API REST (POST /predict/) e do MCP "
        "(extract_entities), sem nenhuma lógica nova (ADR-0003). Playground "
        "opcional, ver ADR-0013."
    ),
    examples=[
        ["Send $100 to John tomorrow.", ""],
        ["Elon Musk visited Brazil in 2024.", ""],
    ],
)


def _build_app() -> FastAPI:
    """Monta a UI do Gradio numa app FastAPI que também expõe `/metrics`. Usar
    `demo.launch()` sozinho não deixaria espaço para uma rota HTTP customizada;
    `gr.mount_gradio_app` é o jeito documentado do próprio Gradio de combinar as
    duas coisas no mesmo processo/porta.
    """
    app = FastAPI()
    app.get("/metrics")(metrics_response)
    return gr.mount_gradio_app(app, demo, path="/")


app = _build_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=7860)
