"""Loopback-only Ollama transport adapter."""

from __future__ import annotations

from typing import Any

from core.llm.contracts import LLMConfigurationError, LLMProviderError, LLMResponse, LLMResponseError
from core.llm.profiles import ModelProfile
from core.llm.adapters.openai_compatible import OpenAICompatibleAdapter, _redacted_error


class OllamaAdapter(OpenAICompatibleAdapter):
    """Use Ollama's OpenAI-compatible endpoint without accepting shell input."""

    @staticmethod
    def _prepared_messages(profile: ModelProfile, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        copied = [dict(item) for item in messages]
        if not profile.disable_thinking:
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
        del profile
        return {}

    def _build_client(self, profile: ModelProfile, credential: str):
        del credential
        if profile.endpoint_scope != "loopback":
            raise LLMConfigurationError("本地 Ollama Profile 只允许回环地址。")
        try:
            from core.llm.ollama_manager import is_valid_model_name

            if not is_valid_model_name(profile.model_name):
                raise LLMConfigurationError("本地模型名称不合法。")
            from openai import OpenAI
        except ImportError as exc:
            raise LLMConfigurationError("当前环境缺少 openai 包，请使用项目虚拟环境安装依赖。") from exc
        return OpenAI(
            api_key="ollama",
            base_url=profile.base_url,
            timeout=profile.request_timeout_seconds,
            max_retries=0,
        )

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
            return super().generate(
                profile=profile,
                credential=credential or "ollama",
                messages=messages,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
        except (LLMConfigurationError, LLMResponseError, LLMProviderError):
            raise
        except Exception as exc:
            raise LLMProviderError(_redacted_error(exc, "")) from exc


__all__ = ["OllamaAdapter"]
