"""One immutable LLM configuration snapshot per Agent run.

The module keeps API and local profiles independent.  It never persists a
credential, and its public representation deliberately excludes the API key.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from config import (
    DEFAULT_API_LLM_PROVIDER,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODE,
    DEFAULT_LLM_MODEL,
    DEFAULT_LOCAL_LLM_BASE_URL,
    DEFAULT_LOCAL_LLM_DISABLE_THINKING,
    DEFAULT_LOCAL_LLM_MODEL,
    DEFAULT_LOCAL_LLM_PROVIDER,
    LLM_API_KEY_ENV,
    LLM_BASE_URL_ENV,
    LLM_MODEL_ENV,
)


LLMMode = Literal["api", "local"]


def _text(value: Any) -> str:
    return str(value or "").strip()


def migrate_legacy_llm_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a non-destructive migration view of legacy local settings."""
    migrated = dict(config or {})
    migrated.setdefault("llm_mode", DEFAULT_LLM_MODE)
    if not _text(migrated.get("llm_api_base_url")) and _text(migrated.get("llm_base_url")):
        migrated["llm_api_base_url"] = _text(migrated.get("llm_base_url"))
    if not _text(migrated.get("llm_api_model")) and _text(migrated.get("llm_model")):
        migrated["llm_api_model"] = _text(migrated.get("llm_model"))
    migrated.setdefault("llm_local_base_url", DEFAULT_LOCAL_LLM_BASE_URL)
    migrated.setdefault("llm_local_model", DEFAULT_LOCAL_LLM_MODEL)
    migrated.setdefault("llm_local_disable_thinking", DEFAULT_LOCAL_LLM_DISABLE_THINKING)
    return migrated


@dataclass(frozen=True)
class LLMRuntimeSettings:
    mode: LLMMode
    provider: str
    api_key: str = field(repr=False)
    base_url: str
    model: str
    disable_thinking: bool
    request_timeout_seconds: int = 120
    max_retries: int = 0

    @property
    def endpoint_scope(self) -> str:
        url = self.base_url.lower()
        return "loopback" if "127.0.0.1" in url or "localhost" in url else "remote"

    @property
    def public_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "disable_thinking": self.disable_thinking,
            "request_timeout_seconds": self.request_timeout_seconds,
            "max_retries": self.max_retries,
            "endpoint_scope": self.endpoint_scope,
        }

    @property
    def config_hash(self) -> str:
        encoded = json.dumps(self.public_dict, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]

    def to_legacy_kwargs(self) -> dict[str, str]:
        return {"api_key": self.api_key, "base_url": self.base_url, "model": self.model}


def _load_saved_config() -> dict[str, Any]:
    try:
        from local_config import load_local_config

        return migrate_legacy_llm_config(load_local_config())
    except Exception:
        return migrate_legacy_llm_config({})


def resolve_active_llm_settings(
    *,
    local_config: Mapping[str, Any] | None = None,
    mode: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> LLMRuntimeSettings:
    """Resolve one active profile without ever falling back between profiles.

    Explicit values are retained for compatibility with current callers.  A
    local profile ignores the remote API key and uses ``ollama`` only as the
    OpenAI SDK placeholder key.
    """
    saved = migrate_legacy_llm_config(local_config) if local_config is not None else _load_saved_config()
    resolved_mode = _text(mode or saved.get("llm_mode") or DEFAULT_LLM_MODE).lower()
    if resolved_mode not in {"api", "local"}:
        resolved_mode = DEFAULT_LLM_MODE
    timeout = int(saved.get("llm_request_timeout_seconds") or 120)
    retries = int(saved.get("llm_max_retries") or 0)
    if resolved_mode == "local":
        # The local profile is intentionally loopback-only.  It must not turn
        # into a remote endpoint merely because a saved field was edited.
        configured_local_base = _text(saved.get("llm_local_base_url")).rstrip("/")
        fixed_local_base = DEFAULT_LOCAL_LLM_BASE_URL.rstrip("/")
        local_base_url = (
            DEFAULT_LOCAL_LLM_BASE_URL
            if configured_local_base.lower() != fixed_local_base.lower()
            else configured_local_base
        )
        return LLMRuntimeSettings(
            mode="local",
            provider=DEFAULT_LOCAL_LLM_PROVIDER,
            api_key="ollama",
            base_url=local_base_url,
            model=_text(saved.get("llm_local_model")) or DEFAULT_LOCAL_LLM_MODEL,
            disable_thinking=bool(saved.get("llm_local_disable_thinking", DEFAULT_LOCAL_LLM_DISABLE_THINKING)),
            request_timeout_seconds=max(5, timeout),
            # Local inference is deliberately single-attempt: retrying a
            # long-running loopback request would silently multiply latency.
            max_retries=0,
        )
    return LLMRuntimeSettings(
        mode="api",
        provider=DEFAULT_API_LLM_PROVIDER,
        api_key=_text(api_key if api_key is not None else saved.get("llm_api_key"))
        or _text(os.environ.get(LLM_API_KEY_ENV))
        or _text(os.environ.get("OPENAI_API_KEY")),
        base_url=_text(base_url if base_url is not None else saved.get("llm_api_base_url"))
        or _text(os.environ.get(LLM_BASE_URL_ENV))
        or DEFAULT_LLM_BASE_URL,
        model=_text(model if model is not None else saved.get("llm_api_model"))
        or _text(os.environ.get(LLM_MODEL_ENV))
        or DEFAULT_LLM_MODEL,
        disable_thinking=False,
        request_timeout_seconds=max(5, timeout),
        max_retries=max(0, retries),
    )
