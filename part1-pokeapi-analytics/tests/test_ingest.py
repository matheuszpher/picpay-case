"""Testes de src/ingest.py — rede sempre mockada via httpx.MockTransport, nunca a API real."""

from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest

from src import ingest

# ---------------------------------------------------------------------------
# extract_id
# ---------------------------------------------------------------------------


def test_extract_id_parses_trailing_segment():
    assert ingest.extract_id("https://pokeapi.co/api/v2/pokemon/25/") == 25


def test_extract_id_handles_no_trailing_slash():
    assert ingest.extract_id("https://pokeapi.co/api/v2/pokemon/1") == 1


# ---------------------------------------------------------------------------
# fetch_index
# ---------------------------------------------------------------------------


def test_fetch_index_paginates_until_next_is_null(monkeypatch):
    page1 = {
        "results": [
            {"name": "bulbasaur", "url": "https://pokeapi.co/api/v2/pokemon/1/"}
        ],
        "next": "https://pokeapi.co/api/v2/pokemon?limit=1&offset=1",
    }
    page2 = {
        "results": [{"name": "ivysaur", "url": "https://pokeapi.co/api/v2/pokemon/2/"}],
        "next": None,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        offset = request.url.params.get("offset")
        if offset == "0" or (offset is None and "offset" not in request.url.params):
            return httpx.Response(200, json=page1)
        return httpx.Response(200, json=page2)

    monkeypatch.setattr(httpx, "Client", _client_factory(handler))

    result = ingest.fetch_index(page_size=1)

    assert result == [
        {"name": "bulbasaur", "url": "https://pokeapi.co/api/v2/pokemon/1/"},
        {"name": "ivysaur", "url": "https://pokeapi.co/api/v2/pokemon/2/"},
    ]


def test_fetch_index_respects_max_items(monkeypatch):
    page1 = {
        "results": [
            {"name": "bulbasaur", "url": "https://pokeapi.co/api/v2/pokemon/1/"},
            {"name": "ivysaur", "url": "https://pokeapi.co/api/v2/pokemon/2/"},
        ],
        "next": "https://pokeapi.co/api/v2/pokemon?limit=2&offset=2",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=page1)

    monkeypatch.setattr(httpx, "Client", _client_factory(handler))

    result = ingest.fetch_index(page_size=2, max_items=1)

    assert len(result) == 1
    assert result[0]["name"] == "bulbasaur"


def test_fetch_index_sends_user_agent(monkeypatch):
    captured_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(request.headers)
        return httpx.Response(200, json={"results": [], "next": None})

    monkeypatch.setattr(httpx, "Client", _client_factory(handler))

    ingest.fetch_index()

    assert captured_headers.get("user-agent") == ingest.USER_AGENT


def test_fetch_index_retries_on_transient_error_then_succeeds(monkeypatch):
    monkeypatch.setattr(time, "sleep", _no_op_sleep)
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] < 3:
            return httpx.Response(503, json={"error": "temporarily unavailable"})
        return httpx.Response(200, json={"results": [], "next": None})

    monkeypatch.setattr(httpx, "Client", _client_factory(handler))

    result = ingest.fetch_index()

    assert result == []
    assert call_count["n"] == 3


def test_fetch_index_does_not_retry_on_non_retryable_status(monkeypatch):
    monkeypatch.setattr(time, "sleep", _no_op_sleep)
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(404, json={"error": "not found"})

    monkeypatch.setattr(httpx, "Client", _client_factory(handler))

    with pytest.raises(httpx.HTTPStatusError):
        ingest.fetch_index()

    assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# fetch_detail
# ---------------------------------------------------------------------------


def test_fetch_detail_uses_cache_when_present(tmp_path):
    cached = {"id": 1, "name": "bulbasaur"}
    (tmp_path / "1.json").write_text(json.dumps(cached), encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("não deveria bater na rede quando o cache existe")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    result = asyncio.run(
        ingest.fetch_detail(client, "https://pokeapi.co/api/v2/pokemon/1/", tmp_path)
    )

    assert result == cached
    asyncio.run(client.aclose())


def test_fetch_detail_fetches_and_writes_cache_on_miss(tmp_path):
    payload = {"id": 1, "name": "bulbasaur"}
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        return httpx.Response(200, json=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    result = asyncio.run(
        ingest.fetch_detail(client, "https://pokeapi.co/api/v2/pokemon/1/", tmp_path)
    )

    assert result == payload
    assert len(calls) == 1
    assert json.loads((tmp_path / "1.json").read_text(encoding="utf-8")) == payload
    asyncio.run(client.aclose())


def test_fetch_detail_writes_cache_atomically_no_tmp_left_behind(tmp_path):
    payload = {"id": 1, "name": "bulbasaur"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    asyncio.run(
        ingest.fetch_detail(client, "https://pokeapi.co/api/v2/pokemon/1/", tmp_path)
    )

    assert (tmp_path / "1.json").exists()
    assert not (tmp_path / "1.json.tmp").exists()
    asyncio.run(client.aclose())


def test_fetch_detail_ignores_leftover_tmp_from_interrupted_write(tmp_path):
    """Simula uma coleta interrompida: só o .tmp existe (escrita parcial), nunca o .json final.

    Deve tratar como cache miss (o .tmp nunca é lido como cache válido) e refazer a busca.
    """
    payload = {"id": 1, "name": "bulbasaur"}
    calls = []

    # escrita parcial/corrompida deixada por uma interrupção anterior
    (tmp_path / "1.json.tmp").write_text('{"id": 1, "name": "bulba', encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        return httpx.Response(200, json=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    result = asyncio.run(
        ingest.fetch_detail(client, "https://pokeapi.co/api/v2/pokemon/1/", tmp_path)
    )

    assert len(calls) == 1  # cache miss: bateu na rede mesmo com o .tmp presente
    assert result == payload
    assert json.loads((tmp_path / "1.json").read_text(encoding="utf-8")) == payload
    asyncio.run(client.aclose())


def test_fetch_detail_retries_on_transient_error_then_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)
    payload = {"id": 1, "name": "bulbasaur"}
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] < 3:
            return httpx.Response(503, json={"error": "temporarily unavailable"})
        return httpx.Response(200, json=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    result = asyncio.run(
        ingest.fetch_detail(client, "https://pokeapi.co/api/v2/pokemon/1/", tmp_path)
    )

    assert result == payload
    assert call_count["n"] == 3
    asyncio.run(client.aclose())


def test_fetch_detail_does_not_retry_on_non_retryable_status(tmp_path, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(404, json={"error": "not found"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(
            ingest.fetch_detail(
                client, "https://pokeapi.co/api/v2/pokemon/1/", tmp_path
            )
        )

    assert call_count["n"] == 1
    asyncio.run(client.aclose())


def test_fetch_detail_raises_after_exhausting_retries(tmp_path, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(500, json={"error": "boom"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(
            ingest.fetch_detail(
                client, "https://pokeapi.co/api/v2/pokemon/1/", tmp_path
            )
        )

    assert call_count["n"] == ingest.MAX_RETRIES + 1
    asyncio.run(client.aclose())


# ---------------------------------------------------------------------------
# fetch_all
# ---------------------------------------------------------------------------


def test_fetch_all_preserves_order_and_is_idempotent(tmp_path, monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        pokemon_id = ingest.extract_id(str(request.url))
        calls.append(pokemon_id)
        return httpx.Response(
            200, json={"id": pokemon_id, "name": f"pokemon-{pokemon_id}"}
        )

    monkeypatch.setattr(httpx, "AsyncClient", _async_client_factory(handler))

    urls = [f"https://pokeapi.co/api/v2/pokemon/{i}/" for i in (3, 1, 2)]

    result = ingest.fetch_all(urls, concurrency=2, cache_dir=tmp_path)

    assert [item["id"] for item in result] == [3, 1, 2]
    assert sorted(calls) == [1, 2, 3]

    # segunda chamada: tudo em cache, nenhuma requisição nova
    calls.clear()
    result_again = ingest.fetch_all(urls, concurrency=2, cache_dir=tmp_path)
    assert calls == []
    assert result_again == result


def test_fetch_all_respects_concurrency_limit(tmp_path, monkeypatch):
    in_flight = {"current": 0, "max": 0}
    lock = asyncio.Lock()

    async def slow_handler(request: httpx.Request) -> httpx.Response:
        async with lock:
            in_flight["current"] += 1
            in_flight["max"] = max(in_flight["max"], in_flight["current"])
        await asyncio.sleep(0.02)
        async with lock:
            in_flight["current"] -= 1
        pokemon_id = ingest.extract_id(str(request.url))
        return httpx.Response(200, json={"id": pokemon_id})

    monkeypatch.setattr(httpx, "AsyncClient", _async_client_factory(slow_handler))

    urls = [f"https://pokeapi.co/api/v2/pokemon/{i}/" for i in range(1, 11)]

    ingest.fetch_all(urls, concurrency=3, cache_dir=tmp_path)

    assert in_flight["max"] <= 3


def test_fetch_all_sends_user_agent(tmp_path, monkeypatch):
    captured_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(request.headers)
        pokemon_id = ingest.extract_id(str(request.url))
        return httpx.Response(200, json={"id": pokemon_id})

    monkeypatch.setattr(httpx, "AsyncClient", _async_client_factory(handler))

    ingest.fetch_all(["https://pokeapi.co/api/v2/pokemon/1/"], cache_dir=tmp_path)

    assert captured_headers.get("user-agent") == ingest.USER_AGENT


def test_fetch_all_works_when_called_from_a_running_event_loop(tmp_path, monkeypatch):
    """Regressão: dentro de um kernel Jupyter/IPython já existe um event loop rodando,
    e `fetch_all` (síncrona) precisa continuar funcionando quando chamada de lá — sem
    isso, um `asyncio.run()` direto levantaria `RuntimeError: cannot be called from a
    running event loop` (foi exatamente o que aconteceu ao rodar o notebook.ipynb)."""

    def handler(request: httpx.Request) -> httpx.Response:
        pokemon_id = ingest.extract_id(str(request.url))
        return httpx.Response(200, json={"id": pokemon_id})

    monkeypatch.setattr(httpx, "AsyncClient", _async_client_factory(handler))

    async def _caller_with_running_loop():
        # fetch_all é síncrona (não "await fetch_all(...)") — o ponto do teste é
        # chamá-la de dentro de uma coroutine já em execução num loop ativo.
        return ingest.fetch_all(
            ["https://pokeapi.co/api/v2/pokemon/1/"], cache_dir=tmp_path
        )

    result = asyncio.run(_caller_with_running_loop())

    assert result == [{"id": 1}]


# ---------------------------------------------------------------------------
# helpers de mock
# ---------------------------------------------------------------------------


async def _fast_sleep(_seconds: float) -> None:
    return None


def _no_op_sleep(_seconds: float) -> None:
    return None


_RealClient = httpx.Client
_RealAsyncClient = httpx.AsyncClient


def _client_factory(handler):
    """Fábrica de um httpx.Client substituto, plugado com MockTransport."""

    def _factory(*_args, **kwargs):
        kwargs.pop("transport", None)
        return _RealClient(transport=httpx.MockTransport(handler), **kwargs)

    return _factory


def _async_client_factory(handler):
    """Fábrica de um httpx.AsyncClient substituto, plugado com MockTransport."""

    def _factory(*_args, **kwargs):
        kwargs.pop("transport", None)
        return _RealAsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    return _factory
