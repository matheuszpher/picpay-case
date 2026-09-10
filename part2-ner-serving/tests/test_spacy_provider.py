"""Testes de src/nercore/providers/spacy_provider.py.

`en_core_web_sm` é dependência normal do pyproject.toml (pinada por URL de wheel), não
uma dependência só de teste: carregar o pacote local dentro de um teste é leitura de
disco, não uma chamada de rede (mesma categoria de "importar pyspark" na Parte 1). Só
o caminho de download de um modelo NÃO instalado é mockado abaixo.
"""

from __future__ import annotations

import pytest

from src.nercore.providers.base import ModelLoadError, NERProvider
from src.nercore.providers.spacy_provider import SpacyNERProvider
from src.nercore.schemas import Entity


def test_ner_provider_is_abstract():
    with pytest.raises(TypeError):
        NERProvider()  # type: ignore[abstract]


def test_load_marks_model_as_loaded(spacy_provider):
    assert spacy_provider.is_loaded("en_core_web_sm")
    assert not spacy_provider.is_loaded("en_core_web_md")


def test_predict_maps_spacy_entities_to_entity_schema(spacy_provider):
    entities = spacy_provider.predict("Elon Musk foi para o Brasil em 2024.")

    assert all(isinstance(e, Entity) for e in entities)
    labels = {e.label for e in entities}
    # en_core_web_sm reconhece pessoa/local/data de forma confiável neste texto.
    assert labels & {"PERSON", "GPE", "DATE"}


def test_predict_entity_offsets_match_text(spacy_provider):
    text = "Bill Gates works at Microsoft."
    entities = spacy_provider.predict(text)

    for entity in entities:
        assert text[entity.start_char : entity.end_char] == entity.text


def test_predict_before_load_raises():
    provider = SpacyNERProvider()
    with pytest.raises(RuntimeError):
        provider.predict("qualquer texto")


def test_load_downloads_when_model_not_installed(monkeypatch):
    provider = SpacyNERProvider()
    download_calls: list[str] = []

    monkeypatch.setattr(
        "src.nercore.providers.spacy_provider.is_package", lambda name: False
    )
    monkeypatch.setattr(
        "src.nercore.providers.spacy_provider.spacy.cli.download",
        lambda name: download_calls.append(name),
    )
    monkeypatch.setattr(
        "src.nercore.providers.spacy_provider.spacy.load", lambda name: object()
    )

    provider.load("en_core_web_sm")

    assert download_calls == ["en_core_web_sm"]
    assert provider.is_loaded("en_core_web_sm")


def test_load_raises_model_load_error_when_download_fails(monkeypatch):
    provider = SpacyNERProvider()

    monkeypatch.setattr(
        "src.nercore.providers.spacy_provider.is_package", lambda name: False
    )

    def _fail(name: str):
        raise SystemExit(1)

    monkeypatch.setattr(
        "src.nercore.providers.spacy_provider.spacy.cli.download", _fail
    )

    with pytest.raises(ModelLoadError):
        provider.load("modelo-que-nao-existe")
