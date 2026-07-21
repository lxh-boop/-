"""OpenAI-compatible transport adapter."""

from __future__ import annotations

from typing import Any

from core.llm.adapters.base import LLMAdapter
from core.llm.contracts import (
    LLMConfigurationError,
    LLMProviderError,
    LLMResponse,
    LLMResponseError,
)
from core.llm.profiles import ModelProfile


def _redacted_error(exc: Exception, credential: str) -> str:
    message = f"{type(exc).__name__}: {exc}"
    if credential:
        message = message.replace(credential, "<redacted>")
    return message[:600]


class OpenAICompatibleAdapter(LLMAdapter):
    """Own SDK construction, request assembly and response extraction."""

    def _build_client(self, profile: ModelProfile, credential: str):
        if not credential:
            raise LLMConfigurationError("远程 API 未配置凭据。")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise LLMConfigurationError("当前环境缺少 openai 包，请使用项目虚拟环境安装依赖。") from exc
        kwargs: dict[str, Any] = {
            "api_key": credential,
            "timeout": profile.request_timeout_seconds,
            "max_retries": profile.max_retries,
        }
        if profile.base_url:
            kwargs["base_url"] = profile.base_url
        return OpenAI(**kwargs)

    @staticmethod
    def _prepared_messages(profile: ModelProfile, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        copied = [dict(item) for item in messages]
        # Model-name handling is allowed only inside profile/adapter code.
        if not (profile.disable_thinking and "qwen" in profile.model_name.lower()):
            return copied
        for item in copied:
            if item.get("role") == "system":
                content = str(item.get("content") or "")
                if "/no_think" not in content:
                    item["content"] = f"{content.rstrip()}\n/no_think".strip()
                return copied
        copied.insert(0, {"role": "system", "content": "/no_think"})
        return copied

    @staticmethod
    def _provider_parameters(profile: ModelProfile) -> dict[str, Any]:
        marker = f"{profile.provider_id} {profile.base_url} {profile.model_name}".lower()
        if "deepseek" in marker and "v4" in marker:
            return {"extra_body": {"thinking": {"type": "disabled"}}}
        return {}

    def generate(
        self,
        *,
        profile: ModelProfile,
        credential: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_output_tokens: int,
    ) -> LLMResponse:
        try:
            client = self._build_client(profile, credential)
            response = client.chat.completions.create(
                model=profile.model_name,
                messages=self._prepared_messages(profile, messages),
                temperature=float(temperature),
                max_tokens=max(1, int(max_output_tokens)),
                **self._provider_parameters(profile),
            )
            message = response.choices[0].message
            content = str(getattr(message, "content", "") or "").strip()
            if not content:
                if getattr(message, "reasoning_content", None):
                    raise LLMResponseError("模型仅返回 reasoning_content；普通 content 为空。")
                raise LLMResponseError("模型返回内容为空。")
            usage = getattr(response, "usage", None)
            return LLMResponse(
                content=content,
                provider_id=profile.provider_id,
                model_name=profile.model_name,
                profile_id=profile.profile_id,
                config_hash=profile.config_hash,
                usage={
                    "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                    "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
                    "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
                },
                provider_request_id=str(getattr(response, "id", "") or ""),
            )
        except (LLMConfigurationError, LLMResponseError):
            raise
        except Exception as exc:
            raise LLMProviderError(_redacted_error(exc, credential)) from exc


__all__ = ["OpenAICompatibleAdapter"]
