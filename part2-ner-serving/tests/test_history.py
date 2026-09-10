"""Testes de src/nercore/history.py: persistência SQLite (ADR-0005)."""

from __future__ import annotations

from datetime import UTC, datetime

from src.nercore.history import PredictionHistory
from src.nercore.schemas import Entity


def _entities() -> list[Entity]:
    return [Entity(label="PERSON", text="Ana", start_char=0, end_char=3)]


def test_add_returns_incrementing_ids(tmp_path):
    history = PredictionHistory(tmp_path / "history.db")

    id1 = history.add("Ana foi", _entities(), "en_core_web_sm", datetime.now(UTC))
    id2 = history.add("Bea foi", _entities(), "en_core_web_sm", datetime.now(UTC))

    assert id2 > id1


def test_list_returns_records_most_recent_first(tmp_path):
    history = PredictionHistory(tmp_path / "history.db")
    older = datetime(2026, 1, 1, tzinfo=UTC)
    newer = datetime(2026, 1, 2, tzinfo=UTC)

    history.add("primeiro", _entities(), "en_core_web_sm", older)
    history.add("segundo", _entities(), "en_core_web_sm", newer)

    records = history.list()

    assert [r.input for r in records] == ["segundo", "primeiro"]
    assert records[0].output == _entities()
    assert records[0].model == "en_core_web_sm"


def test_list_respects_limit_and_offset(tmp_path):
    history = PredictionHistory(tmp_path / "history.db")
    for i in range(5):
        history.add(
            f"texto {i}",
            [],
            "en_core_web_sm",
            datetime(2026, 1, 1 + i, tzinfo=UTC),
        )

    page = history.list(limit=2, offset=1)

    assert [r.input for r in page] == ["texto 3", "texto 2"]


def test_history_persists_after_reopening_the_file(tmp_path):
    db_path = tmp_path / "history.db"
    history = PredictionHistory(db_path)
    history.add(
        "sobrevive ao restart",
        _entities(),
        "en_core_web_sm",
        datetime.now(UTC),
    )

    reopened = PredictionHistory(db_path)
    records = reopened.list()

    assert len(records) == 1
    assert records[0].input == "sobrevive ao restart"
