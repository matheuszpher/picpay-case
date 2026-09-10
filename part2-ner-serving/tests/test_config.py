"""Testes de src/nercore/config.py: defaults e override via variável de ambiente."""

from __future__ import annotations

from src.nercore.config import Settings


def test_settings_defaults():
    settings = Settings(_env_file=None)

    assert settings.DEFAULT_MODEL == "en_core_web_sm"
    assert settings.CACHE_BACKEND == "memory"
    assert settings.HISTORY_DB_PATH == "data/history.db"
    assert settings.LOG_LEVEL == "INFO"


def test_settings_override_via_env(monkeypatch):
    monkeypatch.setenv("DEFAULT_MODEL", "en_core_web_lg")
    monkeypatch.setenv("CACHE_BACKEND", "redis")

    settings = Settings(_env_file=None)

    assert settings.DEFAULT_MODEL == "en_core_web_lg"
    assert settings.CACHE_BACKEND == "redis"
