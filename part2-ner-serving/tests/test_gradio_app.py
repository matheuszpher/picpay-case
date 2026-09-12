"""Testes de src/gradio_app/app.py: só a função de predição, não a UI do Gradio em
si (o mesmo espírito de não testar o Swagger gerado pela API REST, fase 2.4).

FakeProvider isola de spaCy real. `_service` é o mesmo padrão de singleton
preguiçoso do MCP (fase 2.5), substituído via `monkeypatch` nos testes.

`gradio` mora no extra "demo" do pyproject.toml, não em "dev" (ADR-0013: o
playground não pode roubar tempo de CI, que só instala ".[dev]"). `importorskip`
pula o arquivo inteiro, com motivo claro, em qualquer ambiente sem "demo"
instalado (CI), e roda de verdade onde `gradio` estiver disponível (`.venv` local
com "pip install -e '.[dev,demo]'", ou a imagem Docker, que já instala os dois).
"""

from __future__ import annotations

import pytest

gr = pytest.importorskip("gradio")

import src.gradio_app.app as gradio_app
from src.nercore.cache import InMemoryLRUCache
from src.nercore.history import PredictionHistory
from src.nercore.registry import ModelRegistry
from src.nercore.schemas import Entity
from src.nercore.service import NERService
from tests.fakes import FakeProvider


@pytest.fixture
def fake_service(tmp_path, monkeypatch):
    entities = [Entity(label="MONEY", text="100", start_char=5, end_char=8)]

    def factory() -> FakeProvider:
        return FakeProvider(entities=entities)

    registry = ModelRegistry(provider_factory=factory)
    history = PredictionHistory(tmp_path / "history.db")
    cache = InMemoryLRUCache()
    service = NERService(registry=registry, history=history, cache=cache)
    service.load("model-a")

    monkeypatch.setattr(gradio_app, "_service", service)
    return service, entities


def test_predict_and_highlight_returns_gradio_entities_format(fake_service):
    result = gradio_app.predict_and_highlight("Send 100 now", model="model-a")

    assert result == {
        "text": "Send 100 now",
        "entities": [{"entity": "MONEY", "start": 5, "end": 8}],
    }


def test_predict_and_highlight_blank_model_uses_active(fake_service):
    result = gradio_app.predict_and_highlight("texto", model="")

    assert result["text"] == "texto"


def test_predict_and_highlight_empty_text_raises_gradio_error(fake_service):
    with pytest.raises(gr.Error):
        gradio_app.predict_and_highlight("   ", model="model-a")


def test_predict_and_highlight_without_active_model_raises_gradio_error(
    tmp_path, monkeypatch
):
    def factory() -> FakeProvider:
        return FakeProvider()

    registry = ModelRegistry(provider_factory=factory)
    history = PredictionHistory(tmp_path / "history.db")
    cache = InMemoryLRUCache()
    service = NERService(registry=registry, history=history, cache=cache)
    monkeypatch.setattr(gradio_app, "_service", service)

    with pytest.raises(gr.Error):
        gradio_app.predict_and_highlight("texto sem modelo ativo", model="")
