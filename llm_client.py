"""Legacy compatibility shell around :class:`core.llm.LLMService`."""

from __future__ import annotations

from typing import Any

from core.llm import LLMRuntimeSettings, LLMService, resolve_active_llm_settings


class LLMClient:
    """Compatibility API; new code must depend on ``LLMService`` directly."""

    def __init__(
        self,
        settings: LLMRuntimeSettings | str | None = None,
        *,
        mode: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        if isinstance(settings, str):
            api_key = api_key if api_key is not None else settings
            settings = None
        self.settings = settings or resolve_active_llm_settings(
            mode=mode,
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
        self.service = LLMService(self.settings)
        self.mode = self.settings.mode
        self.provider = self.settings.provider
        self.api_key = self.settings.api_key
        self.base_url = self.settings.base_url
        self.model = self.settings.model

    @property
    def last_usage(self) -> dict[str, int]:
        return self.service.last_usage

    @property
    def last_audit_event_id(self) -> str:
        return self.service.last_audit_event_id

    def validate_connection(self) -> tuple[bool, str]:
        return self.service.validate_connection()

    def chat(self, messages: list[dict[str, Any]], temperature: float = 0.2, max_tokens: int = 1200) -> str:
        return self.service.generate_text(
            stage="completion",
            messages=messages,
            temperature=temperature,
            max_output_tokens=max_tokens,
            operation="legacy_chat",
        )

    def chat_audited(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 1200,
        *,
        audit_stage: str,
        audit_operation: str = "",
    ) -> str:
        return self.service.generate_text(
            stage=audit_stage,
            messages=messages,
            temperature=temperature,
            max_output_tokens=max_tokens,
            operation=audit_operation,
        )


__all__ = ["LLMClient"]
