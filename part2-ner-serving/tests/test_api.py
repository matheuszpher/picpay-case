"""Testes de src/api/main.py: rotas REST, error handlers, warm-up (ADR-0008).

FakeProvider isola de spaCy real, exceto no teste de fiação de ponta a ponta ao final
(SpacyNERProvider já instalado, sem rede). `TestClient(app)` é usado SEM o context
manager `with`: isso pula o `lifespan` (Starlette só roda startup/shutdown dentro do
`with`), então o warm-up do DEFAULT_MODEL nunca dispara nestes testes. Cada teste
injeta seu próprio `NERService` via `app.dependency_overrides`, hermético.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.main import app, get_service
from src.nercore.cache import InMemoryLRUCache
from src.nercore.history import PredictionHistory
from src.nercore.providers.spacy_provider import SpacyNERProvider
from src.nercore.registry import ModelRegistry
from src.nercore.schemas import Entity
from src.nercore.service import NERService
from tests.fakes import FakeProvider


def _make_client(
    tmp_path, entities: list[Entity] | None = None, raise_on_load: bool = False
) -> tuple[TestClient, NERService]:
    def factory() -> FakeProvider:
        return FakeProvider(entities=entities or [], raise_on_load=raise_on_load)

    registry = ModelRegistry(provider_factory=factory)
    history = PredictionHistory(tmp_path / "history.db")
    cache = InMemoryLRUCache()
    service = NERService(registry=registry, history=history, cache=cache)

    app.dependency_overrides[get_service] = lambda: service
    return TestClient(app), service


def teardown_function() -> None:
    app.dependency_overrides.clear()


# --- POST /load/ ---


def test_load_returns_200_and_marks_model_active(tmp_path):
    client, _ = _make_client(tmp_path)

    response = client.post("/load/", json={"model": "model-a"})

    assert response.status_code == 200
    assert response.json() == {"model": "model-a", "loaded": True, "active": True}


def test_load_invalid_model_returns_400(tmp_path):
    client, _ = _make_client(tmp_path, raise_on_load=True)

    response = client.post("/load/", json={"model": "modelo-invalido"})

    assert response.status_code == 400
    assert response.json()["error"] == "model_load_error"


def test_load_missing_model_field_returns_422(tmp_path):
    client, _ = _make_client(tmp_path)

    response = client.post("/load/", json={})

    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


# --- POST /predict/ ---


def test_predict_returns_predict_result(tmp_path):
    entities = [Entity(label="PERSON", text="Ana", start_char=0, end_char=3)]
    client, _ = _make_client(tmp_path, entities=entities)
    client.post("/load/", json={"model": "model-a"})

    response = client.post("/predict/", json={"text": "Ana chegou", "model": "model-a"})

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "model-a"
    assert body["cached"] is False
    assert body["entities"] == [e.model_dump() for e in entities]


def test_predict_repeat_is_cached(tmp_path):
    entities = [Entity(label="PERSON", text="Ana", start_char=0, end_char=3)]
    client, _ = _make_client(tmp_path, entities=entities)
    client.post("/load/", json={"model": "model-a"})

    client.post("/predict/", json={"text": "Ana chegou", "model": "model-a"})
    response = client.post("/predict/", json={"text": "Ana chegou", "model": "model-a"})

    assert response.json()["cached"] is True


def test_predict_empty_text_returns_422(tmp_path):
    client, _ = _make_client(tmp_path)
    client.post("/load/", json={"model": "model-a"})

    response = client.post("/predict/", json={"text": "   "})

    assert response.status_code == 422
    assert response.json()["error"] == "empty_text"


def test_predict_without_active_model_returns_409(tmp_path):
    client, _ = _make_client(tmp_path)

    response = client.post("/predict/", json={"text": "qualquer texto"})

    assert response.status_code == 409
    assert response.json()["error"] == "no_active_model"


def test_predict_with_unregistered_model_lazy_loads(tmp_path):
    client, _ = _make_client(tmp_path)

    response = client.post("/predict/", json={"text": "texto", "model": "model-a"})

    assert response.status_code == 200
    assert response.json()["model"] == "model-a"


# --- GET /list/ ---


def test_list_returns_recorded_predictions(tmp_path):
    client, _ = _make_client(tmp_path)
    client.post("/load/", json={"model": "model-a"})
    client.post("/predict/", json={"text": "um"})
    client.post("/predict/", json={"text": "dois"})

    response = client.get("/list/")

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_list_respects_limit(tmp_path):
    client, _ = _make_client(tmp_path)
    client.post("/load/", json={"model": "model-a"})
    client.post("/predict/", json={"text": "um"})
    client.post("/predict/", json={"text": "dois"})

    response = client.get("/list/", params={"limit": 1})

    assert len(response.json()) == 1


# --- GET /models/ ---


def test_models_lists_active_and_loaded(tmp_path):
    client, _ = _make_client(tmp_path)
    client.post("/load/", json={"model": "model-a"})

    response = client.get("/models/")

    assert response.status_code == 200
    body = response.json()
    assert body["active"] == "model-a"
    assert [m["name"] for m in body["models"]] == ["model-a"]
    assert body["models"][0]["is_active"] is True


# --- GET /health/ ---


def test_health_before_any_load(tmp_path):
    client, _ = _make_client(tmp_path)

    response = client.get("/health/")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "active_model": None,
        "models_loaded": 0,
    }


def test_health_after_load(tmp_path):
    client, _ = _make_client(tmp_path)
    client.post("/load/", json={"model": "model-a"})

    response = client.get("/health/")

    body = response.json()
    assert body["status"] == "ok"
    assert body["active_model"] == "model-a"
    assert body["models_loaded"] == 1


def test_every_response_carries_a_request_id_header(tmp_path):
    client, _ = _make_client(tmp_path)

    response = client.get("/health/")

    assert "X-Request-ID" in response.headers


# --- DELETE /models/{version} ---


def test_delete_loaded_model(tmp_path):
    client, _ = _make_client(tmp_path)
    client.post("/load/", json={"model": "model-a"})

    response = client.delete("/models/model-a")

    assert response.status_code == 200
    assert response.json() == {"removed": "model-a"}


def test_delete_unregistered_model_returns_404(tmp_path):
    client, _ = _make_client(tmp_path)

    response = client.delete("/models/model-a")

    assert response.status_code == 404
    assert response.json()["error"] == "model_not_found"


# --- fiação de ponta a ponta com o provider spaCy real (sem rede: modelo já instalado) ---


def test_predict_end_to_end_with_real_spacy_provider(tmp_path):
    registry = ModelRegistry(provider_factory=SpacyNERProvider)
    history = PredictionHistory(tmp_path / "history.db")
    cache = InMemoryLRUCache()
    service = NERService(registry=registry, history=history, cache=cache)

    app.dependency_overrides[get_service] = lambda: service
    client = TestClient(app)

    response = client.post(
        "/predict/",
        json={"text": "Bill Gates works at Microsoft.", "model": "en_core_web_sm"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "en_core_web_sm"
    labels = {e["label"] for e in body["entities"]}
    assert labels & {"PERSON", "ORG"}


# --- GET /metrics ---


def test_metrics_exposes_prometheus_text_format(tmp_path):
    # Nome de modelo exclusivo deste teste: PREDICTIONS_TOTAL e os outros contadores
    # são singletons de módulo (decisão de design da fase 2.6), então reusar um nome
    # de modelo já usado por outro teste desta suíte contaminaria a contagem.
    client, _ = _make_client(tmp_path)
    client.post("/load/", json={"model": "metrics-endpoint-model"})
    client.post("/predict/", json={"text": "texto", "model": "metrics-endpoint-model"})

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert 'ner_predictions_total{model="metrics-endpoint-model"} 1.0' in body
    assert (
        'ner_cache_requests_total{model="metrics-endpoint-model",result="miss"} 1.0'
        in body
    )
    assert "ner_predict_latency_seconds" in body
    assert "ner_http_requests_total" in body
