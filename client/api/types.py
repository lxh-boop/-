from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class LLMRuntimeSettings:
    settings_token: str = ""
    profile_id: str = ""
    mode: str = "api"
    provider: str = ""
    base_url: str = ""
    model: str = ""
    disable_thinking: bool = False
    request_timeout_seconds: int = 120
    max_retries: int = 0
    endpoint_scope: str = ""
    is_configured: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_value(cls, value: Any) -> "LLMRuntimeSettings":
        if isinstance(value, cls):
            return value
        if hasattr(value, "to_dict"):
            value = value.to_dict()
        data = dict(value or {}) if isinstance(value, dict) else {}
        fields = cls.__dataclass_fields__
        return cls(**{key: data[key] for key in fields if key in data})


class PipelineStatus:
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    PARTIAL = "partial"
