"""Application settings (environment variables / .env). Secrets are SecretStr and never printed."""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    trusthost_base_url: str = "https://my.trusthost.ir/api/v1"
    trusthost_api_key: SecretStr
    trusthost_api_secret: SecretStr
    telegram_bot_token: SecretStr
    admin_telegram_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)

    database_url: str = "sqlite+aiosqlite:///./data/bot.db"
    log_level: str = "INFO"
    log_json: bool = True

    trusthost_timeout_seconds: float = Field(default=15.0, gt=0)
    # TrustHost allows 60 req/min for keys without an IP allow-list. Keep headroom.
    trusthost_max_requests_per_minute: int = Field(default=50, ge=1, le=100000)
    notification_poll_minutes: int = Field(default=5, ge=1, le=1440)
    default_language: str = "en"

    @field_validator("admin_telegram_ids", mode="before")
    @classmethod
    def _parse_ids(cls, v: object) -> list[int]:
        if v is None or v == "":
            ids: list[int] = []
        elif isinstance(v, int):
            ids = [v]
        elif isinstance(v, (list, tuple)):
            ids = [int(x) for x in v]
        else:
            raw = str(v).strip()
            if raw.startswith("["):
                ids = [int(x) for x in json.loads(raw)]
            else:
                ids = [int(x) for x in raw.replace(";", ",").split(",") if x.strip()]
        if not ids:
            raise ValueError("ADMIN_TELEGRAM_IDS must contain at least one Telegram user id")
        return ids

    @field_validator("trusthost_base_url")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @field_validator("database_url")
    @classmethod
    def _normalise_db(cls, v: str) -> str:
        if v.startswith("postgresql://"):
            return "postgresql+asyncpg://" + v[len("postgresql://"):]
        if v.startswith("postgres://"):
            return "postgresql+asyncpg://" + v[len("postgres://"):]
        return v

    @field_validator("default_language")
    @classmethod
    def _lang(cls, v: str) -> str:
        return v if v in ("fa", "en") else "en"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
