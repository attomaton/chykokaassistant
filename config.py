"""Centralized application settings, read from environment variables only.

Never hardcode secrets here. Every field below is sourced from the process
environment (optionally via a local .env file for development).
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Required secrets / identifiers ---
    telegram_bot_token: str
    telegram_webhook_secret: str
    openai_api_key: str
    database_url: str

    # --- Administrator bootstrap ---
    admin_setup_secret: str | None = None
    admin_telegram_id: int | None = None

    # --- App ---
    app_url: str = ""
    environment: str = "development"

    # --- AI tuning ---
    openai_model: str = "gpt-5-mini"
    ai_confidence_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    openai_timeout_seconds: float = 20.0

    # --- Knowledge base ---
    business_md_path: str = "data/business.md"
    max_knowledge_characters: int = 80_000

    # --- Conversation context ---
    max_conversation_turns: int = 10
    conversation_ttl_minutes: int = 180

    # --- Limits ---
    max_message_length: int = 2000
    rate_limit_messages_per_minute: int = 15
    telegram_timeout_seconds: float = 15.0

    @field_validator("admin_setup_secret", "admin_telegram_id", "app_url", mode="before")
    @classmethod
    def _blank_to_none(cls, value):
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
