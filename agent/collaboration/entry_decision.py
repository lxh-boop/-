from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.llm import LLMService


class RequestMode(str, Enum):
    ANALYSIS = "analysis"
    PROPOSAL = "proposal"
    CONFIRM = "confirm"
    REJECT = "reject"
    LANGUAGE = "language"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class EntryDecision:
    mode: RequestMode
    reason: str = ""
    reply_language: str = ""
    source: str = "main_coordinator_llm"
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "reason": self.reason,
            "reply_language": self.reply_language,
            "source": self.source,
            "confidence": self.confidence,
        }


class EntryDecisionError(RuntimeError):
    pass


def _relation_type(context: dict[str, Any] | None) -> str:
    raw = dict(context or {})
    state = raw.get("conversation_state") if isinstance(raw.get("conversation_state"), dict) else {}
    turn = raw.get("turn_resolution") if isinstance(raw.get("turn_resolution"), dict) else {}
    return str(state.get("relation_type") or turn.get("relation_type") or raw.get("relation_type") or "").lower()


def _safe_approval_context(context: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(context or {})
    candidates: list[dict[str, Any]] = []

    def visit(value: Any, depth: int = 0) -> None:
        if depth > 7:
            return
        if isinstance(value, dict):
            lowered = {str(key).lower(): item for key, item in value.items()}
            if any(key in lowered for key in ("plan_id", "proposal_id", "approval_id")):
                candidates.append(
                    {
                        "plan_id_present": bool(lowered.get("plan_id") or lowered.get("proposal_id")),
                        "approval_id_present": bool(lowered.get("approval_id")),
                        "status": str(lowered.get("status") or lowered.get("confirmation_status") or "")[:80],
                        "operation_type": str(lowered.get("operation_type") or lowered.get("intent") or "")[:120],
                        "token_present": bool(lowered.get("confirmation_token") or lowered.get("token_present")),
                    }
                )
            for key, item in value.items():
                if str(key).lower() in {
                    "confirmation_token", "confirmation_token_hash", "token", "api_key",
                    "password", "secret", "raw_payload",
                }:
                    continue
                visit(item, depth + 1)
        elif isinstance(value, list):
            for item in value[:30]:
                visit(item, depth + 1)

    visit(raw)
    return {
        "pending_approval_available": any(item.get("plan_id_present") for item in candidates),
        "items": candidates[:5],
    }


def _validate_decision(payload: dict[str, Any]) -> None:
    mode = str(payload.get("mode") or "").strip().lower()
    if mode not in {item.value for item in RequestMode}:
        raise EntryDecisionError(f"invalid_entry_mode:{mode}")
    language = str(payload.get("reply_language") or "").strip().lower()
    if language not in {"", "zh", "en"}:
        raise EntryDecisionError(f"invalid_entry_language:{language}")



class MainEntryDecisionPlanner:
    """Only semantic request-mode decision point for the Agent surface."""

    def __init__(self, *, llm_service: LLMService) -> None:
        self.llm_service = llm_service

    def decide(
        self,
        *,
        query: str,
        memory_summary: str,
        execution_context: dict[str, Any] | None,
        language: str,
    ) -> EntryDecision:
        relation = _relation_type(execution_context)

        # Deterministic protocol states are safety facts, not business routing.
        if relation == "confirmation":
            return EntryDecision(
                mode=RequestMode.CONFIRM,
                reason="conversation_protocol_confirmation",
                source="hard_protocol_state",
                confidence=1.0,
            )
        if relation == "cancellation":
            return EntryDecision(
                mode=RequestMode.REJECT,
                reason="conversation_protocol_cancellation",
                source="hard_protocol_state",
                confidence=1.0,
            )

        system = (
            "你是系统唯一的主 Agent 入口。你只负责理解用户最终业务目标和期望副作用，"
            "并决定后续 request_mode；你不能选择 Worker、规划工具或输出实现细节。"
            "模式定义如下：analysis 表示查询、查看、比较、解释、研究、风险分析或系统诊断，"
            "不会形成可审批的状态变更方案；proposal 表示用户希望生成一个具体但尚未执行的"
            "账户、持仓、策略或其他业务状态变更方案，后续仍需要审批和重新校验；"
            "confirm 只用于明确确认已经存在的待审批计划；reject 只用于拒绝或取消已有计划；"
            "language 只修改回复语言；unsupported 表示目标超出系统能力。"
            "判断时关注用户最终希望获得的产物，而不是是否立即执行："
            "询问观点、风险、原因或是否值得买卖通常属于 analysis；"
            "要求给出具体调仓方案、目标仓位、策略变更配置或待确认操作清单属于 proposal，"
            "即使用户没有要求立即执行；仅说‘确认’但上下文中没有待审批计划不能判为 confirm。"
            "必须忠实保留用户目标，不得把具体方案请求弱化为普通分析，也不得把查看请求扩大为 proposal。"
            '严格输出 JSON：{"mode":"...","reason":"...",'
            '"reply_language":"zh|en|","confidence":0.0}。'
        )
        payload = self.llm_service.generate_json(
            stage="main_agent_single_entry",
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": __import__("json").dumps(
                        {
                            "user_request": str(query or ""),
                            "session_memory_summary": str(memory_summary or "")[:6000],
                            "conversation_protocol": {
                                "relation_type": relation,
                                "approval": _safe_approval_context(execution_context),
                            },
                            "current_reply_language": language,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            max_output_tokens=500,
            validator=_validate_decision,
            operation="request_mode_decision",
        )
        mode = RequestMode(str(payload.get("mode") or "").strip().lower())
        reason = str(payload.get("reason") or "")[:500]
        source = "main_coordinator_llm"
        try:
            confidence = max(0.0, min(float(payload.get("confidence", 0.0)), 1.0))
        except (TypeError, ValueError):
            confidence = 0.0

        return EntryDecision(
            mode=mode,
            reason=reason,
            reply_language=str(payload.get("reply_language") or "").strip().lower(),
            source=source,
            confidence=confidence,
        )
