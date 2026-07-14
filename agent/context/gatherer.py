from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from database.repositories import AgentRepository
from agent.memory import LayeredMemoryService
from agent.memory.memory_context_bridge import build_memory_context_view
from portfolio.storage import PortfolioStorage
from portfolio.user_profile import load_user_context

from agent.context.schemas import ContextItem


BUSINESS_CONSTRAINTS = [
    "本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。",
    "Agent 不连接券商，不执行真实交易。",
    "模拟盘写操作必须先生成预案，经用户确认后重新校验再执行。",
    "不得绕过 Top10/Top15、最低现金比例、单股上限、一手约束、手续费和确认边界。",
    "RAG 证据只用于解释和辅助判断，不能直接当作收益预测或交易指令。",
]

CONTEXT_SECRET_KEYS = {
    "api_key",
    "authorization",
    "confirmation_token",
    "confirmation_token_hash",
    "database_path",
    "db_path",
    "llm_api_key",
    "password",
    "plan_hash",
    "secret",
    "snapshot_id",
    "state_id",
    "tushare_token",
}
CONTEXT_SAFE_TOKEN_KEYS = {"token_estimate", "token_present"}


def _is_context_secret_key(key: Any) -> bool:
    lowered = str(key or "").lower()
    if lowered in CONTEXT_SAFE_TOKEN_KEYS:
        return False
    if lowered in CONTEXT_SECRET_KEYS:
        return True
    if any(marker in lowered for marker in ("api_key", "password", "secret", "confirmation_token")):
        return True
    if "token" in lowered and lowered not in CONTEXT_SAFE_TOKEN_KEYS:
        return True
    return False


def _jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


def _scrub_context_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _scrub_context_payload(item)
            for key, item in value.items()
            if not _is_context_secret_key(key)
        }
    if isinstance(value, list):
        scrubbed = []
        for item in value[:80]:
            if isinstance(item, str) and _is_context_secret_key(item):
                continue
            scrubbed.append(_scrub_context_payload(item))
        return scrubbed
    if isinstance(value, str):
        lowered = value.lower()
        if "traceback (most recent call last)" in lowered or "stack trace" in lowered:
            return "[redacted internal stack]"
        if "agent_quant.db" in lowered:
            return "[redacted local database path]"
        if "confirmation_token" in lowered:
            return value.replace("confirmation_token", "[redacted-field]")
        return value
    return value


def _compact_json(value: Any, max_chars: int = 2400) -> str:
    text = json.dumps(_scrub_context_payload(_jsonable(value)), ensure_ascii=False, sort_keys=True, default=str)
    return text if len(text) <= max_chars else text[:max_chars] + "...[truncated]"


def _portfolio_dir(output_dir: str | Path, user_id: str) -> Path:
    return Path(output_dir) / "portfolio" / str(user_id or "default")


def _gather_user_profile(
    *,
    user_id: str,
    db_path: str | Path | None,
    output_dir: str | Path,
    warnings: list[str],
) -> tuple[ContextItem | None, dict[str, Any]]:
    try:
        profile, risk, goal, constraints = load_user_context(
            user_id,
            db_path=db_path,
            output_dir=output_dir,
        )
    except Exception as exc:
        warnings.append(f"user_profile_unavailable:{type(exc).__name__}")
        return None, {}
    payload = {
        "profile": profile.to_dict(),
        "risk_assessment": risk.to_dict(),
        "investment_goal": goal.to_dict(),
        "constraints": constraints,
    }
    return (
        ContextItem(
            section="user_context",
            title="user_profile",
            content=payload,
            priority=95,
            metadata={"user_id": user_id},
        ),
        constraints,
    )


def _gather_portfolio(
    *,
    user_id: str,
    db_path: str | Path | None,
    output_dir: str | Path,
    warnings: list[str],
) -> ContextItem | None:
    try:
        storage = PortfolioStorage(
            db_path=db_path,
            output_dir=_portfolio_dir(output_dir, user_id),
        )
        account = storage.load_account(f"paper_{user_id}")
        local_positions_path = (
            storage.positions_latest_path
            if storage.positions_latest_path.exists()
            else storage.positions_path
        )
        positions = storage.load_positions(None if local_positions_path.exists() else user_id)
    except Exception as exc:
        warnings.append(f"portfolio_context_unavailable:{type(exc).__name__}")
        return None
    position_rows = []
    for position in positions[:20]:
        position_rows.append(
            {
                "stock_code": position.stock_code,
                "stock_name": position.stock_name,
                "quantity": position.quantity,
                "market_value": position.market_value,
                "position_ratio": position.position_ratio,
                "industry": position.industry,
            }
        )
    payload = {
        "account": account.to_dict() if account else {},
        "position_count": len(position_rows),
        "positions": position_rows,
    }
    return ContextItem(
        section="portfolio_context",
        title="current_paper_portfolio",
        content=payload,
        priority=92,
        metadata={"user_id": user_id},
    )


def _gather_history(
    *,
    user_id: str,
    session_id: str,
    db_path: str | Path | None,
    warnings: list[str],
) -> list[ContextItem]:
    if not session_id:
        return []
    try:
        repo = AgentRepository(db_path)
        conversation = repo.store.get("conversations", {"conversation_id": session_id})
        if not conversation or str(conversation.get("user_id") or "") != str(user_id):
            return []
        messages = repo.list_messages(session_id, limit=12)
    except Exception as exc:
        warnings.append(f"history_context_unavailable:{type(exc).__name__}")
        return []
    safe_messages = [
        {
            "role": row.get("role"),
            "content": str(row.get("content") or "")[:600],
            "created_at": row.get("created_at"),
        }
        for row in messages[-8:]
        if str(row.get("user_id") or "") == str(user_id)
    ]
    if not safe_messages:
        return []
    return [
        ContextItem(
            section="history_context",
            title="recent_messages",
            content=safe_messages,
            priority=55,
            metadata={"conversation_id": session_id},
        )
    ]


def _gather_memory(
    *,
    query: str,
    user_id: str,
    output_dir: str | Path,
    db_path: str | Path | None,
    session_id: str,
    run_id: str,
    agent_role: str,
    warnings: list[str],
) -> list[ContextItem]:
    try:
        memory = LayeredMemoryService(db_path)
        layered = memory.retrieve_layered_memory(
            user_id=user_id,
            query=query,
            session_id=session_id,
            run_id=run_id,
            limit=8,
        )
        layered["agent_view"] = memory.memory_view_for_agent(
            user_id=user_id,
            query=query,
            agent_role=agent_role,
            limit=6,
        )
        phase14_memory = build_memory_context_view(
            user_id=user_id,
            query=query,
            output_dir=output_dir,
            limit=6,
        )
        if phase14_memory.get("item_count"):
            layered["phase14_memory"] = phase14_memory
    except Exception as exc:
        warnings.append(f"memory_context_unavailable:{type(exc).__name__}")
        return []
    if not any(layered.get(key) for key in ("working", "episodic", "semantic", "protocol", "agent_view", "phase14_memory")):
        return []
    return [
        ContextItem(
            section="memory_context",
            title="layered_agent_memory",
            content=layered,
            priority=52,
            metadata={"user_id": user_id, "agent_role": agent_role},
        )
    ]


def _extract_evidence_rows(value: Any, rows: list[dict[str, Any]]) -> None:
    if len(rows) >= 40:
        return
    if isinstance(value, dict):
        marker_keys = {
            "chunk_id",
            "news_id",
            "source_id",
            "retrieval_id",
            "database_record_id",
        }
        if any(key in value and value.get(key) for key in marker_keys):
            rows.append(
                {
                    key: value.get(key)
                    for key in [
                        "chunk_id",
                        "news_id",
                        "source_id",
                        "retrieval_id",
                        "database_record_id",
                        "stock_code",
                        "publish_time",
                        "source",
                        "title",
                        "section_title",
                    ]
                    if value.get(key) not in ("", None)
                }
            )
        for item in value.values():
            _extract_evidence_rows(item, rows)
    elif isinstance(value, list):
        for item in value[:80]:
            _extract_evidence_rows(item, rows)


def _gather_tool_and_evidence(
    *,
    tool_result: dict[str, Any] | None,
    orchestration: dict[str, Any] | None,
) -> list[ContextItem]:
    items: list[ContextItem] = []
    if tool_result:
        items.append(
            ContextItem(
                section="tool_results",
                title=str(tool_result.get("tool_name") or "tool_result"),
                content=_compact_json(tool_result, max_chars=3200),
                priority=88,
            )
        )
    if orchestration:
        items.append(
            ContextItem(
                section="runtime_context",
                title="orchestration_observation",
                content=_compact_json(
                    {
                        "execution_status": orchestration.get("execution_status"),
                        "observations": orchestration.get("observations") or [],
                        "replan_count": orchestration.get("replan_count"),
                        "runtime_limits": orchestration.get("runtime_limits") or {},
                    },
                    max_chars=2200,
                ),
                priority=72,
            )
        )
    evidence_rows: list[dict[str, Any]] = []
    _extract_evidence_rows(tool_result or {}, evidence_rows)
    _extract_evidence_rows(orchestration or {}, evidence_rows)
    if evidence_rows:
        items.append(
            ContextItem(
                section="evidence_context",
                title="source_trace_ids",
                content=evidence_rows,
                priority=86,
                source_ids=[
                    str(row.get("source_id") or row.get("chunk_id") or row.get("news_id") or "")
                    for row in evidence_rows
                    if row.get("source_id") or row.get("chunk_id") or row.get("news_id")
                ],
            )
        )
    return items


def gather_context_items(
    *,
    query: str,
    user_id: str,
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
    session_id: str = "",
    run_id: str = "",
    tool_result: dict[str, Any] | None = None,
    orchestration: dict[str, Any] | None = None,
    decomposition: dict[str, Any] | None = None,
    agent_role: str = "supervisor",
) -> tuple[list[ContextItem], list[str]]:
    warnings: list[str] = []
    items: list[ContextItem] = [
        ContextItem(
            section="user_context",
            title="user_question",
            content={"query": str(query or ""), "reply_scope": "agent_request"},
            priority=100,
        ),
        ContextItem(
            section="runtime_context",
            title="current_run",
            content={
                "run_id": str(run_id or ""),
                "session_id_present": bool(session_id),
                "task_count": len((decomposition or {}).get("tasks") or []),
            },
            priority=82,
        ),
    ]
    profile_item, constraints = _gather_user_profile(
        user_id=user_id,
        db_path=db_path,
        output_dir=output_dir,
        warnings=warnings,
    )
    if profile_item is not None:
        items.append(profile_item)
    portfolio_item = _gather_portfolio(
        user_id=user_id,
        db_path=db_path,
        output_dir=output_dir,
        warnings=warnings,
    )
    if portfolio_item is not None:
        items.append(portfolio_item)
    items.extend(
        _gather_history(
            user_id=user_id,
            session_id=session_id,
            db_path=db_path,
            warnings=warnings,
        )
    )
    items.extend(
        _gather_memory(
            query=query,
            user_id=user_id,
            output_dir=output_dir,
            db_path=db_path,
            session_id=session_id,
            run_id=run_id,
            agent_role=agent_role,
            warnings=warnings,
        )
    )
    items.extend(_gather_tool_and_evidence(tool_result=tool_result, orchestration=orchestration))
    items.append(
        ContextItem(
            section="business_constraints",
            title="business_safety_boundaries",
            content={
                "global_constraints": BUSINESS_CONSTRAINTS,
                "user_constraints": constraints,
            },
            priority=98,
        )
    )
    return items, warnings
