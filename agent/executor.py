from __future__ import annotations

from hashlib import sha256
import json
import re
from pathlib import Path
from typing import Any

from agent.console_trace import flow_event, trace_event, trace_exception
from agent.llm_audit import activate_llm_audit_context
from core.llm.runtime_settings import LLMRuntimeSettings, resolve_active_llm_settings

from agent.communication.integration import (
    approval_refs_from_payload,
    artifact_refs_from_result,
    context_ref_from_bundle,
    publish_agent_message,
    result_summary_payload,
)
from agent.communication.message_types import MessageType
from agent.context import (
    ContextManager,
    build_observer_context,
    build_planner_context,
    build_reporter_context,
)
from agent.router import route_agent_query
from agent.goal_planning import observe_goal_completion
from agent.intent_decomposition.llm_decomposer import critique_report_with_llm, generate_report_with_llm
from agent.handoff import AgentRole, HandoffCoordinator
from agent.orchestration.multi_task_executor import (
    execute_multi_intent_plan,
)
from agent.runtime import (
    AgentRuntimeRecorder,
    RUN_COMPLETED,
    RUN_CANCELLED,
    RUN_FAILED,
    RUN_OBSERVING,
    RUN_PARTIALLY_COMPLETED,
    RUN_PLANNING,
    RUN_REVALIDATING,
    RUN_COMMITTING,
    RUN_RUNNING,
    RUN_WAITING_FOR_APPROVAL,
    STEP_FAILED,
    STEP_SKIPPED,
    STEP_SUCCEEDED,
    sanitize_payload,
    now_text,
)
from agent.runtime_reliability import (
    CircuitBreakerRegistry,
    RuntimeBudget,
    RuntimeCheckpointer,
    RuntimePolicy,
    execute_with_policy,
)
from agent.react.integration import record_executor_result_observation
from agent.logic_integrity import (
    feature_unavailable_payload,
    is_terminal_agent_state,
    terminal_completion_payload,
    terminal_critic_payload,
    validate_agent_logic_integrity,
)
from agent.replan_execution import consume_readonly_replan
from agent.reflection import CriticAction, CriticEngine, CriticSanitizer
from agent.top_k import (
    DEFAULT_CANDIDATE_REDUNDANCY_FACTOR,
    DEFAULT_TARGET_POSITION_COUNT,
    DEFAULT_TOOL_TOP_K,
    resolve_business_top_k,
    resolve_requested_top_k,
)
from agent.session.pending_action_store import get_pending_plan, update_pending_plan
from agent.agent_protocol import (
    AgentOutput,
    make_message_id,
    output_summary as agent_output_summary,
    timeline_entry,
)
from agent.agent_specs import (
    MARKET_INTELLIGENCE,
    PORTFOLIO_ANALYSIS,
    REPORTING,
    RISK_OPERATION,
    SUPERVISOR,
    is_read_only_multi_agent_candidate,
)
from agent.mcp.registry_bridge import (
    is_mcp_tool_name,
    select_relevant_mcp_tools,
)
from agent.mcp.config import build_mcp_context_from_local_config
from agent.specialists import (
    MarketIntelligenceAgent,
    PortfolioAnalysisAgent,
    ReportingAgent,
    RiskOperationAgent,
)
from agent.tool_engine import AGENT_MAIN, AGENT_READ, execute_tool_legacy_dict
from agent.write_gateway import execute_confirmed_plan_v2
from agent.session.confirmation_manager import reject_confirmation_plan
from agent.tools.audit_tool import write_agent_tool_call_log
from agent.tools.backfill_tool import preview_backfill
from agent.tools.capital_management_tool import preview_capital_change
from agent.tools.tool_schemas import ToolPermission, ToolResult
from agent.tools.portfolio_comparison_tools import TargetPortfolioStore
from agent.services.strategy_context_service import StrategyContextService
from database.repositories.agent_repository import AgentRepository
from agent.memory.conversation_state_manager import (
    ResolvedTurn,
    merge_planner_context,
    resolve_conversation_turn,
)


REPLY_LANGUAGE_ZH = "zh"
REPLY_LANGUAGE_EN = "en"
# Compatibility identifier retained for capability/audit readers. The strategy
# conversation mainline uses strategy.save_proposal_draft, not this legacy tool.
LEGACY_STRATEGY_BUILDER_TOOL_NAME = "strategy_builder_tool"

UNAVAILABLE_MESSAGES = {
    REPLY_LANGUAGE_ZH: "目前不能回答，相关功能仍在后续开发中。",
    REPLY_LANGUAGE_EN: (
        "This question cannot be answered at the moment. "
        "The related feature is still under development."
    ),
}

DISCLAIMERS = {
    REPLY_LANGUAGE_ZH: (
        "本回答仅用于机器学习、金融数据分析和项目展示，"
        "不构成投资建议，不用于实盘交易。"
    ),
    REPLY_LANGUAGE_EN: (
        "This response is only for machine learning, financial data analysis, "
        "and project demonstration. It is not investment advice and is not "
        "intended for live trading."
    ),
}

_LANGUAGE_MARKERS = {
    REPLY_LANGUAGE_ZH: [
        "中文回复",
        "用中文回复",
        "请用中文",
        "回答中文",
        "说中文",
        "回复中文",
        "reply in chinese",
        "answer in chinese",
        "respond in chinese",
        "chinese please",
    ],
    REPLY_LANGUAGE_EN: [
        "英文回复",
        "用英文回复",
        "请用英文",
        "回答英文",
        "说英文",
        "回复英文",
        "reply in english",
        "answer in english",
        "respond in english",
        "english please",
    ],
}

_DOMAIN_MARKERS = [
    "排名",
    "排行",
    "top",
    "预测",
    "股票",
    "个股",
    "分析",
    "新闻",
    "公告",
    "rag",
    "证据",
    "持仓",
    "账户",
    "资产",
    "订单",
    "仓位",
    "模拟盘",
    "调仓",
    "回放",
    "后台",
    "调度",
    "任务",
    "报告",
    "资金",
    "入金",
    "出金",
    "stock",
    "ranking",
    "portfolio",
    "position",
    "account",
    "news",
    "report",
    "scheduler",
    "backfill",
    "capital",
]

_STOCK_CODE_REQUIRED_INTENTS = {
    "stock_analysis",
    "stock_news",
    "stock_rag",
    "position_recommendation",
    "replacement_recommendation",
    "preview_add_stock",
    "adjust_position",
}


def _memory_task_hint(query: str) -> str:
    text = str(query or "").lower()
    if any(marker in text for marker in ("持仓", "组合", "portfolio", "position", "holding")):
        return "portfolio"
    if any(marker in text for marker in ("新闻", "公告", "rag", "证据", "news", "evidence")):
        return "market_evidence"
    if any(marker in text for marker in ("股票", "个股", "stock", "分析")):
        return "stock_analysis"
    if any(marker in text for marker in ("策略", "长期", "strategy", "policy")):
        return "strategy"
    return "general"


def normalise_reply_language(language: str | None) -> str:
    value = str(language or "").strip().lower()
    if value in {"en", "english", "英文"}:
        return REPLY_LANGUAGE_EN
    return REPLY_LANGUAGE_ZH


def detect_explicit_reply_language(query: str) -> str | None:
    text = str(query or "").strip().lower()
    if not text:
        return None

    matches: list[tuple[int, str]] = []
    for language, markers in _LANGUAGE_MARKERS.items():
        for marker in markers:
            position = text.rfind(marker)
            if position >= 0:
                matches.append((position, language))

    if not matches:
        return None

    matches.sort(key=lambda item: item[0])
    return matches[-1][1]


def is_language_setting_only(query: str) -> bool:
    text = str(query or "").strip().lower()
    if detect_explicit_reply_language(text) is None:
        return False

    if re.search(r"(?<!\d)\d{6}(?!\d)", text):
        return False

    return not any(marker in text for marker in _DOMAIN_MARKERS)


def resolve_reply_language(
    query: str,
    preferred_language: str | None = None,
) -> str:
    explicit = detect_explicit_reply_language(query)
    if explicit is not None:
        return explicit
    return normalise_reply_language(preferred_language)


def _unavailable(language: str) -> str:
    return UNAVAILABLE_MESSAGES[normalise_reply_language(language)]


def _llm_insufficient_balance_message(language: str) -> str:
    if normalise_reply_language(language) == REPLY_LANGUAGE_EN:
        return (
            "The LLM account has insufficient balance, so the current "
            "request could not be decomposed or executed. Please recharge "
            "the account or switch to an available API key or model, then retry."
        )

    return (
        "大模型账户余额不足，无法完成本次意图拆解和工具调用。"
        "请充值，或更换可用的 API Key/模型后重试。"
    )


def _disclaimer(language: str) -> str:
    return DISCLAIMERS[normalise_reply_language(language)]


def _language_acknowledgement(language: str) -> str:
    if normalise_reply_language(language) == REPLY_LANGUAGE_EN:
        return "Reply language has been set to English."
    return "回复语言已设置为中文。"


def _tool_result_dict(
    result: ToolResult | dict[str, Any],
) -> dict[str, Any]:
    return (
        result.to_dict()
        if hasattr(result, "to_dict")
        else dict(result)
    )


def _attach_runtime_reliability(
    result: ToolResult | dict[str, Any],
    reliability: dict[str, Any],
) -> dict[str, Any]:
    payload = _tool_result_dict(result)
    payload["runtime_reliability"] = dict(reliability or {})
    return payload


def _task_id_for_single(decomposition: dict[str, Any]) -> str:
    tasks = decomposition.get("tasks") if isinstance(decomposition, dict) else []
    if isinstance(tasks, list) and tasks:
        first = tasks[0]
        if isinstance(first, dict) and first.get("task_id"):
            return str(first.get("task_id"))
    return "task_1"


def _runtime_attach_plan_ids(
    runtime: AgentRuntimeRecorder,
    value: Any,
    *,
    user_id: str,
    output_dir: str | Path,
) -> list[str]:
    attached: list[str] = []
    if isinstance(value, dict):
        plan_id = str(value.get("plan_id") or "")
        if plan_id:
            runtime.attach_proposal(plan_id)
            try:
                update_pending_plan(
                    user_id,
                    plan_id,
                    {"run_id": runtime.run_id},
                    output_dir=output_dir,
                )
            except Exception:
                pass
            attached.append(plan_id)
        for child in value.values():
            attached.extend(
                _runtime_attach_plan_ids(
                    runtime,
                    child,
                    user_id=user_id,
                    output_dir=output_dir,
                )
            )
    elif isinstance(value, list):
        for child in value:
            attached.extend(
                _runtime_attach_plan_ids(
                    runtime,
                    child,
                    user_id=user_id,
                    output_dir=output_dir,
                )
            )
    return list(dict.fromkeys(attached))


def _save_runtime_checkpoint(
    runtime: AgentRuntimeRecorder,
    *,
    stage: str,
    completed_steps: list[str] | None = None,
    pending_tasks: list[dict[str, Any]] | None = None,
    references: dict[str, Any] | None = None,
    write_intent: bool = False,
) -> dict[str, Any]:
    try:
        checkpoint = RuntimeCheckpointer(runtime.db_path).save(
            run_id=runtime.run_id,
            stage=stage,
            completed_steps=completed_steps or [],
            pending_tasks=pending_tasks or [],
            references=references or {},
            write_intent=write_intent,
        )
        runtime.merge_metadata({"latest_checkpoint_id": checkpoint.get("checkpoint_id")})
        return checkpoint
    except Exception as exc:
        runtime.merge_metadata({"checkpoint_error": f"{type(exc).__name__}: {exc}"})
        return {}


def _extract_confirmation_identity(query: str) -> tuple[str, str]:
    plan_match = re.search(r"(agent_plan_[A-Za-z0-9_]+)", str(query or ""))
    token_match = re.search(
        r"(?:token|令牌|confirmation_token)\s*[:=：]?\s*([A-Za-z0-9_\-]+)",
        str(query or ""),
        flags=re.IGNORECASE,
    )
    return (
        plan_match.group(1) if plan_match else "",
        token_match.group(1) if token_match else "",
    )


def _resume_run_id_for_confirmation(
    *,
    query: str,
    user_id: str,
    output_dir: str | Path,
    db_path: str | Path | None,
) -> str:
    plan_id, _ = _extract_confirmation_identity(query)
    if not plan_id:
        return ""
    plan = get_pending_plan(user_id, plan_id, output_dir)
    run_id = str((plan or {}).get("run_id") or "")
    if not run_id:
        return ""
    try:
        run = AgentRepository(db_path)._decode_runtime_record(
            "agent_runs",
            AgentRepository(db_path).store.get("agent_runs", {"run_id": run_id}),
        ) or {}
    except Exception:
        return ""
    return run_id if str(run.get("status") or "") == RUN_WAITING_FOR_APPROVAL else ""


def _confirmation_runtime_metadata(
    *,
    db_path: str | Path | None,
    plan_id: str,
    result_dict: dict[str, Any],
) -> dict[str, Any]:
    if not plan_id:
        return {}
    metadata: dict[str, Any] = {
        "plan_id": plan_id,
        "confirmation_status": (result_dict.get("data") or {}).get("confirmation_status"),
        "execution_status": (result_dict.get("data") or {}).get("execution_status"),
        "success": bool(result_dict.get("success")),
    }
    try:
        repo = AgentRepository(db_path)
        approvals = repo.store.list("action_approvals", {"plan_id": plan_id})
        commits = repo.store.list("action_commits", {"plan_id": plan_id})
        if approvals:
            metadata["approval_id"] = str(approvals[-1].get("approval_id") or "")
            metadata["approval_status"] = str(approvals[-1].get("status") or "")
        if commits:
            metadata["commit_id"] = str(commits[-1].get("commit_id") or "")
            metadata["commit_status"] = str(commits[-1].get("status") or "")
            metadata["commit_error_type"] = str(commits[-1].get("error_type") or "")
    except Exception as exc:
        metadata["metadata_load_error"] = f"{type(exc).__name__}: {exc}"
    return metadata


def _query_has_any(query: str, markers: list[str]) -> bool:
    text = str(query or "").lower()
    return any(marker.lower() in text for marker in markers)


def _requested_top_k(
    query: str,
    decomposition: dict[str, Any],
    default_top_k: int,
) -> int:
    del query
    tasks = decomposition.get("tasks") if isinstance(decomposition, dict) else []
    task_top_k = None
    if isinstance(tasks, list):
        for task in tasks:
            if not isinstance(task, dict):
                continue
            params = task.get("parameters") if isinstance(task.get("parameters"), dict) else {}
            value = params.get("top_k")
            if value not in (None, ""):
                task_top_k = value
                break
    return resolve_requested_top_k(
        task_top_k=task_top_k,
        request_default_top_k=default_top_k,
        tool_default_top_k=DEFAULT_TOOL_TOP_K,
    )


def _logic_integrity_for_execution(
    *,
    intent: str,
    decomposition: dict[str, Any],
    orchestration: dict[str, Any],
    result_dict: dict[str, Any],
    completion: dict[str, Any] | None = None,
):
    """Collect factual execution inputs for the deterministic safety gate."""

    data = dict(result_dict.get("data") or {}) if isinstance(result_dict.get("data"), dict) else {}
    task_results = dict(orchestration.get("task_results") or {}) if isinstance(orchestration, dict) else {}
    portfolio_state: dict[str, Any] = {}
    risk_report: dict[str, Any] = {}
    candidates = [data]
    for task_result in task_results.values():
        if isinstance(task_result, dict) and isinstance(task_result.get("data"), dict):
            candidates.append(dict(task_result["data"]))
    for candidate in candidates:
        if not portfolio_state and (
            "consistency_status" in candidate
            or "portfolio_snapshot" in candidate
            or candidate.get("error_code") == "portfolio_snapshot_inconsistent"
        ):
            portfolio_state = candidate
        if not risk_report and ("risk_report" in candidate or "risk" in candidate):
            risk_report = candidate
    diagnostics = decomposition.get("diagnostics") if isinstance(decomposition.get("diagnostics"), dict) else {}
    phase10 = diagnostics.get("phase10_goal_planning") if isinstance(diagnostics.get("phase10_goal_planning"), dict) else {}
    task_plan = phase10.get("task_plan") or decomposition.get("task_plan") or {}
    limits = dict(orchestration.get("replan_limits") or {}) if isinstance(orchestration, dict) else {}
    write_intents = {
        "confirm_execute", "reject_execute", "one_time_position_operation", "preview_add_stock",
        "adjust_position", "capital_management", "backfill", "strategy_change",
    }
    return validate_agent_logic_integrity(
        portfolio_state=portfolio_state,
        risk_report=risk_report,
        task_plan=task_plan if isinstance(task_plan, dict) else {},
        task_results=task_results,
        completion=completion,
        replan_audit=list(orchestration.get("replan_audit") or []) if isinstance(orchestration, dict) else [],
        replan_count=int(orchestration.get("replan_count") or 0) if isinstance(orchestration, dict) else 0,
        replan_limit=limits.get("max_rounds"),
        enforce_task_count=intent == "multi_intent",
        write_requested=intent in write_intents,
        write_allowed=bool(data.get("safe_to_write", True)),
    )


def _feature_unavailable_result(
    *,
    intent: str,
    integrity: Any,
    language: str,
    previous: dict[str, Any],
) -> dict[str, Any]:
    payload = feature_unavailable_payload(integrity, language=language)
    return {
        "success": False,
        "message": payload["message"],
        "data": payload,
        "llm_completion": dict(previous.get("llm_completion") or {}),
        "errors": list(dict.fromkeys([*list(previous.get("errors") or []), *list(integrity.errors)])),
        "warnings": list(previous.get("warnings") or []),
        "tool_name": str(previous.get("tool_name") or intent),
        "status": "feature_unavailable",
        "requires_confirmation": False,
    }


def _consume_post_execution_replan(
    *,
    source: str,
    action: Any,
    completion: dict[str, Any] | None,
    reflection: dict[str, Any] | None,
    orchestration: dict[str, Any],
    result_dict: dict[str, Any],
    user_goal: dict[str, Any],
    user_id: str,
    output_dir: str | Path,
    db_path: str | Path | None,
    default_top_k: int,
    session_id: str,
    language: str,
    context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Execute one bounded, read-only post-completion/critic repair plan."""

    current = dict(orchestration or {})
    limits = dict(current.get("replan_limits") or {})
    configured_limit = context.get("replan_limit")
    if configured_limit is None:
        configured_limit = limits.get("max_rounds") or 2
    missing_outputs = list((completion or {}).get("missing_outputs") or [])
    if not missing_outputs and isinstance(reflection, dict):
        missing_outputs = ["market_evidence"] if str(reflection.get("action") or "").upper() == "REPLAN_READONLY" else []

    def _execute(tasks: list[dict[str, Any]]) -> dict[str, Any]:
        return execute_multi_intent_plan(
            {"tasks": tasks},
            user_id=user_id,
            output_dir=output_dir,
            db_path=db_path,
            default_top_k=default_top_k,
            session_id=session_id,
            language=language,
            context={**dict(context or {}), "readonly_replan": True},
        )

    integrity_state = dict(current.get("logic_integrity") or {})
    result_data = dict(result_dict.get("data") or {}) if isinstance(result_dict.get("data"), dict) else {}
    outcome = consume_readonly_replan(
        source=source,
        action=action,
        replan_count=int(current.get("replan_count") or 0),
        replan_limit=configured_limit,
        replan_audit=list(current.get("replan_audit") or []),
        task_results=dict(current.get("task_results") or {}),
        missing_outputs=missing_outputs,
        user_goal=user_goal,
        execute_plan=_execute,
        safe_to_continue=bool(integrity_state.get("safe_to_continue", result_data.get("safe_to_continue", True))),
        safe_to_write=bool(integrity_state.get("safe_to_write", result_data.get("safe_to_write", True))),
        goal_completed=str((completion or {}).get("status") or "").lower() in {"completed", "complete", "success"},
        budget_exhausted=bool(context.get("budget_exhausted", False)),
    )
    current["replan_count"] = int(outcome.get("replan_count") or 0)
    current["replan_audit"] = list(outcome.get("replan_audit") or [])
    current["replan_state"] = dict(outcome.get("replan_state") or {
        "replan_count": current["replan_count"],
        "replan_limit": int(configured_limit or 0),
        "executed_rounds": current["replan_count"],
        "attempted_rounds": 0,
        "replan_audit": current["replan_audit"],
    })
    current["replan_limits"] = {**limits, "max_rounds": int(configured_limit or 0)}
    current["replan_status"] = str(outcome.get("status") or "")
    execution = dict(outcome.get("execution") or {})
    if execution:
        current["task_results"] = {
            **dict(current.get("task_results") or {}),
            **dict(execution.get("task_results") or {}),
        }
        current["tool_calls"] = [
            *list(current.get("tool_calls") or []),
            *list(execution.get("tool_calls") or []),
        ]
        current["execution_batches"] = [
            *list(current.get("execution_batches") or []),
            *list(execution.get("execution_batches") or []),
        ]
        current["warnings"] = [
            *list(current.get("warnings") or []),
            *list(execution.get("warnings") or []),
        ]
        current["errors"] = [
            *list(current.get("errors") or []),
            *list(execution.get("errors") or []),
        ]
        if str(execution.get("execution_status") or "") == "partially_completed":
            current["execution_status"] = "partially_completed"
        elif not execution.get("success") and current.get("success"):
            current["execution_status"] = "partially_completed"

    # ``result_dict.data`` is the user-facing tool payload.  In particular,
    # protected-operation previews keep their plan/confirmation identity there.
    # Replan bookkeeping belongs to orchestration; replacing the payload with
    # it would silently remove the preview data even when no replan ran.
    updated_result = dict(result_dict)
    public_data = (
        dict(result_dict.get("data") or {})
        if isinstance(result_dict.get("data"), dict)
        else {}
    )
    public_data.update(
        {
            "replan_count": int(current.get("replan_count") or 0),
            "replan_status": str(current.get("replan_status") or ""),
            "replan_audit": list(current.get("replan_audit") or []),
            "replan_limits": dict(current.get("replan_limits") or {}),
        }
    )
    if execution:
        public_data["replan_execution"] = {
            "execution_status": str(execution.get("execution_status") or ""),
            "task_ids": sorted(str(key) for key in (execution.get("task_results") or {})),
        }
        updated_result["warnings"] = list(
            dict.fromkeys(
                [
                    *list(result_dict.get("warnings") or []),
                    *list(execution.get("warnings") or []),
                ]
            )
        )
        updated_result["errors"] = list(
            dict.fromkeys(
                [
                    *list(result_dict.get("errors") or []),
                    *list(execution.get("errors") or []),
                ]
            )
        )
    updated_result["data"] = public_data
    return current, updated_result, outcome


def _make_task(
    task_id: str,
    intent: str,
    parameters: dict[str, Any] | None = None,
    depends_on: list[str] | None = None,
    reason: str = "",
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "intent": intent,
        "parameters": dict(parameters or {}),
        "depends_on": list(depends_on or []),
        "reason": reason,
        "confidence": 1.0,
        "capability_status": "executable",
    }


def _normalise_readonly_multi_agent_tasks(
    *,
    query: str,
    decomposition: dict[str, Any],
    default_top_k: int,
    context: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Partition the exact LLM plan without adding, deleting or rewriting tasks.

    This helper is retained only for compatibility with specialist reporting code.
    The query text, keyword rules and default_top_k never create business tasks.
    Cross-role dependency plans are executed by the normal DAG executor instead.
    """
    del query, default_top_k, context
    tasks = decomposition.get("tasks") if isinstance(decomposition, dict) else []
    task_list = [dict(task) for task in tasks if isinstance(task, dict)]
    market_intents = {
        "ranking", "market.get_ranking", "stock_analysis", "market.analyze_stock",
        "stock_news", "stock_rag", "news_search", "rag_search",
        "evidence.search_news", "evidence.search_rag", "evidence.get_stock_evidence",
        "evidence.get_market_evidence", "evidence.mcp_readonly_evidence",
        "market.compare_stocks", "market.get_signal_summary",
    }
    portfolio_intents = {
        "portfolio_state", "portfolio_risk", "portfolio.get_state",
        "portfolio.get_account_summary", "portfolio.get_positions", "portfolio.get_orders",
        "portfolio.analyze_risk", "portfolio.compare_risk_before_after",
        "portfolio.design_target_portfolio", "portfolio.construct_target_portfolio", "portfolio.load_target_portfolio",
        "portfolio.compare_portfolios", "position_recommendation",
        "replacement_recommendation", "user_profile",
    }
    market_tasks = [task for task in task_list if str(task.get("intent") or "") in market_intents or is_mcp_tool_name(str(task.get("intent") or ""))]
    portfolio_tasks = [task for task in task_list if str(task.get("intent") or "") in portfolio_intents]
    return market_tasks, portfolio_tasks


def _merge_agent_task_results(*items: dict[str, Any]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in items:
        for task_id, result in (item.get("task_results") or {}).items():
            if isinstance(result, dict):
                merged[str(task_id)] = dict(result)
    return merged


def _annotate_tool_calls(
    calls: list[dict[str, Any]],
    role: str,
) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        row = dict(call)
        row["agent_role"] = role
        annotated.append(row)
    return annotated


def _handoff_context_refs(context: dict[str, Any], *, run_id: str, conversation_id: str) -> list[dict[str, Any]]:
    bundle = context.get("context_bundle") if isinstance(context, dict) else {}
    if isinstance(bundle, dict):
        context_id = str(bundle.get("context_id") or "")
        task_id = str(bundle.get("task_id") or "")
    else:
        context_id = ""
        task_id = ""
    return [
        {
            "context_id": context_id,
            "run_id": str(run_id or ""),
            "conversation_id": str(conversation_id or ""),
            "task_id": task_id,
        }
    ]


def _handoff_tool_names(tasks: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        name = str(task.get("intent") or "")
        if name:
            names.append(name)
    return list(dict.fromkeys(names))


def _handoff_task_summary(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "task_count": len(tasks),
        "task_ids": [str(task.get("task_id") or "") for task in tasks if isinstance(task, dict)][:12],
        "intents": _handoff_tool_names(tasks)[:12],
    }


def _execute_readonly_multi_agent_collaboration(
    *,
    query: str,
    decomposition: dict[str, Any],
    user_id: str,
    output_dir: str | Path,
    db_path: str | Path | None,
    default_top_k: int,
    session_id: str,
    run_id: str,
    language: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    market_tasks, portfolio_tasks = _normalise_readonly_multi_agent_tasks(
        query=query,
        decomposition=decomposition,
        default_top_k=default_top_k,
        context=context,
    )
    has_market_tasks = bool(market_tasks)
    selected_agents = [
        *([MARKET_INTELLIGENCE] if has_market_tasks else []),
        PORTFOLIO_ANALYSIS,
        REPORTING,
    ]
    supervisor_message_id = make_message_id(SUPERVISOR)
    supervisor_output = AgentOutput(
        role=SUPERVISOR,
        message_id=supervisor_message_id,
        status="succeeded",
        evidence=[],
        analysis={
            "selected_agents": selected_agents,
            "market_task_ids": [task["task_id"] for task in market_tasks],
            "portfolio_task_ids": [task["task_id"] for task in portfolio_tasks],
            "mcp_candidate_tools": [
                str(task.get("intent") or "")
                for task in market_tasks
                if is_mcp_tool_name(str(task.get("intent") or ""))
            ],
            "read_only": True,
        },
        proposal={"mode": "read_only_multi_agent"},
        risks=[],
        next_actions=["handoff_to_market_intelligence"] if has_market_tasks else ["handoff_to_portfolio_analysis"],
        sources=[],
        tool_calls=[],
        handoff_from="user",
        handoff_to=MARKET_INTELLIGENCE if has_market_tasks else PORTFOLIO_ANALYSIS,
    )
    handoff_context_refs = _handoff_context_refs(context, run_id=run_id, conversation_id=session_id)
    handoff = HandoffCoordinator(
        user_id=user_id,
        output_dir=output_dir,
        conversation_id=session_id,
        run_id=run_id,
    )
    handoff_adapter = handoff.adapter

    market_output: AgentOutput
    market_orchestration: dict[str, Any]
    market_handoff_result = None
    if has_market_tasks:
        market_request = handoff.plan_handoff(
            source_role=AgentRole.COORDINATOR,
            target_role=AgentRole.EVIDENCE_RETRIEVER,
            reason="market_evidence_for_readonly_multi_agent",
            task_id="agent_market",
            input_summary=_handoff_task_summary(market_tasks),
            context_refs=handoff_context_refs,
            tool_names=_handoff_tool_names(market_tasks),
        )

        def _run_market_handoff(request):
            nonlocal market_output, market_orchestration
            market_output, market_orchestration = MarketIntelligenceAgent().run(
                tasks=market_tasks,
                user_id=user_id,
                output_dir=output_dir,
                db_path=db_path,
                default_top_k=default_top_k,
                session_id=session_id,
                language=language,
                context=context,
                handoff_from=SUPERVISOR,
                handoff_to=PORTFOLIO_ANALYSIS,
            )
            return handoff_adapter.result_from_agent_output(
                request,
                market_output,
                role=AgentRole.EVIDENCE_RETRIEVER,
                orchestration=market_orchestration,
            )

        market_handoff_result = handoff.execute_handoff(
            market_request,
            _run_market_handoff,
        )
    else:
        market_output = AgentOutput(
            role=MARKET_INTELLIGENCE,
            message_id=make_message_id(MARKET_INTELLIGENCE),
            status="skipped",
            analysis={"reason": "no_market_tasks_for_user_goal"},
            proposal={},
            handoff_from=SUPERVISOR,
            handoff_to=PORTFOLIO_ANALYSIS,
        )
        market_orchestration = {
            "success": True,
            "answer": "",
            "task_results": {},
            "tool_calls": [],
            "execution_batches": [],
            "warnings": [],
            "errors": [],
            "execution_status": "skipped",
            "observations": [],
            "replan_audit": [],
            "replan_count": 0,
            "invalid_replan_block_count": 0,
            "replan_limits": {"max_rounds": 0},
        }

    portfolio_output: AgentOutput
    portfolio_orchestration: dict[str, Any]
    portfolio_input_summary = _handoff_task_summary(portfolio_tasks)
    portfolio_message_refs: list[dict[str, Any]] = []
    if market_handoff_result is not None:
        portfolio_input_summary = {
            **portfolio_input_summary,
            "market_handoff_id": market_handoff_result.handoff_id,
            "market_status": market_handoff_result.status.value,
        }
        portfolio_message_refs = [{"handoff_id": market_handoff_result.handoff_id, "target_role": market_handoff_result.target_role.value}]
    portfolio_request = handoff.plan_handoff(
        source_role=AgentRole.EVIDENCE_RETRIEVER if market_handoff_result is not None else AgentRole.COORDINATOR,
        target_role=AgentRole.PORTFOLIO_ANALYST,
        reason="portfolio_context_for_readonly_multi_agent",
        task_id="agent_portfolio",
        input_summary=portfolio_input_summary,
        context_refs=handoff_context_refs,
        message_refs=portfolio_message_refs,
        tool_names=_handoff_tool_names(portfolio_tasks),
    )

    def _run_portfolio_handoff(request):
        nonlocal portfolio_output, portfolio_orchestration
        portfolio_output, portfolio_orchestration = PortfolioAnalysisAgent().run(
            tasks=portfolio_tasks,
            user_id=user_id,
            output_dir=output_dir,
            db_path=db_path,
            default_top_k=default_top_k,
            session_id=session_id,
            language=language,
            context=context,
            market_output=market_output.to_dict(),
            handoff_from=MARKET_INTELLIGENCE if market_handoff_result is not None else SUPERVISOR,
            handoff_to=REPORTING,
        )
        return handoff_adapter.result_from_agent_output(
            request,
            portfolio_output,
            role=AgentRole.PORTFOLIO_ANALYST,
            orchestration=portfolio_orchestration,
        )

    portfolio_handoff_result = handoff.execute_handoff(
        portfolio_request,
        _run_portfolio_handoff,
    )
    task_results = _merge_agent_task_results(
        market_orchestration,
        portfolio_orchestration,
    )
    report_output: AgentOutput
    answer: str
    report_input_summary = {
        "portfolio_handoff_id": portfolio_handoff_result.handoff_id,
        "task_result_count": len(task_results),
    }
    report_message_refs = [
        {"handoff_id": portfolio_handoff_result.handoff_id, "target_role": portfolio_handoff_result.target_role.value},
    ]
    if market_handoff_result is not None:
        report_input_summary["market_handoff_id"] = market_handoff_result.handoff_id
        report_message_refs.insert(
            0,
            {"handoff_id": market_handoff_result.handoff_id, "target_role": market_handoff_result.target_role.value},
        )
    report_request = handoff.plan_handoff(
        source_role=AgentRole.PORTFOLIO_ANALYST,
        target_role=AgentRole.REPORT_WRITER,
        reason="report_readonly_multi_agent_results",
        task_id="agent_report",
        input_summary=report_input_summary,
        context_refs=handoff_context_refs,
        message_refs=report_message_refs,
        tool_names=[],
    )

    def _run_report_handoff(request):
        nonlocal report_output, answer
        report_output, answer = ReportingAgent().run(
            market_output=market_output.to_dict(),
            portfolio_output=portfolio_output.to_dict(),
            task_results=task_results,
            language=language,
            handoff_from=PORTFOLIO_ANALYSIS,
            handoff_to="user",
        )
        return handoff_adapter.result_from_agent_output(
            request,
            report_output,
            role=AgentRole.REPORT_WRITER,
        )

    report_handoff_result = handoff.execute_handoff(
        report_request,
        _run_report_handoff,
    )
    agent_outputs = {
        SUPERVISOR: supervisor_output.to_dict(),
        PORTFOLIO_ANALYSIS: portfolio_output.to_dict(),
        REPORTING: report_output.to_dict(),
    }
    if has_market_tasks:
        agent_outputs[MARKET_INTELLIGENCE] = market_output.to_dict()
    agent_timeline = [
        timeline_entry(
            step_id="agent_supervisor",
            role=SUPERVISOR,
            status=supervisor_output.status,
            message_id=supervisor_output.message_id,
            input_summary=query,
            output_summary_text=agent_output_summary(supervisor_output),
            handoff_from="user",
            handoff_to=MARKET_INTELLIGENCE if has_market_tasks else PORTFOLIO_ANALYSIS,
        ),
    ]
    if has_market_tasks:
        agent_timeline.append(
            timeline_entry(
                step_id="agent_market",
                role=MARKET_INTELLIGENCE,
                status=market_output.status,
                message_id=market_output.message_id,
                input_summary={"task_count": len(market_tasks)},
                output_summary_text=agent_output_summary(market_output),
                handoff_from=SUPERVISOR,
                handoff_to=PORTFOLIO_ANALYSIS,
                depends_on=["agent_supervisor"],
            )
        )
    agent_timeline.extend(
        [
        timeline_entry(
            step_id="agent_portfolio",
            role=PORTFOLIO_ANALYSIS,
            status=portfolio_output.status,
            message_id=portfolio_output.message_id,
            input_summary={
                "task_count": len(portfolio_tasks),
                **({"market_message_id": market_output.message_id} if has_market_tasks else {}),
            },
            output_summary_text=agent_output_summary(portfolio_output),
            handoff_from=MARKET_INTELLIGENCE if has_market_tasks else SUPERVISOR,
            handoff_to=REPORTING,
            depends_on=["agent_market"] if has_market_tasks else ["agent_supervisor"],
        ),
        timeline_entry(
            step_id="agent_report",
            role=REPORTING,
            status=report_output.status,
            message_id=report_output.message_id,
            input_summary={
                "portfolio_message_id": portfolio_output.message_id,
                **({"market_message_id": market_output.message_id} if has_market_tasks else {}),
            },
            output_summary_text=agent_output_summary(report_output),
            handoff_from=PORTFOLIO_ANALYSIS,
            handoff_to="user",
            depends_on=["agent_portfolio"],
        ),
        ]
    )

    tool_calls = [
        *_annotate_tool_calls(list(market_orchestration.get("tool_calls") or []), MARKET_INTELLIGENCE),
        *_annotate_tool_calls(list(portfolio_orchestration.get("tool_calls") or []), PORTFOLIO_ANALYSIS),
    ]
    errors = [
        *[str(item) for item in (market_orchestration.get("errors") or [])],
        *[str(item) for item in (portfolio_orchestration.get("errors") or [])],
    ]
    warnings = [
        *[str(item) for item in (market_orchestration.get("warnings") or [])],
        *[str(item) for item in (portfolio_orchestration.get("warnings") or [])],
    ]
    child_observations = [
        *list(market_orchestration.get("observations") or []),
        *list(portfolio_orchestration.get("observations") or []),
    ]
    child_replan_audit = [
        *list(market_orchestration.get("replan_audit") or []),
        *list(portfolio_orchestration.get("replan_audit") or []),
    ]
    success = market_orchestration.get("success", True) and portfolio_orchestration.get("success", True)
    return {
        "success": bool(success),
        "answer": answer,
        "task_results": task_results,
        "tool_calls": tool_calls,
        "execution_order": list(task_results.keys()),
        "execution_batches": [
            *(
                [{"agent_role": MARKET_INTELLIGENCE, "batches": market_orchestration.get("execution_batches") or []}]
                if has_market_tasks
                else []
            ),
            {"agent_role": PORTFOLIO_ANALYSIS, "batches": portfolio_orchestration.get("execution_batches") or []},
        ],
        "warnings": warnings,
        "errors": errors,
        "execution_status": "completed" if success else "failed",
        "observations": [
            *(
                [{"agent_role": MARKET_INTELLIGENCE, "status": market_output.status}]
                if has_market_tasks
                else []
            ),
            {"agent_role": PORTFOLIO_ANALYSIS, "status": portfolio_output.status},
            {"agent_role": REPORTING, "status": report_output.status},
            {
                "agent_role": SUPERVISOR,
                "status": "observed",
                "child_observations": child_observations,
            },
        ],
        "replan_count": int(market_orchestration.get("replan_count") or 0)
        + int(portfolio_orchestration.get("replan_count") or 0),
        "replan_audit": child_replan_audit,
        "invalid_replan_block_count": int(market_orchestration.get("invalid_replan_block_count") or 0)
        + int(portfolio_orchestration.get("invalid_replan_block_count") or 0),
        "replan_limits": {
            "max_rounds": max(
                int((market_orchestration.get("replan_limits") or {}).get("max_rounds") or 0),
                int((portfolio_orchestration.get("replan_limits") or {}).get("max_rounds") or 0),
            ),
        },
        "agent_timeline": agent_timeline,
        "agent_outputs": agent_outputs,
        "phase17_handoff": handoff.merge_handoff_results(
            [
                *([market_handoff_result] if market_handoff_result is not None else []),
                portfolio_handoff_result,
                report_handoff_result,
            ]
        ),
        "multi_agent": True,
        "read_only": True,
        "write_operations_blocked": True,
    }


def _execute_position_approval_multi_agent_workflow(
    *,
    query: str,
    params: dict[str, Any],
    user_id: str,
    output_dir: str | Path,
    db_path: str | Path | None,
    default_top_k: int,
    session_id: str,
    run_id: str,
    language: str,
    context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    stock_code = str(params.get("stock_code") or "")
    market_tasks: list[dict[str, Any]] = []
    if stock_code:
        market_tasks = [
            _make_task(
                "task_market_analysis",
                "stock_analysis",
                {"stock_code": stock_code, "top_k": default_top_k},
                reason="supervisor_market_context_before_protected_operation",
            ),
            _make_task(
                "task_market_news",
                "stock_news",
                {"stock_code": stock_code},
                ["task_market_analysis"],
                "supervisor_market_news_before_protected_operation",
            ),
            _make_task(
                "task_market_rag",
                "stock_rag",
                {"stock_code": stock_code, "query": query, "top_k": min(default_top_k, 10)},
                ["task_market_analysis"],
                "supervisor_market_rag_before_protected_operation",
            ),
        ]
    portfolio_tasks = [
        _make_task(
            "task_portfolio_state",
            "portfolio_state",
            {},
            reason="supervisor_portfolio_state_before_protected_operation",
        ),
        _make_task(
            "task_portfolio_risk",
            "portfolio_risk",
            {},
            ["task_portfolio_state"],
            "supervisor_portfolio_risk_before_protected_operation",
        ),
    ]

    supervisor_message_id = make_message_id(SUPERVISOR)
    supervisor_output = AgentOutput(
        role=SUPERVISOR,
        message_id=supervisor_message_id,
        status="succeeded",
        analysis={
            "selected_agents": [
                MARKET_INTELLIGENCE,
                PORTFOLIO_ANALYSIS,
                RISK_OPERATION,
            ],
            "protected_operation": True,
            "read_only_before_preview": True,
        },
        proposal={"mode": "human_approval_required"},
        next_actions=["handoff_to_market_and_portfolio"],
        handoff_from="user",
        handoff_to=MARKET_INTELLIGENCE,
    )
    handoff_context_refs = _handoff_context_refs(context, run_id=run_id, conversation_id=session_id)
    handoff = HandoffCoordinator(
        user_id=user_id,
        output_dir=output_dir,
        conversation_id=session_id,
        run_id=run_id,
    )
    handoff_adapter = handoff.adapter
    market_output: AgentOutput
    market_orchestration: dict[str, Any]
    market_request = handoff.plan_handoff(
        source_role=AgentRole.COORDINATOR,
        target_role=AgentRole.EVIDENCE_RETRIEVER,
        reason="market_evidence_before_protected_operation",
        task_id="agent_market",
        input_summary=_handoff_task_summary(market_tasks),
        context_refs=handoff_context_refs,
        tool_names=_handoff_tool_names(market_tasks),
    )

    def _run_market_handoff(request):
        nonlocal market_output, market_orchestration
        market_output, market_orchestration = MarketIntelligenceAgent().run(
            tasks=market_tasks,
            user_id=user_id,
            output_dir=output_dir,
            db_path=db_path,
            default_top_k=default_top_k,
            session_id=session_id,
            language=language,
            context=context,
            handoff_from=SUPERVISOR,
            handoff_to=PORTFOLIO_ANALYSIS,
        )
        return handoff_adapter.result_from_agent_output(
            request,
            market_output,
            role=AgentRole.EVIDENCE_RETRIEVER,
            orchestration=market_orchestration,
        )

    market_handoff_result = handoff.execute_handoff(market_request, _run_market_handoff)
    portfolio_output: AgentOutput
    portfolio_orchestration: dict[str, Any]
    portfolio_request = handoff.plan_handoff(
        source_role=AgentRole.EVIDENCE_RETRIEVER,
        target_role=AgentRole.PORTFOLIO_ANALYST,
        reason="portfolio_context_before_protected_operation",
        task_id="agent_portfolio",
        input_summary={
            **_handoff_task_summary(portfolio_tasks),
            "market_handoff_id": market_handoff_result.handoff_id,
            "market_status": market_handoff_result.status.value,
        },
        context_refs=handoff_context_refs,
        message_refs=[{"handoff_id": market_handoff_result.handoff_id, "target_role": market_handoff_result.target_role.value}],
        tool_names=_handoff_tool_names(portfolio_tasks),
    )

    def _run_portfolio_handoff(request):
        nonlocal portfolio_output, portfolio_orchestration
        portfolio_output, portfolio_orchestration = PortfolioAnalysisAgent().run(
            tasks=portfolio_tasks,
            user_id=user_id,
            output_dir=output_dir,
            db_path=db_path,
            default_top_k=default_top_k,
            session_id=session_id,
            language=language,
            context=context,
            market_output=market_output.to_dict(),
            handoff_from=MARKET_INTELLIGENCE,
            handoff_to=RISK_OPERATION,
        )
        return handoff_adapter.result_from_agent_output(
            request,
            portfolio_output,
            role=AgentRole.PORTFOLIO_ANALYST,
            orchestration=portfolio_orchestration,
        )

    portfolio_handoff_result = handoff.execute_handoff(portfolio_request, _run_portfolio_handoff)
    risk_output: AgentOutput
    risk_orchestration: dict[str, Any]
    result_dict: dict[str, Any]
    risk_request = handoff.plan_handoff(
        source_role=AgentRole.PORTFOLIO_ANALYST,
        target_role=AgentRole.STRATEGY_GUARD,
        reason="strategy_guard_preview_before_user_confirmation",
        task_id="agent_risk_operation",
        input_summary={
            "stock_code": stock_code,
            "operation": "paper_position_preview",
            "portfolio_handoff_id": portfolio_handoff_result.handoff_id,
            "portfolio_status": portfolio_handoff_result.status.value,
        },
        context_refs=handoff_context_refs,
        message_refs=[
            {"handoff_id": market_handoff_result.handoff_id, "target_role": market_handoff_result.target_role.value},
            {"handoff_id": portfolio_handoff_result.handoff_id, "target_role": portfolio_handoff_result.target_role.value},
        ],
        tool_names=["portfolio.preview_manual_change"],
    )

    def _run_strategy_guard_handoff(request):
        nonlocal risk_output, risk_orchestration, result_dict
        risk_output, risk_orchestration, result_dict = RiskOperationAgent().run(
            query=query,
            operation_params={**params, "query": str(params.get("query") or query)},
            user_id=user_id,
            output_dir=output_dir,
            db_path=db_path,
            default_top_k=default_top_k,
            session_id=session_id,
            portfolio_output=portfolio_output.to_dict(),
            market_output=market_output.to_dict(),
            handoff_from=PORTFOLIO_ANALYSIS,
            handoff_to="user_confirmation",
        )
        return handoff_adapter.result_from_agent_output(
            request,
            risk_output,
            role=AgentRole.STRATEGY_GUARD,
            orchestration=risk_orchestration,
        )

    risk_handoff_result = handoff.execute_handoff(
        risk_request,
        _run_strategy_guard_handoff,
    )
    agent_outputs = {
        SUPERVISOR: supervisor_output.to_dict(),
        MARKET_INTELLIGENCE: market_output.to_dict(),
        PORTFOLIO_ANALYSIS: portfolio_output.to_dict(),
        RISK_OPERATION: risk_output.to_dict(),
    }
    agent_timeline = [
        timeline_entry(
            step_id="agent_supervisor",
            role=SUPERVISOR,
            status=supervisor_output.status,
            message_id=supervisor_output.message_id,
            input_summary=query,
            output_summary_text=agent_output_summary(supervisor_output),
            handoff_from="user",
            handoff_to=MARKET_INTELLIGENCE,
        ),
        timeline_entry(
            step_id="agent_market",
            role=MARKET_INTELLIGENCE,
            status=market_output.status,
            message_id=market_output.message_id,
            input_summary={"task_count": len(market_tasks), "protected_operation": True},
            output_summary_text=agent_output_summary(market_output),
            handoff_from=SUPERVISOR,
            handoff_to=PORTFOLIO_ANALYSIS,
            depends_on=["agent_supervisor"],
        ),
        timeline_entry(
            step_id="agent_portfolio",
            role=PORTFOLIO_ANALYSIS,
            status=portfolio_output.status,
            message_id=portfolio_output.message_id,
            input_summary={"task_count": len(portfolio_tasks), "market_message_id": market_output.message_id},
            output_summary_text=agent_output_summary(portfolio_output),
            handoff_from=MARKET_INTELLIGENCE,
            handoff_to=RISK_OPERATION,
            depends_on=["agent_market"],
        ),
        timeline_entry(
            step_id="agent_risk_operation",
            role=RISK_OPERATION,
            status=risk_output.status,
            message_id=risk_output.message_id,
            input_summary={"stock_code": stock_code, "operation": "paper_position_preview"},
            output_summary_text=agent_output_summary(risk_output),
            handoff_from=PORTFOLIO_ANALYSIS,
            handoff_to="user_confirmation",
            depends_on=["agent_portfolio"],
        ),
    ]
    task_results = _merge_agent_task_results(
        market_orchestration,
        portfolio_orchestration,
        risk_orchestration,
    )
    tool_calls = [
        *_annotate_tool_calls(list(market_orchestration.get("tool_calls") or []), MARKET_INTELLIGENCE),
        *_annotate_tool_calls(list(portfolio_orchestration.get("tool_calls") or []), PORTFOLIO_ANALYSIS),
        *list(risk_orchestration.get("tool_calls") or []),
    ]
    errors = [
        *[str(item) for item in (market_orchestration.get("errors") or [])],
        *[str(item) for item in (portfolio_orchestration.get("errors") or [])],
        *[str(item) for item in (risk_orchestration.get("errors") or [])],
    ]
    warnings = [
        *[str(item) for item in (market_orchestration.get("warnings") or [])],
        *[str(item) for item in (portfolio_orchestration.get("warnings") or [])],
        *[str(item) for item in (risk_orchestration.get("warnings") or [])],
    ]
    child_observations = [
        *list(market_orchestration.get("observations") or []),
        *list(portfolio_orchestration.get("observations") or []),
    ]
    child_replan_audit = [
        *list(market_orchestration.get("replan_audit") or []),
        *list(portfolio_orchestration.get("replan_audit") or []),
    ]
    result_data = dict(result_dict.get("data") or {})
    risk_proposal = dict(getattr(risk_output, "proposal", {}) or {})
    plan_id = str(result_data.get("plan_id") or risk_proposal.get("plan_id") or result_dict.get("plan_id") or "")
    if plan_id and not result_data.get("plan_id"):
        result_data["plan_id"] = plan_id
        result_data["operation_type"] = result_data.get("operation_type") or risk_proposal.get("operation_type") or "one_time_position_operation"
        result_data["requires_confirmation"] = True
        result_dict = {**dict(result_dict), "data": result_data, "requires_confirmation": True, "plan_id": plan_id}
    orchestration = {
        "success": bool(result_dict.get("success")),
        "answer": "",
        "task_results": task_results,
        "tool_calls": tool_calls,
        "execution_order": list(task_results.keys()),
        "execution_batches": [
            {"agent_role": MARKET_INTELLIGENCE, "batches": market_orchestration.get("execution_batches") or []},
            {"agent_role": PORTFOLIO_ANALYSIS, "batches": portfolio_orchestration.get("execution_batches") or []},
            {"agent_role": RISK_OPERATION, "batches": risk_orchestration.get("execution_batches") or []},
        ],
        "warnings": warnings,
        "errors": errors,
        "execution_status": "waiting_for_approval" if plan_id else "failed",
        "observations": [
            {"agent_role": MARKET_INTELLIGENCE, "status": market_output.status},
            {"agent_role": PORTFOLIO_ANALYSIS, "status": portfolio_output.status},
            {"agent_role": RISK_OPERATION, "status": risk_output.status, "plan_id": plan_id},
            {
                "agent_role": SUPERVISOR,
                "status": "observed",
                "child_observations": child_observations,
            },
        ],
        "replan_count": int(market_orchestration.get("replan_count") or 0)
        + int(portfolio_orchestration.get("replan_count") or 0),
        "replan_audit": child_replan_audit,
        "invalid_replan_block_count": int(market_orchestration.get("invalid_replan_block_count") or 0)
        + int(portfolio_orchestration.get("invalid_replan_block_count") or 0),
        "replan_limits": {
            "max_rounds": max(
                int((market_orchestration.get("replan_limits") or {}).get("max_rounds") or 0),
                int((portfolio_orchestration.get("replan_limits") or {}).get("max_rounds") or 0),
            )
        },
        "agent_timeline": agent_timeline,
        "agent_outputs": agent_outputs,
        "phase17_handoff": handoff.merge_handoff_results(
            [market_handoff_result, portfolio_handoff_result, risk_handoff_result]
        ),
        "multi_agent": True,
        "protected_operation": True,
        "read_only_before_preview": True,
        "waiting_for_confirmation": bool(plan_id),
        "plan_id": plan_id,
        "write_operations_executed": 0,
    }
    return result_dict, orchestration


def _record_agent_timeline(
    runtime: AgentRuntimeRecorder,
    orchestration: dict[str, Any],
) -> None:
    entries = orchestration.get("agent_timeline") if isinstance(orchestration, dict) else []
    if not isinstance(entries, list):
        return
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        step_id = str(entry.get("step_id") or "")
        role = str(entry.get("role") or "")
        if not step_id or not role:
            continue
        metadata = {
            "agent_role": role,
            "message_id": entry.get("message_id"),
            "handoff_from": entry.get("handoff_from"),
            "handoff_to": entry.get("handoff_to"),
            "agent_input_summary": entry.get("input_summary"),
            "agent_output_summary": entry.get("output_summary"),
        }
        runtime.create_step(
            step_id,
            role,
            depends_on=[str(item) for item in (entry.get("depends_on") or [])],
            metadata=metadata,
        )
        status_text = str(entry.get("status") or "")
        step_status = STEP_SUCCEEDED if status_text in {"succeeded", "skipped"} else STEP_FAILED
        runtime.record_step_result(
            step_id,
            {
                "task_id": step_id,
                "intent": role,
                "success": status_text in {"succeeded", "skipped"},
                "step_status": step_status,
                "execution_mode": "agent_role",
                "arguments": {"input_summary": entry.get("input_summary")},
                "message": str(entry.get("output_summary") or ""),
                "data": {},
                "warnings": [],
                "errors": [],
                **metadata,
            },
        )


def _record_confirmation_report_step(
    runtime: AgentRuntimeRecorder,
    *,
    result_dict: dict[str, Any],
    plan_id: str,
) -> None:
    if not plan_id:
        return
    data = dict(result_dict.get("data") or {})
    message_id = make_message_id(REPORTING)
    output = AgentOutput(
        role=REPORTING,
        message_id=message_id,
        status="succeeded" if result_dict.get("success") else "failed",
        analysis={
            "plan_id": plan_id,
            "confirmation_status": data.get("confirmation_status"),
            "execution_status": data.get("execution_status"),
            "order_count": len(data.get("order_ids") or []),
        },
        proposal={"write_operations": len(data.get("order_ids") or [])},
        risks=list(result_dict.get("errors") or []),
        next_actions=["review_execution_audit"],
        handoff_from="commit_gateway",
        handoff_to="user",
    )
    metadata = {
        "agent_role": REPORTING,
        "message_id": message_id,
        "handoff_from": "commit_gateway",
        "handoff_to": "user",
        "agent_input_summary": {"plan_id": plan_id},
        "agent_output_summary": agent_output_summary(output),
    }
    runtime.create_step(
        "agent_report_commit",
        REPORTING,
        depends_on=["task_confirm_execute"],
        metadata=metadata,
    )
    runtime.record_step_result(
        "agent_report_commit",
        {
            "task_id": "agent_report_commit",
            "intent": REPORTING,
            "success": bool(result_dict.get("success")),
            "step_status": STEP_SUCCEEDED if result_dict.get("success") else STEP_FAILED,
            "execution_mode": "agent_role",
            "arguments": {"plan_id": plan_id},
            "message": str(result_dict.get("message") or ""),
            "data": output.to_dict(),
            "warnings": [],
            "errors": list(result_dict.get("errors") or []),
            **metadata,
        },
    )


def _record_runtime_for_result(
    runtime: AgentRuntimeRecorder,
    *,
    intent: str,
    params: dict[str, Any],
    decomposition: dict[str, Any],
    orchestration: dict[str, Any],
    result_dict: dict[str, Any],
    expanded_tool_calls: list[dict[str, Any]],
    output_dir: str | Path,
    user_id: str,
    llm_settings: LLMRuntimeSettings | None = None,
) -> dict[str, Any]:
    runtime_info: dict[str, Any] = {
        "run_id": runtime.run_id,
        "status": runtime.status,
        "replan_count": 0,
        "attached_plan_ids": [],
    }
    reliability_metadata: dict[str, Any] = {}
    for key in (
        "runtime_policy",
        "budget_usage",
        "circuit_states",
        "runtime_limits",
        "artifact_metrics",
        "capability_runtime",
    ):
        value = orchestration.get(key) if isinstance(orchestration, dict) else None
        if value:
            reliability_metadata[key] = value
            runtime_info[key] = value
    supervisor_decision = (
        decomposition.get("supervisor_decision")
        if isinstance(decomposition.get("supervisor_decision"), dict)
        else {}
    )
    if supervisor_decision:
        runtime_info["decision_source"] = str(supervisor_decision.get("decision_source") or "")
        runtime_info["supervisor_decision"] = supervisor_decision
        reliability_metadata["supervisor_decision"] = supervisor_decision
    diagnostics = decomposition.get("diagnostics") if isinstance(decomposition.get("diagnostics"), dict) else {}
    if diagnostics:
        runtime_info["llm_planner_called"] = bool(diagnostics.get("llm_planner_called"))
        runtime_info["rule_hits"] = list(diagnostics.get("rule_hits") or [])
        runtime_info["completeness_guard_triggered"] = bool(diagnostics.get("completeness_guard_triggered"))
        runtime_info["auto_added_tasks"] = list(diagnostics.get("auto_added_tasks") or [])
        runtime_info["denied_low_priority_rules"] = list(diagnostics.get("denied_low_priority_rules") or [])
        runtime_info["mcp_candidate_view"] = diagnostics.get("mcp_candidate_view") or {}
        reliability_metadata["supervisor_planner"] = {
            "decision_source": diagnostics.get("decision_source"),
            "rule_hits": diagnostics.get("rule_hits") or [],
            "llm_planner_called": bool(diagnostics.get("llm_planner_called")),
            "llm_planner_elapsed_ms": diagnostics.get("llm_planner_elapsed_ms", 0.0),
            "llm_planner_token_estimate": diagnostics.get("llm_planner_token_estimate", 0),
            "fallback_used": bool(diagnostics.get("fallback_used")),
            "completeness_guard_triggered": bool(diagnostics.get("completeness_guard_triggered")),
            "auto_added_tasks": list(diagnostics.get("auto_added_tasks") or []),
            "denied_low_priority_rules": list(diagnostics.get("denied_low_priority_rules") or []),
            "mcp_candidate_view": diagnostics.get("mcp_candidate_view") or {},
        }
        phase10_trace = diagnostics.get("phase10_goal_planning")
        if isinstance(phase10_trace, dict) and phase10_trace:
            runtime_info["phase10_goal_planning"] = phase10_trace
            runtime_info["user_goal"] = phase10_trace.get("semantic_goal") or {}
            runtime_info["task_plan"] = phase10_trace.get("task_plan") or {}
            runtime_info["plan_validation"] = phase10_trace.get("plan_validation") or {}
            runtime_info["fast_path_selected"] = bool(phase10_trace.get("fast_path_selected"))
            runtime_info["fast_path_reason"] = str(phase10_trace.get("fast_path_reason") or "")
            runtime_info["decision_source"] = str(phase10_trace.get("decision_source") or runtime_info.get("decision_source") or "")
            reliability_metadata["phase10_goal_planning"] = phase10_trace
    if isinstance(orchestration, dict) and orchestration.get("observations"):
        observations = list(orchestration.get("observations") or [])
        def semantic_triggered_in(rows: list[Any]) -> bool:
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if bool((row.get("semantic_observer") or {}).get("triggered")):
                    return True
                children = row.get("child_observations")
                if isinstance(children, list) and semantic_triggered_in(children):
                    return True
            return False

        semantic_triggered = semantic_triggered_in(observations)
        runtime_info["observe_conclusion"] = {
            "observation_count": len(observations),
            "semantic_observer_triggered": semantic_triggered,
            "replan_triggered": bool(orchestration.get("replan_count")),
        }
        reliability_metadata["observe"] = {
            "observations": observations,
            "replan_audit": list(orchestration.get("replan_audit") or []),
            "invalid_replan_block_count": int(orchestration.get("invalid_replan_block_count") or 0),
        }
    else:
        single_observation = {
            "observe_layer": "deterministic",
            "goal_satisfied": bool(result_dict.get("success")),
            "failed_steps": [] if result_dict.get("success") else [{"task_id": _task_id_for_single(decomposition), "intent": intent, "errors": result_dict.get("errors") or []}],
            "schema_valid": isinstance(result_dict.get("data"), dict) or result_dict.get("data") in (None, ""),
            "dependencies_satisfied": True,
            "permission_budget": {
                "permission_valid": True,
                "budget": dict(result_dict.get("runtime_reliability") or {}).get("budget_usage") or {},
            },
            "semantic_observer": {"triggered": False, "trigger_reasons": [], "result": {}},
            "next_action": "finish" if result_dict.get("success") else "fail",
        }
        runtime_info["observe_conclusion"] = {
            "observation_count": 1,
            "semantic_observer_triggered": False,
            "replan_triggered": False,
        }
        reliability_metadata["observe"] = {
            "observations": [single_observation],
            "replan_audit": [],
            "invalid_replan_block_count": 0,
        }
    phase10_trace = diagnostics.get("phase10_goal_planning") if isinstance(diagnostics, dict) else None
    if isinstance(phase10_trace, dict) and isinstance(phase10_trace.get("semantic_goal"), dict):
        phase10_observe = (
            dict(result_dict.get("llm_completion") or {})
            if isinstance(result_dict.get("llm_completion"), dict)
            else observe_goal_completion(
                phase10_trace.get("semantic_goal") or {},
                {
                    "task_results": orchestration.get("task_results") if isinstance(orchestration, dict) else {},
                    "result": result_dict,
                },
                llm_settings=llm_settings,
            ).to_dict()
        )
        runtime_info["phase10_observe"] = phase10_observe
        runtime_info["observe_status"] = phase10_observe.get("status")
        runtime_info["missing_outputs"] = list(phase10_observe.get("missing_outputs") or [])
        reliability_metadata["phase10_observe"] = phase10_observe
    if reliability_metadata:
        runtime.merge_metadata(reliability_metadata)
    tasks = decomposition.get("tasks") if isinstance(decomposition, dict) else []
    if not isinstance(tasks, list) or not tasks:
        tasks = [{
            "task_id": _task_id_for_single(decomposition),
            "intent": intent,
            "parameters": params,
            "depends_on": [],
        }]

    for task in tasks:
        if not isinstance(task, dict):
            continue
        runtime.create_step(
            str(task.get("task_id") or "task_1"),
            str(task.get("intent") or intent),
            depends_on=[str(item) for item in (task.get("depends_on") or [])],
            metadata={"reason": task.get("reason"), "capability_status": task.get("capability_status")},
        )

    if orchestration.get("multi_agent"):
        _record_agent_timeline(runtime, orchestration)

    if (intent == "multi_intent" or orchestration.get("multi_agent")) and orchestration:
        task_results = orchestration.get("task_results") or {}
        if isinstance(task_results, dict):
            for task_id, task_result in task_results.items():
                if isinstance(task_result, dict):
                    runtime.record_step_result(str(task_id), task_result)
        for call in expanded_tool_calls:
            if not isinstance(call, dict):
                continue
            task_id = str(call.get("task_id") or "")
            task_result = dict((task_results or {}).get(task_id) or {})
            call_reliability = dict(call.get("runtime_reliability") or task_result.get("runtime_reliability") or {})
            if isinstance(call.get("mcp"), dict) and call.get("mcp"):
                call_reliability["mcp"] = dict(call.get("mcp") or {})
            runtime.record_tool_call(
                step_id=task_id or None,
                tool_name=str(call.get("tool_name") or call.get("intent") or ""),
                arguments=sanitize_payload(dict(call.get("arguments") or {})),
                result=task_result,
                permission=str(call.get("permission") or ""),
                reliability=call_reliability,
            )
        runtime_info["replan_count"] = int(orchestration.get("replan_count") or 0)
    else:
        task_id = _task_id_for_single(decomposition)
        status = STEP_SUCCEEDED if result_dict.get("success") else STEP_FAILED
        if result_dict.get("status") == "skipped":
            status = STEP_SKIPPED
        runtime.record_step_result(
            task_id,
            {
                "task_id": task_id,
                "intent": intent,
                "success": bool(result_dict.get("success")),
                "step_status": status,
                "execution_mode": "single",
                "arguments": params,
                "message": result_dict.get("message", ""),
                "data": result_dict.get("data") if isinstance(result_dict.get("data"), dict) else {},
                "warnings": result_dict.get("warnings") or [],
                "errors": result_dict.get("errors") or [],
            },
        )
        runtime.record_tool_call(
            step_id=task_id,
            tool_name=str(result_dict.get("tool_name") or intent),
            arguments=sanitize_payload(params),
            result=result_dict,
            permission=str(result_dict.get("permission") or ""),
            reliability=dict(result_dict.get("runtime_reliability") or {}),
        )

    attached = _runtime_attach_plan_ids(
        runtime,
        result_dict.get("data") if isinstance(result_dict, dict) else {},
        user_id=user_id,
        output_dir=output_dir,
    )
    runtime_info["attached_plan_ids"] = attached
    return runtime_info


def _first_present(
    row: dict[str, Any],
    keys: list[str],
    default: Any = "",
) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return default


def _format_number(value: Any, digits: int = 4) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def _format_ratio(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "-"


def _ranking_answer(
    data: dict[str, Any],
    language: str,
) -> str:
    records = list(data.get("records") or [])
    if not records:
        return _unavailable(language)

    if language == REPLY_LANGUAGE_EN:
        lines = [
            f"The latest top {len(records)} predicted stocks are:",
            "",
            "| Rank | Stock Code | Stock Name | Score | Predicted Return | Risk Level |",
            "|---:|---|---|---:|---:|---|",
        ]
    else:
        lines = [
            f"当前最新预测排名前 {len(records)} 的股票如下：",
            "",
            "| 排名 | 股票代码 | 股票名称 | 预测分数 | 预测收益 | 风险等级 |",
            "|---:|---|---|---:|---:|---|",
        ]

    for index, raw_row in enumerate(records, start=1):
        row = dict(raw_row or {})
        rank = _first_present(row, ["rank", "ranking"], index)
        code = _first_present(
            row,
            ["stock_code", "code", "ts_code"],
            "-",
        )
        name = _first_present(
            row,
            ["stock_name", "name"],
            "-",
        )
        score = _format_number(
            _first_present(
                row,
                ["score", "pred_score", "raw_score"],
                None,
            )
        )
        predicted_return = _format_number(
            _first_present(
                row,
                ["pred_5d_ret", "predicted_return", "prediction"],
                None,
            )
        )
        risk_level = _first_present(
            row,
            ["risk_level", "risk"],
            "-",
        )
        lines.append(
            f"| {rank} | {code} | {name} | {score} | "
            f"{predicted_return} | {risk_level} |"
        )

    if language == REPLY_LANGUAGE_EN:
        lines.extend([
            "",
            "The latest ranking can currently be read and displayed. "
            "Batch deep analysis of news, RAG evidence, and position sizing "
            "for every stock in the ranking is still under development.",
        ])
    else:
        lines.extend([
            "",
            "当前已支持读取并展示最新排名；"
            "对排名中多只股票逐一进行新闻、RAG 和仓位深度分析的功能"
            "仍在后续开发中。",
        ])

    return "\n".join(lines)


def _portfolio_answer(
    data: dict[str, Any],
    language: str,
) -> str:
    positions = list(data.get("positions") or [])
    account = dict(data.get("account") or {})

    position_count = data.get("position_count")
    if position_count is None:
        position_count = len(positions)

    total_assets = _first_present(
        account,
        ["total_assets", "total_asset", "assets"],
        data.get("total_assets"),
    )
    cash = _first_present(
        account,
        ["cash", "available_cash"],
        data.get("cash"),
    )
    market_value = _first_present(
        account,
        ["position_market_value", "market_value"],
        data.get("position_market_value"),
    )

    if language == REPLY_LANGUAGE_EN:
        lines = [
            "Current paper-trading portfolio status:",
            "",
            f"- Number of positions: {position_count}",
        ]
        if total_assets not in (None, ""):
            lines.append(
                f"- Total assets: {_format_number(total_assets, 2)}"
            )
        if cash not in (None, ""):
            lines.append(
                f"- Available cash: {_format_number(cash, 2)}"
            )
        if market_value not in (None, ""):
            lines.append(
                f"- Position market value: "
                f"{_format_number(market_value, 2)}"
            )
    else:
        lines = [
            "当前模拟盘状态：",
            "",
            f"- 持仓数量：{position_count}",
        ]
        if total_assets not in (None, ""):
            lines.append(
                f"- 总资产：{_format_number(total_assets, 2)}"
            )
        if cash not in (None, ""):
            lines.append(
                f"- 可用现金：{_format_number(cash, 2)}"
            )
        if market_value not in (None, ""):
            lines.append(
                f"- 持仓市值：{_format_number(market_value, 2)}"
            )

    if positions:
        if language == REPLY_LANGUAGE_EN:
            lines.extend([
                "",
                "| Stock Code | Stock Name | Quantity | Current Weight |",
                "|---|---|---:|---:|",
            ])
        else:
            lines.extend([
                "",
                "| 股票代码 | 股票名称 | 数量 | 当前仓位 |",
                "|---|---|---:|---:|",
            ])

        for raw_position in positions[:20]:
            position = dict(raw_position or {})
            code = _first_present(
                position,
                ["stock_code", "code"],
                "-",
            )
            name = _first_present(
                position,
                ["stock_name", "name"],
                "-",
            )
            quantity = _first_present(
                position,
                ["quantity", "shares"],
                0,
            )
            ratio = _first_present(
                position,
                ["position_ratio", "weight"],
                None,
            )
            lines.append(
                f"| {code} | {name} | {quantity} | "
                f"{_format_ratio(ratio)} |"
            )

    return "\n".join(lines)




def _portfolio_risk_answer(
    data: dict[str, Any],
    language: str,
) -> str:
    report = data.get("risk_report")
    if not isinstance(report, dict):
        report = {}

    source = str(data.get("source") or "")

    def value(keys: list[str]) -> Any:
        return _first_present(report, keys, None)

    def list_value(keys: list[str]) -> list[str]:
        for key in keys:
            raw = report.get(key)
            if isinstance(raw, list):
                return [
                    str(item)
                    for item in raw
                    if str(item).strip()
                ]
            if isinstance(raw, str) and raw.strip():
                return [raw.strip()]
        return []

    risk_level = value([
        "risk_level",
        "overall_risk_level",
        "portfolio_risk_level",
        "level",
    ])
    risk_score = value([
        "risk_score",
        "overall_risk_score",
        "portfolio_risk_score",
    ])
    position_count = value([
        "position_count",
        "num_positions",
        "holding_count",
    ])
    invested_ratio = value([
        "invested_ratio",
        "position_ratio",
        "gross_exposure",
        "total_exposure",
    ])
    cash_ratio = value([
        "cash_ratio",
        "cash_weight",
    ])
    max_position = value([
        "max_single_position",
        "largest_position_weight",
        "max_position_weight",
        "top1_weight",
    ])
    concentration = value([
        "concentration_hhi",
        "hhi",
        "concentration",
        "top3_concentration",
        "top3_weight",
    ])
    max_drawdown = value([
        "max_drawdown",
        "drawdown",
        "portfolio_drawdown",
    ])
    volatility = value([
        "annualized_volatility",
        "portfolio_volatility",
        "volatility",
        "daily_volatility",
    ])
    warnings = list_value([
        "risk_warnings",
        "warnings",
        "violations",
        "breaches",
        "alerts",
    ])

    if language == REPLY_LANGUAGE_EN:
        source_text = (
            "latest saved risk snapshot"
            if source == "latest_snapshot"
            else (
                "calculated from the current account, "
                "positions, and user constraints"
            )
        )
        lines = [
            "Paper-trading portfolio risk analysis:",
            "",
            f"- Data source: {source_text}",
        ]
        labels = {
            "risk_level": "Risk level",
            "risk_score": "Risk score",
            "position_count": "Number of positions",
            "invested_ratio": "Invested ratio",
            "cash_ratio": "Cash ratio",
            "max_position": "Largest single-position weight",
            "concentration": "Concentration indicator",
            "max_drawdown": "Maximum drawdown",
            "volatility": "Volatility",
        }
    else:
        source_text = (
            "最新已保存风险快照"
            if source == "latest_snapshot"
            else (
                "根据当前账户、持仓和用户约束实时计算"
            )
        )
        lines = [
            "当前模拟盘组合风险分析：",
            "",
            f"- 数据来源：{source_text}",
        ]
        labels = {
            "risk_level": "风险等级",
            "risk_score": "风险分数",
            "position_count": "持仓数量",
            "invested_ratio": "已投资比例",
            "cash_ratio": "现金比例",
            "max_position": "最大单股仓位",
            "concentration": "集中度指标",
            "max_drawdown": "最大回撤",
            "volatility": "波动率",
        }

    if risk_level is not None:
        lines.append(
            f"- {labels['risk_level']}：{risk_level}"
            if language == REPLY_LANGUAGE_ZH
            else f"- {labels['risk_level']}: {risk_level}"
        )
    if risk_score is not None:
        lines.append(
            (
                f"- {labels['risk_score']}："
                f"{_format_number(risk_score)}"
            )
            if language == REPLY_LANGUAGE_ZH
            else (
                f"- {labels['risk_score']}: "
                f"{_format_number(risk_score)}"
            )
        )
    if position_count is not None:
        lines.append(
            (
                f"- {labels['position_count']}："
                f"{position_count}"
            )
            if language == REPLY_LANGUAGE_ZH
            else (
                f"- {labels['position_count']}: "
                f"{position_count}"
            )
        )
    if invested_ratio is not None:
        lines.append(
            (
                f"- {labels['invested_ratio']}："
                f"{_format_ratio(invested_ratio)}"
            )
            if language == REPLY_LANGUAGE_ZH
            else (
                f"- {labels['invested_ratio']}: "
                f"{_format_ratio(invested_ratio)}"
            )
        )
    if cash_ratio is not None:
        lines.append(
            (
                f"- {labels['cash_ratio']}："
                f"{_format_ratio(cash_ratio)}"
            )
            if language == REPLY_LANGUAGE_ZH
            else (
                f"- {labels['cash_ratio']}: "
                f"{_format_ratio(cash_ratio)}"
            )
        )
    if max_position is not None:
        lines.append(
            (
                f"- {labels['max_position']}："
                f"{_format_ratio(max_position)}"
            )
            if language == REPLY_LANGUAGE_ZH
            else (
                f"- {labels['max_position']}: "
                f"{_format_ratio(max_position)}"
            )
        )
    if concentration is not None:
        lines.append(
            (
                f"- {labels['concentration']}："
                f"{_format_number(concentration)}"
            )
            if language == REPLY_LANGUAGE_ZH
            else (
                f"- {labels['concentration']}: "
                f"{_format_number(concentration)}"
            )
        )
    if max_drawdown is not None:
        lines.append(
            (
                f"- {labels['max_drawdown']}："
                f"{_format_ratio(max_drawdown)}"
            )
            if language == REPLY_LANGUAGE_ZH
            else (
                f"- {labels['max_drawdown']}: "
                f"{_format_ratio(max_drawdown)}"
            )
        )
    if volatility is not None:
        lines.append(
            (
                f"- {labels['volatility']}："
                f"{_format_ratio(volatility)}"
            )
            if language == REPLY_LANGUAGE_ZH
            else (
                f"- {labels['volatility']}: "
                f"{_format_ratio(volatility)}"
            )
        )

    if warnings:
        lines.extend([
            "",
            (
                "风险提示："
                if language == REPLY_LANGUAGE_ZH
                else "Risk warnings:"
            ),
        ])
        lines.extend(
            f"- {item}" for item in warnings[:10]
        )

    recognised = any(
        item is not None
        for item in [
            risk_level,
            risk_score,
            position_count,
            invested_ratio,
            cash_ratio,
            max_position,
            concentration,
            max_drawdown,
            volatility,
        ]
    )

    if not recognised and report:
        scalar_items = [
            (key, raw)
            for key, raw in report.items()
            if isinstance(
                raw,
                (str, int, float, bool),
            )
            and raw not in ("", None)
        ][:12]

        if scalar_items:
            lines.extend([
                "",
                (
                    "其他风险字段："
                    if language == REPLY_LANGUAGE_ZH
                    else "Other risk fields:"
                ),
            ])
            lines.extend(
                f"- {key}: {raw}"
                for key, raw in scalar_items
            )

    return "\n".join(lines)


def _stock_analysis_answer(
    data: dict[str, Any],
    language: str,
) -> str:
    code = data.get("stock_code") or "-"
    name = data.get("stock_name") or "-"
    price = _format_number(data.get("current_price"), 2)
    rank = data.get("original_rank")
    adjustment = _format_number(data.get("combined_adjustment"), 3)
    ratio = _format_number(
        data.get("position_adjustment_ratio"),
        3,
    )
    target_weight = _format_ratio(data.get("target_weight"))
    suitability = data.get("suitability_for_user") or "-"

    if language == REPLY_LANGUAGE_EN:
        return "\n".join([
            f"Analysis result for {code} {name}:",
            "",
            f"- Current price: {price}",
            f"- Original rank: {rank if rank is not None else '-'}",
            f"- Combined adjustment: {adjustment}",
            f"- Position adjustment ratio: {ratio}",
            f"- Target weight: {target_weight}",
            f"- Suitability status: {suitability}",
        ])

    return "\n".join([
        f"{code} {name} 的分析结果：",
        "",
        f"- 当前价格：{price}",
        f"- 原始排名：{rank if rank is not None else '-'}",
        f"- 综合调整分：{adjustment}",
        f"- 仓位调整倍率：{ratio}",
        f"- 目标仓位：{target_weight}",
        f"- 用户适配状态：{suitability}",
    ])


def _stock_news_answer(
    data: dict[str, Any],
    language: str,
) -> str:
    events = list(data.get("events") or [])
    event_count = data.get("event_count")
    if event_count is None:
        event_count = len(events)

    if language == REPLY_LANGUAGE_EN:
        lines = [f"Found {event_count} mapped news event(s)."]
    else:
        lines = [f"共找到 {event_count} 条已映射新闻事件。"]

    for event in events[:5]:
        row = dict(event or {})
        title = (
            row.get("title")
            or row.get("headline")
            or row.get("summary")
            or ""
        )
        if title:
            lines.append(f"- {str(title)[:180]}")

    return "\n".join(lines)


def _stock_rag_answer(
    data: dict[str, Any],
    language: str,
) -> str:
    chunks = list(data.get("chunks") or [])

    if language == REPLY_LANGUAGE_EN:
        lines = [f"Found {len(chunks)} RAG evidence chunk(s)."]
    else:
        lines = [f"共找到 {len(chunks)} 条 RAG 证据。"]

    for chunk in chunks[:5]:
        row = dict(chunk or {})
        chunk_id = row.get("chunk_id") or row.get("id") or "-"
        text = (
            row.get("text")
            or row.get("content")
            or row.get("snippet")
            or ""
        )
        lines.append(f"- [{chunk_id}] {str(text)[:180]}")

    return "\n".join(lines)


def _scheduler_answer(
    data: dict[str, Any],
    language: str,
) -> str:
    latest = dict(data.get("latest_job_status") or {})
    status = (
        latest.get("overall_status")
        or latest.get("status")
        or data.get("status")
        or "unknown"
    )
    updated_at = (
        latest.get("updated_at")
        or latest.get("finished_at")
        or latest.get("created_at")
        or data.get("updated_at")
        or "-"
    )

    if language == REPLY_LANGUAGE_EN:
        return "\n".join([
            "Scheduler status:",
            "",
            f"- Status: {status}",
            f"- Last update: {updated_at}",
        ])

    return "\n".join([
        "每日自动更新与调度状态：",
        "",
        f"- 当前状态：{status}",
        f"- 最近更新时间：{updated_at}",
    ])


def _report_answer(
    data: dict[str, Any],
    language: str,
) -> str:
    records = (
        data.get("reports")
        or data.get("records")
        or data.get("items")
        or []
    )
    if not isinstance(records, list):
        records = []

    if language == REPLY_LANGUAGE_EN:
        lines = [f"Found {len(records)} report record(s)."]
    else:
        lines = [f"共找到 {len(records)} 条报告记录。"]

    for record in records[:10]:
        if isinstance(record, dict):
            name = (
                record.get("name")
                or record.get("title")
                or record.get("path")
                or record.get("file")
                or str(record)
            )
        else:
            name = str(record)
        lines.append(f"- {name}")

    return "\n".join(lines)


def _plan_answer(
    intent: str,
    data: dict[str, Any],
    language: str,
) -> str:
    plan_id = data.get("plan_id") or "-"
    expires_at = data.get("expires_at") or "-"

    if language == REPLY_LANGUAGE_EN:
        labels = {
            "preview_add_stock": "Paper-trading preview created.",
            "adjust_position": "Paper-position adjustment preview created.",
            "one_time_position_operation": "One-time paper-position preview created.",
            "strategy_change": "Strategy-change confirmation plan created.",
            "capital_management": "Paper capital change preview created.",
            "backfill": "Historical paper-trading backfill preview created.",
        }
        heading = labels.get(intent, "Confirmation plan created.")
        return "\n".join([
            heading,
            "",
            f"- Plan ID: {plan_id}",
            "- Approval credential: generated and hidden; use the approval UI to confirm.",
            f"- Expires at: {expires_at}",
        ])

    labels = {
        "preview_add_stock": "已生成模拟盘调仓预览。",
        "adjust_position": "已生成模拟盘调仓预览。",
        "one_time_position_operation": "已生成本次一次性模拟盘仓位预览。",
        "strategy_change": "已生成长期策略变更确认计划。",
        "capital_management": "已生成模拟资金变更预览。",
        "backfill": "已生成历史模拟盘回放预览。",
    }
    heading = labels.get(intent, "已生成待确认计划。")
    return "\n".join([
        heading,
        "",
        f"- 计划 ID：{plan_id}",
        "- 确认凭证：已生成并隐藏，请在待确认计划区域点击确认。",
        f"- 过期时间：{expires_at}",
    ])


def _plan_effect_lines(
    intent: str,
    data: dict[str, Any],
    language: str,
) -> list[str]:
    if intent == "one_time_position_operation":
        base_intent = (
            "adjust_position"
            if data.get("current_quantity") is not None
            or data.get("action") in {"reduce", "sell", "buy"}
            else "preview_add_stock"
        )
        lines = _plan_effect_lines(base_intent, data, language)
        if language == REPLY_LANGUAGE_EN:
            lines.append(
                "- This one-time operation does not modify the long-term paper strategy."
            )
        else:
            lines.append("- 本次操作不会修改长期持仓策略，执行后本次覆盖失效。")
        return lines

    if intent == "strategy_change":
        strategy_id = str(data.get("strategy_id") or "-")
        version = str(data.get("strategy_version") or "-")
        implementation_type = str(data.get("implementation_type") or "-")
        if language == REPLY_LANGUAGE_EN:
            return [
                "Impact after confirmation:",
                f"- Register strategy version: {strategy_id} / {version}",
                f"- Implementation type: {implementation_type}",
                "- Registration does not enable the strategy.",
                "- Enabling requires a second confirmation and does not execute today's paper orders.",
            ]
        return [
            "确认后连锁影响：",
            f"- 注册策略版本：{strategy_id} / {version}",
            f"- 实现方式：{implementation_type}",
            "- 注册后默认不启用。",
            "- 启用需要第二次确认；启用也不会立即执行今天的模拟盘订单。",
        ]

    if intent == "adjust_position":
        action = str(data.get("action") or "")
        stock_code = str(data.get("stock_code") or "-")
        stock_name = str(data.get("stock_name") or "")
        trade_quantity = _format_number(data.get("estimated_quantity"), 0)
        current_quantity = _format_number(data.get("current_quantity"), 0)
        target_quantity = _format_number(data.get("target_quantity"), 0)
        current_weight = _format_ratio(data.get("current_weight"))
        target_weight = _format_ratio(data.get("target_weight") or data.get("recommended_weight"))
        before = dict(data.get("before") or {})
        after = dict(data.get("after") or {})
        cash_before = _format_number(before.get("cash"), 2)
        cash_after = _format_number(after.get("estimated_cash"), 2)
        position_count = before.get("position_count")
        if language == REPLY_LANGUAGE_EN:
            action_text = "reduce/sell" if action in {"reduce", "sell"} else "buy/increase"
            return [
                "Impact after confirmation:",
                f"- Paper order: {action_text} {trade_quantity} shares of {stock_code} {stock_name}".strip(),
                f"- Quantity: {current_quantity} -> {target_quantity} shares",
                f"- Weight: {current_weight} -> {target_weight}",
                f"- Cash estimate: {cash_before} -> {cash_after}",
                f"- Position count before: {position_count}",
                "- The paper account, positions, orders, NAV, risk report, and daily snapshot will be updated.",
            ]
        action_text = "卖出/减仓" if action in {"reduce", "sell"} else "买入/加仓"
        return [
            "确认后连锁影响：",
            f"- 模拟订单：{action_text} {stock_code} {stock_name}，数量 {trade_quantity} 股",
            f"- 持仓数量：{current_quantity} 股 -> {target_quantity} 股",
            f"- 持仓仓位：{current_weight} -> {target_weight}",
            f"- 现金预估：{cash_before} -> {cash_after}",
            f"- 当前持仓数：{position_count}",
            "- 会更新模拟盘账户、持仓、订单、净值、风险报告和当日快照。",
        ]

    if intent == "preview_add_stock":
        stock_code = str(data.get("stock_code") or "-")
        stock_name = str(data.get("stock_name") or "")
        trade_quantity = _format_number(data.get("estimated_quantity"), 0)
        estimated_cost = _format_number(data.get("estimated_cost"), 2)
        target_weight = _format_ratio(data.get("recommended_weight"))
        before = dict(data.get("before") or {})
        after = dict(data.get("after") or {})
        cash_before = _format_number(before.get("cash"), 2)
        cash_after = _format_number(after.get("estimated_cash"), 2)
        if language == REPLY_LANGUAGE_EN:
            return [
                "Impact after confirmation:",
                f"- Paper order: buy {trade_quantity} shares of {stock_code} {stock_name}".strip(),
                f"- Target weight: {target_weight}",
                f"- Estimated cost: {estimated_cost}",
                f"- Cash estimate: {cash_before} -> {cash_after}",
                "- The paper account, positions, orders, NAV, risk report, and daily snapshot will be updated.",
            ]
        return [
            "确认后连锁影响：",
            f"- 模拟订单：买入 {stock_code} {stock_name}，数量 {trade_quantity} 股",
            f"- 目标仓位：{target_weight}",
            f"- 预估占用现金：{estimated_cost}",
            f"- 现金预估：{cash_before} -> {cash_after}",
            "- 会更新模拟盘账户、持仓、订单、净值、风险报告和当日快照。",
        ]

    return []


def _plan_answer_with_effects(
    intent: str,
    data: dict[str, Any],
    language: str,
) -> str:
    body = _plan_answer(intent, data, language)
    effect_lines = _plan_effect_lines(intent, data, normalise_reply_language(language))
    if not effect_lines:
        return body
    return "\n".join([body, "", *effect_lines])


def _general_help_answer(language: str) -> str:
    if language == REPLY_LANGUAGE_EN:
        return (
            "Currently supported capabilities include: reading the latest "
            "ranking, reading the paper-trading account and positions, "
            "analyzing portfolio risk, analyzing a specified stock, "
            "querying stock news or RAG evidence, "
            "creating confirmation-required paper-trading previews, managing "
            "paper capital, checking scheduler status, and reading reports."
        )
    return (
        "目前支持：查询最新排名、查询模拟盘账户和持仓、"
        "分析模拟盘组合风险、分析指定股票、"
        "查看指定股票新闻或 RAG 证据、"
        "生成需要确认的模拟盘预览、管理模拟资金、"
        "查询调度状态和查看报告。"
    )


def _generic_success_answer(
    intent: str,
    message: str,
    data: dict[str, Any],
    language: str,
) -> str:
    if intent == "position_recommendation":
        weight = _format_ratio(
            _first_present(
                data,
                ["recommended_weight", "target_weight"],
                None,
            )
        )
        quantity = _first_present(
            data,
            ["estimated_quantity", "quantity"],
            "-",
        )
        if language == REPLY_LANGUAGE_EN:
            return (
                f"Position recommendation generated.\n\n"
                f"- Recommended weight: {weight}\n"
                f"- Estimated quantity: {quantity}"
            )
        return (
            f"已生成模拟仓位建议。\n\n"
            f"- 建议仓位：{weight}\n"
            f"- 预计数量：{quantity}"
        )

    if intent == "replacement_recommendation":
        candidates = data.get("replacement_candidates") or []
        count = len(candidates) if isinstance(candidates, list) else 0
        if language == REPLY_LANGUAGE_EN:
            return f"Generated {count} replacement candidate(s)."
        return f"已生成 {count} 个可替换候选。"

    if intent == "confirm_execute":
        if language == REPLY_LANGUAGE_EN:
            return "The confirmed paper-trading operation has been processed."
        return "已处理确认后的模拟盘操作。"

    if intent == "strategy_change":
        action = str(data.get("conversation_action") or "")
        if action in {"ask_implementation", "llm_unavailable"}:
            if language == REPLY_LANGUAGE_EN:
                return "Would you like me to start preparing the strategy adjustment now?"
            return "那现在需要我开始调整策略吗？"
        if message:
            return message
        if language == REPLY_LANGUAGE_EN:
            return "The strategy proposal draft has been saved without changing formal strategy or portfolio state."
        return "已保存策略方案草案，尚未修改正式策略或模拟盘状态。"

    if language == REPLY_LANGUAGE_EN:
        if message and not re.search(r"[\u4e00-\u9fff]", message):
            return message
        return "The request has been processed."

    if message and re.search(r"[\u4e00-\u9fff]", message):
        return message
    return "请求已处理完成。"


_INTERNAL_NAME_REPLACEMENTS = {
    "portfolio.design_target_portfolio": "目标组合设计步骤",
    "portfolio.construct_target_portfolio": "目标组合构建步骤",
    "portfolio.compare_portfolios": "组合比较步骤",
    "multi_intent_executor": "任务执行流程",
}


def _multi_intent_public_message(
    orchestration: dict[str, Any],
    language: str,
) -> str:
    answer = str(orchestration.get("answer") or "").strip()
    if answer:
        return answer
    status = str(orchestration.get("execution_status") or "").lower()
    if normalise_reply_language(language) == REPLY_LANGUAGE_EN:
        if status == "partially_completed":
            return (
                "Part of the requested analysis was completed, but the full "
                "business goal was not satisfied. Available results and the "
                "remaining limitations are shown below."
            )
        if status == "completed":
            return "The requested analysis was completed."
        return "The requested analysis could not be completed with the available data."
    if status == "partially_completed":
        return "本次请求已获得部分可用结果，但完整业务目标尚未满足；下方将说明现有结果和剩余限制。"
    if status == "completed":
        return "本次请求已完成。"
    return "本次请求未能基于现有数据完整完成。"


def _sanitize_user_facing_answer(answer: str, language: str) -> str:
    text = str(answer or "").strip()
    for internal_name, public_name in _INTERNAL_NAME_REPLACEMENTS.items():
        text = text.replace(f"`{internal_name}`", public_name)
        text = text.replace(internal_name, public_name)

    text = re.sub(r"\btask_[A-Za-z0-9_-]+\b", "相关步骤", text)
    text = re.sub(r"\breplan_[A-Za-z0-9_-]+\b", "补救步骤", text)
    if normalise_reply_language(language) == REPLY_LANGUAGE_ZH:
        replacements = {
            "内部模块异常": "当前处理步骤未能完成",
            "内部校验异常": "当前结果未通过约束校验",
            "内部数据校验失败": "当前结果未通过约束校验",
            "相关功能模块": "相关处理步骤",
            "后续版本将完善此功能": "当前结果未能完整生成，可在数据或约束更新后重新尝试",
            "等该功能修复后": "稍后重新尝试后",
            "功能仍在后续开发中": "当前可用数据不足以完成该请求",
        }
        for old_text, new_text in replacements.items():
            text = text.replace(old_text, new_text)
    else:
        text = re.sub(
            r"internal (module|validation|data validation) (error|failure)",
            "the current result did not pass validation",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"will be implemented in a future version",
            "can be retried when the required data is available",
            text,
            flags=re.IGNORECASE,
        )
    return text.strip()


def _failure_answer(
    intent: str,
    message: str,
    data: dict[str, Any],
    errors: list[str],
    language: str,
) -> str:
    if intent in {"adjust_position", "one_time_position_operation"} and "no_executable_lot_quantity" in errors:
        quantity = _format_number(data.get("current_quantity"), 0)
        lot_size = data.get("lot_size") or 100
        if language == REPLY_LANGUAGE_EN:
            return (
                "No paper-position adjustment plan was created: the requested "
                f"change is smaller than one executable A-share lot. Current "
                f"quantity is {quantity} shares, and the lot rule is {lot_size} "
                "shares. You can use a full exit or sell 100 shares instead."
            )
        return (
            "没有生成模拟盘减仓计划：这次调整不足一手，无法形成可执行订单。\n\n"
            f"- 当前持仓数量：{quantity} 股\n"
            f"- 当前一手规则：{lot_size} 股\n"
            "- 例如 100 股持仓执行“减半”只会涉及约 50 股，所以不会修改持仓。\n"
            "- 可以改成“清仓”或“卖出100股”。"
        )

    if intent in {"adjust_position", "one_time_position_operation"} and message:
        if language == REPLY_LANGUAGE_EN:
            return message
        return f"没有生成模拟盘调仓计划：{message}"

    if message:
        return message
    return _unavailable(language)


def _answer(
    intent: str,
    result: dict[str, Any],
    language: str,
) -> str:
    language = normalise_reply_language(language)
    success = bool(result.get("success"))
    message = str(result.get("message") or "")
    data = dict(result.get("data") or {})
    errors = [str(item) for item in (result.get("errors") or [])]

    if intent == "llm_insufficient_balance":
        body = _llm_insufficient_balance_message(language)
    elif not success:
        body = _failure_answer(intent, message, data, errors, language)
    elif intent == "set_reply_language":
        body = _language_acknowledgement(language)
    elif intent == "ranking":
        body = _ranking_answer(data, language)
    elif intent == "portfolio_state":
        body = _portfolio_answer(data, language)
    elif intent == "portfolio_risk":
        body = _portfolio_risk_answer(data, language)
    elif intent == "stock_analysis":
        body = _stock_analysis_answer(data, language)
    elif intent == "stock_news":
        body = _stock_news_answer(data, language)
    elif intent == "stock_rag":
        body = _stock_rag_answer(data, language)
    elif intent == "scheduler_status":
        body = _scheduler_answer(data, language)
    elif intent == "report":
        body = _report_answer(data, language)
    elif intent == "multi_intent" and message:
        body = message
    elif (
        intent in {
            "preview_add_stock",
            "adjust_position",
            "one_time_position_operation",
            "strategy_change",
            "capital_management",
            "backfill",
        }
        and data.get("plan_id")
    ):
        body = _plan_answer_with_effects(intent, data, language)
    elif intent == "general_help":
        body = _general_help_answer(language)
    else:
        body = _generic_success_answer(
            intent,
            message,
            data,
            language,
        )

    if intent == "llm_insufficient_balance":
        return body.strip()

    return f"{body}\n\n{_disclaimer(language)}".strip()


def _phase16_reflection_summary(critic_payload: dict[str, Any]) -> dict[str, Any]:
    issues = critic_payload.get("issues") if isinstance(critic_payload.get("issues"), list) else []
    return {
        "critic_id": str(critic_payload.get("critic_id") or ""),
        "verdict": str(critic_payload.get("verdict") or ""),
        "action": str(critic_payload.get("action") or ""),
        "severity": str(critic_payload.get("severity") or ""),
        "score": critic_payload.get("score"),
        "issue_count": len(issues),
        "summary": str(critic_payload.get("target_summary") or "")[:500],
        "requires_user_confirmation": bool(critic_payload.get("requires_user_confirmation")),
        "evidence_refs": list(critic_payload.get("evidence_refs") or [])[:10],
        "observation_refs": list(critic_payload.get("observation_refs") or [])[:10],
        "replan_refs": list(critic_payload.get("replan_refs") or [])[:10],
        "message_refs": list(critic_payload.get("message_refs") or [])[:10],
        "memory_refs": list(critic_payload.get("memory_refs") or [])[:10],
        "approval_refs": list(critic_payload.get("approval_refs") or [])[:10],
        "revision_instruction": str(critic_payload.get("revision_instruction") or "")[:500],
        "replan_hint": str(critic_payload.get("replan_hint") or "")[:500],
        "handoff_hint": str(critic_payload.get("handoff_hint") or "")[:500],
    }


def _phase16_blocked_answer(language: str, reflection: dict[str, Any]) -> str:
    action = str(reflection.get("action") or CriticAction.BLOCK_AND_REPORT.value)
    if language == REPLY_LANGUAGE_EN:
        return (
            "The draft answer was blocked by the read-only Reflection Critic "
            f"because it may expose unsafe runtime details. Action: {action}.\n\n"
            f"{_disclaimer(language)}"
        ).strip()
    return (
        "Reflection Critic 已阻断本次草稿回答：可能包含不应展示的运行细节或敏感字段。"
        f"处理动作：{action}。\n\n{_disclaimer(language)}"
    ).strip()


_PUBLIC_PARAMETER_DENY_KEYS = {
    "api_key",
    "authorization",
    "authorization_header",
    "confirmation_token",
    "confirmation_token_hash",
    "cookie",
    "llm_api_key",
    "password",
    "secret",
    "tushare_token",
    "token",
}


def _public_agent_parameters(params: Any) -> Any:
    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            cleaned: dict[str, Any] = {}
            for key, item in value.items():
                key_text = str(key)
                if key_text.lower() in _PUBLIC_PARAMETER_DENY_KEYS:
                    continue
                cleaned[key_text] = scrub(item)
            return cleaned
        if isinstance(value, list):
            return [scrub(item) for item in value[:50]]
        return value

    return scrub(params if params is not None else {})


def _run_phase16_reflection(
    *,
    answer_text: str,
    result_dict: dict[str, Any],
    intent: str,
    language: str,
    output_dir: str | Path,
    user_id: str,
    session_id: str,
    run_id: str,
    task_id: str,
    context_refs: list[dict[str, Any]],
    artifact_refs: list[dict[str, Any]],
    approval_refs: list[dict[str, Any]],
    context_payload: dict[str, Any],
    context_warnings: list[str],
    runtime: AgentRuntimeRecorder,
) -> tuple[str, dict[str, Any]]:
    try:
        summary_payload = result_summary_payload(result_dict)
        publish_agent_message(
            output_dir=output_dir,
            user_id=user_id,
            conversation_id=session_id,
            run_id=run_id,
            task_id=task_id,
            sender="executor",
            receiver="critic_engine",
            message_type=MessageType.REFLECTION_REQUESTED,
            payload={
                "target_type": "FINAL_REPORT",
                "intent": str(intent or ""),
                "tool_name": str(result_dict.get("tool_name") or intent),
                "success": bool(result_dict.get("success")),
                "summary": {
                    "answer_chars": len(answer_text or ""),
                    "result": summary_payload,
                },
                "refs": {
                    "context_refs": context_refs,
                    "artifact_refs": artifact_refs,
                    "approval_refs": approval_refs,
                },
            },
            payload_schema="phase16.reflection_requested.v1",
            context_refs=context_refs,
            artifact_refs=artifact_refs,
            approval_refs=approval_refs,
        )
        engine = CriticEngine(output_dir=output_dir)
        critic_result = engine.criticize_final_result(
            answer_summary=answer_text[:2000],
            success=bool(result_dict.get("success")),
            result_status=str(result_dict.get("status") or ""),
            tool_name=str(result_dict.get("tool_name") or intent),
            conversation_id=session_id,
            run_id=run_id,
            task_id=task_id,
            target_ref=str(result_dict.get("artifact_id") or ""),
            result_summary=summary_payload,
            evidence_refs=artifact_refs,
            observation_refs=[],
            replan_refs=[],
            message_refs=[],
            memory_refs=[],
            approval_refs=approval_refs,
            metadata={"intent": str(intent or ""), "read_only_critic": True},
        )
        engine.save_result(critic_result, user_id=user_id)
        safe_payload = CriticSanitizer().sanitize_for_ui(critic_result)
        reflection_summary = _phase16_reflection_summary(safe_payload)
        trace_event("reflection.hard_critic.result", reflection_summary, run_id=run_id, task_id=task_id)
        flow_event(
            "CRITIC",
            {
                "critic_type": "hard_safety_reflection_critic",
                "result": reflection_summary,
                "approval_decision_uses_structured_fields_only": True,
            },
            run_id=run_id,
            task_id=task_id,
            level="INFO" if str(reflection_summary.get("action") or "PASS").upper() == "PASS" else "WARNING",
        )
        publish_agent_message(
            output_dir=output_dir,
            user_id=user_id,
            conversation_id=session_id,
            run_id=run_id,
            task_id=task_id,
            sender="critic_engine",
            receiver="executor",
            message_type=MessageType.REFLECTION_RESULT,
            payload=reflection_summary,
            payload_schema="phase16.reflection_result.v1",
            context_refs=context_refs,
            artifact_refs=artifact_refs,
            approval_refs=approval_refs,
        )
        context_payload["phase16_reflection"] = reflection_summary
        runtime.merge_metadata({"phase16_reflection": reflection_summary})
        if critic_result.action == CriticAction.BLOCK_AND_REPORT:
            return _phase16_blocked_answer(language, reflection_summary), reflection_summary
        return answer_text, reflection_summary
    except Exception as exc:
        context_warnings.append(f"phase16_critic_failed:{type(exc).__name__}")
        try:
            runtime.merge_metadata({"phase16_critic_failed": f"{type(exc).__name__}: {exc}"[:300]})
        except Exception:
            pass
        return answer_text, {}


def _missing_stock_code_result(
    intent: str,
    language: str,
) -> ToolResult:
    return ToolResult(
        success=False,
        message=_unavailable(language),
        data={"stock_code": ""},
        errors=["missing_stock_code"],
        tool_name=intent,
    )



def _load_llm_report_settings(
    api_key: str | None,
    base_url: str | None,
    model: str | None,
) -> tuple[str | None, str | None, str | None]:
    try:
        from local_config import load_local_config
        config = dict(load_local_config() or {})
    except Exception:
        config = {}
    return (
        str(api_key if api_key is not None else config.get("llm_api_key") or "").strip() or None,
        str(base_url if base_url is not None else config.get("llm_base_url") or "").strip() or None,
        str(model if model is not None else config.get("llm_model") or "").strip() or None,
    )


def _llm_first_report(
    *,
    query: str,
    draft_answer: str,
    result_dict: dict[str, Any],
    decomposition: dict[str, Any],
    orchestration: dict[str, Any],
    runtime_info: dict[str, Any],
    language: str,
    llm_api_key: str | None,
    llm_base_url: str | None,
    llm_model: str | None,
    llm_settings: LLMRuntimeSettings,
    context_bundle,
) -> str:
    result_data = result_dict.get("data") if isinstance(result_dict.get("data"), dict) else {}
    # Deterministic validation failures must keep their actionable remediation
    # wording.  They are not an LLM reporting task and must not be paraphrased
    # into a less precise execution instruction.
    if not bool(result_dict.get("success")):
        return draft_answer
    if result_dict.get("requires_confirmation") or result_data.get("plan_id"):
        return draft_answer
    diagnostics = decomposition.get("diagnostics") if isinstance(decomposition, dict) else {}
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    phase10 = diagnostics.get("phase10_goal_planning") if isinstance(diagnostics.get("phase10_goal_planning"), dict) else {}
    user_goal = phase10.get("semantic_goal") if isinstance(phase10.get("semantic_goal"), dict) else decomposition.get("user_goal") or {}
    completion = runtime_info.get("phase10_observe") if isinstance(runtime_info.get("phase10_observe"), dict) else {}
    if not user_goal:
        return draft_answer
    if llm_settings.mode == "api" and not llm_settings.api_key:
        return draft_answer
    try:
        return generate_report_with_llm(
            query=query,
            user_goal=dict(user_goal),
            result_summary={
                "success": bool(result_dict.get("success")),
                "message": str(result_dict.get("message") or "")[:2000],
                "data": result_dict.get("data") if isinstance(result_dict.get("data"), dict) else {},
                "warnings": list(result_dict.get("warnings") or []),
                "errors": list(result_dict.get("errors") or []),
                "tool_name": str(result_dict.get("tool_name") or ""),
                "orchestration_status": str(orchestration.get("execution_status") or ""),
            },
            completion=dict(completion),
            draft_answer=draft_answer,
            reply_language=language,
            llm_settings=llm_settings,
            context={
                "safe_context": build_reporter_context(
                    context_bundle,
                    user_goal=dict(user_goal),
                    result_summary={
                        "success": bool(result_dict.get("success")),
                        "message": str(result_dict.get("message") or "")[:2000],
                        "warnings": list(result_dict.get("warnings") or []),
                        "errors": list(result_dict.get("errors") or []),
                        "tool_name": str(result_dict.get("tool_name") or ""),
                    },
                    completion=dict(completion),
                )
            },
        )
    except Exception:
        return draft_answer


def _llm_first_semantic_critic(
    *,
    query: str,
    answer: str,
    result_dict: dict[str, Any],
    decomposition: dict[str, Any],
    runtime_info: dict[str, Any],
    language: str,
    llm_api_key: str | None,
    llm_base_url: str | None,
    llm_model: str | None,
    llm_settings: LLMRuntimeSettings,
) -> tuple[str, dict[str, Any]]:
    result_data = result_dict.get("data") if isinstance(result_dict.get("data"), dict) else {}
    if not bool(result_dict.get("success")):
        return answer, {"action": "skipped", "reason": "deterministic_failure_answer"}
    if result_dict.get("requires_confirmation") or result_data.get("plan_id"):
        return answer, {"action": "skipped", "reason": "pending_approval_deterministic_answer"}
    diagnostics = decomposition.get("diagnostics") if isinstance(decomposition, dict) else {}
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    phase10 = diagnostics.get("phase10_goal_planning") if isinstance(diagnostics.get("phase10_goal_planning"), dict) else {}
    user_goal = phase10.get("semantic_goal") if isinstance(phase10.get("semantic_goal"), dict) else decomposition.get("user_goal") or {}
    completion = runtime_info.get("phase10_observe") if isinstance(runtime_info.get("phase10_observe"), dict) else {}
    if not user_goal:
        return answer, {"action": "skipped", "reason": "missing_user_goal"}
    if llm_settings.mode == "api" and not llm_settings.api_key:
        return answer, {"action": "skipped", "reason": "missing_api_key"}
    try:
        review = critique_report_with_llm(
            query=query,
            user_goal=dict(user_goal),
            completion=dict(completion),
            answer=answer,
            result_summary={
                "success": bool(result_dict.get("success")),
                "message": str(result_dict.get("message") or "")[:2000],
                "warnings": list(result_dict.get("warnings") or []),
                "errors": list(result_dict.get("errors") or []),
                "tool_name": str(result_dict.get("tool_name") or ""),
            },
            reply_language=language,
            llm_settings=llm_settings,
        )
    except Exception as exc:
        return answer, {"action": "skipped", "reason": f"critic_failed:{type(exc).__name__}"}

    action = str(review.get("action") or "pass")
    if action == "revise" and str(review.get("revised_answer") or "").strip():
        return str(review.get("revised_answer") or "").strip(), review
    if action == "ask_user":
        question = str(review.get("clarification_question") or "").strip()
        if question:
            return f"{question}\n\n{_disclaimer(language)}", review
    if action == "block":
        message = str(review.get("block_message") or "").strip() or _unavailable(language)
        return f"{message}\n\n{_disclaimer(language)}", review
    return answer, review


def run_agent_request(
    query: str,
    user_id: str = "default",
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
    top_k: int = DEFAULT_TOOL_TOP_K,
    session_id: str = "",
    reply_language: str | None = None,
    llm_api_key: str | None = None,
    llm_base_url: str | None = None,
    llm_model: str | None = None,
    llm_settings: LLMRuntimeSettings | None = None,
    llm_mode: str | None = None,
    decomposition_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw_query = str(query or "").strip()
    active_llm = llm_settings or resolve_active_llm_settings(
        mode=llm_mode,
        api_key=llm_api_key,
        base_url=llm_base_url,
        model=llm_model,
    )
    # Preserve downstream execution variables; LLM stages receive isolated context views.
    # receive ``active_llm`` so the profile cannot change mid-run.
    llm_api_key = active_llm.api_key
    llm_base_url = active_llm.base_url
    llm_model = active_llm.model
    try:
        resolved_turn = resolve_conversation_turn(
            raw_query,
            user_id=user_id,
            conversation_id=session_id,
            db_path=str(db_path) if db_path is not None else None,
        )
    except Exception as exc:
        trace_exception("executor.conversation_state.resolve_failed", exc)
        resolved_turn = ResolvedTurn(
            raw_message=raw_query,
            resolved_message=raw_query,
            relation_type="new_goal",
            conversation_id=session_id,
            warnings=[f"conversation_state_resolve_failed:{type(exc).__name__}"],
            confidence=0.0,
        )

    planner_query = str(resolved_turn.resolved_message or "").strip() or raw_query
    decomposition_context = merge_planner_context(decomposition_context, resolved_turn)
    language = resolve_reply_language(raw_query, reply_language)
    decomposition: dict[str, Any] = {}
    orchestration: dict[str, Any] = {}
    expanded_tool_calls: list[dict[str, Any]] | None = None
    context_payload: dict[str, Any] = {}
    context_warnings: list[str] = []
    resume_run_id = _resume_run_id_for_confirmation(
        query=raw_query,
        user_id=user_id,
        output_dir=output_dir,
        db_path=db_path,
    )
    runtime = AgentRuntimeRecorder(
        user_id=user_id,
        goal=raw_query,
        db_path=db_path,
        session_id=session_id,
        run_id=resume_run_id or None,
    )
    formal_entry_audit = {
        "formal_entry_used": True,
        "formal_entry_name": "agent.executor.run_agent_request",
        "run_id": runtime.run_id,
        "conversation_id": session_id,
    }
    # The formal-entry assertion is created and persisted here, not supplied
    # by a benchmark runner.  It remains available even if later execution
    # exits through an error path.
    runtime.merge_metadata({"formal_entry_audit": formal_entry_audit})
    runtime.merge_metadata(
        {
            "llm_runtime_snapshot": {
                **active_llm.public_dict,
                "config_hash": active_llm.config_hash,
                "snapshot_created_at": now_text(),
            }
        }
    )
    benchmark_context = dict(decomposition_context or {})
    activate_llm_audit_context(
        run_id=runtime.run_id,
        conversation_id=session_id,
        output_dir=output_dir,
        case_id=str(benchmark_context.get("benchmark_case_id") or ""),
        iteration=benchmark_context.get("benchmark_iteration"),
        formal_entry_used=True,
        formal_entry_name="agent.executor.run_agent_request",
    )
    trace_event(
        "executor.request.received",
        {"query": raw_query, "resolved_query": planner_query if planner_query != raw_query else "", "relation_type": resolved_turn.relation_type, "user_id": user_id, "session_id": session_id, "top_k": top_k, "reply_language": language},
        run_id=runtime.run_id,
    )
    flow_event(
        "REQUEST",
        {
            "conversation_id": session_id,
            "user_id": user_id,
            "raw_message": raw_query,
            "resolved_message": planner_query if planner_query != raw_query else "",
            "relation_type": resolved_turn.relation_type,
            "language": language,
            "default_top_k": top_k,
            "next_step": "build passive Context Packet, then extract advisory rule hints and call LLM planner",
        },
        run_id=runtime.run_id,
    )
    flow_event(
        "TURN_RESOLUTION",
        {
            "relation_type": resolved_turn.relation_type,
            "raw_message": raw_query,
            "resolved_message": planner_query,
            "previous_user_goal": resolved_turn.previous_user_goal,
            "previous_result_summary": resolved_turn.previous_result_summary,
            "pending_clarification": resolved_turn.pending_clarification,
            "explicit_parameters": resolved_turn.explicit_parameters,
            "inherited_parameters": resolved_turn.inherited_parameters,
            "active_entities": resolved_turn.active_entities,
            "reference_turn_ids": resolved_turn.reference_turn_ids,
            "confidence": resolved_turn.confidence,
            "warnings": resolved_turn.warnings,
            "next_step": "build context and send the resolved turn to the planner",
        },
        run_id=runtime.run_id,
    )
    runtime_policy = RuntimePolicy.default()
    runtime_budget = RuntimeBudget(runtime_policy)
    runtime_circuit_registry = CircuitBreakerRegistry(runtime_policy)
    context_manager = ContextManager(db_path=db_path, output_dir=output_dir)
    phase12_context_bundle = context_manager.create_initial_context(
        user_id=user_id,
        query=planner_query,
        conversation_id=session_id,
        run_id=runtime.run_id,
        locale="zh-CN" if language == REPLY_LANGUAGE_ZH else "en-US",
        relation_type=resolved_turn.relation_type,
        task_type=_memory_task_hint(planner_query),
        entities=dict(resolved_turn.active_entities or {}),
        stock_codes=list(dict.fromkeys(re.findall(r"(?<!\d)(\d{6})(?!\d)", planner_query))),
        memory_candidate_top_n=40,
        memory_relevance_threshold=0.42,
        memory_token_budget=360,
        metadata={
            "source": "run_agent_request",
            "relation_type": resolved_turn.relation_type,
            "resolved_query_used": planner_query != raw_query,
        },
    )
    phase13_context_refs = context_ref_from_bundle(phase12_context_bundle)
    publish_agent_message(
        output_dir=output_dir,
        user_id=user_id,
        conversation_id=session_id,
        run_id=runtime.run_id,
        sender="ui",
        receiver="executor",
        message_type=MessageType.USER_REQUEST,
        payload={
            "query": raw_query[:1000],
            "resolved_query_used": planner_query != raw_query,
            "relation_type": resolved_turn.relation_type,
            "top_k": int(top_k or 50),
            "reply_language": language,
        },
        payload_schema="phase13.user_request.v1",
        context_refs=phase13_context_refs,
    )
    publish_agent_message(
        output_dir=output_dir,
        user_id=user_id,
        conversation_id=session_id,
        run_id=runtime.run_id,
        sender="context_manager",
        receiver="executor",
        message_type=MessageType.CONTEXT_CREATED,
        payload={
            "context_id": phase12_context_bundle.context_id,
            "locale": phase12_context_bundle.locale,
            "metadata": {"source": "run_agent_request"},
        },
        payload_schema="phase13.context_created.v1",
        context_refs=phase13_context_refs,
    )
    runtime.merge_metadata(
        {
            "runtime_policy": runtime_policy.to_dict(),
            "budget_usage": runtime_budget.to_dict(),
            "context_manager": {
                "context_id": phase12_context_bundle.context_id,
                "schema": "phase12_context_bundle",
            },
        }
    )

    def _guarded_tool(
        tool_name: str,
        operation,
        *,
        read_only: bool,
        token_estimate: int = 0,
    ) -> dict[str, Any]:
        value, metadata = execute_with_policy(
            operation,
            tool_name=tool_name,
            read_only=read_only,
            policy=runtime_policy,
            budget=runtime_budget,
            circuit_registry=runtime_circuit_registry,
            token_estimate=token_estimate,
        )
        runtime.merge_metadata(
            {
                "budget_usage": metadata.budget_usage,
                "circuit_states": runtime_circuit_registry.snapshot(),
            }
        )
        return _attach_runtime_reliability(value, metadata.to_dict())
    if not resume_run_id:
        runtime.transition_run(RUN_PLANNING, "request_received")
        _save_runtime_checkpoint(
            runtime,
            stage=RUN_PLANNING,
            pending_tasks=[{"intent": "route_agent_query", "query": sanitize_payload(planner_query, max_chars=300), "raw_query": sanitize_payload(raw_query, max_chars=300)}],
            references={"session_id": session_id},
        )
    else:
        runtime.merge_metadata(
            {
                "resumed_for_confirmation": {
                    "at": now_text(),
                    "query": sanitize_payload(str(query or ""), max_chars=300),
                }
            }
        )
    if is_language_setting_only(raw_query):
        intent = "set_reply_language"
        params = {"reply_language": language}
        runtime.transition_run(RUN_RUNNING, "hard_rule_language_setting")
        decomposition = {
            "query": raw_query,
            "route_layer": "hard_rule",
            "tasks": [{
                "task_id": "task_1",
                "intent": "set_reply_language",
                "parameters": {
                    "reply_language": language,
                },
                "depends_on": [],
                "reason": "用户明确切换回复语言",
                "confidence": 1.0,
                "capability_status": "executable",
            }],
            "is_multi_intent": False,
            "need_clarification": False,
            "clarification_question": "",
            "unsupported_reason": "",
            "confidence": 1.0,
            "warnings": [],
            "diagnostics": {
                "llm_used": False,
                "hard_rule_applied": True,
                "decision_source": "rule",
                "rule_hits": ["hard_safety"],
                "llm_planner_called": False,
            },
            "supervisor_decision": {
                "decision_source": "rule",
                "intent": "set_reply_language",
                "tasks": [{
                    "task_id": "task_1",
                    "intent": "set_reply_language",
                    "parameters": {
                        "reply_language": language,
                    },
                    "depends_on": [],
                    "reason": "用户明确切换回复语言",
                    "confidence": 1.0,
                    "capability_status": "executable",
                }],
                "agent_sequence": ["supervisor"],
                "dependencies": {"task_1": []},
                "requires_write": False,
                "confidence": 1.0,
                "reason": "硬安全规则命中",
                "safety_flags": ["hard_rule_applied"],
            },
        }
        result = ToolResult(
            success=True,
            message=_language_acknowledgement(language),
            data={"reply_language": language},
            tool_name="agent_executor",
        )
    else:
        route_context = dict(decomposition_context or {})
        route_context.setdefault("user_id", user_id)
        route_context.setdefault("session_id", session_id)
        route_context.setdefault("default_top_k", top_k)
        route_context.setdefault("candidate_redundancy_factor", DEFAULT_CANDIDATE_REDUNDANCY_FACTOR)
        route_context.setdefault("run_id", runtime.run_id)
        route_context.setdefault("query", raw_query)
        route_context.setdefault("resolved_query", planner_query)
        route_context.setdefault("relation_type", resolved_turn.relation_type)
        route_context.setdefault("llm_api_key", llm_api_key)
        route_context.setdefault("llm_base_url", llm_base_url)
        route_context.setdefault("llm_model", llm_model)
        route_context.setdefault("runtime_policy", runtime_policy.to_dict())
        route_context.setdefault("mcp", build_mcp_context_from_local_config())
        strategy_account_id = str(
            route_context.get("account_id") or f"paper_{user_id}"
        )
        try:
            strategy_conversation_context = StrategyContextService(
                db_path=db_path,
                output_dir=output_dir,
            ).load(
                user_id=user_id,
                account_id=strategy_account_id,
                conversation_id=session_id,
            )
            route_context.setdefault(
                "strategy_conversation_context",
                strategy_conversation_context.to_dict(),
            )
        except Exception as exc:
            trace_exception(
                "executor.strategy_context.failed",
                exc,
                run_id=runtime.run_id,
            )
            route_context.setdefault(
                "strategy_conversation_context",
                {
                    "user_id": user_id,
                    "account_id": strategy_account_id,
                    "conversation_id": session_id,
                    "context_error": type(exc).__name__,
                },
            )
        try:
            target_refs = TargetPortfolioStore(output_dir).list_refs(user_id=user_id, conversation_id=session_id)
        except Exception as exc:
            trace_exception("executor.target_portfolio_refs.failed", exc, run_id=runtime.run_id)
            target_refs = []
        route_context.setdefault("target_portfolio_refs", target_refs[:20])
        trace_event("executor.context.target_portfolio_refs", {"refs": target_refs[:20]}, run_id=runtime.run_id)
        route_context.setdefault("context_bundle", phase12_context_bundle.to_minimal_context())
        planner_context = build_planner_context(
            phase12_context_bundle,
            turn_context=route_context,
            target_portfolio_refs=target_refs,
            strategy_context=route_context.get("strategy_conversation_context")
            if isinstance(route_context.get("strategy_conversation_context"), dict)
            else {},
            default_top_k=top_k,
        )
        route_context["planner_context_ref"] = {
            "context_id": phase12_context_bundle.context_id,
            "memory_retrieval_id": phase12_context_bundle.memory_context.retrieval_id,
        }

        flow_event(
            "CONTEXT",
            {
                "context_id": phase12_context_bundle.context_id,
                "conversation_id": session_id,
                "context_sources": {
                    "context_bundle": True,
                    "legacy_compressed_agent_context": False,
                    "memory_retrieval_id": phase12_context_bundle.memory_context.retrieval_id,
                    "memory_candidate_count": phase12_context_bundle.memory_context.candidate_count,
                    "memory_selected_count": phase12_context_bundle.memory_context.selected_count,
                    "target_portfolio_refs": target_refs[:8],
                    "pending_approval": bool(phase12_context_bundle.approval_context.pending_plan_id),
                },
                "minimal_context": phase12_context_bundle.to_minimal_context(),
                "planner_context": planner_context,
                "next_step": "call LLM UserGoal/TaskPlan parser with stage-specific context",
            },
            run_id=runtime.run_id,
        )

        routed = route_agent_query(
            planner_query,
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            llm_model=llm_model,
            llm_settings=active_llm,
            reply_language=language,
            context=planner_context,
        )
        # Downstream tool adapters receive the already-resolved immutable
        # snapshot, never re-read the UI/local configuration mid-run.
        route_context["llm_runtime_settings"] = active_llm
        intent = routed.intent
        params = dict(routed.parameters)
        for inherited_key, inherited_value in (resolved_turn.inherited_parameters or {}).items():
            if params.get(inherited_key) in ("", None, [], {}):
                params[inherited_key] = inherited_value

        decomposition = dict(routed.decomposition)
        decomposition.setdefault("conversation_state", resolved_turn.to_dict())
        route_context["user_goal"] = dict(decomposition.get("user_goal") or {})
        route_context["task_plan"] = dict(decomposition.get("task_plan") or {})
        route_context["user_explicit_top_k"] = params.get("top_k")
        trace_event(
            "executor.route.accepted",
            {"intent": intent, "parameters": params, "execution_route": routed.execution_route, "decomposition": decomposition},
            run_id=runtime.run_id,
        )
        decomposition_diagnostics = (
            decomposition.get("diagnostics")
            if isinstance(decomposition.get("diagnostics"), dict)
            else {}
        )
        phase10_goal_planning = (
            decomposition_diagnostics.get("phase10_goal_planning")
            if isinstance(decomposition_diagnostics.get("phase10_goal_planning"), dict)
            else {}
        )
        planner_token_estimate = int(decomposition_diagnostics.get("llm_planner_token_estimate") or 0)
        if decomposition_diagnostics.get("llm_planner_called"):
            runtime_budget.record_llm_call(token_estimate=planner_token_estimate)
        route_metadata = {
                "supervisor_decision": decomposition.get("supervisor_decision") or {},
                "supervisor_planner": {
                    "decision_source": decomposition_diagnostics.get("decision_source"),
                    "rule_hits": decomposition_diagnostics.get("rule_hits") or [],
                    "llm_planner_called": bool(decomposition_diagnostics.get("llm_planner_called")),
                    "llm_planner_elapsed_ms": decomposition_diagnostics.get("llm_planner_elapsed_ms", 0.0),
                    "llm_planner_token_estimate": planner_token_estimate,
                    "fallback_used": bool(decomposition_diagnostics.get("fallback_used")),
                    "completeness_guard_triggered": bool(decomposition_diagnostics.get("completeness_guard_triggered")),
                    "auto_added_tasks": decomposition_diagnostics.get("auto_added_tasks") or [],
                    "denied_low_priority_rules": decomposition_diagnostics.get("denied_low_priority_rules") or [],
                    "mcp_candidate_view": decomposition_diagnostics.get("mcp_candidate_view") or {},
                },
                "budget_usage": runtime_budget.to_dict(),
        }
        if phase10_goal_planning:
            route_metadata["phase10_goal_planning"] = phase10_goal_planning
            route_metadata["user_goal"] = phase10_goal_planning.get("semantic_goal") or {}
            route_metadata["task_plan"] = phase10_goal_planning.get("task_plan") or {}
            route_metadata["plan_validation"] = phase10_goal_planning.get("plan_validation") or {}
            route_metadata["fast_path_selected"] = bool(phase10_goal_planning.get("fast_path_selected"))
            route_metadata["fast_path_reason"] = str(phase10_goal_planning.get("fast_path_reason") or "")
            route_metadata["decision_source"] = str(phase10_goal_planning.get("decision_source") or "")
        runtime.merge_metadata(route_metadata)
        tasks_for_message = [
            {
                "task_id": str(task.get("task_id") or ""),
                "intent": str(task.get("intent") or ""),
                "depends_on": list(task.get("depends_on") or []),
                "capability_status": str(task.get("capability_status") or ""),
            }
            for task in (decomposition.get("tasks") or [])
            if isinstance(task, dict)
        ]
        publish_agent_message(
            output_dir=output_dir,
            user_id=user_id,
            conversation_id=session_id,
            run_id=runtime.run_id,
            sender="planner",
            receiver="executor",
            message_type=MessageType.GOAL_PARSED,
            payload={
                "intent": intent,
                "route_layer": decomposition.get("route_layer"),
                "task_count": len(tasks_for_message),
                "requires_write": bool((decomposition.get("supervisor_decision") or {}).get("requires_write")),
                "decision_source": decomposition_diagnostics.get("decision_source"),
            },
            payload_schema="phase13.goal_parsed.v1",
            context_refs=phase13_context_refs,
        )
        publish_agent_message(
            output_dir=output_dir,
            user_id=user_id,
            conversation_id=session_id,
            run_id=runtime.run_id,
            sender="planner",
            receiver="executor",
            message_type=MessageType.TASK_PLANNED,
            payload={
                "tasks": tasks_for_message,
                "execution_mode": "multi_intent" if decomposition.get("is_multi_intent") else "single_intent",
            },
            payload_schema="phase13.task_planned.v1",
            context_refs=phase13_context_refs,
        )
        if intent == "confirm_execute" and resume_run_id:
            tasks = decomposition.get("tasks")
            if isinstance(tasks, list) and tasks:
                remapped = []
                for index, task in enumerate(tasks, start=1):
                    row = dict(task) if isinstance(task, dict) else {}
                    row["task_id"] = "task_confirm_execute" if index == 1 else f"task_confirm_execute_{index}"
                    remapped.append(row)
                decomposition["tasks"] = remapped
        stock_code = params.get("stock_code") or ""
        _save_runtime_checkpoint(
            runtime,
            stage=RUN_PLANNING,
            pending_tasks=[
                dict(task)
                for task in (decomposition.get("tasks") or [])
                if isinstance(task, dict)
            ],
            references={"intent": intent, "stock_code": stock_code},
            write_intent=intent in {"confirm_execute", "reject_execute", "one_time_position_operation", "preview_add_stock", "adjust_position", "capital_management", "backfill"},
        )

        goal_outputs = set(
            str(item) for item in ((decomposition.get("user_goal") or {}).get("expected_outputs") or [])
        )
        task_target_count = next(
            (
                (task.get("parameters") or {}).get("target_position_count")
                for task in (decomposition.get("tasks") or [])
                if isinstance(task, dict)
                and isinstance(task.get("parameters"), dict)
                and (task.get("parameters") or {}).get("target_position_count") not in (None, "")
            ),
            None,
        )
        is_target_design_request = "target_portfolio" in goal_outputs or any(
            str(task.get("intent") or "") in {
                "portfolio.design_target_portfolio",
                "portfolio.construct_target_portfolio",
            }
            for task in (decomposition.get("tasks") or [])
            if isinstance(task, dict)
        )
        target_position_count = params.get("target_position_count") or task_target_count
        if is_target_design_request and target_position_count in (None, ""):
            target_position_count = DEFAULT_TARGET_POSITION_COUNT
        if is_target_design_request:
            route_context["business_target_position_count"] = target_position_count
            requested_top_k = resolve_business_top_k(
                user_explicit_top_k=params.get("top_k"),
                target_position_count=target_position_count,
                candidate_redundancy_factor=route_context["candidate_redundancy_factor"],
                request_default_top_k=top_k,
                tool_default_top_k=DEFAULT_TOOL_TOP_K,
            )
        else:
            requested_top_k = resolve_requested_top_k(
                user_explicit_top_k=params.get("top_k"),
                request_default_top_k=top_k,
                tool_default_top_k=DEFAULT_TOOL_TOP_K,
            )

        def _registered_tool(
            tool_name: str,
            arguments: dict[str, Any] | None = None,
            *,
            agent_type: str = AGENT_READ,
            approval_granted: bool = False,
            token_estimate: int = 0,
        ) -> dict[str, Any]:
            payload = execute_tool_legacy_dict(
                tool_name,
                dict(arguments or {}),
                context={
                    "user_id": user_id,
                    "output_dir": output_dir,
                    "db_path": db_path,
                    "default_top_k": requested_top_k,
                    "session_id": session_id,
                    "run_id": runtime.run_id,
                    "conversation_id": session_id,
                    "token_estimate": token_estimate,
                    "query": planner_query,
                    "raw_query": raw_query,
                    "llm_runtime_settings": active_llm,
                    "llm_api_key": active_llm.api_key,
                    "llm_base_url": active_llm.base_url,
                    "llm_model": active_llm.model,
                    "root": ".",
                    "runtime_dir": str(
                        route_context.get("runtime_dir")
                        or (Path(output_dir).parent / "runtime")
                    ),
                },
                context_bundle=phase12_context_bundle,
                tool_context=context_manager.build_tool_context(phase12_context_bundle),
                agent_type=agent_type,
                approval_granted=approval_granted,
                policy=runtime_policy,
                budget=runtime_budget,
                circuit_registry=runtime_circuit_registry,
            )
            runtime_reliability = dict(payload.get("runtime_reliability") or {})
            runtime.merge_metadata(
                {
                    "budget_usage": runtime_reliability.get("budget_usage") or runtime_budget.to_dict(),
                    "circuit_states": runtime_circuit_registry.snapshot(),
                }
            )
            return payload

        try:
            if intent == "reject_execute" and runtime.status == RUN_WAITING_FOR_APPROVAL:
                runtime.transition_run(RUN_CANCELLED, "pending_plan_rejected_by_user")
                _save_runtime_checkpoint(
                    runtime,
                    stage=RUN_CANCELLED,
                    completed_steps=[],
                    pending_tasks=[],
                    references={"plan_id": params.get("plan_id")},
                    write_intent=True,
                )
            elif intent == "confirm_execute" and runtime.status == RUN_WAITING_FOR_APPROVAL:
                runtime.transition_run(RUN_REVALIDATING, "confirm_execute_revalidate")
                _save_runtime_checkpoint(
                    runtime,
                    stage=RUN_REVALIDATING,
                    completed_steps=[],
                    pending_tasks=[{"intent": "confirm_execute", "plan_id": params.get("plan_id")}],
                    references={"plan_id": params.get("plan_id")},
                    write_intent=True,
                )
            else:
                runtime.transition_run(RUN_RUNNING, f"execute_intent:{intent}")
                _save_runtime_checkpoint(
                    runtime,
                    stage=RUN_RUNNING,
                    pending_tasks=[
                        dict(task)
                        for task in (decomposition.get("tasks") or [])
                        if isinstance(task, dict)
                    ],
                    references={"intent": intent},
                    write_intent=intent
                    in {
                        "confirm_execute",
                        "reject_execute",
                        "one_time_position_operation",
                        "preview_add_stock",
                        "adjust_position",
                        "capital_management",
                        "backfill",
                    },
                )
                if intent == "confirm_execute":
                    runtime.transition_run(RUN_REVALIDATING, "confirm_execute_revalidate")
                    _save_runtime_checkpoint(
                        runtime,
                        stage=RUN_REVALIDATING,
                        pending_tasks=[{"intent": "confirm_execute", "plan_id": params.get("plan_id")}],
                        references={"plan_id": params.get("plan_id")},
                        write_intent=True,
                    )
            if intent == "llm_insufficient_balance":
                result = ToolResult(
                    success=False,
                    message=_llm_insufficient_balance_message(
                        language
                    ),
                    data={
                        "decomposition_only": True,
                        "retryable": True,
                        "error_code": "insufficient_balance",
                        "suggested_actions": [
                            "recharge_account",
                            "replace_api_key",
                            "switch_model",
                        ],
                    },
                    errors=["llm_insufficient_balance"],
                    tool_name="intent_decomposition",
                )

            elif intent == "clarification_required":
                question = str(
                    decomposition.get(
                        "clarification_question"
                    )
                    or _unavailable(language)
                )
                result = ToolResult(
                    success=True,
                    message=question,
                    data={
                        "decomposition_only": True,
                        "need_clarification": True,
                    },
                    tool_name="intent_decomposition",
                )

            elif intent == "multi_intent":
                if is_read_only_multi_agent_candidate(decomposition):
                    trace_event(
                        "executor.multi_intent.phase17_handoff",
                        {"tasks": decomposition.get("tasks") or [], "task_plan": decomposition.get("task_plan") or {}},
                        run_id=runtime.run_id,
                    )
                    orchestration = _execute_readonly_multi_agent_collaboration(
                        query=query,
                        decomposition=decomposition,
                        user_id=user_id,
                        output_dir=output_dir,
                        db_path=db_path,
                        default_top_k=requested_top_k,
                        session_id=session_id,
                        run_id=runtime.run_id,
                        language=language,
                        context=route_context,
                    )
                else:
                    trace_event(
                        "executor.multi_intent.exact_dag",
                        {"tasks": decomposition.get("tasks") or [], "task_plan": decomposition.get("task_plan") or {}},
                        run_id=runtime.run_id,
                    )
                    orchestration = execute_multi_intent_plan(
                        decomposition,
                        user_id=user_id,
                        output_dir=output_dir,
                        db_path=db_path,
                        default_top_k=requested_top_k,
                        session_id=session_id,
                        language=language,
                        context=route_context,
                    )
                expanded_tool_calls = list(
                    orchestration.get("tool_calls") or []
                )
                result = ToolResult(
                    success=bool(
                        orchestration.get("success")
                    ),
                    message=_multi_intent_public_message(
                        orchestration,
                        language,
                    ),
                    data=orchestration,
                    warnings=list(
                        orchestration.get("warnings") or []
                    ),
                    errors=list(
                        orchestration.get("errors") or []
                    ),
                    tool_name="multi_intent_executor",
                )

            elif intent in {
                "known_not_integrated",
                "unsupported",
            }:
                unsupported_message = str(
                    decomposition.get("unsupported_reason")
                    or _unavailable(language)
                )
                result = ToolResult(
                    success=False,
                    message=unsupported_message,
                    data={
                        "decomposition_only": True,
                        "execution_deferred": True,
                        "business_rule_fallback_used": False,
                    },
                    errors=[intent],
                    tool_name="intent_decomposition",
                )

            elif (
                intent in _STOCK_CODE_REQUIRED_INTENTS
                and not stock_code
            ):
                result = _missing_stock_code_result(
                    intent,
                    language,
                )

            elif intent == "ranking":
                result = _registered_tool(
                    "ranking",
                    {"top_k": requested_top_k},
                    token_estimate=requested_top_k * 20,
                )
                if not bool(result.get("success")):
                    result["message"] = _unavailable(language)

            elif intent in {"stock_lookup", "classic_stock_score"}:
                result = _registered_tool(
                    intent,
                    {
                        "user_id": user_id,
                        "stock_query": stock_code or params.get("stock_query") or query,
                    },
                    token_estimate=300,
                )

            elif intent == "classic_ranking":
                result = _registered_tool(
                    "classic_ranking",
                    {"user_id": user_id, "sort_by": params.get("sort_by") or "original_rank"},
                    token_estimate=requested_top_k * 25,
                )

            elif intent == "portfolio_state":
                result = _registered_tool(
                    "portfolio_state",
                    {"user_id": user_id},
                    token_estimate=400,
                )

            elif intent == "user_profile":
                result = _registered_tool(
                    "user_profile",
                    {"user_id": user_id},
                    token_estimate=300,
                )

            elif intent == "portfolio_risk":
                result = _registered_tool(
                    "portfolio_risk",
                    {"user_id": user_id},
                    token_estimate=600,
                )

            elif intent == "stock_analysis":
                result = _registered_tool(
                    "stock_analysis",
                    {"user_id": user_id, "stock_code": stock_code, "top_k": requested_top_k},
                    token_estimate=800,
                )

            elif intent == "stock_news":
                result = _registered_tool(
                    "stock_news",
                    {"stock_code": stock_code},
                    token_estimate=800,
                )

            elif intent == "stock_rag":
                result = _registered_tool(
                    "stock_rag",
                    {"stock_code": stock_code, "query": query, "top_k": min(requested_top_k, 10)},
                    token_estimate=1200,
                )

            elif intent in {
                "portfolio.design_target_portfolio",
                "portfolio.construct_target_portfolio",
                "portfolio.load_target_portfolio",
                "portfolio.compare_portfolios",
            }:
                result = _registered_tool(
                    intent,
                    params,
                    token_estimate=1200,
                )

            elif intent == "position_recommendation":
                result = _registered_tool(
                    "position_recommendation",
                    {
                        "user_id": user_id,
                        "stock_code": stock_code,
                        "requested_weight": params.get("requested_weight"),
                        "top_k": requested_top_k,
                    },
                    token_estimate=800,
                )

            elif intent == "replacement_recommendation":
                result = _registered_tool(
                    "replacement_recommendation",
                    {
                        "user_id": user_id,
                        "stock_code": stock_code,
                        "requested_weight": params.get("requested_weight") or 0.05,
                    },
                    token_estimate=1000,
                )

            elif intent == "one_time_position_operation":
                (result_dict, orchestration), workflow_metadata = execute_with_policy(
                    lambda: _execute_position_approval_multi_agent_workflow(
                        query=query,
                        params=params,
                        user_id=user_id,
                        output_dir=output_dir,
                        db_path=db_path,
                        default_top_k=requested_top_k,
                        session_id=session_id,
                        run_id=runtime.run_id,
                        language=language,
                        context=route_context,
                    ),
                    tool_name="one_time_position_operation",
                    read_only=False,
                    policy=runtime_policy,
                    budget=runtime_budget,
                    circuit_registry=runtime_circuit_registry,
                    token_estimate=1000,
                )
                result_dict = dict(result_dict or {})
                result_dict["runtime_reliability"] = workflow_metadata.to_dict()
                runtime.merge_metadata(
                    {
                        "budget_usage": workflow_metadata.budget_usage,
                        "circuit_states": runtime_circuit_registry.snapshot(),
                    }
                )
                result = _attach_runtime_reliability(
                    ToolResult(
                        success=bool(result_dict.get("success")),
                        message=str(result_dict.get("message") or ""),
                        data=dict(result_dict.get("data") or {}),
                        warnings=list(result_dict.get("warnings") or []),
                        errors=list(result_dict.get("errors") or []),
                        permission=str(result_dict.get("permission") or "preview"),
                        tool_name=str(result_dict.get("tool_name") or "manual_position_operation_tool"),
                        requires_confirmation=bool(result_dict.get("requires_confirmation")),
                        confirmation_token=result_dict.get("confirmation_token"),
                    ),
                    workflow_metadata.to_dict(),
                )
                expanded_tool_calls = list(orchestration.get("tool_calls") or [])

            elif intent == "strategy_change":
                conversation_action = str(
                    params.get("conversation_action") or ""
                )
                if not conversation_action:
                    route_layer = str(
                        decomposition.get("route_layer") or ""
                    )
                    conversation_action = (
                        "llm_unavailable"
                        if route_layer in {"rule_fallback", "fallback"}
                        else "save_proposal"
                    )
                draft_result = _registered_tool(
                    "strategy.save_proposal_draft",
                    {
                        "user_id": user_id,
                        "account_id": strategy_account_id,
                        "conversation_id": session_id,
                        "conversation_action": conversation_action,
                        "proposal_id": str(params.get("proposal_id") or ""),
                        "proposal_json": (
                            dict(params.get("proposal_json") or {})
                            if isinstance(params.get("proposal_json"), dict)
                            else {}
                        ),
                        "original_request": str(
                            params.get("original_request") or raw_query
                        ),
                        "user_feedback": str(
                            params.get("user_feedback") or raw_query
                        ),
                        "change_summary": str(
                            params.get("change_summary") or ""
                        ),
                        "base_strategy_id": str(
                            params.get("base_strategy_id")
                            or "hierarchical_top10"
                        ),
                        "base_strategy_version": str(
                            params.get("base_strategy_version") or "1.0.0"
                        ),
                        "source_run_id": runtime.run_id,
                    },
                    agent_type=AGENT_MAIN,
                    token_estimate=800,
                )
                result = draft_result
                if (
                    conversation_action == "prepare_implementation"
                    and draft_result.get("success")
                ):
                    draft_data = (
                        dict(draft_result.get("data") or {})
                        if isinstance(draft_result.get("data"), dict)
                        else {}
                    )
                    proposal_data = dict(draft_data.get("proposal") or {})
                    version_data = dict(
                        draft_data.get("proposal_version") or {}
                    )
                    locked_version = int(
                        version_data.get("version")
                        or proposal_data.get("current_version")
                        or params.get("proposal_version")
                        or 0
                    )
                    result = _registered_tool(
                        "strategy.prepare_implementation",
                        {
                            "proposal_id": str(
                                proposal_data.get("proposal_id")
                                or params.get("proposal_id")
                                or ""
                            ),
                            "proposal_version": locked_version,
                            "user_id": user_id,
                            "account_id": strategy_account_id,
                            "conversation_id": session_id,
                            "run_id": runtime.run_id,
                        },
                        agent_type=AGENT_MAIN,
                        token_estimate=1200,
                    )
                    if (
                        result.get("success")
                        and isinstance(result.get("data"), dict)
                    ):
                        result["data"]["proposal_draft"] = draft_data
                        implementation_data = dict(result["data"])
                        apply_plan = _registered_tool(
                            "strategy.create_apply_plan",
                            {
                                "implementation_id": str(
                                    implementation_data.get(
                                        "implementation_id"
                                    )
                                    or ""
                                ),
                                "user_id": user_id,
                                "account_id": strategy_account_id,
                                "conversation_id": session_id,
                                "run_id": runtime.run_id,
                            },
                            agent_type=AGENT_MAIN,
                            token_estimate=600,
                        )
                        if apply_plan.get("success"):
                            apply_data = dict(
                                apply_plan.get("data") or {}
                            )
                            apply_data["implementation_preview"] = (
                                implementation_data
                            )
                            apply_data["proposal_draft"] = draft_data
                            apply_plan["data"] = apply_data
                            result = apply_plan

            elif intent == "preview_add_stock":
                result = _registered_tool(
                    "portfolio.preview_paper_trade",
                    {
                        "user_id": user_id,
                        "stock_code": stock_code,
                        "requested_weight": params.get("requested_weight"),
                        "top_k": requested_top_k,
                    },
                    agent_type=AGENT_MAIN,
                    token_estimate=800,
                )

            elif intent == "adjust_position":
                result = _registered_tool(
                    "portfolio.preview_adjust_position",
                    {
                        "user_id": user_id,
                        "stock_code": stock_code,
                        "requested_weight": params.get("requested_weight"),
                        "position_adjustment_ratio": params.get("position_adjustment_ratio"),
                        "requested_quantity": params.get("requested_quantity"),
                        "top_k": requested_top_k,
                    },
                    agent_type=AGENT_MAIN,
                    token_estimate=800,
                )

            elif intent == "confirm_execute":
                result = execute_confirmed_plan_v2(
                    params.get("plan_id") or "",
                    params.get("confirmation_token") or "",
                    user_id,
                    conversation_id=session_id,
                    run_id=runtime.run_id,
                    output_dir=output_dir,
                    db_path=db_path,
                ).to_legacy_dict()
                if bool(result.get("success")):
                    runtime.transition_run(RUN_COMMITTING, "confirmed_plan_committing")

            elif intent == "reject_execute":
                rejected, rejection_status, rejected_plan = reject_confirmation_plan(
                    user_id,
                    params.get("plan_id") or "",
                    output_dir=output_dir,
                    db_path=db_path,
                )
                result = ToolResult(
                    success=rejected,
                    message=(
                        "待确认计划已拒绝，模拟盘未发生任何提交。"
                        if rejected
                        else f"计划拒绝失败：{rejection_status}"
                    ),
                    data={
                        "plan_id": params.get("plan_id") or "",
                        "confirmation_status": rejection_status,
                        "execution_status": (rejected_plan or {}).get("execution_status"),
                    },
                    errors=[] if rejected else [rejection_status],
                    permission=ToolPermission.WRITE,
                    tool_name="approval.reject_plan",
                )

            elif intent == "capital_management":
                result = _guarded_tool(
                    "capital_management",
                    lambda: preview_capital_change(
                        user_id,
                        params.get("flow_type") or "deposit",
                        params.get("amount") or 0.0,
                        params.get("effective_date") or "",
                        output_dir=output_dir,
                        db_path=db_path,
                        session_id=session_id,
                    ),
                    read_only=False,
                    token_estimate=500,
                )

            elif intent == "scheduler_status":
                result = _registered_tool(
                    "scheduler_status",
                    {},
                    agent_type=AGENT_MAIN,
                    token_estimate=400,
                )

            elif intent == "python_sandbox_analysis":
                result = _registered_tool(
                    "python_sandbox_analysis",
                    {
                        "code": params.get("code") or "",
                        "snapshot": params.get("snapshot") or {},
                        "snapshot_id": params.get("snapshot_id") or "",
                        "timeout_seconds": params.get("timeout_seconds") or 5.0,
                        "max_output_chars": params.get("max_output_chars") or 4000,
                    },
                    agent_type=AGENT_MAIN,
                    token_estimate=500,
                )

            elif intent == "backfill":
                result = _guarded_tool(
                    "backfill",
                    lambda: preview_backfill(
                        user_id,
                        params.get("start_date") or "",
                        end_date=params.get(
                            "end_date"
                        ) or "latest",
                        output_dir=output_dir,
                        db_path=db_path,
                        session_id=session_id,
                    ),
                    read_only=False,
                    token_estimate=600,
                )

            elif intent in {"report", "report_latest"}:
                result = _registered_tool(
                    intent,
                    {},
                    token_estimate=700,
                )

            elif intent == "empty":
                result = ToolResult(
                    False,
                    _unavailable(language),
                    tool_name="agent_executor",
                )

            else:
                result = ToolResult(
                    True,
                    _general_help_answer(language),
                    data={
                        "available_examples": [
                            "查看最新预测排名前十",
                            "查看当前模拟盘账户和持仓",
                            "分析 600519",
                            "今天把 600519 加入模拟盘 5%",
                            "以后只持有模型排名前 5 的股票",
                            "后台任务状态",
                        ]
                    },
                    tool_name="agent_executor",
                )

        except Exception as exc:
            try:
                runtime.transition_run(RUN_FAILED, f"{type(exc).__name__}:{exc}")
            except Exception:
                pass
            write_agent_tool_call_log(
                user_id,
                tool_name=intent,
                tool_input={"query": query, **params},
                tool_output_summary={},
                status="error",
                error_message=(
                    f"{type(exc).__name__}: {exc}"
                ),
                session_id=session_id,
                output_dir=output_dir,
                db_path=db_path,
            )
            result_dict = {
                "success": False,
                "errors": [str(exc)],
                "error_type": type(exc).__name__,
                "message": str(exc),
                "tool_name": intent,
                "runtime_reliability": dict(getattr(exc, "runtime_metadata", {}) or {}),
            }
            try:
                _record_runtime_for_result(
                    runtime,
                    intent=intent,
                    params=params,
                    decomposition=decomposition,
                    orchestration=orchestration,
                    result_dict=result_dict,
                    expanded_tool_calls=[{"tool_name": intent, "success": False}],
                    output_dir=output_dir,
                    user_id=user_id,
                    llm_settings=active_llm,
                )
            except Exception:
                pass
            return {
                "success": False,
                "run_id": runtime.run_id,
                "formal_entry_audit": formal_entry_audit,
                "runtime": {"run_id": runtime.run_id, "status": runtime.status},
                "intent": intent,
                "parameters": _public_agent_parameters(params),
                "original_query": raw_query,
                "resolved_query": planner_query if planner_query != raw_query else "",
                "conversation_state": resolved_turn.to_dict(),
                "reply_language": language,
                "decomposition": decomposition,
                "orchestration": orchestration,
                "routing_layer": decomposition.get(
                    "route_layer",
                    "unknown",
                ),
                "answer": (
                    f"{_unavailable(language)}\n\n"
                    f"{_disclaimer(language)}"
                ),
                "result": result_dict,
                "tool_calls": [{
                    "tool_name": intent,
                    "success": False,
                }],
                "context": context_payload,
                "context_warnings": list(dict.fromkeys(context_warnings)),
            }

    result_dict = _tool_result_dict(result)
    initial_integrity = _logic_integrity_for_execution(
        intent=intent,
        decomposition=decomposition,
        orchestration=orchestration,
        result_dict=result_dict,
    )
    orchestration = {
        **dict(orchestration or {}),
        "logic_integrity": initial_integrity.to_dict(),
    }
    if initial_integrity.is_logic_error:
        result_dict = _feature_unavailable_result(
            intent=intent,
            integrity=initial_integrity,
            language=language,
            previous=result_dict,
        )
        orchestration["execution_status"] = "feature_unavailable"
    flow_event(
        "TASK_RESULT",
        {
            "execution_scope": "aggregate" if intent == "multi_intent" else "single_task",
            "intent": intent,
            "success": bool(result_dict.get("success")),
            "tool_name": str(result_dict.get("tool_name") or intent),
            "message": str(result_dict.get("message") or ""),
            "produced_output_keys": sorted((result_dict.get("data") or {}).keys()) if isinstance(result_dict.get("data"), dict) else [],
            "produced_outputs": result_dict.get("data") if isinstance(result_dict.get("data"), dict) else {},
            "warnings": list(result_dict.get("warnings") or []),
            "errors": list(result_dict.get("errors") or []),
            "orchestration_status": orchestration.get("execution_status") if isinstance(orchestration, dict) else "",
        },
        run_id=runtime.run_id,
        level="INFO" if result_dict.get("success") else "WARNING",
    )
    phase17_handoff_summary = orchestration.get("phase17_handoff") if isinstance(orchestration, dict) else None
    if isinstance(phase17_handoff_summary, dict) and phase17_handoff_summary.get("handoff_available"):
        handoff_refs = [
            dict(item)
            for item in (phase17_handoff_summary.get("handoff_refs") or [])
            if isinstance(item, dict)
        ]
        role_summaries = [
            dict(item)
            for item in (phase17_handoff_summary.get("handoff_role_summaries") or [])
            if isinstance(item, dict)
        ]
        try:
            phase12_context_bundle.runtime_context.handoff_refs = handoff_refs
            phase12_context_bundle.runtime_context.latest_handoff_trace_id = str(
                phase17_handoff_summary.get("trace_id") or ""
            )
            phase12_context_bundle.runtime_context.handoff_role_summaries = role_summaries
        except Exception as exc:
            context_warnings.append(f"phase17_handoff_context_failed:{type(exc).__name__}")
        context_payload["phase17_handoff"] = {
            "handoff_available": True,
            "trace_id": str(phase17_handoff_summary.get("trace_id") or ""),
            "handoff_count": int(phase17_handoff_summary.get("handoff_count") or 0),
            "roles_used": list(phase17_handoff_summary.get("roles_used") or []),
            "latest_handoff_status": str(phase17_handoff_summary.get("latest_handoff_status") or ""),
            "blocked_handoff_count": int(phase17_handoff_summary.get("blocked_handoff_count") or 0),
            "handoff_refs": handoff_refs,
            "handoff_role_summaries": role_summaries,
            "safety": dict(phase17_handoff_summary.get("safety") or {}),
        }
        runtime.merge_metadata({"phase17_handoff": context_payload["phase17_handoff"]})
    try:
        context_manager.update_from_tool_result(phase12_context_bundle, result_dict)
        context_payload["phase12_context"] = {
            "context_id": phase12_context_bundle.context_id,
            "llm_context": context_manager.build_llm_context(phase12_context_bundle, max_tokens=900),
            "minimal_context": phase12_context_bundle.to_minimal_context(),
        }
        context_manager.save_snapshot(phase12_context_bundle)
    except Exception as exc:
        context_warnings.append(f"phase12_context_update_failed:{type(exc).__name__}")
    if intent == "confirm_execute":
        plan_id_for_metadata = str((result_dict.get("data") or {}).get("plan_id") or params.get("plan_id") or "")
        runtime.merge_metadata(
            {
                "approval_closure": _confirmation_runtime_metadata(
                    db_path=db_path,
                    plan_id=plan_id_for_metadata,
                    result_dict=result_dict,
                )
            }
        )
    diagnostics_for_completion = (
        decomposition.get("diagnostics")
        if isinstance(decomposition.get("diagnostics"), dict)
        else {}
    )
    phase10_for_completion = (
        diagnostics_for_completion.get("phase10_goal_planning")
        if isinstance(diagnostics_for_completion.get("phase10_goal_planning"), dict)
        else {}
    )
    semantic_goal_for_completion = (
        phase10_for_completion.get("semantic_goal")
        if isinstance(phase10_for_completion.get("semantic_goal"), dict)
        else decomposition.get("user_goal") or {}
    )
    if semantic_goal_for_completion:
        if initial_integrity.is_logic_error:
            result_dict["llm_completion"] = terminal_completion_payload(initial_integrity)
        else:
            result_dict["llm_completion"] = observe_goal_completion(
                semantic_goal_for_completion,
                {
                    "task_plan": phase10_for_completion.get("task_plan") or decomposition.get("task_plan") or {},
                    "task_results": orchestration.get("task_results") if isinstance(orchestration, dict) else {},
                    "result": result_dict,
                    "orchestration_status": orchestration.get("execution_status") if isinstance(orchestration, dict) else "",
                },
                api_key=llm_api_key,
                base_url=llm_base_url,
                model=llm_model,
                llm_settings=active_llm,
                context={
                    "safe_context": build_observer_context(
                        phase12_context_bundle,
                        user_goal=semantic_goal_for_completion,
                        task_plan=phase10_for_completion.get("task_plan") or decomposition.get("task_plan") or {},
                        result=result_dict,
                        orchestration=orchestration,
                    ),
                    "run_id": runtime.run_id,
                },
            ).to_dict()
        trace_event("executor.completion.assessed", result_dict["llm_completion"], run_id=runtime.run_id)
        if not isinstance(orchestration.get("task_results"), dict):
            task_id = (
                str((decomposition.get("tasks") or [{}])[0].get("task_id") or intent)
                if isinstance(decomposition.get("tasks"), list)
                else str(intent)
            )
            orchestration = {
                **dict(orchestration or {}),
                "task_results": {
                    task_id: {
                        "task_id": task_id,
                        "intent": intent,
                        "success": bool(result_dict.get("success")),
                        "data": dict(result_dict.get("data") or {}),
                        "arguments": dict(params or {}),
                        "errors": list(result_dict.get("errors") or []),
                    }
                },
                "replan_count": int(orchestration.get("replan_count") or 0),
                "replan_audit": list(orchestration.get("replan_audit") or []),
            }
        orchestration, result_dict, completion_replan = _consume_post_execution_replan(
            source="completion",
            action=result_dict["llm_completion"].get("next_action"),
            completion=result_dict["llm_completion"],
            reflection=None,
            orchestration=orchestration,
            result_dict=result_dict,
            user_goal=semantic_goal_for_completion,
            user_id=user_id,
            output_dir=output_dir,
            db_path=db_path,
            default_top_k=requested_top_k,
            session_id=session_id,
            language=language,
            context=route_context,
        )
        if completion_replan.get("execution"):
            result_dict["llm_completion"] = observe_goal_completion(
                semantic_goal_for_completion,
                {
                    "task_plan": phase10_for_completion.get("task_plan") or decomposition.get("task_plan") or {},
                    "task_results": orchestration.get("task_results") or {},
                    "result": result_dict,
                    "orchestration_status": orchestration.get("execution_status") or "",
                },
                api_key=llm_api_key,
                base_url=llm_base_url,
                model=llm_model,
                llm_settings=active_llm,
                context={
                    "safe_context": build_observer_context(
                        phase12_context_bundle,
                        user_goal=semantic_goal_for_completion,
                        task_plan=phase10_for_completion.get("task_plan") or decomposition.get("task_plan") or {},
                        result=result_dict,
                        orchestration=orchestration,
                    ),
                    "run_id": runtime.run_id,
                },
            ).to_dict()
            trace_event("executor.completion.reassessed_after_replan", result_dict["llm_completion"], run_id=runtime.run_id)

    try:
        record_executor_result_observation(
            result_dict,
            output_dir=output_dir,
            user_id=user_id,
            llm_settings=active_llm,
            conversation_id=session_id,
            run_id=runtime.run_id,
            task_id=str((decomposition.get("tasks") or [{}])[0].get("task_id") or intent)
            if isinstance(decomposition.get("tasks"), list)
            else intent,
            context_bundle=phase12_context_bundle,
        )
        context_payload["phase12_context"] = {
            "context_id": phase12_context_bundle.context_id,
            "llm_context": context_manager.build_llm_context(phase12_context_bundle, max_tokens=900),
            "minimal_context": phase12_context_bundle.to_minimal_context(),
        }
    except Exception as exc:
        context_warnings.append(f"phase15_observation_failed:{type(exc).__name__}")

    write_agent_tool_call_log(
        user_id,
        tool_name=str(
            result_dict.get("tool_name") or intent
        ),
        tool_input={"query": query, **params},
        tool_output_summary={
            "success": result_dict.get("success"),
            "message": result_dict.get("message"),
            "reply_language": language,
            "routing_layer": decomposition.get(
                "route_layer",
                "unknown",
            ),
            "task_count": len(
                decomposition.get("tasks") or []
            ),
            "orchestration_status": orchestration.get(
                "execution_status",
                "",
            ),
        },
        status=(
            "success"
            if result_dict.get("success")
            else "failed"
        ),
        session_id=session_id,
        output_dir=output_dir,
        db_path=db_path,
    )

    if expanded_tool_calls is None:
        expanded_tool_calls = [{
            "tool_name": (
                result_dict.get("tool_name") or intent
            ),
            "success": result_dict.get("success"),
        }]

    try:
        if runtime.status == RUN_RUNNING:
            runtime.transition_run(RUN_OBSERVING, "tool_execution_observed")
        runtime_info = _record_runtime_for_result(
            runtime,
            intent=intent,
            params=params,
            decomposition=decomposition,
            orchestration=orchestration,
            result_dict=result_dict,
            expanded_tool_calls=expanded_tool_calls,
            output_dir=output_dir,
            user_id=user_id,
        )
        if intent == "confirm_execute" and resume_run_id:
            _record_confirmation_report_step(
                runtime,
                result_dict=result_dict,
                plan_id=str((result_dict.get("data") or {}).get("plan_id") or params.get("plan_id") or ""),
            )
        data = result_dict.get("data") if isinstance(result_dict.get("data"), dict) else {}
        requires_approval = bool(
            result_dict.get("requires_confirmation")
            or (isinstance(data, dict) and data.get("plan_id") and intent != "confirm_execute")
        )
        execution_status = str(orchestration.get("execution_status") or "")
        if runtime.status == RUN_COMMITTING:
            runtime.transition_run(
                RUN_COMPLETED if result_dict.get("success") else RUN_FAILED,
                "confirmed_execution_finished",
            )
        elif runtime.status == RUN_REVALIDATING:
            runtime.transition_run(RUN_FAILED, "confirmation_revalidation_failed")
        elif requires_approval and result_dict.get("success"):
            if runtime.status == RUN_OBSERVING:
                runtime.transition_run(RUN_WAITING_FOR_APPROVAL, "proposal_waiting_for_user_confirmation")
                _save_runtime_checkpoint(
                    runtime,
                    stage=RUN_WAITING_FOR_APPROVAL,
                    completed_steps=[
                        str(task.get("task_id") or "")
                        for task in (decomposition.get("tasks") or [])
                        if isinstance(task, dict) and task.get("task_id")
                    ],
                    pending_tasks=[
                        {
                            "intent": "confirm_execute",
                            "plan_id": (data or {}).get("plan_id"),
                        }
                    ],
                    references={
                        "intent": intent,
                        "attached_plan_ids": runtime_info.get("attached_plan_ids") or [],
                    },
                    write_intent=True,
                )
        elif execution_status == "partially_completed":
            runtime.transition_run(
                RUN_PARTIALLY_COMPLETED,
                str((result_dict.get("llm_completion") or {}).get("status") or "partially_completed"),
            )
        elif result_dict.get("success"):
            completion_status = str((result_dict.get("llm_completion") or {}).get("status") or "").lower()
            is_partial = completion_status in {"partial", "missing", "conflict", "invalid", "unknown"}
            runtime.transition_run(
                RUN_PARTIALLY_COMPLETED if is_partial else RUN_COMPLETED,
                completion_status or execution_status or "request_completed",
            )
        else:
            runtime.transition_run(RUN_FAILED, "request_failed")
        runtime_info["status"] = runtime.status
    except Exception as runtime_exc:
        runtime_info = {
            "run_id": runtime.run_id,
            "status": runtime.status,
            "error": f"{type(runtime_exc).__name__}: {runtime_exc}",
        }

    answer_text = _answer(
        intent,
        result_dict,
        language,
    )
    trace_event("executor.report.draft", {"intent": intent, "draft": _answer(intent, result_dict, language)}, run_id=runtime.run_id)
    terminal_before_report = is_terminal_agent_state(initial_integrity) or is_terminal_agent_state(result_dict.get("data"))
    if terminal_before_report:
        answer_text = str(result_dict.get("message") or answer_text)
        llm_semantic_critic = {
            "status": "suppressed",
            "reason": "terminal_priority_logic_error",
            "safe_to_continue": False,
        }
    else:
        answer_text = _llm_first_report(
            query=query,
            draft_answer=answer_text,
            result_dict=result_dict,
            decomposition=decomposition,
            orchestration=orchestration,
            runtime_info=runtime_info,
            language=language,
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            llm_model=llm_model,
            llm_settings=active_llm,
            context_bundle=phase12_context_bundle,
        )
        answer_text, llm_semantic_critic = _llm_first_semantic_critic(
            query=query,
            answer=answer_text,
            result_dict=result_dict,
            decomposition=decomposition,
            runtime_info=runtime_info,
            language=language,
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            llm_model=llm_model,
            llm_settings=active_llm,
        )
    answer_text = _sanitize_user_facing_answer(answer_text, language)
    runtime_info["llm_semantic_critic"] = llm_semantic_critic
    trace_event("executor.semantic_critic.result", llm_semantic_critic, run_id=runtime.run_id)
    final_artifact_refs = artifact_refs_from_result(result_dict)
    final_approval_refs = approval_refs_from_payload(result_dict.get("data") if isinstance(result_dict.get("data"), dict) else {})
    final_task_id = (
        str((decomposition.get("tasks") or [{}])[0].get("task_id") or intent)
        if isinstance(decomposition.get("tasks"), list)
        else str(intent)
    )
    if terminal_before_report:
        reflection_payload = terminal_critic_payload(initial_integrity)
    else:
        answer_text, reflection_payload = _run_phase16_reflection(
            answer_text=answer_text,
            result_dict=result_dict,
            intent=intent,
            language=language,
            output_dir=output_dir,
            user_id=user_id,
            session_id=session_id,
            run_id=runtime.run_id,
            task_id=final_task_id,
            context_refs=phase13_context_refs,
            artifact_refs=final_artifact_refs,
            approval_refs=final_approval_refs,
            context_payload=context_payload,
            context_warnings=context_warnings,
            runtime=runtime,
        )
    if str(reflection_payload.get("action") or "").upper() == CriticAction.REPLAN_READONLY.value:
        critic_goal = semantic_goal_for_completion if isinstance(semantic_goal_for_completion, dict) else {}
        orchestration, result_dict, critic_replan = _consume_post_execution_replan(
            source="critic",
            action=reflection_payload.get("action"),
            completion=result_dict.get("llm_completion") if isinstance(result_dict.get("llm_completion"), dict) else {},
            reflection=reflection_payload,
            orchestration=orchestration,
            result_dict=result_dict,
            user_goal=critic_goal,
            user_id=user_id,
            output_dir=output_dir,
            db_path=db_path,
            default_top_k=requested_top_k,
            session_id=session_id,
            language=language,
            context=route_context,
        )
        reflection_payload["replan"] = {
            "status": critic_replan.get("status"),
            "replan_count": critic_replan.get("replan_count"),
        }
        if critic_replan.get("execution"):
            expanded_tool_calls = [
                *list(expanded_tool_calls or []),
                *list((critic_replan.get("execution") or {}).get("tool_calls") or []),
            ]
            if critic_goal:
                result_dict["llm_completion"] = observe_goal_completion(
                    critic_goal,
                    {
                        "task_plan": phase10_for_completion.get("task_plan") or decomposition.get("task_plan") or {},
                        "task_results": orchestration.get("task_results") or {},
                        "result": result_dict,
                        "orchestration_status": orchestration.get("execution_status") or "",
                    },
                    api_key=llm_api_key,
                    base_url=llm_base_url,
                    model=llm_model,
                    llm_settings=active_llm,
                    context={
                    "safe_context": build_observer_context(
                        phase12_context_bundle,
                        user_goal=semantic_goal_for_completion,
                        task_plan=phase10_for_completion.get("task_plan") or decomposition.get("task_plan") or {},
                        result=result_dict,
                        orchestration=orchestration,
                    ),
                    "run_id": runtime.run_id,
                },
                ).to_dict()
            answer_text = _sanitize_user_facing_answer(_answer(intent, result_dict, language), language)
        runtime_info["replan_count"] = int(orchestration.get("replan_count") or 0)
        runtime_info["replan_audit"] = list(orchestration.get("replan_audit") or [])
    final_integrity = _logic_integrity_for_execution(
        intent=intent,
        decomposition=decomposition,
        orchestration=orchestration,
        result_dict=result_dict,
        completion=result_dict.get("llm_completion") if isinstance(result_dict.get("llm_completion"), dict) else {},
    )
    orchestration["logic_integrity"] = final_integrity.to_dict()
    if final_integrity.is_logic_error:
        result_dict = _feature_unavailable_result(
            intent=intent,
            integrity=final_integrity,
            language=language,
            previous=result_dict,
        )
        orchestration["execution_status"] = "feature_unavailable"
        answer_text = str(result_dict["message"])
        reflection_payload = {
            **dict(reflection_payload or {}),
            "logic_integrity": final_integrity.to_dict(),
            "action": "FEATURE_UNAVAILABLE",
        }
        llm_semantic_critic = {
            **dict(llm_semantic_critic or {}),
            "deterministic_logic_gate": final_integrity.to_dict(),
        }
    answer_text = _sanitize_user_facing_answer(answer_text, language)
    publish_agent_message(
        output_dir=output_dir,
        user_id=user_id,
        conversation_id=session_id,
        run_id=runtime.run_id,
        sender="executor",
        receiver="ui",
        message_type=MessageType.FINAL_REPORT,
        payload={
            "success": bool(result_dict.get("success")),
            "intent": intent,
            "answer": answer_text[:2000],
            "runtime_status": runtime_info.get("status"),
            "tool_name": str(result_dict.get("tool_name") or intent),
            "reflection": reflection_payload,
            "llm_semantic_critic": llm_semantic_critic,
        },
        payload_schema="phase13.final_report.v1",
        context_refs=phase13_context_refs,
        artifact_refs=final_artifact_refs,
        approval_refs=final_approval_refs,
        warnings=list(dict.fromkeys(context_warnings)),
    )

    # Planning and runtime traces may carry the broad canonical parameter
    # schema.  Return only its public projection; this removes even empty
    # secret placeholders such as ``confirmation_token`` from read-only
    # responses and UI/message mirrors.  A real protected-operation preview
    # keeps its token only in the direct result payload used by the explicit
    # confirmation flow.
    response_result = (
        result_dict
        if bool(result_dict.get("requires_confirmation"))
        else _public_agent_parameters(result_dict)
    )
    response_data = (
        result_dict.get("data")
        if bool(result_dict.get("requires_confirmation"))
        else _public_agent_parameters(
            result_dict.get("data") if isinstance(result_dict.get("data"), dict) else {}
        )
    )
    final_response = {
        "success": bool(result_dict.get("success")),
        "run_id": runtime.run_id,
        "formal_entry_audit": formal_entry_audit,
        "runtime": _public_agent_parameters(runtime_info),
        "intent": intent,
        "parameters": _public_agent_parameters(params),
        "original_query": raw_query,
        "resolved_query": planner_query if planner_query != raw_query else "",
        "conversation_state": resolved_turn.to_dict(),
        "reply_language": language,
        "decomposition": _public_agent_parameters(decomposition),
        "orchestration": _public_agent_parameters(orchestration),
        "routing_layer": decomposition.get(
            "route_layer",
            "unknown",
        ),
        "answer": answer_text,
        "result": response_result,
        "data": response_data,
        "status": orchestration.get("execution_status") if isinstance(orchestration, dict) else "",
        "pending_approval": bool(
            result_dict.get("requires_confirmation")
            or (
                isinstance(result_dict.get("data"), dict)
                and result_dict.get("data", {}).get("plan_id")
                and intent != "confirm_execute"
            )
        ),
        "plan_id": (
            result_dict.get("data", {}).get("plan_id")
            if isinstance(result_dict.get("data"), dict)
            else ""
        ),
        "tool_calls": _public_agent_parameters(expanded_tool_calls),
        "context": context_payload,
        "context_warnings": list(dict.fromkeys(context_warnings)),
        "reflection": reflection_payload,
        "llm_semantic_critic": llm_semantic_critic,
    }
    final_status = str(final_response.get("status") or result_dict.get("status") or runtime_info.get("status") or "unknown")
    if final_status == "feature_unavailable" or str((result_dict.get("data") or {}).get("status") or "") == "feature_unavailable":
        message_source = "deterministic_feature_unavailable"
    elif final_response["pending_approval"]:
        message_source = "approval_pending"
    elif bool(result_dict.get("success")):
        message_source = "deterministic_or_tool_result"
    else:
        message_source = "deterministic_failure"
    response_hash = sha256(
        json.dumps(
            {
                "run_id": runtime.run_id,
                "status": final_status,
                "answer": answer_text,
                "message_source": message_source,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    final_response_audit = {
        "run_id": runtime.run_id,
        "conversation_id": session_id,
        "llm_runtime": {**active_llm.public_dict, "config_hash": active_llm.config_hash},
        "final_status": final_status,
        "message_source": message_source,
        "template_type": "feature_unavailable" if message_source == "deterministic_feature_unavailable" else "standard",
        "logic_integrity_status": str((orchestration.get("logic_integrity") or {}).get("status") or "unknown"),
        "completion_status": str((result_dict.get("llm_completion") or {}).get("status") or ""),
        "critic_action": str((reflection_payload or {}).get("action") or ""),
        "replan_count": int(orchestration.get("replan_count") or 0),
        "safe_to_write": bool((result_dict.get("data") or {}).get("safe_to_write", True)),
        "pending_approval": bool(final_response["pending_approval"]),
        "response_hash": response_hash,
    }
    publish_agent_message(
        output_dir=output_dir,
        user_id=user_id,
        conversation_id=session_id,
        run_id=runtime.run_id,
        sender="executor",
        receiver="ui,audit",
        message_type=MessageType.FINAL_RESPONSE,
        payload=final_response_audit,
        payload_schema="phase_stable_portfolio.final_response.v1",
        context_refs=phase13_context_refs,
        artifact_refs=final_artifact_refs,
        approval_refs=final_approval_refs,
        warnings=list(dict.fromkeys(context_warnings)),
    )
    flow_event("FINAL_RESPONSE", final_response_audit, run_id=runtime.run_id)
    final_response["final_response_audit"] = final_response_audit
    trace_event(
        "executor.request.complete",
        {
            "success": final_response.get("success"),
            "intent": final_response.get("intent"),
            "routing_layer": final_response.get("routing_layer"),
            "conversation_state": final_response.get("conversation_state"),
            "resolved_query": final_response.get("resolved_query"),
            "answer": final_response.get("answer"),
            "runtime": final_response.get("runtime"),
            "decomposition": final_response.get("decomposition"),
            "orchestration": final_response.get("orchestration"),
            "reflection": final_response.get("reflection"),
            "llm_semantic_critic": final_response.get("llm_semantic_critic"),
        },
        run_id=runtime.run_id,
    )
    return final_response
