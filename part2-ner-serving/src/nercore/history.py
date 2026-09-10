"""Histórico de predições persistido em SQLite, atrás de uma interface (ADR-0005).

Uma conexão é aberta e fechada a cada chamada, em vez de mantida aberta entre
chamadas: o volume de escrita esperado é baixo (uma linha por predição) e evita
compartilhar uma conexão SQLite entre threads do servidor ASGI.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from src.nercore.schemas import Entity, PredictionRecord

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    input TEXT NOT NULL,
    output TEXT NOT NULL,
    model TEXT NOT NULL,
    timestamp TEXT NOT NULL
)
"""

# Índice em (timestamp, model): /list é read-heavy (ADR-0005) e ordena por timestamp;
# incluir model no índice também favorece um futuro filtro por modelo sem exigir novo
# índice.
_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_predictions_timestamp_model
ON predictions (timestamp, model)
"""


class PredictionHistory:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE)
            conn.execute(_CREATE_INDEX)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def add(
        self, input: str, output: list[Entity], model: str, timestamp: datetime
    ) -> int:
        output_json = json.dumps([entity.model_dump() for entity in output])
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO predictions (input, output, model, timestamp) "
                "VALUES (?, ?, ?, ?)",
                (input, output_json, model, timestamp.isoformat()),
            )
            return cursor.lastrowid

    def list(self, limit: int = 100, offset: int = 0) -> list[PredictionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, input, output, model, timestamp FROM predictions "
                "ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [
            PredictionRecord(
                id=row[0],
                input=row[1],
                output=[Entity(**entity) for entity in json.loads(row[2])],
                model=row[3],
                timestamp=datetime.fromisoformat(row[4]),
            )
            for row in rows
        ]
