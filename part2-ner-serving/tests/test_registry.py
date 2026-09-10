"""Testes de src/nercore/registry.py."""

from __future__ import annotations

import pytest

from src.nercore.providers.base import ModelLoadError
from src.nercore.registry import ModelNotFoundError, ModelRegistry
from tests.fakes import FakeProvider


def _factory() -> FakeProvider:
    return FakeProvider()


def test_register_loads_and_activates():
    registry = ModelRegistry(provider_factory=_factory)

    registry.register("model-a")

    assert registry.active == "model-a"
    assert registry.is_registered("model-a")


def test_register_is_idempotent_does_not_reload():
    providers: list[FakeProvider] = []

    def factory() -> FakeProvider:
        provider = FakeProvider()
        providers.append(provider)
        return provider

    registry = ModelRegistry(provider_factory=factory)
    registry.register("model-a")
    registry.register("model-a")

    assert len(providers) == 1
    assert providers[0].load_calls == ["model-a"]


def test_register_second_model_switches_active():
    registry = ModelRegistry(provider_factory=_factory)
    registry.register("model-a")
    registry.register("model-b")

    assert registry.active == "model-b"
    assert registry.is_registered("model-a")
    assert registry.is_registered("model-b")


def test_register_propagates_load_failure_without_registering():
    def factory() -> FakeProvider:
        return FakeProvider(raise_on_load=True)

    registry = ModelRegistry(provider_factory=factory)

    with pytest.raises(ModelLoadError):
        registry.register("model-a")

    assert not registry.is_registered("model-a")
    assert registry.active is None


def test_list_reflects_active_model():
    registry = ModelRegistry(provider_factory=_factory)
    registry.register("model-a")
    registry.register("model-b")

    infos = {info.name: info for info in registry.list()}

    assert infos["model-a"].is_active is False
    assert infos["model-b"].is_active is True
    assert all(info.loaded for info in infos.values())


def test_set_active_requires_registered_model():
    registry = ModelRegistry(provider_factory=_factory)
    registry.register("model-a")

    with pytest.raises(ModelNotFoundError):
        registry.set_active("model-b")


def test_remove_active_model_clears_active():
    registry = ModelRegistry(provider_factory=_factory)
    registry.register("model-a")

    registry.remove("model-a")

    assert registry.active is None
    assert not registry.is_registered("model-a")


def test_remove_inactive_model_keeps_active():
    registry = ModelRegistry(provider_factory=_factory)
    registry.register("model-a")
    registry.register("model-b")

    registry.remove("model-a")

    assert registry.active == "model-b"
    assert not registry.is_registered("model-a")


def test_remove_unregistered_model_raises():
    registry = ModelRegistry(provider_factory=_factory)

    with pytest.raises(ModelNotFoundError):
        registry.remove("model-a")


def test_get_provider_returns_the_instance_bound_to_that_model():
    registry = ModelRegistry(provider_factory=_factory)
    registry.register("model-a")

    provider = registry.get_provider("model-a")

    assert isinstance(provider, FakeProvider)
    assert provider.is_loaded("model-a")


def test_get_provider_unregistered_model_raises():
    registry = ModelRegistry(provider_factory=_factory)

    with pytest.raises(ModelNotFoundError):
        registry.get_provider("model-a")
