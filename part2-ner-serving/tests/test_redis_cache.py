"""Testes de src/nercore/cache.py::RedisCache contra um Redis de verdade (ADR-0004).

Diferente de SQLite (embutido) ou do Spark local da Parte 1 (biblioteca, sem
processo externo), Redis exige um servidor rodando. Sem um disponível em
REDIS_URL, os testes deste arquivo são pulados com um motivo claro, mesmo padrão
do skip de Parquet/hadoop.dll no Windows da Parte 1: roda de verdade no
Docker/CI (ambiente oficial, ADR-0016), onde o serviço `redis` já sobe junto.
"""

from __future__ import annotations

import pytest
import redis as redis_lib

from src.nercore.cache import RedisCache, cache_key
from src.nercore.config import settings
from src.nercore.schemas import Entity

# Lido de settings.REDIS_URL (não fixo em "localhost"): permite apontar para o
# hostname certo em cada ambiente (localhost no .venv, o nome do serviço "redis"
# dentro do docker-compose ou de um container avulso na mesma rede), via a
# variável de ambiente REDIS_URL.
_REDIS_URL = settings.REDIS_URL


def _redis_available() -> bool:
    try:
        client = redis_lib.Redis.from_url(_REDIS_URL, socket_connect_timeout=0.5)
        return bool(client.ping())
    except redis_lib.exceptions.RedisError:
        return False
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _redis_available(),
    reason=(
        "Redis não está acessível em redis://localhost:6379/0; suba com "
        "'docker compose up -d redis' antes de rodar estes testes localmente, "
        "ou rode a suíte completa no Docker/CI (ambiente oficial, ADR-0016)."
    ),
)


def _entities(label: str) -> list[Entity]:
    return [Entity(label=label, text="x", start_char=0, end_char=1)]


@pytest.fixture
def cache():
    instance = RedisCache(_REDIS_URL)
    yield instance
    # Limpa só as chaves deste namespace, para não deixar lixo entre execuções nem
    # mexer em nada fora do que este cache escreve.
    client = redis_lib.Redis.from_url(_REDIS_URL, decode_responses=True)
    for key in client.scan_iter(match=f"{RedisCache.KEY_PREFIX}*"):
        client.delete(key)


def test_get_miss_returns_none(cache):
    assert cache.get(cache_key("en_core_web_sm", "texto nunca visto")) is None


def test_set_then_get_hits(cache):
    key = cache_key("en_core_web_sm", "Ana chegou")

    cache.set(key, _entities("PERSON"))

    assert cache.get(key) == _entities("PERSON")


def test_value_survives_a_new_client_instance(cache):
    # Prova que o dado está de verdade no Redis, não num estado do objeto Python:
    # uma segunda instância de RedisCache, apontando pro mesmo Redis, também lê.
    key = cache_key("en_core_web_sm", "persistencia")
    cache.set(key, _entities("GPE"))

    other = RedisCache(_REDIS_URL)

    assert other.get(key) == _entities("GPE")


def test_same_text_different_model_is_a_miss(cache):
    key_sm = cache_key("en_core_web_sm", "texto")
    key_lg = cache_key("en_core_web_lg", "texto")

    cache.set(key_sm, _entities("PERSON"))

    assert cache.get(key_lg) is None


def test_keys_are_namespaced_in_redis(cache):
    key = cache_key("en_core_web_sm", "namespace")
    cache.set(key, _entities("DATE"))

    client = redis_lib.Redis.from_url(_REDIS_URL, decode_responses=True)

    assert client.get(f"ner:cache:{key}") is not None
