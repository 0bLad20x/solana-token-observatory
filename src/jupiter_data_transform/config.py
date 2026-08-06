from __future__ import annotations

from functools import cached_property

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or a local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = Field(alias="DATABASE_URL")
    jupiter_api_keys_raw: str = Field(alias="JUPITER_API_KEYS")
    jupiter_base_url: str = Field(default="https://api.jup.ag", alias="JUPITER_BASE_URL")
    jupiter_request_timeout_seconds: float = Field(
        default=20.0,
        gt=0,
        alias="JUPITER_REQUEST_TIMEOUT_SECONDS",
    )
    collect_interval_seconds: float = Field(
        default=60.0,
        gt=0,
        alias="COLLECT_INTERVAL_SECONDS",
    )

    @field_validator("database_url", "jupiter_api_keys_raw")
    @classmethod
    def reject_blank_values(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @cached_property
    def jupiter_api_keys(self) -> tuple[str, ...]:
        keys = tuple(key.strip() for key in self.jupiter_api_keys_raw.split(",") if key.strip())
        if not keys:
            raise ValueError("JUPITER_API_KEYS must contain at least one API key")
        return keys
