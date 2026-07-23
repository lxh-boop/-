from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _int_env(name: str, default: int, *, minimum: int = 1, maximum: int | None = None) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    value = max(minimum, value)
    return min(value, maximum) if maximum is not None else value


def _float_env(name: str, default: float, *, minimum: float = 0.1) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


@dataclass(frozen=True)
class AgentApiSettings:
    host: str = "0.0.0.0"
    port: int = 8010
    output_dir: Path = Path("outputs")
    db_path: str = ""
    request_timeout_seconds: float = 180.0
    max_concurrency: int = 4
    rate_limit_requests: int = 30
    rate_limit_window_seconds: int = 60
    redis_url: str = ""
    api_key: str = ""
    default_top_k: int = 50
    cors_origins: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> "AgentApiSettings":
        origins = tuple(
            item.strip()
            for item in os.getenv("AGENT_API_CORS_ORIGINS", "").split(",")
            if item.strip()
        )
        return cls(
            host=os.getenv("AGENT_API_HOST", "0.0.0.0"),
            port=_int_env("AGENT_API_PORT", 8010, maximum=65535),
            output_dir=Path(os.getenv("AGENT_OUTPUT_DIR", "outputs")),
            db_path=os.getenv("AGENT_DB_PATH", ""),
            request_timeout_seconds=_float_env("AGENT_API_TIMEOUT_SECONDS", 180.0),
            max_concurrency=_int_env("AGENT_API_MAX_CONCURRENCY", 4, maximum=64),
            rate_limit_requests=_int_env("AGENT_API_RATE_LIMIT_REQUESTS", 30, maximum=10000),
            rate_limit_window_seconds=_int_env("AGENT_API_RATE_LIMIT_WINDOW_SECONDS", 60, maximum=86400),
            redis_url=os.getenv("AGENT_REDIS_URL", ""),
            api_key=os.getenv("AGENT_API_KEY", ""),
            default_top_k=_int_env("AGENT_DEFAULT_TOP_K", 50, maximum=100),
            cors_origins=origins,
        )
