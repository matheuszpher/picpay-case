"""Transporte MCP: fino, expõe `extract_entities` reusando `nercore.service` (ADR-0003).

Cenário: o assistente de PIX por WhatsApp do PicPay recebe uma mensagem do usuário
("manda 50 pra Maria amanhã") e usa esta tool para extrair entidades (PERSON, MONEY,
DATE) antes de montar a transação. Nenhuma lógica de negócio vive aqui: a mesma
`NERService` que a API REST usa (fase 2.4) é reaproveitada sem duplicação.
"""

from __future__ import annotations

import logging

from fastmcp import FastMCP

from src.nercore.cache import build_cache
from src.nercore.config import settings
from src.nercore.history import PredictionHistory
from src.nercore.providers.base import ModelLoadError
from src.nercore.providers.spacy_provider import SpacyNERProvider
from src.nercore.registry import ModelRegistry
from src.nercore.schemas import Entity
from src.nercore.service import NERService

logger = logging.getLogger(__name__)

mcp = FastMCP(name="picpay-ner-serving")

_service: NERService | None = None


def _build_service() -> NERService:
    registry = ModelRegistry(provider_factory=SpacyNERProvider)
    history = PredictionHistory(settings.HISTORY_DB_PATH)
    cache = build_cache(settings.CACHE_BACKEND, settings.REDIS_URL)
    return NERService(registry=registry, history=history, cache=cache)


def _get_service() -> NERService:
    """Constrói o `NERService` só no primeiro uso (não no import do módulo), e tenta
    pré-carregar o modelo default uma única vez com a mesma tolerância a falha da API
    REST (fase 2.4, decisão de design nº 5): se não der, o processo MCP continua no
    ar, e quem chamar `extract_entities` sem `model` recebe o erro do `NERService`
    (`NoActiveModelError`, traduzido pelo fastmcp em `ToolError`), não um processo
    derrubado.
    """
    global _service
    if _service is None:
        _service = _build_service()
        try:
            _service.load(settings.DEFAULT_MODEL)
        except ModelLoadError:
            logger.exception(
                "falha ao pré-carregar o modelo default '%s' no primeiro uso do MCP",
                settings.DEFAULT_MODEL,
            )
    return _service


@mcp.tool
def extract_entities(text: str, model: str | None = None) -> list[Entity]:
    """Extrai entidades nomeadas (pessoas, valores, datas, locais) de um texto.

    Reusa a mesma lógica da API REST (`POST /predict/`): cache, histórico e
    lazy-load de modelo funcionam exatamente da mesma forma aqui.
    """
    service = _get_service()
    result = service.predict(text, model=model)
    return result.entities


if __name__ == "__main__":
    # Transporte stdio (padrão de mcp.run()): é o que ferramentas como
    # `fastmcp run/list/call` e clientes de desktop (Claude Desktop) esperam ao
    # apontar para este arquivo diretamente. Sem isto, o arquivo só define os
    # objetos e termina, sem nunca falar o protocolo MCP.
    mcp.run()
