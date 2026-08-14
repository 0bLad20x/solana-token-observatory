import os
from dataclasses import dataclass
from pathlib import Path

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
    jupiter_search_api_keys: list[str]
    jupiter_recent_api_key: str
    jupiter_base_url: str
    jupiter_calls_per_minute: float
    pumpportal_api_key: str
    request_timeout_seconds: float
    discovery_interval_seconds: float
    pumpfun_batch_interval_seconds: float

    @property
    def jupiter_seconds_per_key(self) -> float:
        return 60.0 / self.jupiter_calls_per_minute

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(dotenv_path=Path.cwd() / ".env")
        search_keys = [
            key.strip()
            for key in _required("JUPITER_SEARCH_API_KEYS").splitlines()
            if key.strip()
        ]
        return cls(
            database_url=_required("DATABASE_URL"),
            jupiter_search_api_keys=search_keys,
            jupiter_recent_api_key=_required("JUPITER_RECENT_API_KEY"),
            jupiter_base_url=os.getenv("JUPITER_BASE_URL", "https://api.jup.ag").rstrip("/"),
            jupiter_calls_per_minute=_positive_float("JUPITER_CALLS_PER_MINUTE", "58"),
            pumpportal_api_key=_required("PUMPPORTAL_API_KEY"),
            request_timeout_seconds=_positive_float("JUPITER_REQUEST_TIMEOUT_SECONDS", "20"),
            discovery_interval_seconds=_positive_float("DISCOVERY_INTERVAL_SECONDS", "30"),
            pumpfun_batch_interval_seconds=_positive_float("PUMPFUN_BATCH_INTERVAL_SECONDS", "10"),
        )
