from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RedisSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REDIS_", extra="ignore")

    host: str = Field(default="localhost")
    port: int = Field(default=6379)
    password: Optional[str] = Field(default=None)
    db: int = Field(default=0)
    stream_max_len: int = Field(default=100_000)
    consumer_group: str = Field(default="nexusflow-workers")

    @property
    def url(self) -> str:
        if self.password:
            return f"redis://:{self.password}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="POSTGRES_", extra="ignore")

    host: str = Field(default="localhost")
    port: int = Field(default=5432)
    user: str = Field(default="nexusflow")
    password: str = Field(default="nexusflow_dev")
    db: str = Field(default="nexusflow")
    pool_size: int = Field(default=20)
    max_overflow: int = Field(default=10)
    pool_timeout: int = Field(default=30)

    @property
    def dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.db}"
        )


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLM_", extra="ignore")

    provider: str = Field(default="openai")
    openai_api_key: Optional[str] = Field(default=None)
    openai_model: str = Field(default="gpt-4o")
    openai_base_url: Optional[str] = Field(default=None)
    local_base_url: Optional[str] = Field(default=None)
    local_model: Optional[str] = Field(default=None)
    max_tokens_per_task: int = Field(default=50_000)
    cost_alert_threshold_usd: float = Field(default=1.0)


class OrchestratorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ORCHESTRATOR_", extra="ignore")

    max_concurrent_subtasks: int = Field(default=10)
    max_retries: int = Field(default=3)
    retry_base_delay: float = Field(default=2.0)
    task_timeout_seconds: int = Field(default=300)
    heartbeat_interval_seconds: int = Field(default=30)


class BatchingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BATCHING_", extra="ignore")

    window_ms: int = Field(default=100)
    max_batch_size: int = Field(default=20)
    min_batch_size: int = Field(default=5)


class GatewaySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GATEWAY_", extra="ignore")

    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    debug: bool = Field(default=False)
    rate_limit_rpm: int = Field(default=60)
    jwt_secret: str = Field(default="CHANGE_ME_IN_PRODUCTION")
    jwt_algorithm: str = Field(default="HS256")
    jwt_expire_minutes: int = Field(default=60 * 24)


class StreamingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STREAMING_", extra="ignore")

    port: int = Field(default=8001)
    max_connections: int = Field(default=500)
    ws_ping_interval: int = Field(default=20)
    buffer_size: int = Field(default=100)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")
    service_name: str = Field(default="nexusflow")

    redis: RedisSettings = Field(default_factory=RedisSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    orchestrator: OrchestratorSettings = Field(default_factory=OrchestratorSettings)
    batching: BatchingSettings = Field(default_factory=BatchingSettings)
    gateway: GatewaySettings = Field(default_factory=GatewaySettings)
    streaming: StreamingSettings = Field(default_factory=StreamingSettings)

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        allowed = {"development", "staging", "production"}
        if v not in allowed:
            raise ValueError(f"environment must be one of {allowed}")
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton. Call get_settings.cache_clear() in tests."""
    return Settings()
