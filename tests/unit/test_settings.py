import os
from unittest.mock import patch
import pytest

from nexusflow.shared.config.settings import get_settings, Settings


def test_default_settings(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.delenv("REDIS_HOST", raising=False)
    monkeypatch.delenv("REDIS_PORT", raising=False)
    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    monkeypatch.delenv("POSTGRES_PORT", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    settings = get_settings()
    assert settings.environment == "development"
    assert settings.is_production is False
    assert settings.redis.host == "localhost"
    assert settings.redis.port == 6379
    assert settings.database.host == "localhost"
    assert settings.database.port == 5432
    get_settings.cache_clear()


def test_redis_url_property(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.delenv("REDIS_HOST", raising=False)
    monkeypatch.delenv("REDIS_PORT", raising=False)

    settings = get_settings()
    assert settings.redis.url == "redis://localhost:6379/0"

    settings.redis.password = "secret"
    assert settings.redis.url == "redis://:secret@localhost:6379/0"
    settings.redis.password = None
    get_settings.cache_clear()


def test_postgres_dsn_property():
    get_settings.cache_clear()
    settings = get_settings()
    assert "postgresql+asyncpg://" in settings.database.dsn
    assert "nexusflow" in settings.database.dsn
    get_settings.cache_clear()


def test_settings_validation_invalid_env():
    with pytest.raises(ValueError, match="environment must be one of"):
        Settings(environment="invalid-env")

