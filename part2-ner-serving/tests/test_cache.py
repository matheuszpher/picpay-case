"""Testes de src/nercore/cache.py: interface + LRU em processo (ADR-0004)."""

from __future__ import annotations

import pytest

from src.nercore.cache import InMemoryLRUCache, RedisCache, build_cache, cache_key
from src.nercore.schemas import Entity


def _entities(label: str) -> list[Entity]:
    return [Entity(label=label, text="x", start_char=0, end_char=1)]


def test_cache_key_includes_model_and_text():
    key_a = cache_key("en_core_web_sm", "mesmo texto")
    key_b = cache_key("en_core_web_lg", "mesmo texto")

    assert key_a != key_b


def test_cache_key_is_deterministic():
    assert cache_key("en_core_web_sm", "texto") == cache_key("en_core_web_sm", "texto")


def test_get_miss_returns_none():
    cache = InMemoryLRUCache()

    assert cache.get(cache_key("en_core_web_sm", "texto")) is None


def test_set_then_get_hits():
    cache = InMemoryLRUCache()
    key = cache_key("en_core_web_sm", "texto")

    cache.set(key, _entities("PERSON"))

    assert cache.get(key) == _entities("PERSON")


def test_same_text_different_model_is_a_miss():
    cache = InMemoryLRUCache()
    key_sm = cache_key("en_core_web_sm", "texto")
    key_lg = cache_key("en_core_web_lg", "texto")

    cache.set(key_sm, _entities("PERSON"))

    assert cache.get(key_lg) is None


def test_lru_evicts_the_least_recently_used_entry():
    cache = InMemoryLRUCache(max_size=2)
    key_a, key_b, key_c = "a", "b", "c"

    cache.set(key_a, _entities("A"))
    cache.set(key_b, _entities("B"))
    cache.get(key_a)  # "a" volta a ser a mais recente
    cache.set(key_c, _entities("C"))  # deveria evictar "b", não "a"

    assert cache.get(key_a) is not None
    assert cache.get(key_b) is None
    assert cache.get(key_c) is not None


def test_max_size_must_be_positive():
    with pytest.raises(ValueError):
        InMemoryLRUCache(max_size=0)


# --- build_cache ---


def test_build_cache_memory_returns_in_memory_lru_cache():
    cache = build_cache("memory", "redis://localhost:6379/0")

    assert isinstance(cache, InMemoryLRUCache)


def test_build_cache_redis_returns_redis_cache_without_connecting():
    # redis.Redis.from_url() é preguiçoso: não conecta até o primeiro comando, então
    # isto não precisa de um Redis de verdade no ar.
    cache = build_cache("redis", "redis://localhost:6379/0")

    assert isinstance(cache, RedisCache)


def test_build_cache_unknown_backend_raises():
    with pytest.raises(ValueError):
        build_cache("memcached", "redis://localhost:6379/0")
