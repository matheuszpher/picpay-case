"""Fixtures compartilhadas entre os testes (ADR-0002, ADR-0011).

O modelo spaCy real é uma dependência instalada (en-core-web-sm, pinada no
pyproject.toml), não um download em tempo de teste. Carregá-lo ainda tem custo
perceptível (~200ms-1s), por isso o escopo de sessão evita recarregar a cada teste,
mesmo padrão da fixture `spark` na Parte 1.
"""

from __future__ import annotations

import pytest

from src.nercore.providers.spacy_provider import SpacyNERProvider


@pytest.fixture(scope="session")
def spacy_provider() -> SpacyNERProvider:
    provider = SpacyNERProvider()
    provider.load("en_core_web_sm")
    return provider
