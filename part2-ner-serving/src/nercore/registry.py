"""Registro de modelos carregados e qual está ativo (ADR-0011).

Cada modelo registrado ganha sua própria instância de `NERProvider` (ver decisão de
design registrada em `docs/IMPLEMENTATION.md`, seção "Provider de NER": um provider =
no máximo um modelo carregado). `provider_factory` é injetado no construtor, em vez de
fixo em `SpacyNERProvider`, pra permitir os testes usarem `FakeProvider` sem tocar
spaCy.
"""

from __future__ import annotations

from collections.abc import Callable

from src.nercore.providers.base import NERProvider
from src.nercore.schemas import ModelInfo


class ModelNotFoundError(Exception):
    """O modelo pedido não está registrado neste processo."""


class ModelRegistry:
    def __init__(self, provider_factory: Callable[[], NERProvider]) -> None:
        self._provider_factory = provider_factory
        self._providers: dict[str, NERProvider] = {}
        self._active: str | None = None

    def register(self, model_name: str) -> None:
        """Carrega `model_name` (se ainda não carregado) e o marca como ativo.

        Idempotente: registrar um modelo já carregado só troca o ativo, sem chamar
        `provider.load()` de novo. Se o carregamento falhar, nada é registrado e o
        ativo não muda (propaga a exceção do provider, ex.: `ModelLoadError`).
        """
        if model_name not in self._providers:
            provider = self._provider_factory()
            provider.load(model_name)
            self._providers[model_name] = provider
        self._active = model_name

    @property
    def active(self) -> str | None:
        return self._active

    def set_active(self, model_name: str) -> None:
        if model_name not in self._providers:
            raise ModelNotFoundError(f"modelo '{model_name}' não está registrado")
        self._active = model_name

    def list(self) -> list[ModelInfo]:
        return [
            ModelInfo(name=name, loaded=True, is_active=(name == self._active))
            for name in self._providers
        ]

    def is_registered(self, model_name: str) -> bool:
        return model_name in self._providers

    def remove(self, model_name: str) -> None:
        """Remove `model_name`. Se era o ativo, o ativo vira `None` (nunca implícito
        para outro modelo, pra o cliente nunca receber resposta de um modelo que não
        pediu).
        """
        if model_name not in self._providers:
            raise ModelNotFoundError(f"modelo '{model_name}' não está registrado")
        del self._providers[model_name]
        if self._active == model_name:
            self._active = None

    def get_provider(self, model_name: str) -> NERProvider:
        if model_name not in self._providers:
            raise ModelNotFoundError(f"modelo '{model_name}' não está registrado")
        return self._providers[model_name]
