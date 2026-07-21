from __future__ import annotations

import re
from typing import Any

from agent.communication.message_types import AgentMessage

from .memory_sanitizer import MemorySanitizer
from .memory_types import MemoryRecord, MemoryScope, MemoryStatus, MemoryType


STOCK_CODE_RE = re.compile(r"(?<!\d)\d{6}(?!\d)")
PREFERENCE_MARKERS = ("偏好", "更喜欢", "记住", "以后", "prefer", "preference", "remember")
ONE_TIME_MARKERS = ("这次", "本次", "临时", "只这一次", "only this time")


class MemoryCandidateExtractor:
    def __init__(self, *, sanitizer: MemorySanitizer | None = None) -> None:
        self.sanitizer = sanitizer or MemorySanitizer()

    def extract_from_message(self, message: AgentMessage | dict[str, Any]) -> list[MemoryRecord]:
        data = message.to_dict() if hasattr(message, "to_dict") else dict(message or {})
        payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
        content = str(data.get("content") or payload.get("content") or payload.get("message") or payload.get("text") or "")
        role = str(data.get("role") or payload.get("role") or data.get("sender") or "").lower()
        user_id = str(data.get("user_id") or payload.get("user_id") or "default_user")
        if role and role not in {"user", "human", "end_user"} and data.get("message_type") != "USER_REQUEST":
            return []
        if not content.strip():
            return []
        if _contains_any(content, ONE_TIME_MARKERS):
            return []
        if not _contains_any(content, PREFERENCE_MARKERS):
            return []
        record = MemoryRecord(
            user_id=user_id,
            conversation_id=str(data.get("conversation_id") or ""),
            run_id=str(data.get("run_id") or ""),
            task_id=str(data.get("task_id") or ""),
            source_type="user_message",
            source_id=str(data.get("message_id") or payload.get("message_id") or data.get("source_id") or ""),
            memory_type=MemoryType.SEMANTIC,
            memory_subtype="preference",
            scope=MemoryScope.USER,
            status=MemoryStatus.CANDIDATE,
            content=content,
            summary=_safe_summary(content),
            topics=_topics_from_text(content),
            stock_codes=sorted(set(STOCK_CODE_RE.findall(content))),
            importance=0.7,
            confidence=0.7,
            metadata={
                "candidate_source": "message",
                "requires_user_confirmation": True,
                "user_confirmed": False,
            },
        )
        return [self.sanitizer.sanitize_record(record)]

    def extract_from_artifact(self, artifact: dict[str, Any]) -> list[MemoryRecord]:
        data = dict(artifact or {})
        summary = data.get("content_summary") or (data.get("metadata") or {}).get("content_summary") or {}
        produced_outputs = data.get("produced_outputs") or summary.get("produced_outputs") or []
        artifact_id = str(data.get("artifact_id") or "")
        user_id = str(data.get("user_id") or "default_user")
        records: list[MemoryRecord] = []
        if any(item in produced_outputs for item in ("evidence", "market_evidence")):
            records.append(
                MemoryRecord(
                    user_id=user_id,
                    run_id=str(data.get("run_id") or ""),
                    source_type="artifact",
                    source_id=artifact_id,
                    memory_type=MemoryType.EVIDENCE,
                    status=MemoryStatus.CANDIDATE,
                    memory_subtype="artifact_evidence_summary",
                    content=str(summary.get("message") or summary.get("summary") or "Evidence artifact summary."),
                    summary=str(summary.get("message") or "Evidence artifact summary.")[:500],
                    artifact_refs=[{"artifact_id": artifact_id, "artifact_type": data.get("artifact_type") or "tool_result"}],
                    metadata={"candidate_source": "artifact", "produced_outputs": list(produced_outputs)},
                    importance=0.5,
                    confidence=0.7,
                )
            )
        if any(item in produced_outputs for item in ("portfolio_state", "account_summary", "position_count")):
            records.append(
                MemoryRecord(
                    user_id=user_id,
                    run_id=str(data.get("run_id") or ""),
                    source_type="artifact",
                    source_id=artifact_id,
                    memory_type=MemoryType.PORTFOLIO,
                    status=MemoryStatus.CANDIDATE,
                    memory_subtype="portfolio_summary",
                    content="Portfolio artifact summary available.",
                    summary=str(summary.get("message") or "Portfolio artifact summary available.")[:500],
                    artifact_refs=[{"artifact_id": artifact_id, "artifact_type": data.get("artifact_type") or "tool_result"}],
                    metadata={"candidate_source": "artifact", "produced_outputs": list(produced_outputs)},
                    importance=0.55,
                    confidence=0.75,
                )
            )
        return [self.sanitizer.sanitize_record(record) for record in records]

    def extract_from_context(self, context: dict[str, Any]) -> list[MemoryRecord]:
        """ContextBundle is the run working memory; do not duplicate it.

        Pending plans and approvals remain in their dedicated persistence
        stores. They are referenced by ContextBundle instead of being copied
        into MemoryManager.
        """

        del context
        return []

    def extract(
        self,
        value: Any,
        *,
        source_type: str = "",
        user_id: str = "default_user",
    ) -> list[MemoryRecord]:
        if isinstance(value, AgentMessage):
            return self.extract_from_message(value)
        if isinstance(value, dict):
            if source_type == "artifact" or value.get("artifact_id"):
                return self.extract_from_artifact(value)
            if source_type == "context" or value.get("approval_context"):
                return self.extract_from_context({"user_id": user_id, **value})
            if (
                source_type == "message"
                or value.get("payload")
                or value.get("message_type")
                or value.get("content")
            ):
                return self.extract_from_message({"user_id": user_id, **value})
        if isinstance(value, str):
            return self.extract_from_message(
                {"user_id": user_id, "role": "user", "content": value}
            )
        return []


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(marker.lower() in lowered for marker in markers)


def _safe_summary(text: str) -> str:
    clean = " ".join(str(text or "").split())
    return clean[:240]


def _topics_from_text(text: str) -> list[str]:
    lowered = str(text or "").lower()
    topics = []
    if any(marker in lowered for marker in ("风险", "drawdown", "稳健", "保守")):
        topics.append("risk")
    if any(marker in lowered for marker in ("语言", "中文", "英文", "language")):
        topics.append("language")
    if any(marker in lowered for marker in ("证据", "新闻", "evidence")):
        topics.append("evidence")
    return topics
