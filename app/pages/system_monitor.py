from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

try:
    import streamlit as st
except ImportError:
    class _StreamlitStub:
        def __getattr__(self, name):
            def _noop(*args, **kwargs):
                return None
            return _noop
    st = _StreamlitStub()

from application.system_monitor_service import (
    build_handoff_health_summary,
    build_memory_store_health_summary,
    build_message_bus_health_summary,
    build_react_health_summary,
    build_reflection_health_summary,
    build_system_monitor_snapshot,
    collect_and_store_system_monitor_snapshot,
    list_system_monitor_alerts,
    list_system_monitor_history,
)


SYSTEM_MONITOR_PAGE_TITLE = "系统监控"
SYSTEM_MONITOR_TOP_LEVEL_PAGE = "系统监控"
SYSTEM_MONITOR_DISCLAIMER = "本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。"


def _fmt(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _metric_rows(snapshot: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for layer in ["data", "model", "rag", "agent", "portfolio"]:
        metrics = snapshot.get(f"{layer}_metrics") or {}
        for key, value in metrics.items():
            rows.append({"layer": layer, "metric": key, "value": _fmt(value)})
    return pd.DataFrame(rows)


def _history_rows(history: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for item in history:
        rows.append(
            {
                "trade_date": item.get("trade_date"),
                "status": item.get("overall_status"),
                "data_version": item.get("data_version"),
                "model_version": item.get("model_version"),
                "rag_index_version": item.get("rag_index_version"),
                "run_id": item.get("run_id"),
                "portfolio_snapshot_id": item.get("portfolio_snapshot_id"),
                "updated_at": item.get("updated_at") or item.get("created_at"),
            }
        )
    return pd.DataFrame(rows)


def _runtime_health_rows(snapshot: dict[str, Any]) -> pd.DataFrame:
    agent_metrics = snapshot.get("agent_metrics") or {}
    runtime_health = agent_metrics.get("runtime_health") or {}
    if not isinstance(runtime_health, dict):
        runtime_health = {}
    rows = [
        {"metric": "success_rate", "value": _fmt(runtime_health.get("success_rate"))},
        {"metric": "p50_latency_seconds", "value": _fmt(runtime_health.get("p50_latency"))},
        {"metric": "p95_latency_seconds", "value": _fmt(runtime_health.get("p95_latency"))},
        {"metric": "tool_failure_rate", "value": _fmt(runtime_health.get("tool_failure_rate"))},
        {"metric": "retry_count", "value": _fmt(runtime_health.get("retry_count"))},
        {"metric": "timeout_count", "value": _fmt(runtime_health.get("timeout_count"))},
        {"metric": "circuit_states", "value": _fmt(runtime_health.get("circuit_states"))},
        {"metric": "over_budget_count", "value": _fmt(runtime_health.get("over_budget_count"))},
        {"metric": "resumable_run_count", "value": _fmt(runtime_health.get("resumable_run_count"))},
    ]
    return pd.DataFrame(rows)


def _build_message_bus_health_summary(*, user_id: str = "default", output_dir: str | Path = "outputs") -> dict[str, Any]:
    return build_message_bus_health_summary(user_id=user_id, output_dir=output_dir)


def _message_bus_health_rows(summary: dict[str, Any]) -> pd.DataFrame:
    rows = [
        {"metric": "status", "value": _fmt(summary.get("status"))},
        {"metric": "latest_run_id", "value": _fmt(summary.get("latest_run_id"))},
        {"metric": "latest_run_message_count", "value": _fmt(summary.get("latest_run_message_count"))},
        {"metric": "message_store_summary", "value": _fmt(summary.get("message_store_summary"))},
        {"metric": "error_message_count", "value": _fmt(summary.get("error_message_count"))},
        {"metric": "pending_approval_message_count", "value": _fmt(summary.get("pending_approval_message_count"))},
        {"metric": "artifact_message_count", "value": _fmt(summary.get("artifact_message_count"))},
    ]
    return pd.DataFrame(rows)


def _memory_store_health_rows(summary: dict[str, Any]) -> pd.DataFrame:
    rows = [
        {"metric": "status", "value": _fmt(summary.get("status"))},
        {"metric": "store", "value": _fmt(summary.get("store"))},
        {"metric": "exists", "value": _fmt(summary.get("exists"))},
        {"metric": "total_count", "value": _fmt(summary.get("total_count"))},
        {"metric": "user_count", "value": _fmt(summary.get("user_count"))},
        {"metric": "latest_memory_count", "value": _fmt(summary.get("latest_memory_count"))},
        {"metric": "latest_memory_types", "value": _fmt(", ".join(summary.get("latest_memory_types") or []))},
        {"metric": "secret_safe", "value": _fmt(summary.get("secret_safe"))},
        {"metric": "write_permission", "value": _fmt(summary.get("write_permission"))},
    ]
    return pd.DataFrame(rows)


def _react_health_rows(summary: dict[str, Any]) -> pd.DataFrame:
    rows = [
        {"metric": "status", "value": _fmt(summary.get("status"))},
        {"metric": "latest_run_id", "value": _fmt(summary.get("latest_run_id") or summary.get("run_id"))},
        {"metric": "run_file_count", "value": _fmt(summary.get("run_file_count"))},
        {"metric": "react_log_summary", "value": _fmt(summary.get("react_log_summary"))},
        {"metric": "observation_count", "value": _fmt(summary.get("observation_count"))},
        {"metric": "blocking_observation_count", "value": _fmt(summary.get("blocking_observation_count"))},
        {"metric": "latest_observation_type", "value": _fmt(summary.get("latest_observation_type"))},
        {"metric": "replan_message_count", "value": _fmt(summary.get("replan_message_count"))},
        {"metric": "secret_safe", "value": _fmt((summary.get("safety") or {}).get("secrets_redacted"))},
    ]
    return pd.DataFrame(rows)


def _reflection_health_rows(summary: dict[str, Any]) -> pd.DataFrame:
    rows = [
        {"metric": "status", "value": _fmt(summary.get("status"))},
        {"metric": "latest_run_id", "value": _fmt(summary.get("latest_run_id"))},
        {"metric": "run_file_count", "value": _fmt(summary.get("run_file_count"))},
        {"metric": "latest_critic_count", "value": _fmt(summary.get("latest_critic_count"))},
        {"metric": "critic_pass_count", "value": _fmt(summary.get("critic_pass_count"))},
        {"metric": "critic_fail_count", "value": _fmt(summary.get("critic_fail_count"))},
        {"metric": "blocking_issue_count", "value": _fmt(summary.get("blocking_issue_count"))},
        {"metric": "latest_critic_action", "value": _fmt(summary.get("latest_critic_action"))},
        {"metric": "latest_critic_severity", "value": _fmt(summary.get("latest_critic_severity"))},
        {"metric": "latest_critic_score", "value": _fmt(summary.get("latest_critic_score"))},
        {"metric": "reflection_log_summary", "value": _fmt(summary.get("reflection_log_summary"))},
        {"metric": "secret_safe", "value": _fmt((summary.get("safety") or {}).get("secrets_redacted"))},
    ]
    return pd.DataFrame(rows)


def _handoff_health_rows(summary: dict[str, Any]) -> pd.DataFrame:
    rows = [
        {"metric": "status", "value": _fmt(summary.get("status"))},
        {"metric": "latest_run_id", "value": _fmt(summary.get("latest_run_id"))},
        {"metric": "run_file_count", "value": _fmt(summary.get("run_file_count"))},
        {"metric": "latest_handoff_count", "value": _fmt(summary.get("latest_handoff_count"))},
        {"metric": "latest_handoff_status", "value": _fmt(summary.get("latest_handoff_status"))},
        {"metric": "blocked_handoff_count", "value": _fmt(summary.get("blocked_handoff_count"))},
        {"metric": "roles_used", "value": _fmt(", ".join(summary.get("roles_used") or []))},
        {"metric": "handoff_messages_seen", "value": _fmt(summary.get("handoff_messages_seen"))},
        {"metric": "secret_safe", "value": _fmt((summary.get("safety") or {}).get("secrets_redacted"))},
    ]
    return pd.DataFrame(rows)


def render_system_monitor_page(
    *,
    user_id: str = "default",
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
) -> None:
    st.title(SYSTEM_MONITOR_PAGE_TITLE)
    st.warning(SYSTEM_MONITOR_DISCLAIMER)

    preview = build_system_monitor_snapshot(
        db_path=db_path or "data/agent_quant.db",
        user_id=user_id,
        output_dir=output_dir,
    )
    snapshot = preview.snapshot
    alerts = preview.alerts

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("总状态", snapshot.get("overall_status", "normal"))
    col2.metric("交易日期", snapshot.get("trade_date", ""))
    col3.metric("告警数", len(alerts))
    col4.metric("缺失模块", len(snapshot.get("missing_modules") or []))

    if st.button("保存监控快照", key=f"system_monitor_save_{user_id}"):
        saved = collect_and_store_system_monitor_snapshot(
            db_path=db_path or "data/agent_quant.db",
            user_id=user_id,
            output_dir=output_dir,
        )
        snapshot = saved.snapshot
        alerts = saved.alerts
        st.success(f"监控快照已保存：{snapshot.get('snapshot_id')}")

    version_info = snapshot.get("version_info") or {}
    with st.expander("版本与关联", expanded=True):
        st.dataframe(
            pd.DataFrame(
                [
                    {"item": key, "value": _fmt(value)}
                    for key, value in version_info.items()
                ]
            ),
            width="stretch",
            hide_index=True,
        )

    if alerts:
        st.subheader("告警")
        st.dataframe(pd.DataFrame(alerts), width="stretch", hide_index=True)
    else:
        st.success("当前没有触发告警。")

    st.subheader("分层指标")
    metrics_df = _metric_rows(snapshot)
    if metrics_df.empty:
        st.info("暂无可展示指标。")
    else:
        st.dataframe(metrics_df, width="stretch", hide_index=True)

    st.subheader("Runtime Reliability")
    runtime_df = _runtime_health_rows(snapshot)
    if runtime_df.empty:
        st.info("No runtime reliability metrics yet.")
    else:
        st.dataframe(runtime_df, width="stretch", hide_index=True)

    st.subheader("MessageBus Health")
    message_bus_summary = _build_message_bus_health_summary(user_id=user_id, output_dir=output_dir)
    st.dataframe(_message_bus_health_rows(message_bus_summary), width="stretch", hide_index=True)

    st.subheader("MemoryStore Health")
    memory_summary = build_memory_store_health_summary(user_id=user_id, output_dir=output_dir)
    st.dataframe(_memory_store_health_rows(memory_summary), width="stretch", hide_index=True)

    st.subheader("ReAct Health")
    react_summary = build_react_health_summary(user_id=user_id, output_dir=output_dir)
    st.dataframe(_react_health_rows(react_summary), width="stretch", hide_index=True)

    st.subheader("Reflection Health")
    reflection_summary = build_reflection_health_summary(user_id=user_id, output_dir=output_dir)
    st.dataframe(_reflection_health_rows(reflection_summary), width="stretch", hide_index=True)

    st.subheader("Handoff Health")
    handoff_summary = build_handoff_health_summary(user_id=user_id, output_dir=output_dir)
    st.dataframe(_handoff_health_rows(handoff_summary), width="stretch", hide_index=True)

    missing = snapshot.get("missing_modules") or []
    if missing:
        with st.expander("缺失模块", expanded=False):
            st.dataframe(pd.DataFrame({"module": missing}), width="stretch", hide_index=True)

    st.subheader("历史趋势")
    history = list_system_monitor_history(db_path=db_path or "data/agent_quant.db", user_id=user_id, limit=30)
    history_df = _history_rows(history)
    if history_df.empty:
        st.info("暂无已保存的历史快照。")
    else:
        st.dataframe(history_df, width="stretch", hide_index=True)

    stored_alerts = list_system_monitor_alerts(db_path=db_path or "data/agent_quant.db", user_id=user_id, limit=100)
    with st.expander("历史告警", expanded=False):
        if stored_alerts:
            st.dataframe(pd.DataFrame(stored_alerts), width="stretch", hide_index=True)
        else:
            st.info("暂无历史告警。")


def render(*args, **kwargs) -> None:
    render_system_monitor_page(*args, **kwargs)
