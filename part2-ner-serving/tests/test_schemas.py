"""Testes de src/nercore/schemas.py: os modelos de domínio compartilhados por REST e MCP."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from src.nercore.schemas import (
    Entity,
    LoadRequest,
    ModelInfo,
    PredictionRecord,
    PredictRequest,
    PredictResult,
)


def test_entity_holds_span_and_label():
    entity = Entity(label="PERSON", text="Elon Musk", start_char=0, end_char=9)

    assert entity.label == "PERSON"
    assert entity.text == "Elon Musk"
    assert entity.start_char == 0
    assert entity.end_char == 9


def test_predict_result_groups_entities_with_cache_flag():
    result = PredictResult(
        model="en_core_web_sm",
        entities=[Entity(label="GPE", text="Brasil", start_char=0, end_char=6)],
        cached=True,
    )

    assert result.model == "en_core_web_sm"
    assert result.cached is True
    assert len(result.entities) == 1


def test_model_info_flags():
    info = ModelInfo(name="en_core_web_sm", loaded=True, is_active=False)

    assert info.loaded is True
    assert info.is_active is False


def test_prediction_record_requires_timestamp():
    record = PredictionRecord(
        id=1,
        input="Elon Musk foi ao Brasil",
        output=[],
        model="en_core_web_sm",
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
    )

    assert record.id == 1
    assert record.output == []
    assert isinstance(record.timestamp, datetime)


def test_predict_request_model_is_optional():
    request = PredictRequest(text="qualquer texto")

    assert request.model is None


def test_load_request_requires_model():
    with pytest.raises(ValidationError):
        LoadRequest()  # type: ignore[call-arg]
