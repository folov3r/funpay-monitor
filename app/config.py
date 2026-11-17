"""Application settings loaded from environment variables and `.env`."""

from __future__ import annotations

import contextlib
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
    vk_admin_ids: str = ""

    database_url: str = "postgresql+asyncpg://funpay:funpay@localhost:5432/funpay"

    #: Local API used by the desktop window and the browser UI.
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8765, ge=1, le=65535)
    #: Run the parse scheduler inside the API process (desktop build).
    scheduler_enabled: bool = True
    #: User id that owns subscriptions created from the desktop UI.
    local_user_vk_id: int = 0
    #: Days of price history returned by the API and used by alerts.
    history_days: int = Field(default=7, ge=1)
    #: Override the per-user directory for the SQLite file (desktop build).
    data_dir: str = ""

    parse_interval_minutes: int = Field(default=15, ge=1)
    request_delay_seconds: float = Field(default=3.0, ge=0)
    alert_cooldown_hours: int = Field(default=6, ge=0)
    #: Delete the /add dialog messages after a subscription is saved. Kept as a
    #: flag so the cleanup can be rolled back without touching the handlers.
    chat_cleanup_enabled: bool = True

    def admin_vk_ids(self) -> frozenset[int]:
        """Parse ``VK_ADMIN_IDS`` as a comma/space separated set of VK ids."""
        ids: set[int] = set()
        for chunk in self.vk_admin_ids.replace(",", " ").split():
            with contextlib.suppress(ValueError):
                ids.add(int(chunk))
        return frozenset(ids)


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
