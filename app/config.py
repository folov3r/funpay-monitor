"""Application settings loaded from environment variables and `.env`."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    log_level: str = "INFO"

    vk_group_token: str = ""
    vk_group_id: int = 0

    database_url: str = "postgresql+asyncpg://funpay:funpay@localhost:5432/funpay"

    parse_interval_minutes: int = Field(default=15, ge=1)
    request_delay_seconds: float = Field(default=3.0, ge=0)
    alert_cooldown_hours: int = Field(default=6, ge=0)


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
