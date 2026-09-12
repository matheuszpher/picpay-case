"""Cache de predição: interface + LRU em processo por padrão, Redis plugável (ADR-0004).

A chave inclui a versão do modelo (`sha256(f"{model}::{text}")`), então cada versão é
imutável e não existe o problema clássico de cache stale (ver ADR-0004). O valor
guardado é a lista de entidades pura (`list[Entity]`), não um `PredictResult` inteiro:
o campo `cached` de `PredictResult` depende de SE a chamada atual foi hit ou miss, e
quem decide isso é o `NERService` (fase 2.3), não o cache.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from collections import OrderedDict

import redis

from src.nercore.schemas import Entity


def cache_key(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}::{text}".encode()).hexdigest()


class PredictionCache(ABC):
    @abstractmethod
    def get(self, key: str) -> list[Entity] | None:
        """Devolve as entidades cacheadas para `key`, ou `None` em cache miss."""

    @abstractmethod
    def set(self, key: str, value: list[Entity]) -> None:
        """Guarda `value` sob `key`."""


class InMemoryLRUCache(PredictionCache):
    def __init__(self, max_size: int = 1024) -> None:
        if max_size <= 0:
            raise ValueError("max_size deve ser positivo")
        self._max_size = max_size
        self._store: OrderedDict[str, list[Entity]] = OrderedDict()

    def get(self, key: str) -> list[Entity] | None:
        if key not in self._store:
            return None
        self._store.move_to_end(key)
        return self._store[key]

    def set(self, key: str, value: list[Entity]) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = value
        if len(self._store) > self._max_size:
            self._store.popitem(last=False)


class RedisCache(PredictionCache):
    """Cache compartilhado entre réplicas, para quando o LRU em processo deixa de
    bastar (ADR-0004). A política de evicção LRU não vive aqui: fica a cargo do
    próprio servidor Redis (`maxmemory-policy allkeys-lru`, configurado no
    `docker-compose.yml`), não de código Python. Este cliente só faz get/set.
    """

    KEY_PREFIX = "ner:cache:"

    def __init__(self, redis_url: str) -> None:
        self._client = redis.Redis.from_url(redis_url, decode_responses=True)

    def get(self, key: str) -> list[Entity] | None:
        raw = self._client.get(self.KEY_PREFIX + key)
        if raw is None:
            return None
        return [Entity(**entity) for entity in json.loads(raw)]

    def set(self, key: str, value: list[Entity]) -> None:
        raw = json.dumps([entity.model_dump() for entity in value])
        self._client.set(self.KEY_PREFIX + key, raw)


def build_cache(cache_backend: str, redis_url: str) -> PredictionCache:
    """Fábrica lida pelas camadas de transporte (fase 2.4/2.5), nunca por
    `NERService`: `nercore` conhece as duas implementações, mas quem decide qual
    usar em produção é a configuração (`CACHE_BACKEND`), lida uma única vez na
    composição do serviço.
    """
    if cache_backend == "memory":
        return InMemoryLRUCache()
    if cache_backend == "redis":
        return RedisCache(redis_url)
    raise ValueError(f"CACHE_BACKEND desconhecido: '{cache_backend}'")
