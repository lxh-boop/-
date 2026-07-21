"""Adapter protocol."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.llm.contracts import LLMResponse
from core.llm.profiles import ModelProfile


class LLMAdapter(ABC):
    @abstractmethod
    def generate(
        self,
        *,
        profile: ModelProfile,
        credential: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_output_tokens: int,
    ) -> LLMResponse:
        raise NotImplementedError


__all__ = ["LLMAdapter"]
