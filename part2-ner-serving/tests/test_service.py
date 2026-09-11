"""Testes de src/nercore/service.py: orquestração completa (ADR-0003).

FakeProvider isola de spaCy real; registry, history e cache são reais (só o provider
concreto é fake), pra exercitar a fiação entre as camadas, não só o service em
isolamento.
"""

from __future__ import annotations

import pytest

from src.nercore.cache import InMemoryLRUCache
from src.nercore.history import PredictionHistory
from src.nercore.registry import ModelNotFoundError, ModelRegistry
from src.nercore.schemas import Entity
from src.nercore.service import EmptyTextError, NERService, NoActiveModelError
from tests.fakes import FakeProvider


def _make_service(tmp_path, entities: list[Entity] | None = None):
    def factory() -> FakeProvider:
        return FakeProvider(entities=entities or [])

    registry = ModelRegistry(provider_factory=factory)
    history = PredictionHistory(tmp_path / "history.db")
    cache = InMemoryLRUCache()
    service = NERService(registry=registry, history=history, cache=cache)
    return service, registry, history


def test_predict_without_active_model_and_without_explicit_model_raises(tmp_path):
    service, _, _ = _make_service(tmp_path)

    with pytest.raises(NoActiveModelError):
        service.predict("qualquer texto")


def test_predict_empty_text_raises_before_resolving_model(tmp_path):
    service, _, _ = _make_service(tmp_path)

    with pytest.raises(EmptyTextError):
        service.predict("   ")


def test_active_model_reflects_registry(tmp_path):
    service, _, _ = _make_service(tmp_path)

    assert service.active_model is None

    service.load("model-a")

    assert service.active_model == "model-a"


def test_predict_with_explicit_model_lazy_loads_and_becomes_active(tmp_path):
    service, registry, _ = _make_service(tmp_path)

    result = service.predict("texto", model="model-a")

    assert result.model == "model-a"
    assert registry.active == "model-a"
    assert registry.get_provider("model-a").load_calls == ["model-a"]


def test_load_registers_model_as_active(tmp_path):
    service, registry, _ = _make_service(tmp_path)

    service.load("model-a")

    assert registry.active == "model-a"
    assert registry.get_provider("model-a").load_calls == ["model-a"]


def test_predict_without_model_uses_active(tmp_path):
    service, _, _ = _make_service(tmp_path)
    service.load("model-a")

    result = service.predict("texto")

    assert result.model == "model-a"


def test_predict_is_a_cache_miss_the_first_time(tmp_path):
    entities = [Entity(label="PERSON", text="Ana", start_char=0, end_char=3)]
    service, registry, _ = _make_service(tmp_path, entities=entities)
    service.load("model-a")

    result = service.predict("Ana chegou", model="model-a")

    assert result.cached is False
    assert result.entities == entities
    assert registry.get_provider("model-a").predict_calls == ["Ana chegou"]


def test_predict_is_a_cache_hit_on_repeat_and_does_not_call_provider_again(tmp_path):
    entities = [Entity(label="PERSON", text="Ana", start_char=0, end_char=3)]
    service, registry, _ = _make_service(tmp_path, entities=entities)
    service.load("model-a")

    first = service.predict("Ana chegou", model="model-a")
    second = service.predict("Ana chegou", model="model-a")

    assert first.cached is False
    assert second.cached is True
    assert second.entities == entities
    assert registry.get_provider("model-a").predict_calls == ["Ana chegou"]


def test_predict_same_text_different_model_is_a_separate_cache_entry(tmp_path):
    service, _, _ = _make_service(tmp_path)
    service.load("model-a")
    service.load("model-b")

    result_a = service.predict("texto", model="model-a")
    result_b = service.predict("texto", model="model-b")

    assert result_a.cached is False
    assert result_b.cached is False


def test_predict_records_history_even_on_cache_hit(tmp_path):
    service, _, history = _make_service(tmp_path)
    service.load("model-a")

    service.predict("texto", model="model-a")
    service.predict("texto", model="model-a")

    assert len(history.list()) == 2


def test_predict_with_already_loaded_non_active_model_does_not_switch_active(
    tmp_path,
):
    service, registry, _ = _make_service(tmp_path)
    service.load("model-a")
    service.load("model-b")

    service.predict("texto", model="model-a")

    assert registry.active == "model-b"


def test_list_predictions_delegates_to_history(tmp_path):
    service, _, _ = _make_service(tmp_path)
    service.load("model-a")
    service.predict("um", model="model-a")
    service.predict("dois", model="model-a")

    records = service.list_predictions(limit=1)

    assert len(records) == 1


def test_list_models_delegates_to_registry(tmp_path):
    service, _, _ = _make_service(tmp_path)
    service.load("model-a")

    models = service.list_models()

    assert [m.name for m in models] == ["model-a"]


def test_delete_model_delegates_to_registry(tmp_path):
    service, _, _ = _make_service(tmp_path)
    service.load("model-a")

    service.delete_model("model-a")

    with pytest.raises(ModelNotFoundError):
        service.delete_model("model-a")
