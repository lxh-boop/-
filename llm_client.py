from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

from agent.llm_audit import record_llm_call
from config import DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MODEL, LLM_API_KEY_ENV, LLM_BASE_URL_ENV, LLM_MODEL_ENV
from core.llm.runtime_settings import LLMRuntimeSettings, resolve_active_llm_settings


class LLMClient:
    """OpenAI-compatible client with explicit API/local deployment modes.

    A client is bound to one immutable ``LLMRuntimeSettings`` object.  It never
    switches providers after an error.
    """

    def __init__(
        self,
        settings: LLMRuntimeSettings | str | None = None,
        *,
        mode: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        # ``LLMClient("token")`` was accepted by the legacy client.  Keep
        # that positional form while making the immutable settings snapshot
        # the preferred API.
        if isinstance(settings, str):
            api_key = api_key if api_key is not None else settings
            settings = None
        self.settings = settings or resolve_active_llm_settings(
            mode=mode,
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
        self.mode = self.settings.mode
        self.provider = self.settings.provider
        self.api_key = self.settings.api_key
        self.base_url = self.settings.base_url
        self.model = self.settings.model
        self.last_usage: dict[str, int] = {}
        self.last_audit_event_id = ""

    def _mode_label(self) -> str:
        return "本地 Ollama" if self.mode == "local" else "远程 API"

    def _build_client(self):
        if self.mode == "api" and not self.api_key:
            raise RuntimeError(
                f"远程 API 未配置 API Key。请在 APP 输入或设置环境变量 {LLM_API_KEY_ENV}；未自动切换到本地模型。"
            )
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("当前环境缺少 openai 包，请使用项目虚拟环境安装依赖。") from exc
        kwargs: dict[str, Any] = {
            "api_key": self.api_key or "ollama",
            "timeout": self.settings.request_timeout_seconds,
            "max_retries": self.settings.max_retries,
        }
        if self.base_url:
            kwargs["base_url"] = self.base_url
        return OpenAI(**kwargs)

    def _is_deepseek_v4(self) -> bool:
        text = f"{self.base_url} {self.model}".lower()
        return self.mode == "api" and "deepseek" in text and "v4" in text

    def _prepared_messages(self, messages: list[dict]) -> list[dict]:
        """Copy messages and add Qwen3's local no-think instruction once."""
        copied = [dict(item) for item in messages]
        if not (self.mode == "local" and self.settings.disable_thinking and "qwen3" in self.model.lower()):
            return copied
        for item in copied:
            if item.get("role") == "system":
                content = str(item.get("content") or "")
                if "/no_think" not in content:
                    item["content"] = f"{content.rstrip()}\n/no_think".strip()
                return copied
        copied.insert(0, {"role": "system", "content": "/no_think"})
        return copied

    def validate_connection(self) -> tuple[bool, str]:
        if self.mode == "local":
            from core.llm.ollama_manager import validate_local_model

            result = validate_local_model(self.model, timeout_seconds=min(self.settings.request_timeout_seconds, 120))
            return result.success, result.message
        try:
            self.chat(
                messages=[
                    {"role": "system", "content": "只回复 OK。"},
                    {"role": "user", "content": "请回复 OK，用于连接测试。"},
                ],
                temperature=0.0,
                max_tokens=20,
            )
            return True, f"远程 API 连接成功，当前模型：{self.model}"
        except Exception as exc:
            return False, f"远程 API 调用失败：{exc}"

    def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 1200) -> str:
        self.last_usage = {}
        try:
            client = self._build_client()
            request_kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": self._prepared_messages(messages),
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if self._is_deepseek_v4():
                request_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
            response = client.chat.completions.create(**request_kwargs)
            usage = getattr(response, "usage", None)
            self.last_usage = {
                "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
                "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
            }
            message = response.choices[0].message
            content = str(getattr(message, "content", "") or "").strip()
            if not content:
                reasoning = getattr(message, "reasoning_content", None)
                if reasoning:
                    raise RuntimeError("模型仅返回 reasoning_content；普通 content 为空。")
                raise RuntimeError("模型返回内容为空。")
            return content
        except Exception as exc:
            raise RuntimeError(
                f"{self._mode_label()}调用失败：{exc}。当前配置禁止自动切换模型，本次未执行任何自动回退。"
            ) from exc

    def chat_audited(
        self,
        messages: list[dict],
        temperature: float = 0.2,
        max_tokens: int = 1200,
        *,
        audit_stage: str,
        audit_operation: str = "",
    ) -> str:
        request_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        started = time.perf_counter()
        try:
            content = self.chat(messages=messages, temperature=temperature, max_tokens=max_tokens)
        except Exception as exc:
            self.last_audit_event_id = record_llm_call(
                stage=audit_stage,
                provider=self.provider,
                model=self.model,
                temperature=temperature,
                request_at=request_at,
                response_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                duration_ms=round((time.perf_counter() - started) * 1000),
                success=False,
                error_type=type(exc).__name__,
                error_message=str(exc),
                operation=audit_operation,
                deployment_mode=self.mode,
                config_hash=self.settings.config_hash,
                endpoint_scope=self.settings.endpoint_scope,
            )
            raise
        self.last_audit_event_id = record_llm_call(
            stage=audit_stage,
            provider=self.provider,
            model=self.model,
            temperature=temperature,
            request_at=request_at,
            response_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            duration_ms=round((time.perf_counter() - started) * 1000),
            success=True,
            operation=audit_operation,
            deployment_mode=self.mode,
            config_hash=self.settings.config_hash,
            endpoint_scope=self.settings.endpoint_scope,
        )
        return content
