from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value


def _positive_float(name: str, default: str) -> float:
    value = float(os.getenv(name, default))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    jupiter_api_key: str
    jupiter_base_url: str
    request_timeout_seconds: float
    collect_interval_seconds: float

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        return cls(
            database_url=_required("DATABASE_URL"),
            jupiter_api_key=_required("JUPITER_API_KEY"),
            jupiter_base_url=os.getenv("JUPITER_BASE_URL", "https://api.jup.ag").rstrip("/"),
            request_timeout_seconds=_positive_float("JUPITER_REQUEST_TIMEOUT_SECONDS", "20"),
            collect_interval_seconds=_positive_float("COLLECT_INTERVAL_SECONDS", "60"),
        )
