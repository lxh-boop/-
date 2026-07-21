"""Unified, profile-bound LLM service."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import local
from typing import Any, Callable

from core.llm.contracts import LLMConfigurationError, LLMJSONError, LLMResponse, extract_json_object
from core.llm.registry import AdapterRegistry
from core.llm.runtime_settings import LLMRuntimeSettings


@dataclass
class _ServiceState:
    thread_local: local = field(default_factory=local)


@dataclass(frozen=True)
class LLMService:
    """One immutable model binding reused for every stage of an Agent run."""

    settings: LLMRuntimeSettings
    registry: AdapterRegistry = field(default_factory=AdapterRegistry, repr=False, compare=False)
    _state: _ServiceState = field(default_factory=_ServiceState, repr=False, compare=False)

    @property
    def profile(self):
        return self.settings.profile

    @property
    def profile_id(self) -> str:
        return self.profile.profile_id

    @property
    def config_hash(self) -> str:
        return self.profile.config_hash

    @property
    def is_available(self) -> bool:
        return self.settings.is_configured

    @property
    def last_response(self) -> LLMResponse | None:
        return getattr(self._state.thread_local, "last_response", None)

    @property
    def last_usage(self) -> dict[str, int]:
        response = self.last_response
        return dict(response.usage) if response is not None else {}

    @property
    def last_audit_event_id(self) -> str:
        return str(getattr(self._state.thread_local, "last_audit_event_id", "") or "")

    def _set_response(self, response: LLMResponse | None, event_id: str) -> None:
        self._state.thread_local.last_response = response
        self._state.thread_local.last_audit_event_id = event_id

    def _record_call(
        self,
        *,
        stage: str,
        operation: str,
        temperature: float,
        request_at: str,
        started: float,
        success: bool,
        response: LLMResponse | None = None,
        error: Exception | None = None,
    ) -> str:
        try:
            from agent.llm_audit import record_llm_call

            return record_llm_call(
                stage=stage,
                provider=self.profile.provider_id,
                model=self.profile.model_name,
                temperature=temperature,
                request_at=request_at,
                response_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                duration_ms=round((time.perf_counter() - started) * 1000),
                success=success,
                provider_request_id=(response.provider_request_id if response else ""),
                error_type=(type(error).__name__ if error else ""),
                error_message=(str(error)[:500] if error else ""),
                operation=operation,
                deployment_mode=self.profile.deployment_mode,
                profile_id=self.profile_id,
                config_hash=self.config_hash,
                endpoint_scope=self.profile.endpoint_scope,
            )
        except Exception:
            return ""

    @staticmethod
    def _record_schema(event_id: str, valid: bool) -> None:
        try:
            from agent.llm_audit import record_schema_result

            record_schema_result(event_id, valid)
        except Exception:
            return

    def generate_text(
        self,
        *,
        stage: str,
        messages: list[dict[str, Any]],
        max_output_tokens: int,
        temperature: float = 0.2,
        operation: str = "",
    ) -> str:
        if not self.is_available:
            raise LLMConfigurationError("当前 Model Profile 未配置可用凭据或模型。")
        request_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        started = time.perf_counter()
        try:
            response = self.registry.adapter_for(self.profile).generate(
                profile=self.profile,
                credential=self.settings.credential,
                messages=[dict(item) for item in messages],
                temperature=float(temperature),
                max_output_tokens=max(1, int(max_output_tokens)),
            )
        except Exception as exc:
            event_id = self._record_call(
                stage=stage,
                operation=operation or "primary",
                temperature=temperature,
                request_at=request_at,
                started=started,
                success=False,
                error=exc,
            )
            self._set_response(None, event_id)
            mode_label = "本地 Ollama" if self.profile.deployment_mode == "local" else "远程 API"
            raise type(exc)(
                f"{mode_label}调用失败：{exc}。当前配置禁止自动切换模型，本次未执行任何自动回退。"
            ) from exc
        event_id = self._record_call(
            stage=stage,
            operation=operation or "primary",
            temperature=temperature,
            request_at=request_at,
            started=started,
            success=True,
            response=response,
        )
        self._set_response(response, event_id)
        return response.content

    def generate_json(
        self,
        *,
        stage: str,
        messages: list[dict[str, Any]],
        max_output_tokens: int,
        validator: Callable[[dict[str, Any]], None] | None = None,
        operation: str = "",
    ) -> dict[str, Any]:
        """Generate JSON and perform exactly one schema-repair request."""

        output = self.generate_text(
            stage=stage,
            messages=messages,
            max_output_tokens=max_output_tokens,
            temperature=0.0,
            operation=operation or "primary",
        )
        first_event_id = self.last_audit_event_id
        try:
            parsed = extract_json_object(output)
            if validator:
                validator(parsed)
            self._record_schema(first_event_id, True)
            return parsed
        except Exception as first_exc:
            self._record_schema(first_event_id, False)
            repair_messages = [
                *[dict(item) for item in messages],
                {"role": "assistant", "content": str(output or "")[:6000]},
                {
                    "role": "user",
                    "content": (
                        "上一个输出不是符合要求的 JSON。请保持原任务不变，"
                        "严格按照系统给出的 schema 重新输出一个 JSON 对象。"
                        "不要 Markdown，不要解释，不要猜测缺失信息；不确定时必须请求澄清。"
                    ),
                },
            ]
            repaired = self.generate_text(
                stage=stage,
                messages=repair_messages,
                max_output_tokens=max_output_tokens,
                temperature=0.0,
                operation="schema_repair",
            )
            repair_event_id = self.last_audit_event_id
            try:
                parsed = extract_json_object(repaired)
                if validator:
                    validator(parsed)
                self._record_schema(repair_event_id, True)
                return parsed
            except Exception as second_exc:
                self._record_schema(repair_event_id, False)
                raise LLMJSONError(
                    f"LLM JSON/schema repair failed: {type(first_exc).__name__}; "
                    f"{type(second_exc).__name__}: {second_exc}"
                ) from second_exc

    def validate_connection(self) -> tuple[bool, str]:
        try:
            self.generate_text(
                stage="completion",
                messages=[
                    {"role": "system", "content": "只回复 OK。"},
                    {"role": "user", "content": "请回复 OK，用于连接测试。"},
                ],
                temperature=0.0,
                max_output_tokens=20,
                operation="connection_validation",
            )
            label = "本地 Ollama" if self.profile.deployment_mode == "local" else "远程 API"
            return True, f"{label}连接成功，当前模型：{self.profile.model_name}"
        except Exception as exc:
            label = "本地 Ollama" if self.profile.deployment_mode == "local" else "远程 API"
            return False, f"{label}调用失败：{exc}"


__all__ = ["LLMService"]
