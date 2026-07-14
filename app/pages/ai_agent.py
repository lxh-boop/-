from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime
from typing import Any

import pandas as pd

try:
    import streamlit as st
except ImportError:
    class _StreamlitStub:
        session_state: dict[str, Any] = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def columns(self, spec, **kwargs):
            count = spec if isinstance(spec, int) else len(spec)
            return [self for _ in range(int(count))]

        def expander(self, *args, **kwargs):
            return self

        def chat_message(self, *args, **kwargs):
            return self

        def spinner(self, *args, **kwargs):
            return self

        def text_input(self, label, value="", **kwargs):
            return value

        def chat_input(self, *args, **kwargs):
            return None

        def button(self, *args, **kwargs):
            return False

        def rerun(self):
            return None

        def __getattr__(self, name):
            def _noop(*args, **kwargs):
                return None

            return _noop

    st = _StreamlitStub()

from agent.communication import MessageStore
from agent.console_trace import trace_event, trace_exception
from agent.executor import run_agent_request
from agent.mcp.registry_bridge import summarize_mcp_usage
from agent.memory.memory_context_bridge import (
    build_memory_safe_summary,
    list_memory_records_safe_page,
)
from agent.react.react_context_bridge import (
    build_react_safe_summary,
    list_safe_observation_summaries,
)
from agent.runtime import load_run_snapshot
from agent.session.confirmation_manager import reject_confirmation_plan
from agent.session.pending_action_store import load_pending_actions
from agent.tools.portfolio_state_tool import query_portfolio_state
from agent.tools.scheduler_tool import query_scheduler_status
from agent.tools.tool_registry import list_tools
from agent.tools.tool_schemas import PAPER_AGENT_DISCLAIMER
from agent.write_gateway import execute_confirmed_plan_v2
from app.reflection_ui import build_reflection_safe_summary, format_reflection_caption
from app.handoff_ui import build_handoff_safe_summary, format_handoff_caption
from database.repositories.agent_repository import AgentRepository


COMPLIANCE_NOTE = "本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。"
UNAVAILABLE_MESSAGE = "目前不能回答，相关功能仍在后续开发中。"

WELCOME_MESSAGE = (
    "你好，我是项目中的 AI Agent。\n\n"
    "你可以直接询问每日预测排名、个股分析、新闻证据、模拟盘账户、"
    "当前持仓、历史订单、调仓预览、历史回放和调度状态。\n\n"
    "涉及模拟盘执行、资金变更或历史回放的操作，仍需确认后才能执行。"
)

QUICK_QUESTIONS = [
    "查看当前模拟盘账户和持仓",
    "查看当前预测排名前十的股票",
    "分析 600519",
    "查看每日自动更新和调度状态",
]


def _legacy_direct_commit_disabled(*args: Any, **kwargs: Any) -> None:
    raise RuntimeError("legacy direct commit is disabled; use Write Gateway")


def answer_classic_ai_agent_question(
    question: str,
    user_id: str = "default",
    trade_date: str | None = None,
    stock_code: str | None = None,
    output_dir: str = "outputs",
) -> dict[str, Any]:
    del trade_date, stock_code
    if not str(question or "").strip():
        return {
            "success": False,
            "answer": "请输入问题。",
            "evidence": [],
            "risk": "",
            "compliance": COMPLIANCE_NOTE,
        }
    try:
        result = run_agent_request(question, user_id=user_id, output_dir=output_dir)
    except Exception as exc:
        trace_exception("ui.classic_agent.failed", exc)
        return {
            "success": False,
            "answer": f"LLM-First Agent 当前无法完成请求，请检查模型连接后重试。\n\n{COMPLIANCE_NOTE}",
            "evidence": [],
            "risk": "",
            "compliance": COMPLIANCE_NOTE,
            "error_type": type(exc).__name__,
        }
    return {
        "success": result.get("success", True),
        "answer": result.get("answer", ""),
        "evidence": ((result.get("result") or {}).get("data", {}).get("evidence_ids", [])),
        "risk": "; ".join((result.get("result") or {}).get("warnings", []) or []),
        "compliance": COMPLIANCE_NOTE,
        "agent_result": result,
    }


def _messages_key(user_id: str) -> str:
    return f"ai_agent_chat_messages::{user_id}"


def _session_key(user_id: str) -> str:
    return f"ai_agent_chat_session_id::{user_id}"


def _init_chat(user_id: str) -> tuple[list[dict[str, Any]], str]:
    messages_key = _messages_key(user_id)
    session_key = _session_key(user_id)

    if session_key not in st.session_state:
        st.session_state[session_key] = f"streamlit_{uuid.uuid4().hex}"

    if messages_key not in st.session_state:
        st.session_state[messages_key] = [
            {
                "role": "assistant",
                "content": WELCOME_MESSAGE,
                "agent_result": None,
            }
        ]

    return (
        st.session_state[messages_key],
        str(st.session_state[session_key]),
    )


def _clear_chat(user_id: str) -> None:
    st.session_state[_session_key(user_id)] = (
        f"streamlit_{uuid.uuid4().hex}"
    )
    st.session_state[_messages_key(user_id)] = [
        {
            "role": "assistant",
            "content": "新的对话已经开始。\n\n" + WELCOME_MESSAGE,
            "agent_result": None,
        }
    ]


AGENT_PAGE_CACHE_TTL_SECONDS = 60
PHASE8_CONVERSATION_PAGE_SIZE = 20
PHASE8_MESSAGE_PAGE_SIZE = 10
PHASE8_LEGACY_DIRECT_LOAD_SIZE = 50
PHASE15_VISIBLE_MESSAGE_WINDOW = 10
PHASE15_LOAD_MORE_STEP = 10
PHASE15_MAX_MESSAGE_WINDOW = 100


def _phase8_cache_resource(func):
    cache = getattr(st, "cache_resource", None)
    if st.__class__.__name__ != "_StreamlitStub" and callable(cache):
        try:
            return cache(func)
        except Exception:
            return func
    return func


def _phase8_cache_data(**cache_kwargs):
    def decorator(func):
        cache = getattr(st, "cache_data", None)
        if st.__class__.__name__ != "_StreamlitStub" and callable(cache):
            try:
                return cache(**cache_kwargs)(func)
            except Exception:
                return func
        return func
    return decorator


@_phase8_cache_resource
def _get_agent_repository(db_path: str | None) -> AgentRepository:
    return AgentRepository(db_path or None)


@_phase8_cache_data(ttl=AGENT_PAGE_CACHE_TTL_SECONDS)
def _cached_tool_list() -> list[Any]:
    return list(list_tools() or [])


def _phase8_db_key(db_path: str | None) -> str:
    return str(db_path or "")


def _phase8_session_dict(key: str) -> dict[str, Any]:
    value = st.session_state.get(key)
    if not isinstance(value, dict):
        value = {}
        st.session_state[key] = value
    return value


def _phase8_perf_state(user_id: str) -> dict[str, Any]:
    state = _phase8_session_dict(f"ai_agent_phase8_perf::{user_id}")
    for key, default in {
        "page_render_ms": 0.0,
        "conversation_list_ms": 0.0,
        "messages_load_ms": 0.0,
        "pending_plan_ms": 0.0,
        "memory_lazy_load_ms": 0.0,
        "db_query_count": 0,
        "cache_hit": 0,
        "cache_miss": 0,
        "rerun_count": 0,
        "last_rerun_reason": "",
    }.items():
        state.setdefault(key, default)
    return state


def _phase8_begin_page_render(user_id: str) -> float:
    state = _phase8_perf_state(user_id)
    for key in ("page_render_ms", "conversation_list_ms", "messages_load_ms", "pending_plan_ms", "memory_lazy_load_ms"):
        state[key] = 0.0
    state["db_query_count"] = 0
    state["cache_hit"] = 0
    state["cache_miss"] = 0
    return time.perf_counter()


def _phase8_record_metric(user_id: str, metric: str, started_at: float) -> None:
    _phase8_perf_state(user_id)[metric] = round((time.perf_counter() - started_at) * 1000, 3)


def _phase8_add_db_queries(user_id: str, count: int = 1) -> None:
    state = _phase8_perf_state(user_id)
    state["db_query_count"] = int(state.get("db_query_count") or 0) + max(0, int(count))


def _phase8_cache_probe(user_id: str, cache_name: str, signature: Any) -> bool:
    seen = _phase8_session_dict(f"ai_agent_phase8_cache_seen::{user_id}")
    key = f"{cache_name}:{json.dumps(signature, sort_keys=True, default=str)}"
    hit = bool(seen.get(key))
    seen[key] = True
    state = _phase8_perf_state(user_id)
    counter = "cache_hit" if hit else "cache_miss"
    state[counter] = int(state.get(counter) or 0) + 1
    return hit


def _phase8_cache_versions(user_id: str) -> dict[str, Any]:
    return _phase8_session_dict(f"ai_agent_phase8_cache_versions::{user_id}")


def _phase8_cache_version(user_id: str, scope: str) -> int:
    return int(_phase8_cache_versions(user_id).get(scope) or 0)


def _phase8_bump_cache(user_id: str, *scopes: str) -> None:
    versions = _phase8_cache_versions(user_id)
    for scope in scopes:
        versions[scope] = int(versions.get(scope) or 0) + 1


def _phase8_message_limit_key(user_id: str, conversation_id: str) -> str:
    return f"ai_agent_phase8_message_limit::{user_id}::{conversation_id}"


def _phase8_message_limit(user_id: str, conversation_id: str) -> int:
    value = st.session_state.get(_phase8_message_limit_key(user_id, conversation_id), PHASE8_MESSAGE_PAGE_SIZE)
    return max(PHASE8_MESSAGE_PAGE_SIZE, min(PHASE15_MAX_MESSAGE_WINDOW, int(value or PHASE8_MESSAGE_PAGE_SIZE)))


def _phase8_set_message_limit(user_id: str, conversation_id: str, limit: int) -> None:
    st.session_state[_phase8_message_limit_key(user_id, conversation_id)] = max(
        PHASE8_MESSAGE_PAGE_SIZE,
        min(PHASE15_MAX_MESSAGE_WINDOW, int(limit)),
    )


def _phase15_next_message_limit(current_limit: int) -> int:
    return max(
        PHASE8_MESSAGE_PAGE_SIZE,
        min(PHASE15_MAX_MESSAGE_WINDOW, int(current_limit or PHASE8_MESSAGE_PAGE_SIZE) + PHASE15_LOAD_MORE_STEP),
    )


def _phase15_should_offer_load_earlier(messages: list[dict[str, Any]], current_limit: int) -> bool:
    return len(messages or []) >= max(PHASE8_MESSAGE_PAGE_SIZE, int(current_limit or PHASE8_MESSAGE_PAGE_SIZE))


def _phase15_trim_visible_messages(messages: list[dict[str, Any]], current_limit: int) -> list[dict[str, Any]]:
    limit = max(PHASE8_MESSAGE_PAGE_SIZE, min(PHASE15_MAX_MESSAGE_WINDOW, int(current_limit or PHASE8_MESSAGE_PAGE_SIZE)))
    return list(messages or [])[-limit:]


def _phase15_run_id_from_result(result: dict[str, Any] | None) -> str:
    if not isinstance(result, dict):
        return ""
    runtime = result.get("runtime") if isinstance(result.get("runtime"), dict) else {}
    return str(result.get("run_id") or runtime.get("run_id") or "")


def _phase15_lazy_detail_key(prefix: str, user_id: str, run_id: str) -> str:
    return f"ai_agent_phase15_lazy::{prefix}::{user_id}::{run_id or 'no_run'}"


def _phase8_loaded_conversation_key(user_id: str) -> str:
    return f"ai_agent_phase8_messages_loaded_for::{user_id}"


def _phase51_reset_conversation_view_state(user_id: str) -> None:
    prefixes = (
        f"ai_agent_phase8_developer_details::{user_id}::",
        "ai_agent_phase15_lazy::",
    )
    for key in list(getattr(st, "session_state", {}).keys()):
        text = str(key)
        if text.startswith(prefixes[0]) or (text.startswith(prefixes[1]) and f"::{user_id}::" in text):
            try:
                del st.session_state[key]
            except Exception:
                pass


def _phase8_record_rerun(user_id: str, reason: str) -> None:
    state = _phase8_perf_state(user_id)
    state["rerun_count"] = int(state.get("rerun_count") or 0) + 1
    state["last_rerun_reason"] = reason


def _phase8_rerun(user_id: str, reason: str) -> None:
    _phase8_record_rerun(user_id, reason)
    st.rerun()


@_phase8_cache_data(ttl=AGENT_PAGE_CACHE_TTL_SECONDS)
def _cached_active_conversations(user_id: str, db_path_key: str, limit: int, offset: int, version: int) -> list[dict[str, Any]]:
    del version
    return _get_agent_repository(db_path_key or None).list_active_conversations(user_id, limit=limit, offset=offset)


@_phase8_cache_data(ttl=AGENT_PAGE_CACHE_TTL_SECONDS)
def _cached_recent_messages(user_id: str, db_path_key: str, conversation_id: str, limit: int, offset: int, version: int) -> list[dict[str, Any]]:
    del version
    return _get_agent_repository(db_path_key or None).list_recent_messages(conversation_id, user_id=user_id, limit=limit, offset=offset)


@_phase8_cache_data(ttl=AGENT_PAGE_CACHE_TTL_SECONDS)
def _cached_current_conversation(user_id: str, db_path_key: str, conversation_id: str, version: int) -> dict[str, Any]:
    del version
    row = _get_agent_repository(db_path_key or None).get_conversation(conversation_id) or {}
    return row if str(row.get("user_id") or "") == str(user_id) else {}


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _get_reply_language(user_id: str) -> str:
    return str(st.session_state.get(f"ai_agent_reply_language::{user_id}") or "zh")


def _welcome_message(language: str = "zh") -> str:
    return WELCOME_MESSAGE


def _estimate_tokens(text: str) -> int:
    value = str(text or "")
    return max(1, len(value) // 2) if value else 0


SENSITIVE_UI_KEYS = {
    "api_key",
    "authorization",
    "business_state_version",
    "confirmation_token",
    "confirmation_token_hash",
    "database_path",
    "db_path",
    "exception_stack",
    "llm_api_key",
    "password",
    "plan_hash",
    "secret",
    "snapshot_id",
    "stack_trace",
    "state_id",
    "token",
    "tushare_token",
}

SAFE_TOKEN_STATUS_KEYS = {
    "confirmation_required",
    "context_window_token_estimate",
    "pending_approval_exists",
    "token_estimate",
    "token_present",
    "window_token_estimate",
}

WINDOWS_PATH_PATTERN = re.compile(r"(?i)\b[a-z]:\\[^\s\"'<>|]+")


def _is_sensitive_ui_key(key: Any) -> bool:
    lowered = str(key or "").lower()
    if lowered in SAFE_TOKEN_STATUS_KEYS:
        return False
    if lowered in SENSITIVE_UI_KEYS:
        return True
    if any(marker in lowered for marker in ("api_key", "password", "secret", "confirmation_token")):
        return True
    if "token" in lowered and lowered not in SAFE_TOKEN_STATUS_KEYS:
        return True
    return False


def _redact_sensitive_ui_text(value: str, *, max_chars: int) -> str:
    text = str(value or "")
    lowered = text.lower()
    if "traceback (most recent call last)" in lowered or "stack trace" in lowered:
        return "[redacted internal stack]"
    if "agent_quant.db" in lowered:
        return "[redacted local database path]"
    if WINDOWS_PATH_PATTERN.search(text):
        return WINDOWS_PATH_PATTERN.sub("[redacted local path]", text)[:max_chars]
    return text if len(text) <= max_chars else text[:max_chars] + "...[truncated]"


def _redact_ui_payload(value: Any, *, max_chars: int = 1200) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "***" if _is_sensitive_ui_key(key) else _redact_ui_payload(item, max_chars=max_chars)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_ui_payload(item, max_chars=max_chars) for item in value[:30]]
    if isinstance(value, str):
        return _redact_sensitive_ui_text(value, max_chars=max_chars)
    return value


def _redact_ui_payload_for_display(value: Any, *, max_chars: int = 1200) -> Any:
    value = _redact_ui_payload(value, max_chars=max_chars)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_ui_key(key):
                continue
            result[str(key)] = _redact_ui_payload_for_display(item, max_chars=max_chars)
        return result
    if isinstance(value, list):
        return [_redact_ui_payload_for_display(item, max_chars=max_chars) for item in value[:30]]
    return value


def _count_mapping_items(value: Any) -> int:
    return len(value) if isinstance(value, dict) else 0


def _safe_artifact_refs_from_context(*values: Any) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, dict):
            value = value.get("artifact_refs") or value.get("artifacts") or []
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, str):
                artifact_id = item.strip()
                artifact_type = ""
            elif isinstance(item, dict):
                artifact_id = str(item.get("artifact_id") or item.get("id") or "").strip()
                artifact_type = str(item.get("artifact_type") or item.get("type") or "").strip()
            else:
                continue
            if not artifact_id or artifact_id in seen:
                continue
            seen.add(artifact_id)
            refs.append({"artifact_id": artifact_id[:96], "artifact_type": artifact_type[:64]})
    return refs[:20]


def _phase12_context_payload(result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    context = result.get("context")
    if not isinstance(context, dict):
        return {}
    payload = context.get("phase12_context")
    return payload if isinstance(payload, dict) else {}


def _build_context_safe_summary(result: dict[str, Any] | None) -> dict[str, Any]:
    """Return a UI-safe Phase 12 context summary without secrets or large objects."""
    result = result if isinstance(result, dict) else {}
    phase12 = _phase12_context_payload(result)
    minimal = phase12.get("minimal_context") if isinstance(phase12.get("minimal_context"), dict) else {}
    llm_context = phase12.get("llm_context") if isinstance(phase12.get("llm_context"), dict) else {}
    runtime = result.get("runtime") if isinstance(result.get("runtime"), dict) else {}
    orchestration = result.get("orchestration") if isinstance(result.get("orchestration"), dict) else {}

    approval = {}
    for candidate in (
        minimal.get("approval"),
        minimal.get("approval_context"),
        llm_context.get("approval_context"),
        phase12.get("approval_context"),
    ):
        if isinstance(candidate, dict):
            approval = candidate
            break

    artifact_contexts = [
        minimal.get("artifact_refs"),
        minimal.get("artifact_context"),
        llm_context.get("artifact_context"),
        phase12.get("artifact_context"),
    ]
    artifact_refs = _safe_artifact_refs_from_context(*artifact_contexts)
    task_results = orchestration.get("task_results") if isinstance(orchestration.get("task_results"), dict) else {}
    context_warnings = result.get("context_warnings")
    if not isinstance(context_warnings, list):
        context_warnings = (result.get("context") or {}).get("context_warnings") if isinstance(result.get("context"), dict) else []
    if not isinstance(context_warnings, list):
        context_warnings = []

    pending_plan_id = str(approval.get("pending_plan_id") or "").strip()
    context_id = str(
        phase12.get("context_id")
        or minimal.get("context_id")
        or llm_context.get("context_id")
        or ""
    )
    run_id = str(
        result.get("run_id")
        or runtime.get("run_id")
        or minimal.get("run_id")
        or llm_context.get("run_id")
        or ""
    )
    trace_id = str(
        runtime.get("trace_id")
        or result.get("trace_id")
        or llm_context.get("trace_id")
        or ""
    )

    summary = {
        "context_available": bool(context_id or phase12),
        "context_id": context_id,
        "run_id": run_id,
        "trace_id": trace_id,
        "current_task_count": _count_mapping_items(task_results),
        "artifact_ref_count": len(artifact_refs),
        "artifact_refs": artifact_refs,
        "pending_approval_exists": bool(pending_plan_id),
        "pending_approval": {
            "plan_id": pending_plan_id[:96],
            "status": str(approval.get("status") or "")[:64],
            "requires_user_confirmation": bool(pending_plan_id),
        },
        "context_warning_count": len(context_warnings),
        "context_warnings": [str(item)[:160] for item in context_warnings[:5] if str(item).strip()],
        "safety": {
            "secrets_redacted": True,
            "large_objects_hidden": True,
            "raw_paths_hidden": True,
        },
    }
    return _redact_ui_payload(summary, max_chars=240)


def _format_context_safe_caption(summary: dict[str, Any] | None) -> str:
    if not isinstance(summary, dict) or not summary.get("context_available"):
        return ""
    context_id = str(summary.get("context_id") or "")
    run_id = str(summary.get("run_id") or "")
    trace_id = str(summary.get("trace_id") or "")
    parts = [
        f"context_id={context_id[-12:] or '-'}",
        f"run_id={run_id[-12:] or '-'}",
        f"trace_id={trace_id[-12:] or '-'}",
        f"tasks={int(summary.get('current_task_count') or 0)}",
        f"artifacts={int(summary.get('artifact_ref_count') or 0)}",
        f"pending_approval={'yes' if summary.get('pending_approval_exists') else 'no'}",
    ]
    return "Context safe summary: " + " | ".join(parts)


def _message_ref_counts(message: Any) -> dict[str, int]:
    return {
        "context": len(getattr(message, "context_refs", []) or []),
        "artifact": len(getattr(message, "artifact_refs", []) or []),
        "approval": len(getattr(message, "approval_refs", []) or []),
        "tool_call": len(getattr(message, "tool_call_refs", []) or []),
        "source": len(getattr(message, "source_refs", []) or []),
    }


def _safe_message_summary_text(message: Any) -> str:
    payload = getattr(message, "payload", {}) if message is not None else {}
    if not isinstance(payload, dict):
        return ""
    for key in ("summary", "message", "answer", "tool_name", "intent", "status"):
        value = payload.get(key)
        if value not in (None, "", []):
            return str(value)[:180]
    return ""


def _build_message_trace_safe_summary(
    result: dict[str, Any] | None,
    *,
    user_id: str = "default",
    output_dir: str = "outputs",
) -> dict[str, Any]:
    result = result if isinstance(result, dict) else {}
    runtime = result.get("runtime") if isinstance(result.get("runtime"), dict) else {}
    run_id = str(result.get("run_id") or runtime.get("run_id") or "")
    if not run_id:
        return {
            "message_trace_available": False,
            "message_count": 0,
            "messages": [],
            "safety": {
                "secrets_redacted": True,
                "raw_paths_hidden": True,
                "raw_payload_hidden": True,
            },
        }
    try:
        store = MessageStore(output_dir=output_dir)
        messages = store.list_messages_by_run(run_id, user_id=user_id)
        trace = store.build_trace(run_id, user_id=user_id)
    except Exception as exc:
        return {
            "message_trace_available": False,
            "run_id": run_id,
            "message_count": 0,
            "messages": [],
            "load_error": f"{type(exc).__name__}",
            "safety": {
                "secrets_redacted": True,
                "raw_paths_hidden": True,
                "raw_payload_hidden": True,
            },
        }

    type_values = [str(getattr(item.message_type, "value", item.message_type)) for item in messages]
    rows = []
    for message in messages[-30:]:
        rows.append(
            {
                "time": str(getattr(message, "created_at", "") or "")[:19],
                "message_type": str(getattr(getattr(message, "message_type", ""), "value", getattr(message, "message_type", ""))),
                "sender": str(getattr(message, "sender", "") or "")[:80],
                "receiver": str(getattr(message, "receiver", "") or "")[:80],
                "status": str(getattr(getattr(message, "status", ""), "value", getattr(message, "status", ""))),
                "summary": _safe_message_summary_text(message),
                "refs": _message_ref_counts(message),
            }
        )
    summary = {
        "message_trace_available": bool(messages),
        "message_trace_id": trace.trace_id,
        "run_id": run_id,
        "message_count": len(messages),
        "last_message_type": type_values[-1] if type_values else "",
        "tool_call_count": sum(1 for item in type_values if item == "TOOL_CALL_REQUESTED"),
        "error_count": sum(1 for item in type_values if item == "ERROR_RAISED"),
        "approval_message_count": sum(1 for item in type_values if item in {"APPROVAL_REQUESTED", "APPROVAL_RESULT_RECEIVED"}),
        "artifact_message_count": sum(1 for item in type_values if item == "ARTIFACT_CREATED"),
        "messages": rows,
        "safety": {
            "secrets_redacted": True,
            "raw_paths_hidden": True,
            "raw_payload_hidden": True,
        },
    }
    return _redact_ui_payload(summary, max_chars=260)


def _format_message_trace_caption(summary: dict[str, Any] | None) -> str:
    if not isinstance(summary, dict) or not summary.get("message_trace_available"):
        return ""
    return (
        "Message trace: "
        f"messages={int(summary.get('message_count') or 0)} | "
        f"last={summary.get('last_message_type') or '-'} | "
        f"tools={int(summary.get('tool_call_count') or 0)} | "
        f"errors={int(summary.get('error_count') or 0)}"
    )


def _conversation_title_from_message(message: str) -> str:
    title = " ".join(str(message or "").strip().split())
    return (title[:28] + ("..." if len(title) > 28 else "")) if title else "New conversation"


def _create_conversation(user_id: str, db_path: str | None, *, title: str = "", language: str = "zh") -> str:
    conversation_id = f"conv_{uuid.uuid4().hex[:12]}"
    now = _now_text()
    _get_agent_repository(db_path).upsert_conversation(
        {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "title": title or "New conversation",
            "status": "active",
            "language": language,
            "created_at": now,
            "updated_at": now,
            "last_message_at": "",
            "metadata": {"surface": "ai_agent", "created_by": "streamlit_page"},
        }
    )
    _phase8_bump_cache(user_id, "conversations", f"current:{conversation_id}", f"messages:{conversation_id}")
    return conversation_id


def _list_active_conversations(user_id: str, db_path: str | None, *, limit: int = PHASE8_CONVERSATION_PAGE_SIZE, offset: int = 0) -> list[dict[str, Any]]:
    started_at = time.perf_counter()
    version = _phase8_cache_version(user_id, "conversations")
    signature = [_phase8_db_key(db_path), limit, offset, version]
    cache_hit = _phase8_cache_probe(user_id, "conversation_list", signature)
    if not cache_hit:
        _phase8_add_db_queries(user_id, 1)
    rows = _cached_active_conversations(user_id, _phase8_db_key(db_path), int(limit), int(offset), version)
    _phase8_record_metric(user_id, "conversation_list_ms", started_at)
    return list(rows or [])


def _conversation_exists(user_id: str, conversation_id: str, db_path: str | None) -> bool:
    if not conversation_id:
        return False
    row = _get_agent_repository(db_path).get_conversation(conversation_id)
    return bool(row and str(row.get("user_id") or "") == str(user_id) and str(row.get("status") or "active") == "active")


def _rename_conversation(user_id: str, conversation_id: str, title: str, db_path: str | None) -> bool:
    if not _conversation_exists(user_id, conversation_id, db_path):
        return False
    ok = _get_agent_repository(db_path).store.update(
        "conversations",
        {"conversation_id": conversation_id},
        {"title": str(title or "New conversation")[:80], "updated_at": _now_text()},
    ) > 0
    if ok:
        _phase8_bump_cache(user_id, "conversations", f"current:{conversation_id}")
    return ok


def _delete_conversation(user_id: str, conversation_id: str, db_path: str | None) -> bool:
    if not _conversation_exists(user_id, conversation_id, db_path):
        return False
    repo = _get_agent_repository(db_path)
    row = repo.get_conversation(conversation_id) or {}
    repo.upsert_conversation(
        {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "title": row.get("title") or "New conversation",
            "status": "deleted",
            "language": row.get("language") or "zh",
            "created_at": row.get("created_at") or _now_text(),
            "updated_at": _now_text(),
            "last_message_at": row.get("last_message_at") or "",
            "metadata": {"deleted_from": "ai_agent_page"},
        }
    )
    _phase8_bump_cache(user_id, "conversations", f"current:{conversation_id}", f"messages:{conversation_id}")
    return True


def _message_from_row(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata_json") if isinstance(row.get("metadata_json"), dict) else row.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    return {
        "role": str(row.get("role") or "assistant"),
        "content": str(row.get("content") or ""),
        "agent_result": metadata.get("agent_result") if isinstance(metadata.get("agent_result"), dict) else None,
        "message_id": str(row.get("message_id") or ""),
        "run_id": str(metadata.get("run_id") or ""),
        "created_at": str(row.get("created_at") or ""),
    }


def _load_conversation_messages(user_id: str, conversation_id: str, db_path: str | None, *, language: str = "zh", limit: int = PHASE8_LEGACY_DIRECT_LOAD_SIZE, offset: int = 0) -> list[dict[str, Any]]:
    started_at = time.perf_counter()
    version = _phase8_cache_version(user_id, f"messages:{conversation_id}")
    signature = [_phase8_db_key(db_path), conversation_id, limit, offset, version]
    cache_hit = _phase8_cache_probe(user_id, "messages_load", signature)
    if not cache_hit:
        _phase8_add_db_queries(user_id, 1)
    rows = _cached_recent_messages(user_id, _phase8_db_key(db_path), conversation_id, int(limit), int(offset), version)
    messages = [_message_from_row(row) for row in rows if str(row.get("user_id") or "") == str(user_id)]
    if not messages:
        messages = [{"role": "assistant", "content": _welcome_message(language), "agent_result": None}]
    _phase8_record_metric(user_id, "messages_load_ms", started_at)
    return messages


def _phase15_load_more_messages(
    *,
    user_id: str,
    conversation_id: str,
    db_path: str | None,
    language: str,
) -> int:
    current = _phase8_message_limit(user_id, conversation_id)
    next_limit = _phase15_next_message_limit(current)
    _phase8_set_message_limit(user_id, conversation_id, next_limit)
    st.session_state[_messages_key(user_id)] = _load_conversation_messages(
        user_id,
        conversation_id,
        db_path,
        language=language,
        limit=next_limit,
    )
    st.session_state[_phase8_loaded_conversation_key(user_id)] = conversation_id
    return next_limit


def _persist_conversation_message(
    *,
    user_id: str,
    conversation_id: str,
    role: str,
    content: str,
    db_path: str | None,
    language: str,
    agent_result: dict[str, Any] | None = None,
) -> str:
    repo = _get_agent_repository(db_path)
    now = _now_text()
    message_id = f"msg_{uuid.uuid4().hex[:12]}"
    run_id = str((agent_result or {}).get("run_id") or "")
    repo.upsert_message(
        {
            "message_id": message_id,
            "conversation_id": conversation_id,
            "user_id": user_id,
            "role": role,
            "content": str(content or ""),
            "language": language,
            "created_at": now,
            "token_estimate": _estimate_tokens(content),
            "metadata": _redact_ui_payload({"surface": "ai_agent", "agent_result": agent_result or None, "run_id": run_id}),
        }
    )
    conversation = repo.get_conversation(conversation_id) or {}
    title = str(conversation.get("title") or "")
    if role == "user" and (not title or title == "New conversation"):
        title = _conversation_title_from_message(content)
    repo.upsert_conversation(
        {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "title": title or "New conversation",
            "status": "active",
            "language": language,
            "created_at": conversation.get("created_at") or now,
            "updated_at": now,
            "last_message_at": now,
            "metadata": {"surface": "ai_agent", "last_run_id": run_id},
        }
    )
    _phase8_bump_cache(user_id, "conversations", f"current:{conversation_id}", f"messages:{conversation_id}")
    return message_id


def _init_chat(user_id: str, db_path: str | None = None) -> tuple[list[dict[str, Any]], str]:
    messages_key = _messages_key(user_id)
    session_key = _session_key(user_id)
    language = _get_reply_language(user_id)
    conversation_id = str(st.session_state.get(session_key) or "")
    if not _conversation_exists(user_id, conversation_id, db_path):
        conversations = _list_active_conversations(user_id, db_path, limit=PHASE8_CONVERSATION_PAGE_SIZE)
        conversation_id = str(conversations[0].get("conversation_id") or "") if conversations else ""
    if not conversation_id:
        conversation_id = _create_conversation(user_id, db_path, language=language)
    st.session_state[session_key] = conversation_id
    loaded_key = _phase8_loaded_conversation_key(user_id)
    if st.session_state.get(loaded_key) != conversation_id or messages_key not in st.session_state:
        st.session_state[messages_key] = _load_conversation_messages(
            user_id,
            conversation_id,
            db_path,
            language=language,
            limit=_phase8_message_limit(user_id, conversation_id),
        )
        st.session_state[loaded_key] = conversation_id
    else:
        st.session_state[messages_key] = _phase15_trim_visible_messages(
            st.session_state.get(messages_key) or [],
            _phase8_message_limit(user_id, conversation_id),
        )
        _phase8_perf_state(user_id)["cache_hit"] = int(_phase8_perf_state(user_id).get("cache_hit") or 0) + 1
    return st.session_state[messages_key], conversation_id


def _clear_chat(user_id: str, db_path: str | None = None) -> None:
    language = _get_reply_language(user_id)
    conversation_id = _create_conversation(user_id, db_path, language=language)
    _phase51_reset_conversation_view_state(user_id)
    st.session_state[_session_key(user_id)] = conversation_id
    _phase8_set_message_limit(user_id, conversation_id, PHASE8_MESSAGE_PAGE_SIZE)
    st.session_state[_phase8_loaded_conversation_key(user_id)] = conversation_id
    st.session_state[_messages_key(user_id)] = [{"role": "assistant", "content": _welcome_message(language), "agent_result": None}]


def _switch_conversation(user_id: str, conversation_id: str, db_path: str | None = None) -> None:
    if not _conversation_exists(user_id, conversation_id, db_path):
        return
    language = _get_reply_language(user_id)
    _phase51_reset_conversation_view_state(user_id)
    st.session_state[_session_key(user_id)] = conversation_id
    st.session_state[_messages_key(user_id)] = _load_conversation_messages(
        user_id,
        conversation_id,
        db_path,
        language=language,
        limit=_phase8_message_limit(user_id, conversation_id),
    )
    st.session_state[_phase8_loaded_conversation_key(user_id)] = conversation_id


def _phase8_run_conversation_map(plans: list[dict[str, Any]], db_path: str | None) -> dict[str, str]:
    run_ids = sorted({str(plan.get("run_id") or "") for plan in plans if str(plan.get("run_id") or "").strip()})
    if not run_ids:
        return {}
    rows = _get_agent_repository(db_path).list_agent_runs_by_ids(run_ids)
    return {str(row.get("run_id") or ""): str(row.get("conversation_id") or "") for row in rows}


def _pending_plans_for_conversation(user_id: str, output_dir: str, db_path: str | None, conversation_id: str) -> list[dict[str, Any]]:
    started_at = time.perf_counter()
    pending = _safe_pending(user_id, output_dir)
    candidates = [plan for plan in pending.values() if plan.get("execution_status") not in {"executed", "cancelled"}]
    run_map = _phase8_run_conversation_map(candidates, db_path)
    if any(str(plan.get("run_id") or "").strip() for plan in candidates):
        _phase8_add_db_queries(user_id, 1)
    active = []
    for plan in candidates:
        run_id = str(plan.get("run_id") or "")
        if not run_id or run_id not in run_map or run_map.get(run_id) == str(conversation_id or ""):
            active.append(plan)
    active.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    _phase8_record_metric(user_id, "pending_plan_ms", started_at)
    return active


OPERATION_TYPE_LABELS = {
    "execute_add_stock": "加入持仓预览",
    "execute_adjust_position": "调仓预览",
    "capital_change": "资金变更",
    "paper_backfill": "历史回放",
    "register_strategy": "注册策略",
    "enable_strategy": "启用策略",
    "strategy_change": "策略变更",
}


def _format_business_value(value: Any, *, max_chars: int = 260) -> str:
    if value in (None, "", [], {}):
        return "-"
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            if str(key) in {"confirmation_token", "confirmation_token_hash", "plan_hash", "snapshot_id", "business_state_version", "module_path"}:
                continue
            if item not in (None, "", [], {}):
                parts.append(f"{key}: {_format_business_value(item, max_chars=80)}")
            if len(parts) >= 5:
                break
        text = "；".join(parts) if parts else "-"
    elif isinstance(value, list):
        text = " / ".join(_format_business_value(item, max_chars=100) for item in value[:5])
    else:
        text = str(value)
    return text if len(text) <= max_chars else text[:max_chars] + "..."


def _format_preview_cell(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(_redact_ui_payload(value), ensure_ascii=False, default=str)
    return str(value or "")


def _plan_is_expired(plan: dict[str, Any]) -> bool:
    expires_at = str(plan.get("expires_at") or "")
    if not expires_at:
        return False
    try:
        return datetime.fromisoformat(expires_at.replace("Z", "+00:00")).replace(tzinfo=None) < datetime.now()
    except Exception:
        return False


def _plan_stage(plan: dict[str, Any]) -> str:
    if str(plan.get("execution_status") or "") == "executed":
        return "完成"
    if str(plan.get("execution_status") or "") == "cancelled":
        return "已取消"
    if _plan_is_expired(plan) or str(plan.get("confirmation_status") or "") == "expired":
        return "已过期"
    return "等待确认"


def _plan_target(plan: dict[str, Any]) -> str:
    changes = plan.get("proposed_changes") or plan.get("changes") or []
    if isinstance(changes, dict):
        changes = [changes]
    targets = []
    for item in changes if isinstance(changes, list) else []:
        if isinstance(item, dict):
            stock = " ".join(str(item.get(key) or "") for key in ("stock_code", "stock_name")).strip()
            strategy = " ".join(str(item.get(key) or "") for key in ("strategy_name", "version")).strip()
            targets.append(stock or strategy or _format_business_value(item))
    return "；".join(dict.fromkeys(targets)) if targets else "当前模拟盘 / 当前策略"


def _build_plan_card(plan: dict[str, Any]) -> dict[str, Any]:
    operation_type = str(plan.get("operation_type") or plan.get("intent") or "")
    warnings = plan.get("warnings") or []
    if isinstance(warnings, str):
        warnings = [warnings]
    return {
        "operation_type": OPERATION_TYPE_LABELS.get(operation_type, operation_type or "待确认操作"),
        "target": _plan_target(plan),
        "before": _format_business_value(plan.get("before_state_summary") or plan.get("before") or {}),
        "changes": _format_business_value(plan.get("proposed_changes") or []),
        "after": _format_business_value(plan.get("after_state_preview") or plan.get("after") or {}),
        "reason": str(plan.get("reason") or (plan.get("metadata") or {}).get("reason") or "根据当前请求生成的待确认操作预案。"),
        "risks": "；".join(str(item) for item in warnings if str(item).strip()) or "未发现额外风险提示，仍需确认前复核。",
        "estimated_impact": _format_business_value((plan.get("validation_results") or {}).get("estimated_impact") if isinstance(plan.get("validation_results"), dict) else {}),
        "reversible": "可通过后续模拟盘操作修正；不会接入真实券商。",
        "expires_at": str(plan.get("expires_at") or "-"),
        "stage": _plan_stage(plan),
    }


def _technical_plan_details(plan: dict[str, Any]) -> dict[str, Any]:
    hidden = {"confirmation_token", "confirmation_token_hash", "plan_hash", "business_state_version", "snapshot_id", "state_id"}
    return {key: _redact_ui_payload(value) for key, value in plan.items() if str(key) not in hidden}


def _phase51_plan_summary_rows(plan: dict[str, Any]) -> list[dict[str, str]]:
    card = _build_plan_card(plan)
    labels = [
        ("操作类型", "operation_type"),
        ("影响对象", "target"),
        ("修改前", "before"),
        ("拟执行变更", "changes"),
        ("修改后预览", "after"),
        ("变化原因", "reason"),
        ("风险提示", "risks"),
        ("预计影响", "estimated_impact"),
        ("是否可撤销", "reversible"),
        ("计划有效期", "expires_at"),
    ]
    return [{"label": label, "value": str(card.get(key) or "-")} for label, key in labels]


def _phase51_conversation_title(row: dict[str, Any], *, language: str) -> str:
    raw = str(row.get("title") or "").strip()
    if not raw or raw == "New conversation":
        return "新会话"
    return raw[:42] + ("..." if len(raw) > 42 else "")


def _phase51_conversation_label(row: dict[str, Any], active_conversation_id: str, *, language: str) -> str:
    conversation_id = str(row.get("conversation_id") or "")
    title = _phase51_conversation_title(row, language=language)
    updated_at = str(row.get("last_message_at") or row.get("updated_at") or "")[:16]
    marker = "* " if conversation_id == str(active_conversation_id or "") else ""
    suffix = conversation_id[-8:] if conversation_id else "-"
    time_part = f" | {updated_at}" if updated_at else ""
    return f"{marker}{title}{time_part} | {suffix}"


def _phase51_active_conversation_options(
    conversations: list[dict[str, Any]],
    session_id: str,
) -> list[str]:
    options = [
        str(row.get("conversation_id") or "")
        for row in conversations
        if str(row.get("conversation_id") or "")
    ]
    if session_id and session_id not in options:
        options.insert(0, session_id)
    return options


def _phase51_render_conversation_manager(
    *,
    user_id: str,
    db_path: str | None,
    session_id: str,
    language: str,
) -> None:
    conversations = _list_active_conversations(user_id, db_path, limit=PHASE8_CONVERSATION_PAGE_SIZE)
    rows_by_id = {
        str(row.get("conversation_id") or ""): dict(row)
        for row in conversations
        if str(row.get("conversation_id") or "")
    }
    current_row = _phase51_current_conversation(user_id, db_path, session_id)
    if session_id and session_id not in rows_by_id:
        rows_by_id[session_id] = current_row or {"conversation_id": session_id, "title": "New conversation"}
    options = _phase51_active_conversation_options(list(rows_by_id.values()), session_id)

    st.markdown("#### Conversation manager / 对话管理")
    with st.container():
        st.caption(f"Current conversation / 当前会话标识: `{session_id[-12:] or '-'}`")
        action_cols = st.columns([1, 1, 2])
        with action_cols[0]:
            if st.button("New conversation / 新建对话", key=f"ai_agent_new_conversation::{user_id}", use_container_width=True):
                _clear_chat(user_id, db_path)
                _phase8_rerun(user_id, "conversation_new")
        with action_cols[1]:
            if st.button("Delete current / 删除当前会话", key=f"ai_agent_delete_conversation::{user_id}::{session_id}", use_container_width=True):
                _delete_conversation(user_id, session_id, db_path)
                remaining = [
                    row
                    for row in _list_active_conversations(user_id, db_path, limit=PHASE8_CONVERSATION_PAGE_SIZE)
                    if str(row.get("conversation_id") or "") != session_id
                ]
                if remaining:
                    _switch_conversation(user_id, str(remaining[0].get("conversation_id") or ""), db_path)
                else:
                    _clear_chat(user_id, db_path)
                _phase8_rerun(user_id, "conversation_delete")

        selected = session_id
        if options:
            try:
                selected = st.selectbox(
                    "Switch conversation / 切换对话",
                    options,
                    index=options.index(session_id) if session_id in options else 0,
                    format_func=lambda item: _phase51_conversation_label(rows_by_id.get(str(item), {"conversation_id": item}), session_id, language=language),
                    key=f"ai_agent_conversation_select::{user_id}",
                )
            except Exception:
                selected = session_id
        if selected and str(selected) != str(session_id):
            _switch_conversation(user_id, str(selected), db_path)
            _phase8_rerun(user_id, "conversation_switch")

        st.caption(f"Conversations loaded / 已加载会话数: {len(options)}")


def _phase51_is_welcome_message(message: dict[str, Any], language: str) -> bool:
    return (
        str(message.get("role") or "") == "assistant"
        and str(message.get("content") or "").strip() == _welcome_message(language).strip()
        and not message.get("agent_result")
    )


def _phase51_public_messages(messages: list[dict[str, Any]], language: str) -> list[dict[str, Any]]:
    has_user_message = any(str(message.get("role") or "") == "user" for message in messages)
    if not has_user_message:
        return []
    return [message for message in messages if not _phase51_is_welcome_message(message, language)]


def _phase51_last_agent_result(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in reversed(messages):
        result = message.get("agent_result")
        if str(message.get("role") or "") == "assistant" and isinstance(result, dict):
            return result
    return None


def _phase51_current_conversation(user_id: str, db_path: str | None, session_id: str) -> dict[str, Any]:
    version = _phase8_cache_version(user_id, f"current:{session_id}")
    signature = [_phase8_db_key(db_path), session_id, version]
    cache_hit = _phase8_cache_probe(user_id, "current_conversation", signature)
    if not cache_hit:
        _phase8_add_db_queries(user_id, 1)
    return _cached_current_conversation(user_id, _phase8_db_key(db_path), session_id, version)


def _phase8_developer_details_key(user_id: str, session_id: str) -> str:
    return f"ai_agent_phase8_developer_details::{user_id}::{session_id}"


def _phase8_developer_details_enabled(user_id: str, session_id: str) -> bool:
    return bool(st.session_state.get(_phase8_developer_details_key(user_id, session_id), False))


def _phase8_perf_snapshot(user_id: str) -> dict[str, Any]:
    state = _phase8_perf_state(user_id)
    keys = [
        "page_render_ms",
        "conversation_list_ms",
        "messages_load_ms",
        "pending_plan_ms",
        "memory_lazy_load_ms",
        "db_query_count",
        "cache_hit",
        "cache_miss",
        "rerun_count",
        "last_rerun_reason",
    ]
    return {key: state.get(key) for key in keys}


def _phase51_render_developer_details(
    *,
    user_id: str,
    session_id: str,
    messages: list[dict[str, Any]],
    tools: list[Any],
    db_path: str | None,
    output_dir: str | Path = "outputs",
    language: str = "zh",
) -> None:
    with st.expander("Developer details", expanded=False):
        st.markdown("#### Phase 8 Loading")
        st.json(_phase8_perf_snapshot(user_id))
        st.caption(build_memory_safe_summary(user_id=user_id, output_dir=output_dir))
        st.markdown("#### Memory safe summary")
        st.caption("Memory records are loaded as a small sanitized page only after this is enabled.")
        if st.checkbox("Load memory safe page", key=_phase15_lazy_detail_key("memory_page", user_id, session_id)):
            st.json(list_memory_records_safe_page(user_id=user_id, output_dir=output_dir, limit=5, offset=0))
        load_details = st.checkbox("Load developer details", key=_phase8_developer_details_key(user_id, session_id))
        if not load_details:
            st.caption("Memory, replay, timeline, and tools are loaded only after this is enabled.")
            return
        started_at = time.perf_counter()
        last_result = _phase51_last_agent_result(messages) or {}
        st.markdown("#### MCP")
        st.json(_redact_ui_payload_for_display(summarize_mcp_usage(last_result)))
        st.markdown("#### Last agent result")
        st.json(_redact_ui_payload_for_display(last_result))
        _phase8_record_metric(user_id, "memory_lazy_load_ms", started_at)
        st.divider()
        st.json(_redact_ui_payload_for_display(tools or _safe_tools()))


def _extract_warnings(result: dict[str, Any]) -> list[str]:
    warnings: list[str] = []

    direct = result.get("warnings")
    if isinstance(direct, list):
        warnings.extend(str(item) for item in direct if str(item).strip())
    elif direct:
        warnings.append(str(direct))

    nested = result.get("result")
    if isinstance(nested, dict):
        nested_warnings = nested.get("warnings")
        if isinstance(nested_warnings, list):
            warnings.extend(
                str(item)
                for item in nested_warnings
                if str(item).strip()
            )
        elif nested_warnings:
            warnings.append(str(nested_warnings))

    return list(dict.fromkeys(warnings))


def _normalise_answer(result: dict[str, Any], language: str | None = None) -> str:
    del language
    answer = str(
        result.get("answer")
        or result.get("message")
        or result.get("response")
        or ""
    ).strip()

    internal_failure_markers = [
        "Missing or invalid stock code",
        "Agent request failed",
        "Please enter a question or command",
        "invalid_stock_code",
        "missing_stock_code",
    ]

    if _is_explainable_business_failure(result):
        pass
    elif (
        not result.get("success", False)
        or not answer
        or any(marker in answer for marker in internal_failure_markers)
    ):
        answer = UNAVAILABLE_MESSAGE

    if "不构成投资建议" not in answer:
        answer = f"{answer}\n\n{COMPLIANCE_NOTE}".strip()

    return answer


def _run_agent(
    query: str,
    *,
    user_id: str,
    output_dir: str,
    db_path: str | None,
    default_topk: int,
    session_id: str,
    llm_api_key: str | None = None,
    llm_base_url: str | None = None,
    llm_model: str | None = None,
) -> dict[str, Any]:
    trace_event("ui.agent.submit", {"query": query, "user_id": user_id, "session_id": session_id})
    try:
        result = run_agent_request(
            query,
            user_id=user_id,
            output_dir=output_dir,
            db_path=db_path,
            top_k=int(default_topk or 50),
            session_id=session_id,
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            llm_model=llm_model,
        )
        if isinstance(result, dict):
            return result
        return {
            "success": True,
            "answer": str(result),
            "raw_result": result,
        }
    except Exception as exc:
        trace_exception("ui.agent.failed", exc, run_id="", task_id="")
        # LLM-First mode must never fall back to the legacy keyword registry.
        return {
            "success": False,
            "answer": (
                "LLM-First Agent 当前无法可靠理解或执行本次请求。"
                "请检查模型连接、API 配置或补充必要信息后重试。\n\n"
                + COMPLIANCE_NOTE
            ),
            "error_type": type(exc).__name__,
            "fallback_used": False,
        }


def _render_result_details(
    result: dict[str, Any] | None,
    *,
    user_id: str = "default",
    output_dir: str = "outputs",
) -> None:
    if not result:
        return

    for warning in _extract_warnings(result):
        st.warning(warning)

    context_summary = _build_context_safe_summary(result)
    if context_summary.get("context_available") or context_summary.get("run_id"):
        caption = _format_context_safe_caption(context_summary)
        if caption:
            st.caption(caption)
        with st.expander("Context 安全摘要", expanded=False):
            if st.checkbox(
                "Load context safe summary",
                key=_phase15_lazy_detail_key("context", user_id, str(context_summary.get("run_id") or "")),
            ):
                st.json(context_summary)

    message_trace_summary = _build_message_trace_safe_summary(result, user_id=user_id, output_dir=output_dir)
    if message_trace_summary.get("message_trace_available"):
        caption = _format_message_trace_caption(message_trace_summary)
        if caption:
            st.caption(caption)
        with st.expander("Message Trace 安全摘要", expanded=False):
            if st.checkbox(
                "Load message trace safe summary",
                key=_phase15_lazy_detail_key("message_trace", user_id, str(message_trace_summary.get("run_id") or "")),
            ):
                st.json(message_trace_summary)

    reflection_summary = build_reflection_safe_summary(result, user_id=user_id, output_dir=output_dir)
    if reflection_summary.get("reflection_available"):
        caption = format_reflection_caption(reflection_summary)
        if caption:
            st.caption(caption)
        with st.expander("Reflection Critic 安全摘要", expanded=False):
            if st.checkbox(
                "Load Reflection Critic safe summary",
                key=_phase15_lazy_detail_key("reflection_summary", user_id, str(reflection_summary.get("run_id") or "")),
            ):
                st.json(reflection_summary)

    handoff_summary = build_handoff_safe_summary(result, user_id=user_id, output_dir=output_dir)
    if handoff_summary.get("handoff_available"):
        caption = format_handoff_caption(handoff_summary)
        if caption:
            st.caption(caption)
        with st.expander("Handoff 安全摘要", expanded=False):
            if st.checkbox(
                "Load Handoff safe summary",
                key=_phase15_lazy_detail_key("handoff_summary", user_id, str(handoff_summary.get("run_id") or "")),
            ):
                st.json(handoff_summary)

    with st.expander("查看工具调用与原始结果", expanded=False):
        run_id = _phase15_run_id_from_result(result)
        if st.checkbox(
            "Load sanitized tool/result details",
            key=_phase15_lazy_detail_key("tool_result", user_id, run_id or str(id(result))),
        ):
            st.json(_redact_ui_payload_for_display(result))


    react_summary = build_react_safe_summary(user_id=user_id, output_dir=output_dir, run_id=run_id)
    if react_summary.get("run_id") or react_summary.get("observation_count"):
        st.caption(
            "ReAct trace: "
            f"observations={int(react_summary.get('observation_count') or 0)} | "
            f"blocking={int(react_summary.get('blocking_observation_count') or 0)} | "
            f"replans={int(react_summary.get('replan_message_count') or 0)}"
        )
        with st.expander("ReAct trace safe summary", expanded=False):
            if st.checkbox(
                "Load ReAct trace safe summary",
                key=_phase15_lazy_detail_key("react_summary", user_id, run_id),
            ):
                st.json(react_summary)
            if st.checkbox(
                "Load ReAct observation page",
                key=_phase15_lazy_detail_key("react_observations", user_id, run_id),
            ):
                st.json(
                    list_safe_observation_summaries(
                        user_id=user_id,
                        output_dir=output_dir,
                        run_id=run_id,
                        limit=5,
                        offset=0,
                    )
                )


def _render_history(messages: list[dict[str, Any]], *, user_id: str = "default", output_dir: str = "outputs") -> None:
    for message in messages:
        role = str(message.get("role") or "assistant")
        content = str(message.get("content") or "")

        with st.chat_message(role):
            st.markdown(content)
            _render_result_details(message.get("agent_result"), user_id=user_id, output_dir=output_dir)


def _task_rows_from_orchestration(orchestration: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(orchestration, dict):
        return rows
    for task_id, item in (orchestration.get("task_results") or {}).items():
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "task_id": str(task_id),
                "intent": str(item.get("intent") or ""),
                "status": str(item.get("step_status") or item.get("status") or ""),
                "execution_mode": str(item.get("execution_mode") or ""),
                "duration_seconds": item.get("duration_seconds", ""),
            }
        )
    return rows


def _tool_rows_from_result(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    rows = []
    for item in result.get("tool_calls") or []:
        if isinstance(item, dict):
            rows.append(
                {
                    "task_id": str(item.get("task_id") or ""),
                    "tool_name": str(item.get("tool_name") or item.get("name") or ""),
                    "success": item.get("success", item.get("status")),
                }
            )
    return rows


def _collect_source_references(result: dict[str, Any] | None) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key in ("source_file", "file_path", "path"):
                if value.get(key):
                    found.append({"source": str(value.get(key))})
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(result or {})
    return found[:50]


def _sandbox_rows_from_orchestration(orchestration: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(orchestration, dict):
        return rows
    for task_id, task_result in (orchestration.get("task_results") or {}).items():
        if not isinstance(task_result, dict) or task_result.get("intent") != "python_sandbox_analysis":
            continue
        data = dict(task_result.get("data") or {})
        rows.append(
            {
                "task_id": str(task_id),
                "status": str(data.get("status") or task_result.get("step_status") or ""),
                "snapshot_id": str(data.get("snapshot_id") or ""),
                "code_hash": str(data.get("code_hash") or "")[:12],
                "duration_seconds": data.get("duration_seconds", task_result.get("duration_seconds", "")),
                "refusal_reason": str(data.get("refusal_reason") or ""),
            }
        )
    return rows


def _is_explainable_business_failure(result: dict[str, Any] | None) -> bool:
    if not isinstance(result, dict):
        return False
    errors = (result.get("result") or {}).get("errors") if isinstance(result.get("result"), dict) else []
    text = " ".join(str(item) for item in errors if item)
    text += " " + str(result.get("intent") or "")
    return "insufficient_strategy_rule" in text or "strategy_change" in text


def _runtime_summary_from_result(result: dict[str, Any] | None, db_path: str | None = None) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    runtime = result.get("runtime") if isinstance(result.get("runtime"), dict) else {}
    run_id = str(result.get("run_id") or runtime.get("run_id") or "")
    if not run_id:
        return {}
    snapshot: dict[str, Any] = {}
    if db_path:
        try:
            snapshot = load_run_snapshot(db_path, run_id)
        except Exception as exc:
            snapshot = {"load_error": f"{type(exc).__name__}: {exc}"}
    run = snapshot.get("run") if isinstance(snapshot.get("run"), dict) else {}
    steps = snapshot.get("steps") if isinstance(snapshot.get("steps"), list) else []
    tool_calls = snapshot.get("tool_calls") if isinstance(snapshot.get("tool_calls"), list) else []
    sources = snapshot.get("sources") if isinstance(snapshot.get("sources"), list) else []
    return {
        "run_id": run_id,
        "status": str(run.get("status") or runtime.get("status") or ""),
        "steps": [
            {
                "step_id": str(row.get("step_id") or ""),
                "intent": str(row.get("intent") or ""),
                "status": str(row.get("status") or ""),
                "duration_seconds": row.get("duration_seconds", ""),
                "observation": str(row.get("observation_summary") or "")[:160],
                "agent_role": str((row.get("metadata_json") or {}).get("agent_role") or ""),
                "agent_input_summary": str((row.get("metadata_json") or {}).get("agent_input_summary") or "")[:180],
                "agent_output_summary": str((row.get("metadata_json") or {}).get("agent_output_summary") or "")[:220],
            }
            for row in steps
            if isinstance(row, dict)
        ],
        "tool_calls": [
            {
                "tool_call_id": str(row.get("tool_call_id") or ""),
                "tool_name": str(row.get("tool_name") or ""),
                "status": str(row.get("status") or ""),
                "error_type": str(row.get("error_type") or ""),
            }
            for row in tool_calls
            if isinstance(row, dict)
        ],
        "sources": [
            {
                "source_type": str(row.get("source_type") or ""),
                "title": str(row.get("source_title") or ""),
                "snippet": str(row.get("snippet") or "")[:160],
            }
            for row in sources
            if isinstance(row, dict)
        ],
        "load_error": str(snapshot.get("load_error") or ""),
    }


def _render_pending_plan(
    user_id: str,
    plan: dict[str, Any],
    output_dir: str,
    db_path: str | None,
    session_id: str,
) -> None:
    plan_id = str(plan.get("plan_id") or "")
    intent = str(plan.get("intent") or "")

    with st.expander(
        f"待确认计划：{intent} / {plan_id}",
        expanded=False,
    ):
        st.json(_technical_plan_details(plan))

        confirm_col, reject_col = st.columns(2)
        if confirm_col.button(
            "确认执行",
            key=f"agent_confirm_button_{plan_id}",
        ):
            token = str(plan.get("confirmation_token") or "")
            if not token:
                st.error("确认凭证已失效，请重新生成计划。")
                return
            result = execute_confirmed_plan_v2(
                plan_id=plan_id,
                confirmation_token=token,
                user_id=user_id,
                conversation_id=session_id,
                run_id=str(plan.get("run_id") or ""),
                output_dir=output_dir,
                db_path=db_path,
            )
            if result.success:
                st.success(result.message)
            else:
                st.error(result.message)
            st.json(_redact_ui_payload_for_display(result.to_dict()))
            if result.success:
                _phase8_rerun(user_id, "pending_confirm")
            return

        if reject_col.button(
            "拒绝计划",
            key=f"agent_reject_button_{plan_id}",
        ):
            rejected, status, _ = reject_confirmation_plan(
                user_id,
                plan_id,
                output_dir=output_dir,
                db_path=db_path,
            )
            if rejected:
                st.success("计划已拒绝，模拟盘未发生提交。")
                _phase8_rerun(user_id, "pending_reject")
            else:
                st.error(f"计划拒绝失败：{status}")
            return

            if intent == "execute_add_stock":
                result = _legacy_direct_commit_disabled(
                    user_id,
                    plan_id,
                    token,
                    output_dir=output_dir,
                    db_path=db_path,
                    session_id=session_id,
                )
            elif intent == "capital_change":
                result = _legacy_direct_commit_disabled(
                    user_id,
                    plan_id,
                    token,
                    output_dir=output_dir,
                    db_path=db_path,
                    session_id=session_id,
                )
            elif intent == "paper_backfill":
                result = _legacy_direct_commit_disabled(
                    user_id,
                    plan_id,
                    token,
                    output_dir=output_dir,
                    db_path=db_path,
                    session_id=session_id,
                )
            else:
                st.error(f"不支持的确认计划类型：{intent}")
                return

            if result.success:
                st.success(result.message)
            else:
                st.error(result.message)

            st.json(_redact_ui_payload_for_display(result.to_dict()))

            if result.success:
                _phase8_rerun(user_id, "pending_confirm")


def _safe_portfolio_state(
    user_id: str,
    output_dir: str,
    db_path: str | None,
) -> dict[str, Any]:
    try:
        return query_portfolio_state(
            user_id,
            output_dir=output_dir,
            db_path=db_path,
        )
    except Exception as exc:
        return {
            "position_count": 0,
            "status": "unavailable",
            "error": f"{type(exc).__name__}: {exc}",
        }


def _safe_scheduler_status() -> dict[str, Any]:
    try:
        return query_scheduler_status(".")
    except Exception as exc:
        return {
            "status": "unavailable",
            "error": f"{type(exc).__name__}: {exc}",
        }


def _safe_tools() -> list[Any]:
    try:
        return list(_cached_tool_list() or [])
    except Exception as exc:
        return [{
            "status": "unavailable",
            "error": f"{type(exc).__name__}: {exc}",
        }]


def _safe_pending(
    user_id: str,
    output_dir: str,
) -> dict[str, dict[str, Any]]:
    try:
        return dict(load_pending_actions(user_id, output_dir) or {})
    except Exception:
        return {}


def render_ai_agent_page(
    ranking: pd.DataFrame | None = None,
    metrics: dict | None = None,
    llm_api_key: str | None = None,
    llm_base_url: str | None = None,
    llm_model: str | None = None,
    default_topk: int = 10,
    model_name: str | None = None,
    user_id: str = "default",
    output_dir: str = "outputs",
    db_path: str | None = None,
) -> None:
    del ranking, metrics, model_name
    page_started_at = _phase8_begin_page_render(user_id)
    _phase51_compat_literals = ("会话", "待确认计划")
    del _phase51_compat_literals

    st.subheader("AI Agent 控制中心")
    st.caption(
        "使用自然语言查询预测、新闻、模拟盘和系统状态。"
        "Agent 只能读取证据、生成模拟盘预览，并在确认后调用"
        "后端模拟盘工具；不连接券商，不做真实交易。"
    )

    messages, session_id = _init_chat(user_id, db_path)
    _phase51_render_conversation_manager(
        user_id=user_id,
        db_path=db_path,
        session_id=session_id,
        language=_get_reply_language(user_id),
    )
    active_pending = _pending_plans_for_conversation(user_id, output_dir, db_path, session_id)
    tools: list[Any] = []

    cols = st.columns(5)
    cols[0].metric("User ID", user_id)
    cols[1].metric("工具", "on demand")
    cols[2].metric("待确认", len(active_pending))
    cols[3].metric("DB queries", _phase8_perf_state(user_id).get("db_query_count", 0))
    cols[4].metric("Cache hit", _phase8_perf_state(user_id).get("cache_hit", 0))

    title_col, clear_col = st.columns([5, 1])

    with title_col:
        st.markdown("### 对话")
        st.caption(f"当前会话：`{session_id[-8:]}`")

    with clear_col:
        if st.button(
            "清空对话",
            key=f"ai_agent_clear_chat::{user_id}",
            use_container_width=True,
        ):
            _clear_chat(user_id, db_path)
            _phase8_rerun(user_id, "conversation_new")

    st.markdown("#### 快捷提问")
    quick_columns = st.columns(2)
    selected_question: str | None = None

    for index, question in enumerate(QUICK_QUESTIONS):
        with quick_columns[index % 2]:
            if st.button(
                question,
                key=f"ai_agent_quick::{user_id}::{index}",
                use_container_width=True,
            ):
                selected_question = question

    st.divider()
    current_message_limit = _phase8_message_limit(user_id, session_id)
    st.caption(
        f"Showing the latest {min(len(messages or []), current_message_limit)} messages "
        f"(window={current_message_limit}, default={PHASE15_VISIBLE_MESSAGE_WINDOW})."
    )
    if _phase15_should_offer_load_earlier(messages, current_message_limit):
        if st.button(
            "Load earlier messages",
            key=f"ai_agent_phase15_load_earlier::{user_id}::{session_id}::{current_message_limit}",
        ):
            _phase15_load_more_messages(
                user_id=user_id,
                conversation_id=session_id,
                db_path=db_path,
                language=_get_reply_language(user_id),
            )
            _phase8_rerun(user_id, "message_load_earlier")
    _render_history(messages, user_id=user_id, output_dir=output_dir)

    typed_question = st.chat_input(
        "请输入问题，例如：分析 600519，或查看当前模拟盘持仓"
    )
    question = str(
        typed_question or selected_question or ""
    ).strip()

    if question:
        messages.append({
            "role": "user",
            "content": question,
            "agent_result": None,
        })
        _persist_conversation_message(
            user_id=user_id,
            conversation_id=session_id,
            role="user",
            content=question,
            db_path=db_path,
            language=_get_reply_language(user_id),
        )

        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            with st.spinner("Agent 正在识别意图并调用工具..."):
                result = _run_agent(
                    question,
                    user_id=user_id,
                    output_dir=output_dir,
                    db_path=db_path,
                    default_topk=default_topk,
                    session_id=session_id,
                    llm_api_key=llm_api_key,
                    llm_base_url=llm_base_url,
                    llm_model=llm_model,
                )

            answer = _normalise_answer(result)

            if result.get("success", False):
                st.caption("Agent 已完成处理。")
            else:
                st.caption("相关功能仍在后续开发中。")

            st.markdown(answer)
            _render_result_details(result, user_id=user_id, output_dir=output_dir)

        messages.append({
            "role": "assistant",
            "content": answer,
            "agent_result": result,
        })
        _persist_conversation_message(
            user_id=user_id,
            conversation_id=session_id,
            role="assistant",
            content=answer,
            db_path=db_path,
            language=_get_reply_language(user_id),
            agent_result=result,
        )
        _phase8_rerun(user_id, "message_submit")

    st.divider()

    active_plans = active_pending

    with st.expander(
        f"待确认计划（{len(active_plans)}）",
        expanded=bool(active_plans),
    ):
        if not active_plans:
            st.info("当前没有待确认计划。")

        for plan in sorted(
            active_plans,
            key=lambda item: str(item.get("created_at") or ""),
            reverse=True,
        ):
            _render_pending_plan(
                user_id,
                plan,
                output_dir,
                db_path,
                session_id,
            )

    _phase8_record_metric(user_id, "page_render_ms", page_started_at)
    _phase51_render_developer_details(
        user_id=user_id,
        session_id=session_id,
        messages=messages,
        tools=tools,
        db_path=db_path,
        output_dir=output_dir,
        language=_get_reply_language(user_id),
    )

    st.warning(COMPLIANCE_NOTE)
    st.caption(PAPER_AGENT_DISCLAIMER)


def render(*args, **kwargs) -> None:
    render_ai_agent_page(*args, **kwargs)
