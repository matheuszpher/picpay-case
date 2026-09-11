"""Orquestração completa: registry (provider) + cache + history (ADR-0003).

REST (fase 2.4) e MCP (fase 2.5) só chamam este módulo; nenhuma lógica de negócio deve
vazar para as camadas de transporte, e nenhuma delas conhece spaCy, SQLite ou o
formato da chave de cache diretamente.
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.nercore.cache import PredictionCache, cache_key
from src.nercore.history import PredictionHistory
from src.nercore.registry import ModelRegistry
from src.nercore.schemas import ModelInfo, PredictionRecord, PredictResult


class NoActiveModelError(Exception):
    """`predict()` foi chamado sem `model` e nenhum modelo está ativo ainda."""


class EmptyTextError(Exception):
    """`predict()` foi chamado com texto vazio ou só espaços."""


class NERService:
    def __init__(
        self,
        registry: ModelRegistry,
        history: PredictionHistory,
        cache: PredictionCache,
    ) -> None:
        self._registry = registry
        self._history = history
        self._cache = cache

    def load(self, model: str) -> None:
        self._registry.register(model)

    @property
    def active_model(self) -> str | None:
        return self._registry.active

    def predict(self, text: str, model: str | None = None) -> PredictResult:
        if not text.strip():
            raise EmptyTextError("texto vazio ou só espaços não pode ser predito")

        resolved_model = self._resolve_model(model)
        if not self._registry.is_registered(resolved_model):
            # Lazy-load pelo mesmo caminho de load(): também marca resolved_model
            # como ativo (registry.register faz isso), conforme "ativo = último
            # carregado". Um modelo explícito já carregado, mas não ativo, NÃO
            # dispara este caminho e portanto não rouba o ativo (ver seção 7 do
            # IMPLEMENTATION.md).
            self._registry.register(resolved_model)

        key = cache_key(resolved_model, text)
        cached_entities = self._cache.get(key)
        if cached_entities is not None:
            entities = cached_entities
            cached = True
        else:
            provider = self._registry.get_provider(resolved_model)
            entities = provider.predict(text)
            self._cache.set(key, entities)
            cached = False

        # Histórico registra toda predição retornada, inclusive cache hit: o cache
        # economiza inferência, não o registro (decisão de design nº 4 do mini-spec).
        self._history.add(text, entities, resolved_model, datetime.now(UTC))

        return PredictResult(model=resolved_model, entities=entities, cached=cached)

    def _resolve_model(self, model: str | None) -> str:
        if model is not None:
            return model
        if self._registry.active is None:
            raise NoActiveModelError(
                "nenhum modelo ativo; informe 'model' ou carregue um com load()"
            )
        return self._registry.active

    def list_predictions(
        self, limit: int = 100, offset: int = 0
    ) -> list[PredictionRecord]:
        return self._history.list(limit=limit, offset=offset)

    def list_models(self) -> list[ModelInfo]:
        return self._registry.list()

    def delete_model(self, model: str) -> None:
        self._registry.remove(model)
