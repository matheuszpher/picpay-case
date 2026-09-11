"""Testes de src/api/observability.py: logs JSON e métricas Prometheus (ADR-0009,
ADR-0014).
"""

from __future__ import annotations

import json
import logging
import sys

from src.api.observability import (
    CACHE_REQUESTS_TOTAL,
    PREDICT_LATENCY_SECONDS,
    PREDICTIONS_TOTAL,
    JSONFormatter,
    record_prediction,
)


def _make_record(
    level: int = logging.INFO, msg: str = "mensagem", exc_info=None, **extra
) -> logging.LogRecord:
    record = logging.LogRecord(
        name="ner_serving",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=exc_info,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def _sample_value(metric, suffix: str, **labels) -> float:
    for family in metric.collect():
        for sample in family.samples:
            if sample.name.endswith(suffix) and sample.labels == labels:
                return sample.value
    return 0.0


# --- JSONFormatter ---


def test_json_formatter_includes_standard_and_extra_fields():
    record = _make_record(msg="http_request", request_id="abc-123", status_code=200)

    payload = json.loads(JSONFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "ner_serving"
    assert payload["message"] == "http_request"
    assert payload["request_id"] == "abc-123"
    assert payload["status_code"] == 200
    assert "timestamp" in payload


def test_json_formatter_without_extra_only_has_standard_fields():
    record = _make_record(msg="oi")

    payload = json.loads(JSONFormatter().format(record))

    assert set(payload.keys()) == {"timestamp", "level", "logger", "message"}


def test_json_formatter_includes_exception_traceback():
    try:
        raise ValueError("boom")
    except ValueError:
        record = _make_record(
            level=logging.ERROR, msg="falhou", exc_info=sys.exc_info()
        )

    payload = json.loads(JSONFormatter().format(record))

    assert "ValueError: boom" in payload["exc_info"]


def test_json_formatter_output_is_a_single_json_line():
    record = _make_record(msg='mensagem com "aspas" e \n quebra de linha')

    output = JSONFormatter().format(record)

    assert len(output.splitlines()) == 1
    json.loads(output)  # não levanta


# --- métricas Prometheus ---


def test_record_prediction_increments_predictions_counter():
    record_prediction(model="obs-model-1", cached=False, duration_seconds=0.05)

    assert _sample_value(PREDICTIONS_TOTAL, "_total", model="obs-model-1") == 1


def test_record_prediction_observes_latency_histogram():
    record_prediction(model="obs-model-2", cached=False, duration_seconds=0.05)

    assert _sample_value(PREDICT_LATENCY_SECONDS, "_count", model="obs-model-2") == 1


def test_record_prediction_tracks_cache_hit_and_miss_separately():
    record_prediction(model="obs-model-3", cached=True, duration_seconds=0.01)
    record_prediction(model="obs-model-3", cached=False, duration_seconds=0.02)

    hits = _sample_value(
        CACHE_REQUESTS_TOTAL, "_total", model="obs-model-3", result="hit"
    )
    misses = _sample_value(
        CACHE_REQUESTS_TOTAL, "_total", model="obs-model-3", result="miss"
    )
    assert hits == 1
    assert misses == 1
