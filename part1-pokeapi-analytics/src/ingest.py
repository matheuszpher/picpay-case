"""Coleta assíncrona da PokeAPI com cache bronze (ADR-0006). Sem Spark aqui de propósito."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path

import httpx

BASE_URL = "https://pokeapi.co/api/v2"
USER_AGENT = "picpay-ml-case-part1/0.1 (github.com/picpay-ml-case)"
DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_RETRIES = 5
BACKOFF_BASE_SECONDS = 0.5

logger = logging.getLogger(__name__)


def fetch_index(page_size: int = 100, max_items: int | None = None) -> list[dict]:
    """Pagina GET /pokemon até esgotar (ou até max_items). Retorna [{name, url}, ...]."""
    results: list[dict] = []
    url: str | None = f"{BASE_URL}/pokemon"
    params: dict | None = {"limit": page_size, "offset": 0}

    with httpx.Client(
        timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT}
    ) as client:
        while url is not None:
            payload = _get_with_retry_sync(client, url, params=params)
            results.extend(payload["results"])
            if max_items is not None and len(results) >= max_items:
                return results[:max_items]
            url = payload.get("next")
            params = None  # 'next' já vem com a querystring completa

    return results


def _get_with_retry_sync(
    client: httpx.Client,
    url: str,
    params: dict | None = None,
    max_retries: int = MAX_RETRIES,
    backoff_base: float = BACKOFF_BASE_SECONDS,
) -> dict:
    for attempt in range(max_retries + 1):
        try:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            if (
                exc.response.status_code not in RETRYABLE_STATUS_CODES
                or attempt == max_retries
            ):
                raise
        except httpx.RequestError:
            if attempt == max_retries:
                raise
        delay = backoff_base * (2**attempt)
        logger.warning(
            "retry %s/%s for %s in %.1fs", attempt + 1, max_retries, url, delay
        )
        time.sleep(delay)

    raise RuntimeError("unreachable")  # pragma: no cover


def extract_id(url: str) -> int:
    """Extrai o id numérico do final de uma URL /pokemon/{id}/."""
    return int(url.rstrip("/").rsplit("/", 1)[-1])


async def fetch_detail(
    client: httpx.AsyncClient, url: str, cache_dir: str | Path
) -> dict:
    """Detalhe de um pokémon; lê do cache bronze se existir, senão busca e grava (idempotente)."""
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    cache_file = cache_path / f"{extract_id(url)}.json"

    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    data = await _get_with_retry(client, url)
    tmp = cache_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(cache_file)
    return data


async def _get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    max_retries: int = MAX_RETRIES,
    backoff_base: float = BACKOFF_BASE_SECONDS,
) -> dict:
    for attempt in range(max_retries + 1):
        try:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            if (
                exc.response.status_code not in RETRYABLE_STATUS_CODES
                or attempt == max_retries
            ):
                raise
        except httpx.RequestError:
            if attempt == max_retries:
                raise
        delay = backoff_base * (2**attempt)
        logger.warning(
            "retry %s/%s for %s in %.1fs", attempt + 1, max_retries, url, delay
        )
        await asyncio.sleep(delay)

    raise RuntimeError("unreachable")  # pragma: no cover


def fetch_all(
    urls: list[str], concurrency: int = 10, cache_dir: str | Path = "data/bronze"
) -> list[dict]:
    """Coleta concorrente (semáforo) dos detalhes; ordem preservada, idempotente via cache bronze."""
    return asyncio.run(_fetch_all_async(urls, concurrency, cache_dir))


async def _fetch_all_async(
    urls: list[str], concurrency: int, cache_dir: str | Path
) -> list[dict]:
    semaphore = asyncio.Semaphore(concurrency)

    async def _bound_fetch(client: httpx.AsyncClient, url: str) -> dict:
        async with semaphore:
            return await fetch_detail(client, url, cache_dir)

    async with httpx.AsyncClient(
        timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT}
    ) as client:
        return await asyncio.gather(*(_bound_fetch(client, url) for url in urls))


def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Ingestão bronze da PokeAPI")
    parser.add_argument(
        "--max-items", type=int, default=None, help="limita a coleta (dev)"
    )
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--cache-dir", default="data/bronze")
    args = parser.parse_args()

    index = fetch_index(max_items=args.max_items)
    urls = [entry["url"] for entry in index]
    details = fetch_all(urls, concurrency=args.concurrency, cache_dir=args.cache_dir)
    logger.info(
        "coletados %d/%d pokémons em %s", len(details), len(urls), args.cache_dir
    )


if __name__ == "__main__":
    _main()
