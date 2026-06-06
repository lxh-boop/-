from __future__ import annotations

import os
from typing import Any

from config import (
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    LLM_API_KEY_ENV,
    LLM_BASE_URL_ENV,
    LLM_MODEL_ENV,
)


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        self.api_key = (api_key or os.environ.get(LLM_API_KEY_ENV, "")).strip()
        self.base_url = (
            base_url
            if base_url is not None
            else os.environ.get(LLM_BASE_URL_ENV, DEFAULT_LLM_BASE_URL)
        ).strip()
        self.model = (
            model
            or os.environ.get(LLM_MODEL_ENV, DEFAULT_LLM_MODEL)
            or DEFAULT_LLM_MODEL
        ).strip()

    def _build_client(self):
        if not self.api_key:
            raise RuntimeError(
                f"未配置大模型 API Key。请在 APP 输入，或设置环境变量 {LLM_API_KEY_ENV}。"
            )

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "当前环境缺少 openai 包，请运行：pip install openai"
            ) from exc

        kwargs: dict[str, Any] = {"api_key": self.api_key}

        if self.base_url:
            kwargs["base_url"] = self.base_url

        return OpenAI(**kwargs)

    def _is_deepseek_v4(self) -> bool:
        text = f"{self.base_url} {self.model}".lower()
        return "deepseek" in text and "v4" in text

    def validate_connection(self) -> tuple[bool, str]:
        try:
            self.chat(
                messages=[
                    {
                        "role": "system",
                        "content": "你只需要回复 OK。",
                    },
                    {
                        "role": "user",
                        "content": "请回复 OK，用于连接测试。",
                    },
                ],
                temperature=0.0,
                max_tokens=20,
            )
            return True, f"AI 连接成功，当前模型：{self.model}"
        except Exception as exc:
            return False, f"AI 连接失败：{exc}"

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.2,
        max_tokens: int = 1200,
    ) -> str:
        client = self._build_client()

        try:
            request_kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

            if self._is_deepseek_v4():
                # DeepSeek V4 enables thinking mode by default. In OpenAI-compatible
                # clients this can put text in reasoning_content while content is empty.
                request_kwargs["extra_body"] = {
                    "thinking": {"type": "disabled"},
                }

            response = client.chat.completions.create(
                **request_kwargs,
            )
        except Exception as exc:
            raise RuntimeError(f"大模型调用失败：{exc}") from exc

        try:
            message = response.choices[0].message
            content = message.content
            reasoning_content = getattr(message, "reasoning_content", None)
        except Exception as exc:
            raise RuntimeError(f"大模型返回格式无法解析：{exc}") from exc

        content = str(content or "").strip()

        if not content:
            if reasoning_content:
                raise RuntimeError(
                    "大模型只返回了 reasoning_content，普通 content 为空。"
                    "这通常表示服务开启了 thinking mode；请确认当前 Base URL 和模型支持关闭 thinking。"
                )
            raise RuntimeError("大模型返回内容为空。")

        return content
