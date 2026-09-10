"""Modelos de domínio compartilhados entre REST e MCP (ADR-0002, ADR-0003).

Pydantic é usado aqui não por validação de request (isso é papel do transporte REST),
mas porque o mesmo modelo de dados precisa atravessar nercore -> api -> mcp_server sem
duplicação de forma. `LoadRequest` e `PredictRequest` são os únicos dois pensados como
corpo de requisição; os demais são objetos de domínio devolvidos pelo core.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class Entity(BaseModel):
    label: str
    text: str
    start_char: int
    end_char: int


class PredictResult(BaseModel):
    model: str
    entities: list[Entity]
    cached: bool


class ModelInfo(BaseModel):
    name: str
    loaded: bool
    is_active: bool


class PredictionRecord(BaseModel):
    id: int
    input: str
    output: list[Entity]
    model: str
    timestamp: datetime


class LoadRequest(BaseModel):
    model: str


class PredictRequest(BaseModel):
    text: str
    model: str | None = None
