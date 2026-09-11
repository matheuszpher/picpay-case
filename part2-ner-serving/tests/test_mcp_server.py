"""Testes de src/mcp_server/server.py: tool MCP extract_entities (ADR-0003).

FakeProvider isola de spaCy real. `extract_entities` é chamada diretamente como
função Python (o decorador `@mcp.tool` não envolve a função original, só anexa
metadados, confirmado inspecionando `fastmcp` antes de escrever este arquivo) e
também uma vez via `fastmcp.Client` em memória, para provar que o protocolo MCP de
verdade também funciona, não só a chamada direta.
"""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

import src.mcp_server.server as server_module
from src.mcp_server.server import extract_entities, mcp
from src.nercore.cache import InMemoryLRUCache
from src.nercore.history import PredictionHistory
from src.nercore.registry import ModelRegistry
from src.nercore.schemas import Entity
from src.nercore.service import EmptyTextError, NERService, NoActiveModelError
from tests.fakes import FakeProvider


@pytest.fixture
def fake_service(tmp_path, monkeypatch):
    entities = [Entity(label="MONEY", text="R$ 50", start_char=6, end_char=11)]

    def factory() -> FakeProvider:
        return FakeProvider(entities=entities)

    registry = ModelRegistry(provider_factory=factory)
    history = PredictionHistory(tmp_path / "history.db")
    cache = InMemoryLRUCache()
    service = NERService(registry=registry, history=history, cache=cache)
    service.load("model-a")

    monkeypatch.setattr(server_module, "_service", service)
    return service, entities


def test_extract_entities_direct_call_returns_entities(fake_service):
    _, entities = fake_service

    result = extract_entities("manda R$ 50 pra Maria")

    assert result == entities


def test_extract_entities_uses_explicit_model_and_records_history(fake_service):
    service, _ = fake_service

    extract_entities("texto", model="model-a")

    records = service.list_predictions()
    assert len(records) == 1
    assert records[0].model == "model-a"


def test_extract_entities_empty_text_raises(fake_service):
    with pytest.raises(EmptyTextError):
        extract_entities("   ")


def test_extract_entities_without_active_model_raises(tmp_path, monkeypatch):
    def factory() -> FakeProvider:
        return FakeProvider()

    registry = ModelRegistry(provider_factory=factory)
    history = PredictionHistory(tmp_path / "history.db")
    cache = InMemoryLRUCache()
    service = NERService(registry=registry, history=history, cache=cache)
    monkeypatch.setattr(server_module, "_service", service)

    with pytest.raises(NoActiveModelError):
        extract_entities("texto sem modelo ativo")


def test_extract_entities_via_mcp_wire(fake_service):
    async def _call():
        async with Client(mcp) as client:
            return await client.call_tool("extract_entities", {"text": "manda R$ 50"})

    result = asyncio.run(_call())

    assert result.data[0].label == "MONEY"
    assert result.data[0].text == "R$ 50"


def test_extract_entities_via_mcp_wire_wraps_domain_errors_in_tool_error(
    fake_service,
):
    async def _call():
        async with Client(mcp) as client:
            return await client.call_tool("extract_entities", {"text": "   "})

    with pytest.raises(ToolError):
        asyncio.run(_call())
