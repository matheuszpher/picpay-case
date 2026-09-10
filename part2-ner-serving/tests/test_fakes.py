"""Testes de tests/fakes.py: o FakeProvider precisa se comportar como um NERProvider real
o bastante para os testes de registry/service/api (fases seguintes) confiarem nele.
"""

from __future__ import annotations

import pytest

from src.nercore.providers.base import ModelLoadError, NERProvider
from src.nercore.schemas import Entity
from tests.fakes import FakeProvider


def test_fake_provider_is_a_ner_provider():
    assert isinstance(FakeProvider(), NERProvider)


def test_load_then_is_loaded():
    provider = FakeProvider()

    assert not provider.is_loaded("modelo-x")
    provider.load("modelo-x")
    assert provider.is_loaded("modelo-x")
    assert provider.load_calls == ["modelo-x"]


def test_predict_returns_configured_entities_and_records_calls():
    entities = [Entity(label="PERSON", text="Ana", start_char=0, end_char=3)]
    provider = FakeProvider(entities=entities)

    result = provider.predict("Ana foi ao mercado")

    assert result == entities
    assert provider.predict_calls == ["Ana foi ao mercado"]


def test_raise_on_load_simulates_download_failure():
    provider = FakeProvider(raise_on_load=True)

    with pytest.raises(ModelLoadError):
        provider.load("modelo-x")
    assert not provider.is_loaded("modelo-x")
