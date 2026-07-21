"""Stable, credential-free model profiles."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal, Mapping
from urllib.parse import parse_qsl, urlsplit

from config import (
    DEFAULT_API_LLM_CONTEXT_WINDOW,
    DEFAULT_API_LLM_PROVIDER,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_LOCAL_LLM_BASE_URL,
    DEFAULT_LOCAL_LLM_CONTEXT_WINDOW,
    DEFAULT_LOCAL_LLM_DISABLE_THINKING,
    DEFAULT_LOCAL_LLM_MODEL,
    DEFAULT_LOCAL_LLM_PROVIDER,
)


DeploymentMode = Literal["api", "local"]
_PROFILE_ID_SAFE = re.compile(r"[^A-Za-z0-9_.:-]+")
_OLLAMA_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def _int(value: Any, default: int, *, minimum: int = 0) -> int:
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return max(minimum, int(default))


@dataclass(frozen=True, slots=True)
class ModelProfile:
    profile_id: str
    provider_id: str
    deployment_mode: DeploymentMode
    model_name: str
    base_url: str
    credential_ref: str
    disable_thinking: bool
    request_timeout_seconds: int
    max_retries: int
    context_window: int
    supports_json_schema: bool
    supports_tools: bool

    @property
    def endpoint_scope(self) -> str:
        url = self.base_url.lower()
        return "loopback" if "127.0.0.1" in url or "localhost" in url else "remote"

    @property
    def public_dict(self) -> dict[str, Any]:
        return {**asdict(self), "endpoint_scope": self.endpoint_scope}

    @property
    def config_hash(self) -> str:
        encoded = json.dumps(self.public_dict, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _provider_for_api(config: Mapping[str, Any]) -> str:
    configured = _text(config.get("llm_api_provider"))
    if configured:
        return configured.lower()
    # Provider inference is intentionally confined to the profile boundary.
    marker = f"{_text(config.get('llm_api_base_url'))} {_text(config.get('llm_api_model'))}".lower()
    return "deepseek" if "deepseek" in marker else DEFAULT_API_LLM_PROVIDER


def _safe_base_url(value: Any) -> str:
    base_url = _text(value)
    if not base_url:
        return ""
    parsed = urlsplit(base_url)
    sensitive_query_keys = {"api_key", "apikey", "key", "token", "access_token", "authorization"}
    query_keys = {str(key).strip().lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
    if parsed.username or parsed.password or query_keys & sensitive_query_keys:
        raise ValueError("Base URL 不得包含凭据、Token 或认证查询参数。")
    return base_url


def _profile_id(
    *,
    configured: Any,
    deployment_mode: str,
    provider_id: str,
    model_name: str,
    base_url: str,
) -> str:
    existing = _PROFILE_ID_SAFE.sub("_", _text(configured))[:160]
    if existing:
        return existing
    identity = json.dumps(
        {
            "deployment_mode": deployment_mode,
            "provider_id": provider_id,
            "model_name": model_name,
            "base_url": base_url,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:10]
    safe_model = _PROFILE_ID_SAFE.sub("_", model_name)[:48] or "model"
    return f"{deployment_mode}:{provider_id}:{safe_model}:{suffix}"


def build_model_profile(
    config: Mapping[str, Any],
    *,
    mode: DeploymentMode,
    credential_ref: str,
) -> ModelProfile:
    """Build one immutable profile; credentials are referenced, never copied."""

    timeout = _int(config.get("llm_request_timeout_seconds"), 120, minimum=5)
    if mode == "local":
        model_name = _text(config.get("llm_local_model")) or DEFAULT_LOCAL_LLM_MODEL
        if not _OLLAMA_MODEL.fullmatch(model_name):
            raise ValueError("本地模型名称不合法。")
        configured_base = _safe_base_url(config.get("llm_local_base_url")).rstrip("/")
        fixed_base = DEFAULT_LOCAL_LLM_BASE_URL.rstrip("/")
        base_url = DEFAULT_LOCAL_LLM_BASE_URL if configured_base.lower() != fixed_base.lower() else configured_base
        provider_id = DEFAULT_LOCAL_LLM_PROVIDER
        return ModelProfile(
            profile_id=_profile_id(
                configured=config.get("llm_local_profile_id"),
                deployment_mode=mode,
                provider_id=provider_id,
                model_name=model_name,
                base_url=base_url,
            ),
            provider_id=provider_id,
            deployment_mode=mode,
            model_name=model_name,
            base_url=base_url,
            credential_ref="none",
            disable_thinking=(
                _bool(config.get("llm_local_disable_thinking"), DEFAULT_LOCAL_LLM_DISABLE_THINKING)
                and "qwen" in model_name.lower()
            ),
            request_timeout_seconds=timeout,
            max_retries=0,
            context_window=_int(
                config.get("llm_local_context_window"),
                DEFAULT_LOCAL_LLM_CONTEXT_WINDOW,
                minimum=1024,
            ),
            supports_json_schema=_bool(config.get("llm_local_supports_json_schema"), False),
            supports_tools=_bool(config.get("llm_local_supports_tools"), False),
        )

    provider_id = _provider_for_api(config)
    base_url = _safe_base_url(config.get("llm_api_base_url")) or DEFAULT_LLM_BASE_URL
    model_name = _text(config.get("llm_api_model")) or DEFAULT_LLM_MODEL
    return ModelProfile(
        profile_id=_profile_id(
            configured=config.get("llm_api_profile_id"),
            deployment_mode=mode,
            provider_id=provider_id,
            model_name=model_name,
            base_url=base_url,
        ),
        provider_id=provider_id,
        deployment_mode=mode,
        model_name=model_name,
        base_url=base_url,
        credential_ref=credential_ref,
        disable_thinking=_bool(config.get("llm_api_disable_thinking"), False),
        request_timeout_seconds=timeout,
        max_retries=_int(config.get("llm_max_retries"), 0, minimum=0),
        context_window=_int(
            config.get("llm_api_context_window"),
            DEFAULT_API_LLM_CONTEXT_WINDOW,
            minimum=1024,
        ),
        supports_json_schema=_bool(config.get("llm_api_supports_json_schema"), True),
        supports_tools=_bool(config.get("llm_api_supports_tools"), True),
    )


__all__ = ["DeploymentMode", "ModelProfile", "build_model_profile"]
