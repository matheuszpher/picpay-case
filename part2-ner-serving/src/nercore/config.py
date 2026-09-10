"""Configuração via variáveis de ambiente (pydantic-settings).

Arquivo novo, não fazia parte do esqueleto da Fase 0: `history.py` (HISTORY_DB_PATH) e
`cache.py` (CACHE_BACKEND/REDIS_URL) dependem de um lugar central pra ler essas
variáveis, então este módulo precisa existir antes deles (fase 2.1), mesmo a árvore
original do mini-spec não o listando como etapa própria.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", case_sensitive=True)

    DEFAULT_MODEL: str = "en_core_web_sm"
    CACHE_BACKEND: str = "memory"
    REDIS_URL: str = "redis://localhost:6379/0"
    HISTORY_DB_PATH: str = "data/history.db"
    LOG_LEVEL: str = "INFO"


settings = Settings()
