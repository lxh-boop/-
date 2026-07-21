from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .entry_decision import EntryDecision, RequestMode


_PLAN_RE = re.compile(r"\b(agent_plan_[A-Za-z0-9_-]+)\b")
_TOKEN_RE = re.compile(
    r"(?:token|令牌|confirmation_token)\s*[:=：]?\s*([A-Za-z0-9_-]+)",
    flags=re.IGNORECASE,
)


def _walk_values(value: Any, target_keys: set[str], depth: int = 0) -> list[Any]:
    if depth > 8:
        return []
    values: list[Any] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in target_keys and item not in (None, "", [], {}):
                values.append(item)
            values.extend(_walk_values(item, target_keys, depth + 1))
    elif isinstance(value, list):
        for item in value[:100]:
            values.extend(_walk_values(item, target_keys, depth + 1))
    return values


def _first_text(values: list[Any]) -> str:
    for value in values:
        if isinstance(value, (str, int, float)) and str(value).strip():
            return str(value).strip()
    return ""


def _extract_identity(query: str, context: dict[str, Any] | None) -> tuple[str, str]:
    text = str(query or "")
    plan_match = _PLAN_RE.search(text)
    token_match = _TOKEN_RE.search(text)
    raw = dict(context or {})
    plan_id = plan_match.group(1) if plan_match else _first_text(
        _walk_values(raw, {"plan_id", "proposal_id", "pending_plan_id"})
    )
    token = token_match.group(1) if token_match else _first_text(
        _walk_values(raw, {"confirmation_token", "token"})
    )
    return plan_id, token


def _legacy_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_legacy_dict"):
        return dict(value.to_legacy_dict())
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    return dict(value or {}) if isinstance(value, dict) else {"success": False, "message": str(value)}


def _control_response(
    *,
    success: bool,
    answer: str,
    action: str,
    effective_intent: str,
    data: dict[str, Any] | None = None,
    errors: list[str] | None = None,
    need_clarification: bool = False,
    clarification_question: str = "",
) -> dict[str, Any]:
    payload = dict(data or {})
    return {
        "success": bool(success),
        "answer": answer,
        "task_results": {
            "control_gateway": {
                "success": bool(success),
                "intent": action,
                "step_status": "succeeded" if success else ("waiting_context" if need_clarification else "failed"),
                "execution_mode": "hard_safety_gateway",
                "message": answer,
                "data": payload,
                "warnings": [],
                "errors": list(errors or []),
                "agent_id": "MAIN_COORDINATOR",
                "status": "completed" if success else ("need_context" if need_clarification else "failed"),
                "summary": answer,
                "findings": [],
                "recommendations": [],
                "confidence": 1.0,
                "evidence_refs": [],
                "artifact_refs": [],
                "missing_items": [],
                "metadata": {"gateway": "control_gateway", "internal_call_count": 1 if action in {"confirm", "reject"} else 0},
            }
        },
        "tool_calls": [],
        "internal_tool_call_count": 1 if action in {"confirm", "reject"} else 0,
        "execution_order": ["control_gateway"],
        "execution_batches": [{"batch_index": 1, "task_ids": ["control_gateway"], "agents": ["MAIN_COORDINATOR"], "parallel": False}],
        "warnings": [],
        "errors": list(errors or []),
        "execution_status": "waiting_context" if need_clarification else ("completed" if success else "failed"),
        "need_clarification": bool(need_clarification),
        "clarification_question": clarification_question,
        "missing_context": [],
        "observations": [{"task_id": "control_gateway", "agent_id": "MAIN_COORDINATOR", "status": "completed" if success else "failed", "summary": answer[:500]}],
        "replan_audit": [],
        "replan_count": 0,
        "invalid_replan_block_count": 0,
        "replan_limits": {"max_rounds": 0},
        "agent_outputs": {},
        "agent_timeline": [],
        "handoff": {"handoff_available": False, "handoff_count": 0, "handoff_refs": [], "safety": {"write_gateway_required": True}},
        "control_action": action,
        "effective_intent": effective_intent,
        "control_data": payload,
    }


class ControlGateway:
    """Hard safety gateway inside the single Main Coordinator entry."""

    def __init__(self, *, output_dir: str | Path, db_path: str | Path | None) -> None:
        self.output_dir = output_dir
        self.db_path = db_path

    def execute(
        self,
        *,
        decision: EntryDecision,
        query: str,
        user_id: str,
        session_id: str,
        run_id: str,
        language: str,
        execution_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if decision.mode == RequestMode.LANGUAGE:
            target = decision.reply_language or language
            answer = "Reply language has been set to English." if target == "en" else "回复语言已设置为中文。"
            return _control_response(
                success=True,
                answer=answer,
                action="language",
                effective_intent="set_reply_language",
                data={"reply_language": target},
            )
        if decision.mode == RequestMode.CONFIRM:
            return self._confirm(
                query=query,
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                language=language,
                execution_context=execution_context,
            )
        if decision.mode == RequestMode.REJECT:
            return self._reject(
                query=query,
                user_id=user_id,
                language=language,
                execution_context=execution_context,
            )
        raise ValueError(f"unsupported_control_mode:{decision.mode.value}")

    def _confirm(
        self,
        *,
        query: str,
        user_id: str,
        session_id: str,
        run_id: str,
        language: str,
        execution_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        plan_id, token = _extract_identity(query, execution_context)
        if plan_id:
            try:
                from agent.session.pending_action_store import get_pending_plan

                pending = get_pending_plan(user_id, plan_id, self.output_dir) or {}
                token = token or str(pending.get("confirmation_token") or "")
            except Exception:
                pass
        if not plan_id:
            question = "Which pending plan should be confirmed? Please provide its plan ID." if language == "en" else "需要确认哪一个待审批计划？请提供计划 ID。"
            return _control_response(
                success=False,
                answer=question,
                action="confirm",
                effective_intent="confirm_execute",
                need_clarification=True,
                clarification_question=question,
                errors=["missing_plan_id"],
            )
        if not token:
            question = "The confirmation credential is missing. Please confirm from the pending-plan card." if language == "en" else "缺少确认凭证，请从待确认计划卡片发起确认。"
            return _control_response(
                success=False,
                answer=question,
                action="confirm",
                effective_intent="confirm_execute",
                data={"plan_id": plan_id},
                need_clarification=True,
                clarification_question=question,
                errors=["missing_confirmation_token"],
            )
        try:
            from agent.write_gateway import execute_confirmed_plan_v2

            result = _legacy_dict(
                execute_confirmed_plan_v2(
                    plan_id,
                    token,
                    user_id,
                    conversation_id=session_id,
                    run_id=run_id,
                    output_dir=self.output_dir,
                    db_path=self.db_path,
                )
            )
        except Exception as exc:
            result = {"success": False, "message": f"{type(exc).__name__}: {exc}", "data": {}, "errors": [type(exc).__name__]}
        success = bool(result.get("success"))
        answer = str(result.get("message") or "")
        if not answer:
            answer = (
                "The confirmed paper-trading operation has been processed."
                if success and language == "en"
                else "已处理确认后的模拟盘操作。"
                if success
                else "确认执行失败。"
            )
        data = dict(result.get("data") or {})
        data.setdefault("plan_id", plan_id)
        return _control_response(
            success=success,
            answer=answer,
            action="confirm",
            effective_intent="confirm_execute",
            data=data,
            errors=[str(item) for item in (result.get("errors") or [])],
        )

    def _reject(
        self,
        *,
        query: str,
        user_id: str,
        language: str,
        execution_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        plan_id, _ = _extract_identity(query, execution_context)
        if not plan_id:
            question = "Which pending plan should be rejected? Please provide its plan ID." if language == "en" else "需要拒绝哪一个待审批计划？请提供计划 ID。"
            return _control_response(
                success=False,
                answer=question,
                action="reject",
                effective_intent="reject_execute",
                need_clarification=True,
                clarification_question=question,
                errors=["missing_plan_id"],
            )
        try:
            from agent.session.confirmation_manager import reject_confirmation_plan

            rejected, status, plan = reject_confirmation_plan(
                user_id,
                plan_id,
                output_dir=self.output_dir,
                db_path=self.db_path,
            )
            answer = (
                "The pending plan was rejected; no paper-trading commit occurred."
                if rejected and language == "en"
                else "待确认计划已拒绝，模拟盘未发生任何提交。"
                if rejected
                else f"计划拒绝失败：{status}"
            )
            return _control_response(
                success=bool(rejected),
                answer=answer,
                action="reject",
                effective_intent="reject_execute",
                data={
                    "plan_id": plan_id,
                    "confirmation_status": status,
                    "execution_status": (plan or {}).get("execution_status") if isinstance(plan, dict) else "",
                },
                errors=[] if rejected else [str(status)],
            )
        except Exception as exc:
            return _control_response(
                success=False,
                answer=f"计划拒绝失败：{type(exc).__name__}",
                action="reject",
                effective_intent="reject_execute",
                data={"plan_id": plan_id},
                errors=[type(exc).__name__],
            )
