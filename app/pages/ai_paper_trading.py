from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from app.components.compact_metric import render_compact_metric
from app.display_labels import action_label, display_label, risk_level_label
from config import DEFAULT_INITIAL_CASH, DEFAULT_PAPER_TRADING_START_DATE
from evaluation.evaluation_store import load_ai_reliability_state
from portfolio.trading_permissions import (
    DEFAULT_TRADING_PERMISSIONS,
    TRADING_PERMISSION_LABELS,
    format_permission_summary,
    normalize_trading_permissions,
)
from pipelines.schemas import PipelineStatus
from news_db_sync import sync_event_cache_to_agent_db
from pipelines.replay_audit_ledger import (
    list_replay_audit_dates,
    list_replay_audit_runs,
    load_replay_audit_day,
    load_replay_audit_markdown,
)
from portfolio.decision_attribution import (
    explain_stock_decision_attribution,
    render_decision_attribution_markdown,
)

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

        def spinner(self, *args, **kwargs):
            return self

        def form(self, *args, **kwargs):
            return self

        def form_submit_button(self, *args, **kwargs):
            return False

        def selectbox(self, label, options=None, index=0, **kwargs):
            options = list(options or [])
            return options[index] if options else None

        def multiselect(self, label, options=None, default=None, **kwargs):
            return list(default or [])

        def button(self, *args, **kwargs):
            return False

        def checkbox(self, *args, **kwargs):
            return False

        def date_input(self, *args, **kwargs):
            return kwargs.get("value")

        def text_input(self, *args, **kwargs):
            return kwargs.get("value", "")

        def number_input(self, *args, **kwargs):
            return kwargs.get("value", 0.0)

        def __getattr__(self, name):
            def _noop(*args, **kwargs):
                return None

            return _noop

    st = _StreamlitStub()

from app.classic_services import (
    cancel_pending_paper_cash_flow,
    get_classic_user_profile_form_options,
    list_daily_order_snapshot_dates,
    list_daily_position_snapshot_dates,
    load_classic_user_context,
    load_daily_order_snapshot,
    load_daily_position_snapshot,
    load_paper_backfill_status,
    load_paper_cash_flows,
    load_paper_trading_snapshot,
    run_paper_trading_from_latest,
    save_classic_user_context,
)
from agent.tool_engine import AGENT_MAIN, execute_tool
from agent.write_gateway import execute_confirmed_plan_v2

try:
    from app.classic_services import has_required_paper_trading_profile
except ImportError:
    def has_required_paper_trading_profile(user_context: dict[str, Any] | None) -> bool:
        data = user_context or {}
        try:
            capital = float(data.get("available_capital") or data.get("initial_capital") or 0.0)
        except Exception:
            capital = 0.0
        return all(
            [
                data.get("user_id"),
                capital > 0,
                data.get("risk_level"),
                data.get("goal_type") or data.get("investment_goal"),
                data.get("liquidity_need"),
                data.get("trading_style"),
            ]
        )


AI_PAPER_TRADING_PAGE_TITLE = "AI 模拟盘"
AI_PAPER_TRADING_TOP_LEVEL_PAGE = "AI 模拟盘"
AI_PAPER_TRADING_DISCLAIMER = "本页面仅用于模拟盘和项目展示，不是真实交易，不接券商接口，不构成投资建议，不承诺收益。"
ASSET_CURVE_TITLE = "账户资产走势"
ASSET_CURVE_COLUMNS = {
    "total_assets": "账户总资产",
    "net_contribution": "净投入资金",
    "position_market_value": "持仓市值",
    "cash": "现金",
}
FIXED_PAPER_STRATEGY = {
    "strategy": "hierarchical_top10",
    "top_k": 15,
    "entry_top_k": 10,
    "hold_buffer_rank": 15,
    "max_positions": 10,
}

PAPER_UI_SECRET_KEYS = {
    "api_key",
    "authorization",
    "business_state_version",
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
    "token",
    "tushare_token",
}
PAPER_UI_SAFE_TOKEN_KEYS = {"token_estimate", "token_present"}
PAPER_WINDOWS_PATH_PATTERN = re.compile(r"(?i)\b[a-z]:\\[^\s\"'<>|]+")


def _is_paper_ui_secret_key(key: Any) -> bool:
    lowered = str(key or "").lower()
    if lowered in PAPER_UI_SAFE_TOKEN_KEYS:
        return False
    if lowered in PAPER_UI_SECRET_KEYS:
        return True
    if any(marker in lowered for marker in ("api_key", "password", "secret", "confirmation_token")):
        return True
    if "token" in lowered and lowered not in PAPER_UI_SAFE_TOKEN_KEYS:
        return True
    return False


def _redact_paper_ui_payload(value: Any, *, max_chars: int = 1200) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "***" if _is_paper_ui_secret_key(key) else _redact_paper_ui_payload(item, max_chars=max_chars)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_paper_ui_payload(item, max_chars=max_chars) for item in value[:50]]
    if isinstance(value, str):
        lowered = value.lower()
        if "traceback (most recent call last)" in lowered or "stack trace" in lowered:
            return "[redacted internal stack]"
        if "agent_quant.db" in lowered:
            return "[redacted local database path]"
        if PAPER_WINDOWS_PATH_PATTERN.search(value):
            return PAPER_WINDOWS_PATH_PATTERN.sub("[redacted local path]", value)[:max_chars]
        return value if len(value) <= max_chars else value[:max_chars] + "...[truncated]"
    return value
FIXED_PAPER_STRATEGY_TEXT = (
    "固定模拟盘策略：Top10 新买入，Top15 持仓缓冲，Top10 目标仓位 80%，"
    "目标现金 5%，单股最高 30%，按 A 股一手约束执行，并保留硬风险阻断/退出。"
)
PAPER_PAGE_CACHE_TTL_SECONDS = 60


def _legacy_direct_write_disabled(*args: Any, **kwargs: Any) -> None:
    raise RuntimeError("legacy direct paper-trading write is disabled; use Write Gateway")


def _path_cache_version(path: str | Path) -> tuple[str, int, int]:
    resolved = Path(path)
    try:
        stat = resolved.stat()
        size = stat.st_size if resolved.is_file() else 0
        return str(resolved), int(stat.st_mtime_ns), int(size)
    except OSError:
        return str(resolved), 0, 0


def _paper_cache_versions(
    user_id: str,
    output_dir: str | Path,
    db_path: str | Path | None = None,
) -> tuple[tuple[str, int, int], ...]:
    root = Path(output_dir) / "portfolio" / str(user_id)
    paths = [
        root / "paper_account_latest.json",
        root / "paper_account.json",
        root / "paper_positions_latest.csv",
        root / "paper_positions.csv",
        root / "paper_orders_latest.csv",
        root / "paper_orders.csv",
        root / "paper_nav_latest.csv",
        root / "portfolio_risk_report_latest.json",
        root / "portfolio_risk_report.json",
        root / "ai_paper_decisions_latest.json",
        root / "paper_execution_diagnostics_latest.json",
        root / "paper_trading_settings.json",
        root / "history" / "orders",
        root / "history" / "positions",
    ]
    if db_path:
        paths.append(Path(db_path))
    return tuple(_path_cache_version(path) for path in paths)


@st.cache_data(ttl=PAPER_PAGE_CACHE_TTL_SECONDS)
def _cached_paper_trading_snapshot(
    user_id: str,
    output_dir: str,
    db_path: str,
    versions: tuple[tuple[str, int, int], ...],
) -> dict[str, Any]:
    del versions
    return load_paper_trading_snapshot(
        user_id,
        output_dir=output_dir,
        db_path=db_path or None,
    )


def load_cached_paper_trading_snapshot(
    user_id: str,
    output_dir: str | Path,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    return _cached_paper_trading_snapshot(
        str(user_id),
        str(output_dir),
        str(db_path or ""),
        _paper_cache_versions(user_id, output_dir, db_path),
    )


@st.cache_data(ttl=PAPER_PAGE_CACHE_TTL_SECONDS)
def _cached_ai_reliability_state(
    user_id: str,
    output_dir: str,
    version: tuple[str, int, int],
) -> dict[str, Any]:
    del version
    return load_ai_reliability_state(user_id, output_dir=output_dir)


def load_cached_ai_reliability_state(
    user_id: str,
    output_dir: str | Path,
) -> dict[str, Any]:
    state_path = Path(output_dir) / "portfolio" / str(user_id) / "ai_reliability_state.json"
    return _cached_ai_reliability_state(
        str(user_id),
        str(output_dir),
        _path_cache_version(state_path),
    )


@st.cache_data(ttl=PAPER_PAGE_CACHE_TTL_SECONDS)
def _cached_paper_cash_flows(
    user_id: str,
    output_dir: str,
    db_path: str,
    versions: tuple[tuple[str, int, int], ...],
) -> list[dict[str, Any]]:
    del versions
    return load_paper_cash_flows(
        user_id,
        output_dir=output_dir,
        db_path=db_path or None,
    )


def load_cached_paper_cash_flows(
    user_id: str,
    output_dir: str | Path,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    root = Path(output_dir) / "portfolio" / str(user_id)
    versions = (
        _path_cache_version(root / "cash_flows.json"),
        _path_cache_version(root / "paper_cash_flows.json"),
        _path_cache_version(db_path) if db_path else ("", 0, 0),
    )
    return _cached_paper_cash_flows(
        str(user_id),
        str(output_dir),
        str(db_path or ""),
        versions,
    )


@st.cache_data(ttl=PAPER_PAGE_CACHE_TTL_SECONDS)
def _cached_daily_order_snapshot(
    user_id: str,
    trade_date: str,
    output_dir: str,
    versions: tuple[tuple[str, int, int], ...],
) -> pd.DataFrame:
    del versions
    return load_daily_order_snapshot(user_id, trade_date, output_dir)


def load_cached_daily_order_snapshot(
    user_id: str,
    trade_date: str,
    output_dir: str | Path,
) -> pd.DataFrame:
    root = Path(output_dir) / "portfolio" / str(user_id)
    token = "".join(ch for ch in str(trade_date) if ch.isdigit())[:8]
    return _cached_daily_order_snapshot(
        str(user_id),
        str(trade_date),
        str(output_dir),
        (
            _path_cache_version(root / "history" / "orders"),
            _path_cache_version(root / "history" / "orders" / f"orders_{token}.csv"),
            _path_cache_version(root / "paper_orders_latest.csv"),
        ),
    )


@st.cache_data(ttl=PAPER_PAGE_CACHE_TTL_SECONDS)
def _cached_daily_position_snapshot(
    user_id: str,
    trade_date: str,
    output_dir: str,
    versions: tuple[tuple[str, int, int], ...],
) -> pd.DataFrame:
    del versions
    return load_daily_position_snapshot(user_id, trade_date, output_dir)


def load_cached_daily_position_snapshot(
    user_id: str,
    trade_date: str,
    output_dir: str | Path,
) -> pd.DataFrame:
    root = Path(output_dir) / "portfolio" / str(user_id)
    token = "".join(ch for ch in str(trade_date) if ch.isdigit())[:8]
    return _cached_daily_position_snapshot(
        str(user_id),
        str(trade_date),
        str(output_dir),
        (
            _path_cache_version(root / "history" / "positions"),
            _path_cache_version(root / "history" / "positions" / f"positions_{token}.csv"),
            _path_cache_version(root / "paper_positions_latest.csv"),
        ),
    )


def clear_ai_paper_trading_page_cache() -> None:
    _cached_paper_trading_snapshot.clear()
    _cached_ai_reliability_state.clear()
    _cached_paper_cash_flows.clear()
    _cached_daily_order_snapshot.clear()
    _cached_daily_position_snapshot.clear()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in [None, ""]:
            return default
        return float(value)
    except Exception:
        return default


def get_ai_paper_trading_page_sections() -> list[str]:
    return [
        "用户与账户摘要",
        "用户画像与初始资产",
        ASSET_CURVE_TITLE,
        "历史回放",
        "资金管理",
        "资金分配详情",
        "当日组合构建诊断",
        "每日决策审计",
        "今日模拟盘动作",
        "当前持仓",
        "历史订单",
        "每日持仓快照",
        "组合风险",
    ]


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        if path.stat().st_size == 0:
            return pd.DataFrame()
        return pd.read_csv(path, dtype={"stock_code": str, "code": str}, encoding="utf-8-sig")
    except (pd.errors.EmptyDataError, OSError):
        return pd.DataFrame()


def _format_weight(value: Any) -> str:
    try:
        return f"{float(value):.2%}"
    except Exception:
        return ""


def _format_money(value: Any) -> str:
    try:
        return f"{float(value):,.2f}"
    except Exception:
        return ""


def _format_date(value: Any) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value or "")


def _format_structured_value(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return str(value or "")


def _result_payload(result: Any) -> dict[str, Any]:
    if hasattr(result, "to_dict"):
        return result.to_dict()
    if isinstance(result, dict):
        return dict(result)
    return {"result": str(result)}


def _write_tool_context(user_id: str, output_dir: str | Path, db_path: str | Path | None) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "output_dir": output_dir,
        "db_path": db_path,
        "session_id": f"ai_paper_trading:{user_id}",
        "conversation_id": f"ai_paper_trading:{user_id}",
    }


def _render_write_proposal_confirmation(
    *,
    user_id: str,
    plan: dict[str, Any] | None,
    state_key: str,
    output_dir: str | Path,
    db_path: str | Path | None,
    result_key: str | None = None,
) -> None:
    if not plan:
        return
    plan_id = str(plan.get("plan_id") or "")
    if not plan_id:
        return
    with st.expander(f"Pending confirmation plan: {plan_id}", expanded=True):
        st.json(_redact_paper_ui_payload(plan))
        token = st.text_input(
            "confirmation_token",
            value="",
            key=f"{state_key}_token_{plan_id}",
        )
        if st.button("Confirm protected write", key=f"{state_key}_confirm_{plan_id}"):
            if not token:
                st.warning("Please enter the confirmation token before executing.")
                return
            result = execute_confirmed_plan_v2(
                plan_id=plan_id,
                confirmation_token=token,
                user_id=user_id,
                conversation_id=f"ai_paper_trading:{user_id}",
                output_dir=output_dir,
                db_path=db_path,
            )
            st.json(_redact_paper_ui_payload(result.to_dict()))
            if result.success:
                clear_ai_paper_trading_page_cache()
                st.success(result.message)
                if result_key:
                    st.session_state[result_key] = dict(result.data or {})
                st.session_state.pop(state_key, None)
                st.rerun()
            else:
                st.error(result.message)


def _option_index(options: list[Any], value: Any, default: int = 0) -> int:
    text = str(value or "")
    values = [str(item) for item in options]
    return values.index(text) if text in values else default


def _list_value(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
        return [item.strip() for item in value.split(",") if item.strip()]
    return [value]


def build_user_profile_payload(user_id: str, data: dict[str, Any]) -> dict[str, Any]:
    payload = dict(data or {})
    payload["user_id"] = str(user_id or payload.get("user_id") or "default")
    initial_capital = _safe_float(
        payload.get("initial_capital") or payload.get("available_capital"),
        DEFAULT_INITIAL_CASH,
    )
    payload["initial_capital"] = initial_capital
    payload["available_capital"] = initial_capital
    payload["trading_permissions"] = (
        normalize_trading_permissions(
            payload.get("trading_permissions")
        )
    )
    return payload


def _metric(label_key: str, value: str) -> dict[str, str]:
    return {"label": display_label(label_key), "value": value}


def build_capital_summary_rows(
    account: dict[str, Any] | None,
    risk_report: dict[str, Any] | None,
    reliability_state: dict[str, Any] | None,
    user_id: str,
    diagnostics: dict[str, Any] | None = None,
) -> list[list[dict[str, str]]]:
    account = account or {}
    risk_report = risk_report or {}
    reliability_state = reliability_state or {}
    diagnostics = diagnostics or {}
    return [
        [
            _metric("total_assets", _format_money(account.get("total_assets") or 0)),
            _metric("paper_trading_start_date", str(account.get("paper_trading_start_date") or DEFAULT_PAPER_TRADING_START_DATE)),
            _metric("absolute_profit", _format_money(account.get("absolute_profit") or 0)),
            _metric("time_weighted_return", _format_weight(account.get("time_weighted_return") or 0)),
            _metric("current_cash", _format_money(account.get("cash") or 0)),
        ],
        [
            _metric("user_id", user_id),
            _metric("initial_cash", _format_money(account.get("initial_cash") or 0)),
            _metric("cumulative_deposit", _format_money(account.get("cumulative_deposit") or 0)),
            _metric("cumulative_withdrawal", _format_money(account.get("cumulative_withdrawal") or 0)),
            _metric("net_contribution", _format_money(account.get("net_contribution") or account.get("initial_cash") or 0)),
            _metric("cumulative_fee", _format_money(account.get("cumulative_fee") or 0)),
        ],
        [
            _metric("position_market_value", _format_money(account.get("position_market_value") or 0)),
            _metric("daily_return", _format_weight(account.get("daily_return") or 0)),
            _metric("max_drawdown", _format_weight(account.get("max_drawdown") or 0)),
            _metric("composite_nav", f"{float(account.get('composite_nav') or account.get('nav') or 1.0):.4f}"),
        ],
        [
            _metric("cash_ratio", _format_weight(risk_report.get("cash_ratio") or 0)),
            _metric("capital_utilization_rate", _format_weight(diagnostics.get("capital_utilization_rate") or 0)),
            _metric("portfolio_risk_level", risk_level_label(risk_report.get("risk_level"))),
            _metric("ai_reliability", f"{float(reliability_state.get('ai_reliability_weight') or 0.0):.2f}"),
        ],
    ]


def build_allocation_summary_table(diagnostics: dict[str, Any] | None) -> pd.DataFrame:
    data = diagnostics or {}
    rows = []
    for key in [
        "total_asset",
        "reserved_cash",
        "planned_investable_cash",
        "initial_allocated_cash",
        "released_budget",
        "redistributed_cash",
        "actual_invested_cash",
        "unavoidable_residual_cash",
        "cash_ratio_after_allocation",
        "maximum_cash_ratio",
        "capital_utilization_rate",
        "cash_cap_exception",
        "cash_cap_exception_reason",
    ]:
        value = data.get(key, "")
        if key.endswith("_ratio") or key.endswith("_rate"):
            value = _format_weight(value)
        elif key == "cash_cap_exception":
            value = "是" if bool(value) else "否"
        elif key != "cash_cap_exception_reason":
            value = _format_money(value or 0)
        rows.append({"项目": display_label(key), "数值": value})
    return pd.DataFrame(rows).astype(str)


def build_allocation_detail_table(diagnostics: dict[str, Any] | None) -> pd.DataFrame:
    details = list((diagnostics or {}).get("allocation_details") or [])
    if not details:
        return pd.DataFrame()
    rows = []
    for item in details:
        rows.append(
            {
                "股票代码": str(item.get("stock_code") or "").zfill(6),
                "股票名称": item.get("stock_name", ""),
                "排名": item.get("final_rank", ""),
                "综合调整": item.get("combined_adjustment", ""),
                "仓位调整比例": _format_weight(item.get("position_adjustment_ratio", 1.0)),
                "理想目标仓位": _format_weight(item.get("ideal_target_weight", item.get("target_weight"))),
                "初始分配金额": _format_money(item.get("initial_target_amount")),
                "初始数量": item.get("initial_quantity", 0),
                "最终数量": item.get("final_quantity", 0),
                "最终仓位": _format_weight(item.get("final_weight")),
                "一手总成本": _format_money(item.get("one_lot_total_cost")),
                "释放预算": _format_money(item.get("released_budget")),
                "获得再分配": _format_money(item.get("received_redistribution")),
                "移除轮次": item.get("removed_round", ""),
                "未执行原因": item.get("unexecuted_reason") or item.get("cannot_execute_reason") or item.get("removed_reason", ""),
            }
        )
    return pd.DataFrame(rows).astype(str)


def build_decision_attribution_summary_table(payload: dict[str, Any] | None) -> pd.DataFrame:
    data = payload or {}
    formal = data.get("formal_recommendation") or {}
    decision = data.get("paper_decision") or {}
    allocation = data.get("allocation_trace") or {}
    formula = data.get("formula_check") or {}
    sources = data.get("sources") or {}
    rows = [
        {"项目": "股票", "数值": f"{data.get('stock_code', '')} {formal.get('stock_name') or decision.get('stock_name') or ''}".strip()},
        {"项目": "交易日期", "数值": data.get("trade_date", "")},
        {"项目": "原始排名/分数", "数值": f"{formal.get('original_rank', '')} / {formal.get('original_score', '')}"},
        {"项目": "新闻调整", "数值": formal.get("news_adjustment", "")},
        {"项目": "用户调整", "数值": formal.get("user_adjustment", "")},
        {"项目": "有效新闻调整", "数值": formal.get("effective_news_adjustment", "")},
        {"项目": "综合调整", "数值": formal.get("combined_adjustment", "")},
        {"项目": "仓位调整比例", "数值": formal.get("position_adjustment_ratio", "")},
        {"项目": "推荐目标仓位", "数值": _format_weight(formal.get("target_weight", 0))},
        {"项目": "模拟盘动作", "数值": action_label(decision.get("paper_action") or decision.get("action") or "")},
        {"项目": "当前仓位", "数值": _format_weight(decision.get("current_weight", 0))},
        {"项目": "执行目标仓位", "数值": _format_weight(decision.get("target_weight", 0))},
        {"项目": "执行数量", "数值": decision.get("order_quantity", "")},
        {"项目": "执行金额", "数值": _format_money(decision.get("order_amount", 0))},
        {"项目": "交易费用", "数值": _format_money(decision.get("total_fee", 0))},
        {"项目": "分配策略", "数值": allocation.get("strategy_mode", "")},
        {"项目": "一手约束相关轮次", "数值": len(allocation.get("lot_execution_rounds") or [])},
        {"项目": "公式核对", "数值": _format_structured_value({
            "effective": formula.get("effective_news_adjustment_matches"),
            "combined": formula.get("combined_adjustment_matches"),
            "ratio": formula.get("position_adjustment_ratio_matches"),
        })},
        {"项目": "推荐来源", "数值": sources.get("recommendation", "")},
        {"项目": "模拟盘决策来源", "数值": sources.get("paper_decision", "")},
        {"项目": "执行诊断来源", "数值": sources.get("diagnostics", "")},
    ]
    return pd.DataFrame(rows).astype(str)


def build_portfolio_construction_diagnostic_table(diagnostics: dict[str, Any] | None, account: dict[str, Any] | None = None, risk_report: dict[str, Any] | None = None) -> pd.DataFrame:
    data = diagnostics or {}
    account = account or {}
    risk_report = risk_report or {}
    rows = [
        {"项目": "原始 Top10 数量", "数值": data.get("initial_top10_count", "")},
        {"项目": "AI 调整股票数量", "数值": data.get("ai_adjustment_count", data.get("candidate_count", ""))},
        {"项目": "递归处理轮次数", "数值": len(data.get("lot_execution_rounds", []) or [])},
        {"项目": "因一手约束移除", "数值": data.get("removed_candidate_count", "")},
        {"项目": "权限阻断候选数", "数值": data.get("permission_blocked_count", 0)},
        {"项目": "权限阻断股票", "数值": _format_structured_value([
            {
                "stock_code": item.get("stock_code"),
                "reason": item.get("reason_code"),
            }
            for item in data.get("permission_blocked_candidates", []) or []
        ])},
        {"项目": "权限冻结仓位", "数值": _format_weight(data.get("permission_frozen_weight", 0))},
        {"项目": "移除股票", "数值": _format_structured_value([item.get("stock_code") for item in data.get("removed_candidates", []) or []])},
        {"项目": "释放仓位", "数值": _format_weight(sum(_safe_float(item.get("released_weight"), 0) for item in data.get("removed_candidates", []) or []))},
        {"项目": "成功重新分配仓位", "数值": _format_money(data.get("redistributed_cash", 0))},
        {"项目": "最终未分配仓位", "数值": _format_weight(data.get("unallocated_ratio", 0))},
        {"项目": "最终可执行股票数量", "数值": data.get("executable_candidate_count", data.get("target_position_count", ""))},
        {"项目": "最大单股仓位", "数值": _format_weight(data.get("maximum_position_weight", risk_report.get("max_single_position", "")))},
        {"项目": "主候选实际仓位", "数值": _format_weight(data.get("actual_top10_ratio", 0))},
        {"项目": "缓冲仓位", "数值": _format_weight(data.get("top11_15_bucket_weight", 0))},
        {"项目": "实际持仓数量", "数值": risk_report.get("position_count", "")},
        {"项目": "实际持仓比例", "数值": _format_weight(risk_report.get("invested_ratio", data.get("actual_top10_ratio", 0)))},
        {"项目": "现金比例", "数值": _format_weight(risk_report.get("cash_ratio", data.get("cash_ratio_after_allocation", 0)))},
        {"项目": "未分配原因", "数值": _format_structured_value(data.get("unallocated_reason") or data.get("reasons") or "")},
    ]
    return pd.DataFrame(rows).astype(str)


def build_daily_audit_source_table(record: dict[str, Any] | None) -> pd.DataFrame:
    sources = (record or {}).get("sources") or {}
    rows = [
        {"项目": "原始排名来源", "数值": sources.get("original_ranking_file_path", "")},
        {"项目": "原始排名哈希", "数值": sources.get("original_ranking_file_hash", "")},
        {"项目": "原始排名 run_id", "数值": sources.get("original_ranking_run_id", "")},
        {"项目": "原始排名模型版本", "数值": sources.get("original_ranking_model_version", "")},
        {"项目": "AI 修正来源", "数值": sources.get("ai_adjustment_file_path", "")},
        {"项目": "AI 修正哈希", "数值": sources.get("ai_adjustment_file_hash", "")},
        {"项目": "AI 修正 run_id", "数值": sources.get("ai_adjustment_run_id", "")},
        {"项目": "历史价格来源", "数值": sources.get("historical_price_source", "")},
        {"项目": "用户配置版本", "数值": sources.get("user_config_version", "")},
        {"项目": "手续费配置版本", "数值": sources.get("fee_config_version", "")},
    ]
    return pd.DataFrame(rows).astype(str)


def build_daily_audit_validation_table(record: dict[str, Any] | None) -> pd.DataFrame:
    validation = (record or {}).get("validation") or {}
    rows = [
        {"项目": "当日状态", "数值": (record or {}).get("status", "")},
        {"项目": "原始排名数量", "数值": validation.get("original_ranking_count", "")},
        {"项目": "AI 修正数量", "数值": validation.get("ai_adjustment_count", "")},
        {"项目": "对齐股票数量", "数值": validation.get("aligned_stock_count", "")},
        {"项目": "重复排名数量", "数值": validation.get("duplicate_rank_count", "")},
        {"项目": "重复股票数量", "数值": validation.get("duplicate_stock_count", "")},
        {"项目": "缺 AI 股票", "数值": _format_structured_value(validation.get("missing_ai_stock_codes", []))},
        {"项目": "缺价格股票", "数值": _format_structured_value(validation.get("missing_price_stock_codes", []))},
        {"项目": "日期匹配", "数值": "是" if validation.get("date_match") else "否"},
        {"项目": "校验错误", "数值": _format_structured_value(validation.get("validation_errors", []))},
    ]
    return pd.DataFrame(rows).astype(str)


def build_daily_audit_decision_summary_table(record: dict[str, Any] | None) -> pd.DataFrame:
    summary = (record or {}).get("decision_summary") or {}
    account = (record or {}).get("closing_account") or {}
    rows = [
        {"项目": "Top10 数量", "数值": summary.get("top10_count", "")},
        {"项目": "AI 调整数量", "数值": summary.get("ai_adjusted_count", "")},
        {"项目": "递归轮次数", "数值": summary.get("recursive_round_count", "")},
        {"项目": "一手约束排除", "数值": summary.get("lot_removed_count", "")},
        {"项目": "开盘持仓数量", "数值": summary.get("opening_position_count", "")},
        {"项目": "买入数量", "数值": summary.get("buy_count", "")},
        {"项目": "卖出数量", "数值": summary.get("sell_count", "")},
        {"项目": "收盘持仓数量", "数值": summary.get("closing_position_count", "")},
        {"项目": "实际主组合仓位", "数值": _format_weight(summary.get("actual_top10_ratio", 0))},
        {"项目": "实际现金比例", "数值": _format_weight(summary.get("cash_ratio", 0))},
        {"项目": "账户总资产", "数值": _format_money(account.get("total_assets", 0))},
        {"项目": "账户现金", "数值": _format_money(account.get("cash", 0))},
        {"项目": "持仓市值", "数值": _format_money(account.get("position_market_value", 0))},
    ]
    return pd.DataFrame(rows).astype(str)


def build_cash_flow_table(flows: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    type_map = {"deposit": "追加资金", "withdrawal": "减少资金"}
    status_map = {"pending": "待生效", "applied": "已生效", "rejected": "已拒绝", "cancelled": "已取消"}
    for item in flows or []:
        rows.append(
            {
                "日期": item.get("effective_date", ""),
                "类型": type_map.get(str(item.get("flow_type") or ""), item.get("flow_type", "")),
                "金额": _format_money(item.get("amount") or 0),
                "状态": status_map.get(str(item.get("status") or ""), item.get("status", "")),
                "备注": item.get("reason", ""),
                "创建时间": item.get("created_at", ""),
                "生效时间": item.get("applied_at", ""),
                "流水编号": item.get("cash_flow_id", ""),
            }
        )
    return pd.DataFrame(rows)


def build_today_action_table(decisions: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for item in decisions or []:
        rows.append(
            {
                "股票代码": str(item.get("stock_code") or "").zfill(6),
                "股票名称": item.get("stock_name", ""),
                "模拟盘执行": action_label(item.get("paper_action")),
                "目标仓位": _format_weight(item.get("target_weight")),
                "当前仓位": _format_weight(item.get("current_weight")),
                "订单金额": _format_money(item.get("order_amount")),
                "订单数量": item.get("order_quantity", ""),
                "成交价格": item.get("executed_price", ""),
                "新闻调整": item.get("news_adjustment", ""),
                "用户调整": item.get("user_adjustment", ""),
                "有效新闻调整": item.get("effective_news_adjustment", ""),
                "综合调整": item.get("combined_adjustment", ""),
                "仓位调整比例": _format_weight(item.get("position_adjustment_ratio", 1.0)),
                "调仓理由": item.get("reason", ""),
                "风险提示": item.get("risk_warning", ""),
            }
        )
    return pd.DataFrame(rows)


def build_current_position_table(positions: pd.DataFrame) -> pd.DataFrame:
    if positions.empty:
        return positions
    df = positions.copy()
    for column in ["stock_code", "stock_name", "quantity", "market_value", "cost_price", "current_price", "unrealized_pnl", "position_ratio", "industry"]:
        if column not in df.columns:
            df[column] = ""
    df["股票代码"] = df["stock_code"].astype(str).str.zfill(6)
    df["股票名称"] = df["stock_name"]
    df["持仓数量"] = df["quantity"]
    df["持仓市值"] = df["market_value"]
    df["成本价"] = df["cost_price"]
    df["当前价"] = df["current_price"]
    df["浮动盈亏"] = df["unrealized_pnl"]
    df["仓位占比"] = pd.to_numeric(df["position_ratio"], errors="coerce").map(_format_weight)
    df["行业"] = df["industry"]
    return df[["股票代码", "股票名称", "持仓数量", "持仓市值", "成本价", "当前价", "浮动盈亏", "仓位占比", "行业"]]


def build_order_history_table(orders: pd.DataFrame) -> pd.DataFrame:
    if orders.empty:
        return orders
    df = orders.copy()
    quantity = pd.to_numeric(df.get("quantity", 0), errors="coerce").fillna(0)
    raw_action = df.get("paper_action", df.get("action", "")).astype(str)
    df = df[(quantity > 0) & raw_action.isin(["paper_buy", "paper_sell", "paper_reduce", "buy", "sell"])].copy()
    if df.empty:
        return pd.DataFrame()
    df["日期"] = df.get("trade_date", "")
    df["时间"] = df.get("decision_time", df.get("created_at", ""))
    df["股票代码"] = df.get("stock_code", "").astype(str).str.zfill(6)
    df["股票名称"] = df.get("stock_name", "")
    df["动作"] = raw_action.map(action_label)
    df["数量"] = df.get("quantity", "")
    df["价格"] = df.get("executed_price", "")
    df["金额"] = df.get("order_amount", "")
    df["调仓理由"] = df.get("reason", "")
    return df[["日期", "时间", "股票代码", "股票名称", "动作", "数量", "价格", "金额", "调仓理由"]]


def _render_cash_cap_warning(risk_report: dict[str, Any], diagnostics: dict[str, Any], settings: dict[str, Any]) -> None:
    try:
        cash_ratio = float(risk_report.get("cash_ratio") or 0.0)
        maximum_cash_ratio = float(settings.get("maximum_cash_ratio") or diagnostics.get("maximum_cash_ratio") or 0.30)
    except Exception:
        return
    if cash_ratio <= maximum_cash_ratio:
        return
    reason = diagnostics.get("cash_cap_exception_reason") or "当前现金比例超过 30%，但不存在可合法执行的 Top10 买入候选。"
    legal_count = int(float(diagnostics.get("legal_candidate_count_after_allocation") or 0))
    st.warning(
        f"当前现金比例 {_format_weight(cash_ratio)} 超过最高现金比例 {_format_weight(maximum_cash_ratio)}。"
        f"是否存在可执行 Top10 候选：{'是' if legal_count > 0 else '否'}。超限原因：{reason}"
    )


def _render_user_profile_settings(
    user_id: str,
    user_context: dict[str, Any] | None,
    output_dir: str | Path,
    db_path: str | Path | None,
) -> dict[str, Any]:
    context = dict(user_context or {})
    options = get_classic_user_profile_form_options()
    initial_capital = _safe_float(
        context.get("available_capital") or context.get("initial_capital"),
        DEFAULT_INITIAL_CASH,
    )
    profile_ready = has_required_paper_trading_profile(context)
    permission_state = normalize_trading_permissions(
        context.get("trading_permissions")
    )

    with st.expander("用户画像与初始资产", expanded=not profile_ready):
        st.caption("初始模拟资产会保存为用户画像的 available_capital；首次创建模拟账户和历史回放会使用该金额。已有账户不会被直接覆盖，后续资金变化请使用下方资金管理。")
        with st.form(key=f"user_profile_form_{user_id}"):
            row1 = st.columns(3)
            nickname = row1[0].text_input("昵称", value=str(context.get("nickname") or ""))
            initial_capital_value = row1[1].number_input(
                "初始模拟资产",
                min_value=0.0,
                value=float(initial_capital),
                step=10000.0,
            )
            income_level = row1[2].text_input("收入水平", value=str(context.get("income_level") or ""))

            row2 = st.columns(4)
            age_range = row2[0].selectbox(
                "年龄区间",
                options=options["age_range"],
                index=_option_index(options["age_range"], context.get("age_range"), 1),
            )
            income_stability = row2[1].selectbox(
                "收入稳定性",
                options=options["income_stability"],
                index=_option_index(options["income_stability"], context.get("income_stability"), 1),
            )
            investment_experience = row2[2].selectbox(
                "投资经验",
                options=options["investment_experience"],
                index=_option_index(options["investment_experience"], context.get("investment_experience"), 2),
            )
            liquidity_need = row2[3].selectbox(
                "流动性需求",
                options=options["liquidity_need"],
                index=_option_index(options["liquidity_need"], context.get("liquidity_need"), 1),
            )

            row3 = st.columns(4)
            risk_level = row3[0].selectbox(
                "风险等级",
                options=options["risk_level"],
                index=_option_index(options["risk_level"], context.get("risk_level"), 2),
            )
            max_drawdown_tolerance = row3[1].selectbox(
                "最大回撤容忍",
                options=options["max_drawdown_tolerance"],
                index=_option_index(options["max_drawdown_tolerance"], context.get("max_drawdown_tolerance"), 2),
            )
            single_loss_tolerance = row3[2].selectbox(
                "单笔亏损容忍",
                options=options["single_loss_tolerance"],
                index=_option_index(options["single_loss_tolerance"], context.get("single_loss_tolerance"), 1),
            )
            volatility_tolerance = row3[3].selectbox(
                "波动容忍",
                options=options["volatility_tolerance"],
                index=_option_index(options["volatility_tolerance"], context.get("volatility_tolerance"), 1),
            )

            row4 = st.columns(4)
            investment_horizon = row4[0].selectbox(
                "投资期限",
                options=options["investment_horizon"],
                index=_option_index(options["investment_horizon"], context.get("investment_horizon"), 2),
            )
            goal_type = row4[1].selectbox(
                "投资目标",
                options=options["goal_type"],
                index=_option_index(options["goal_type"], context.get("goal_type"), 4),
            )
            target_return = row4[2].selectbox(
                "目标收益",
                options=options["target_return"],
                index=_option_index(options["target_return"], context.get("target_return"), 2),
            )
            target_period = row4[3].selectbox(
                "目标周期",
                options=options["target_period"],
                index=_option_index(options["target_period"], context.get("target_period"), 2),
            )

            row5 = st.columns(4)
            priority = row5[0].selectbox(
                "目标优先级",
                options=options["priority"],
                index=_option_index(options["priority"], context.get("priority"), 1),
            )
            capital_usage = row5[1].selectbox(
                "资金用途",
                options=options["capital_usage"],
                index=_option_index(options["capital_usage"], context.get("capital_usage"), 1),
            )
            trading_style = row5[2].selectbox(
                "交易风格",
                options=options["trading_style"],
                index=_option_index(options["trading_style"], context.get("trading_style"), 1),
            )
            holding_period_preference = row5[3].text_input(
                "持仓周期偏好",
                value=str(context.get("holding_period_preference") or "中线"),
            )

            row6 = st.columns(3)
            preferred_industries = row6[0].multiselect(
                "偏好行业",
                options=options["preferred_industries"],
                default=[item for item in _list_value(context.get("preferred_industries")) if item in options["preferred_industries"]],
            )
            avoided_industries = row6[1].multiselect(
                "规避行业",
                options=options["avoided_industries"],
                default=[item for item in _list_value(context.get("avoided_industries")) if item in options["avoided_industries"]],
            )
            allow_high_volatility = row6[2].checkbox(
                "允许高波动资产",
                value=bool(context.get("allow_high_volatility", False)),
            )

            st.markdown("**股票交易权限**")
            st.caption(
                "权限是模拟盘硬约束。未开通对应权限的股票不会新增买入或加仓；"
                "已有持仓仍可持有、减仓或卖出。"
            )
            row7 = st.columns(3)
            permission_main_board = row7[0].checkbox(
                TRADING_PERMISSION_LABELS["main_board"],
                value=permission_state["main_board"],
                key=f"permission_main_board_{user_id}",
            )
            permission_chinext = row7[1].checkbox(
                TRADING_PERMISSION_LABELS["chinext"],
                value=permission_state["chinext"],
                key=f"permission_chinext_{user_id}",
            )
            permission_star_market = row7[2].checkbox(
                TRADING_PERMISSION_LABELS["star_market"],
                value=permission_state["star_market"],
                key=f"permission_star_market_{user_id}",
            )

            row8 = st.columns(3)
            permission_bse = row8[0].checkbox(
                TRADING_PERMISSION_LABELS["bse"],
                value=permission_state["bse"],
                key=f"permission_bse_{user_id}",
            )
            permission_risk_warning = row8[1].checkbox(
                TRADING_PERMISSION_LABELS["risk_warning"],
                value=permission_state["risk_warning"],
                key=f"permission_risk_warning_{user_id}",
            )
            permission_stock_connect = row8[2].checkbox(
                TRADING_PERMISSION_LABELS["stock_connect"],
                value=permission_state["stock_connect"],
                key=f"permission_stock_connect_{user_id}",
            )

            submitted = st.form_submit_button("保存用户画像与初始资产")

        if submitted:
            payload = build_user_profile_payload(
                user_id,
                {
                    "nickname": nickname,
                    "initial_capital": initial_capital_value,
                    "income_level": income_level,
                    "age_range": age_range,
                    "income_stability": income_stability,
                    "investment_experience": investment_experience,
                    "liquidity_need": liquidity_need,
                    "risk_level": risk_level,
                    "max_drawdown_tolerance": max_drawdown_tolerance,
                    "single_loss_tolerance": single_loss_tolerance,
                    "volatility_tolerance": volatility_tolerance,
                    "investment_horizon": investment_horizon,
                    "goal_type": goal_type,
                    "target_return": target_return,
                    "target_period": target_period,
                    "priority": priority,
                    "capital_usage": capital_usage,
                    "preferred_industries": preferred_industries,
                    "avoided_industries": avoided_industries,
                    "holding_period_preference": holding_period_preference,
                    "allow_high_volatility": allow_high_volatility,
                    "trading_style": trading_style,
                    "trading_permissions": {
                        "main_board": permission_main_board,
                        "chinext": permission_chinext,
                        "star_market": permission_star_market,
                        "bse": permission_bse,
                        "risk_warning": permission_risk_warning,
                        "stock_connect": permission_stock_connect,
                    },
                },
            )
            result = save_classic_user_context(payload, db_path=db_path, output_dir=output_dir)
            context = load_classic_user_context(
                user_id,
                db_path=db_path,
                output_dir=output_dir,
            ) or payload
            permission_state = normalize_trading_permissions(
                context.get("trading_permissions")
            )
            st.success(
                f"用户画像与初始资产已保存："
                f"{result.get('status', 'saved')}"
            )

        st.caption(
            "当前已开通权限："
            + format_permission_summary(
                context.get("trading_permissions")
            )
        )

    return context


def build_asset_curve_chart_data(nav_history: pd.DataFrame) -> pd.DataFrame:
    if nav_history.empty:
        return pd.DataFrame()
    nav_df = nav_history.copy()
    nav_df["trade_date"] = pd.to_datetime(nav_df.get("trade_date"), errors="coerce")
    for column in ["total_assets", "net_contribution", "position_market_value", "cash"]:
        if column in nav_df.columns:
            nav_df[column] = pd.to_numeric(nav_df[column], errors="coerce")
        else:
            nav_df[column] = 0.0
    chart_df = nav_df.dropna(subset=["trade_date"]).set_index("trade_date")
    return chart_df[list(ASSET_CURVE_COLUMNS)].rename(columns=ASSET_CURVE_COLUMNS)


def build_asset_curve_table(nav_history: pd.DataFrame) -> pd.DataFrame:
    if nav_history.empty:
        return pd.DataFrame()
    nav_df = nav_history.copy()
    nav_df["trade_date"] = pd.to_datetime(nav_df.get("trade_date"), errors="coerce")
    for column in [
        "total_assets",
        "net_contribution",
        "position_market_value",
        "cash",
        "daily_deposit",
        "daily_withdrawal",
        "daily_profit",
        "daily_return",
        "daily_fee",
        "cumulative_fee",
    ]:
        if column in nav_df.columns:
            nav_df[column] = pd.to_numeric(nav_df[column], errors="coerce")
        else:
            nav_df[column] = 0.0
    display_columns = [
        "trade_date",
        "total_assets",
        "net_contribution",
        "position_market_value",
        "cash",
        "daily_deposit",
        "daily_withdrawal",
        "daily_profit",
        "daily_return",
        "daily_fee",
        "cumulative_fee",
    ]
    return nav_df[display_columns].tail(30).rename(
        columns={
            "trade_date": "交易日期",
            "total_assets": "账户总资产",
            "net_contribution": "净投入资金",
            "position_market_value": "持仓市值",
            "cash": "现金",
            "daily_deposit": "当日入金",
            "daily_withdrawal": "当日出金",
            "daily_profit": "当日盈亏",
            "daily_return": "当日收益率",
            "daily_fee": "当日手续费",
            "cumulative_fee": "累计手续费",
        }
    )


def _render_composite_nav(nav_history: pd.DataFrame) -> None:
    if nav_history.empty:
        return
    st.subheader(ASSET_CURVE_TITLE)
    st.caption("主曲线使用真实人民币金额：账户总资产 = 现金 + 持仓市值；净投入资金用于区分外部入金/出金，不把资金流误算为收益。")
    chart_df = build_asset_curve_chart_data(nav_history)
    if not chart_df.empty:
        st.line_chart(chart_df)
    table = build_asset_curve_table(nav_history)
    if not table.empty:
        st.dataframe(table, width="stretch")


def render(
    user_id: str = "default",
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
    top_k: int = 10,
    user_context: dict[str, Any] | None = None,
) -> None:
    st.title(AI_PAPER_TRADING_PAGE_TITLE)
    st.warning(AI_PAPER_TRADING_DISCLAIMER)

    user_context = user_context or load_classic_user_context(user_id, db_path=db_path, output_dir=output_dir)
    user_context = _render_user_profile_settings(user_id, user_context, output_dir, db_path)
    st.caption(
        "当前交易权限："
        + format_permission_summary(
            user_context.get("trading_permissions")
        )
    )
    st.caption(FIXED_PAPER_STRATEGY_TEXT)
    profile_ready = has_required_paper_trading_profile(user_context)
    if not profile_ready:
        st.info("请先填写用户画像和模拟盘资金量。")

    if st.button("更新 AI 模拟盘", disabled=not profile_ready):
        try:
            sync_event_cache_to_agent_db(
                db_path=db_path,
                output_dir=output_dir,
            )
            ranking_path = Path(output_dir) / "ranking_latest.csv"
            if not ranking_path.exists():
                st.error("缺少 outputs/ranking_latest.csv，请先执行“每日更新并生成预测排名”。")
            else:
                result = run_paper_trading_from_latest(
                    user_id=user_id,
                    output_dir=output_dir,
                    db_path=db_path,
                    dry_run=False,
                    paper_trading_enabled=True,
                    top_k=max(10, int(top_k)),
                )
                if getattr(result, "status", "") in {PipelineStatus.FAILED, "failed"}:
                    st.error(result.message)
                else:
                    clear_ai_paper_trading_page_cache()
                    st.success("AI 模拟盘已按当前 ranking_latest.csv 更新，未调用模型生成。")
        except Exception as exc:
            st.error(f"AI 模拟盘更新失败：{exc}")

    snapshot = load_cached_paper_trading_snapshot(user_id, output_dir=output_dir, db_path=db_path)
    reliability_state = load_cached_ai_reliability_state(user_id, output_dir=output_dir)
    account = snapshot.get("account") or {}
    risk_report = snapshot.get("risk_report") or {}
    diagnostics = snapshot.get("execution_diagnostics") or {}
    settings = snapshot.get("trading_settings") or {}

    st.subheader("用户与账户摘要")
    for row in build_capital_summary_rows(account, risk_report, reliability_state, user_id, diagnostics):
        cols = st.columns(len(row))
        for col, item in zip(cols, row):
            with col:
                render_compact_metric(item["label"], item["value"], streamlit_module=st)
    _render_cash_cap_warning(risk_report, diagnostics, settings)

    with st.expander("资金分配详情", expanded=False):
        st.caption("Stage 5O 分层 Top10：Top1-5 的 12 和 Top6-10 的 5 是基础分配权重，不是最终账户百分比；最终会按新闻、用户、风险修正后重新归一化到 Top10 目标 80%。")
        st.dataframe(build_allocation_summary_table(diagnostics), width="stretch")
        detail_df = build_allocation_detail_table(diagnostics)
        if detail_df.empty:
            st.info("暂无 Top10 分配明细。")
        else:
            st.dataframe(detail_df, width="stretch")

    with st.expander("当日组合构建诊断", expanded=False):
        st.caption("该诊断用于检查 stored ranking / stored AI adjustment、固定原始 Top10、30% 单股上限和递归一手约束后的组合构建结果。")
        st.dataframe(build_portfolio_construction_diagnostic_table(diagnostics, account, risk_report), width="stretch")

    with st.expander("单股决策归因", expanded=False):
        decisions = snapshot.get("decisions") or []
        options: dict[str, str] = {}
        for item in decisions:
            code = str(item.get("stock_code") or "").split(".")[0].zfill(6)
            if not code.strip("0"):
                continue
            name = str(item.get("stock_name") or "")
            options[f"{code} {name}".strip()] = code
        if not options:
            st.info("暂无可归因的模拟盘决策。")
        else:
            selected_label = st.selectbox(
                "选择股票",
                options=list(options.keys()),
                index=0,
                key=f"decision_attribution_stock_{user_id}",
            )
            selected_code = options[selected_label]
            selected_record = next(
                (
                    item
                    for item in decisions
                    if str(item.get("stock_code") or "").split(".")[0].zfill(6) == selected_code
                ),
                {},
            )
            selected_trade_date = str(selected_record.get("trade_date") or "")
            attribution = explain_stock_decision_attribution(
                user_id=user_id,
                stock_code=selected_code,
                trade_date=selected_trade_date or None,
                output_dir=output_dir,
                db_path=db_path,
            )
            for warning in attribution.get("warnings") or []:
                st.warning(warning)
            st.dataframe(build_decision_attribution_summary_table(attribution), width="stretch")
            with st.expander("查看归因说明", expanded=False):
                st.markdown(render_decision_attribution_markdown(attribution))
            with st.expander("查看归因 JSON", expanded=False):
                st.json(_redact_paper_ui_payload(attribution))

    st.subheader("每日决策审计")
    audit_runs = list_replay_audit_runs(user_id)
    if not audit_runs:
        st.info("暂无历史回放决策审计日志。执行带 audit-log 的历史回放后可在这里查看每日买卖原因。")
    else:
        audit_cols = st.columns(2)
        selected_run_id = audit_cols[0].selectbox("回放 run_id", options=audit_runs, index=0, key=f"replay_audit_run_{user_id}")
        audit_dates = list_replay_audit_dates(user_id, selected_run_id)
        if not audit_dates:
            audit_cols[1].info("该 run 暂无每日审计记录。")
        else:
            selected_audit_date = audit_cols[1].selectbox("交易日期", options=audit_dates, index=0, key=f"replay_audit_date_{user_id}_{selected_run_id}")
            audit_record = load_replay_audit_day(user_id, selected_run_id, selected_audit_date)
            audit_markdown = load_replay_audit_markdown(user_id, selected_run_id, selected_audit_date)
            st.dataframe(build_daily_audit_source_table(audit_record), width="stretch")
            st.dataframe(build_daily_audit_validation_table(audit_record), width="stretch")
            st.dataframe(build_daily_audit_decision_summary_table(audit_record), width="stretch")
            with st.expander("原始排名"):
                st.dataframe(pd.DataFrame(audit_record.get("original_ranking") or []), width="stretch")
            with st.expander("已保存 AI 修正"):
                st.dataframe(pd.DataFrame(audit_record.get("stored_ai_adjustments") or []), width="stretch")
            with st.expander("候选过滤"):
                st.dataframe(pd.DataFrame(audit_record.get("candidate_filtering") or []), width="stretch")
            with st.expander("权重分配与一手轮次"):
                st.json(
                    _redact_paper_ui_payload({
                        "weight_allocation": audit_record.get("weight_allocation") or {},
                        "lot_execution": audit_record.get("lot_execution") or {},
                    })
                )
            with st.expander("买入原因"):
                st.dataframe(pd.DataFrame(audit_record.get("buy_decisions") or []), width="stretch")
            with st.expander("卖出原因"):
                st.dataframe(pd.DataFrame(audit_record.get("sell_decisions") or []), width="stretch")
            with st.expander("查看 JSON"):
                st.json(_redact_paper_ui_payload(audit_record))
            with st.expander("查看 Markdown"):
                st.code(audit_markdown, language="markdown")
            st.download_button(
                "导出当日审计记录",
                data=json.dumps(audit_record, ensure_ascii=False, indent=2),
                file_name=f"replay_audit_{selected_audit_date.replace('-', '')}.json",
                mime="application/json",
            )

    nav_history = snapshot.get("nav_history")
    if isinstance(nav_history, pd.DataFrame):
        _render_composite_nav(nav_history)

    st.subheader("历史回放")
    result_key = f"paper_backfill_result_{user_id}"
    if st.session_state.get(result_key):
        latest_result = st.session_state[result_key]
        st.success(
            "历史回放已完成："
            f"完成 {latest_result.get('completed_days', 0)} 天，"
            f"买入 {latest_result.get('buy_order_count', 0)} 笔，"
            f"卖出 {latest_result.get('sell_order_count', 0)} 笔。"
        )
        with st.expander("查看最近一次回放结果", expanded=False):
            st.json(_redact_paper_ui_payload(latest_result))
    start_date_value = st.date_input(
        "模拟起始日期",
        value=date.fromisoformat(DEFAULT_PAPER_TRADING_START_DATE),
        key=f"paper_backfill_start_{user_id}",
    )
    end_date_value = st.text_input("结束日期", value="latest", key=f"paper_backfill_end_{user_id}")
    st.caption("点击后会备份旧结果，并从所选起始日重新生成历史模拟盘交易。默认从 2026-04-01 开始。")
    if st.button("重新执行历史回放", key=f"paper_backfill_run_{user_id}"):
        start_text = _format_date(start_date_value)
        try:
            with st.spinner(f"正在从 {start_text} 重新生成历史模拟盘交易..."):
                result = execute_tool(
                    "backfill.preview",
                    {
                        "user_id": user_id,
                        "start_date": start_text,
                        "end_date": end_date_value or "latest",
                        "initial_cash": float(user_context.get("available_capital") or DEFAULT_INITIAL_CASH),
                        "resume": False,
                        "force": True,
                        "skip_news": False,
                        "strategy": FIXED_PAPER_STRATEGY["strategy"],
                        "top_k": FIXED_PAPER_STRATEGY["top_k"],
                        "entry_top_k": FIXED_PAPER_STRATEGY["entry_top_k"],
                        "hold_buffer_rank": FIXED_PAPER_STRATEGY["hold_buffer_rank"],
                        "max_positions": FIXED_PAPER_STRATEGY["max_positions"],
                        "continue_on_error": True,
                    },
                    context=_write_tool_context(user_id, output_dir, db_path),
                    agent_type=AGENT_MAIN,
                )
                if result.success:
                    st.session_state[f"paper_backfill_pending_plan_{user_id}"] = dict(result.data or {})
                    st.success(result.message)
                else:
                    st.error(result.message)
                st.json(_redact_paper_ui_payload(result.to_dict()))
                return
                result = _legacy_direct_write_disabled(
                    user_id=user_id,
                    start_date=start_text,
                    end_date=end_date_value or "latest",
                    initial_cash=float(user_context.get("available_capital") or DEFAULT_INITIAL_CASH),
                    resume=False,
                    force=True,
                    skip_news=False,
                    strategy=FIXED_PAPER_STRATEGY["strategy"],
                    top_k=FIXED_PAPER_STRATEGY["top_k"],
                    entry_top_k=FIXED_PAPER_STRATEGY["entry_top_k"],
                    hold_buffer_rank=FIXED_PAPER_STRATEGY["hold_buffer_rank"],
                    max_positions=FIXED_PAPER_STRATEGY["max_positions"],
                    continue_on_error=True,
                    output_dir=output_dir,
                    db_path=db_path,
            )
            clear_ai_paper_trading_page_cache()
            st.session_state[result_key] = _result_payload(result)
            st.rerun()
        except Exception as exc:
            st.error(f"历史回放失败：{exc}")
    _render_write_proposal_confirmation(
        user_id=user_id,
        plan=st.session_state.get(f"paper_backfill_pending_plan_{user_id}"),
        state_key=f"paper_backfill_pending_plan_{user_id}",
        output_dir=output_dir,
        db_path=db_path,
        result_key=result_key,
    )
    backfill_status = load_paper_backfill_status(user_id, output_dir=output_dir)
    if backfill_status:
        with st.expander("回放进度"):
            st.json(_redact_paper_ui_payload(backfill_status))

    st.subheader("资金管理")
    flows = load_cached_paper_cash_flows(user_id, output_dir=output_dir, db_path=db_path)
    flow_cols = st.columns(4)
    operation_label = flow_cols[0].selectbox("资金操作", options=["追加资金", "减少资金"], index=0, key=f"cash_flow_type_{user_id}")
    amount_value = flow_cols[1].number_input("金额", min_value=0.0, value=0.0, step=10000.0, key=f"cash_flow_amount_{user_id}")
    effective_date_value = flow_cols[2].date_input("生效日期", value=date.today(), key=f"cash_flow_date_{user_id}")
    reason_value = flow_cols[3].text_input("备注", value="", key=f"cash_flow_reason_{user_id}")
    if st.button("确认资金变更", key=f"cash_flow_add_{user_id}"):
        try:
            result = execute_tool(
                "capital.change.preview",
                {
                    "user_id": user_id,
                    "flow_type": "deposit" if operation_label == "杩藉姞璧勯噾" else "withdrawal",
                    "amount": float(amount_value),
                    "effective_date": _format_date(effective_date_value),
                    "reason": reason_value,
                },
                context=_write_tool_context(user_id, output_dir, db_path),
                agent_type=AGENT_MAIN,
            )
            if result.success:
                st.session_state[f"capital_change_pending_plan_{user_id}"] = dict(result.data or {})
                st.success(result.message)
            else:
                st.error(result.message)
            st.json(_redact_paper_ui_payload(result.to_dict()))
            return
            flow = _legacy_direct_write_disabled(
                user_id=user_id,
                flow_type="deposit" if operation_label == "追加资金" else "withdrawal",
                amount=float(amount_value),
                effective_date=_format_date(effective_date_value),
                reason=reason_value,
                output_dir=output_dir,
                db_path=db_path,
            )
            clear_ai_paper_trading_page_cache()
            st.success("资金流水已记录；如生效日期在历史区间内，需要从该日期重新回放。")
            st.json(_redact_paper_ui_payload(flow))
        except Exception as exc:
            st.error(f"资金变更失败：{exc}")
    _render_write_proposal_confirmation(
        user_id=user_id,
        plan=st.session_state.get(f"capital_change_pending_plan_{user_id}"),
        state_key=f"capital_change_pending_plan_{user_id}",
        output_dir=output_dir,
        db_path=db_path,
    )
    pending_flows = [item for item in flows if item.get("status") == "pending"]
    if pending_flows:
        cancel_id = st.selectbox("取消待生效资金变更", options=[item["cash_flow_id"] for item in pending_flows], key=f"cash_flow_cancel_id_{user_id}")
        if st.button("取消待生效资金变更", key=f"cash_flow_cancel_{user_id}"):
            try:
                st.json(_redact_paper_ui_payload(cancel_pending_paper_cash_flow(cancel_id, user_id, output_dir=output_dir, db_path=db_path)))
                clear_ai_paper_trading_page_cache()
                st.success("待生效资金流水已取消。")
            except Exception as exc:
                st.error(f"取消失败：{exc}")
    flow_table = build_cash_flow_table(load_cached_paper_cash_flows(user_id, output_dir=output_dir, db_path=db_path))
    if flow_table.empty:
        st.info("暂无历史资金流水。")
    else:
        st.dataframe(flow_table, width="stretch")

    st.subheader("今日模拟盘动作")
    action_df = build_today_action_table(snapshot.get("decisions") or [])
    if action_df.empty:
        st.info("暂无今日模拟盘动作。")
    else:
        st.dataframe(action_df, width="stretch")

    st.subheader("当前持仓")
    position_df = build_current_position_table(snapshot.get("positions", pd.DataFrame()))
    if position_df.empty:
        st.info("当前没有模拟持仓。")
        diagnostic_rows = [
            {"项目": "候选股票总数", "数值": diagnostics.get("candidate_count", 0)},
            {"项目": "数值调整候选数量", "数值": diagnostics.get("ai_adjustment_count", diagnostics.get("candidate_count", 0))},
            {"项目": "目标仓位大于 0", "数值": diagnostics.get("positive_target_weight_count", 0)},
            {"项目": "有效价格数量", "数值": diagnostics.get("valid_price_count", 0)},
            {"项目": "买得起一手数量", "数值": diagnostics.get("affordable_lot_count", 0)},
            {"项目": "最终买入订单数量", "数值": diagnostics.get("executable_order_count", 0)},
            {"项目": "主要原因", "数值": "；".join(diagnostics.get("reasons", []) or [])},
        ]
        st.dataframe(pd.DataFrame(diagnostic_rows).astype(str), width="stretch")
    else:
        st.dataframe(position_df, width="stretch")

    st.subheader("历史订单")
    order_dates = snapshot.get("order_snapshot_dates") or []
    if not order_dates:
        st.info("暂无历史订单。")
    else:
        selected_order_date = st.selectbox("历史订单日期", options=order_dates, index=0)
        raw_order_history = load_cached_daily_order_snapshot(user_id, selected_order_date, output_dir)
        if raw_order_history.empty and isinstance(snapshot.get("orders"), pd.DataFrame):
            orders_df = snapshot.get("orders").copy()
            if "trade_date" in orders_df.columns:
                raw_order_history = orders_df[
                    pd.to_datetime(orders_df["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
                    == str(selected_order_date)
                ].copy()
        order_history_df = build_order_history_table(raw_order_history)
        if order_history_df.empty:
            st.info("该日期没有模拟订单。")
        else:
            st.dataframe(order_history_df, width="stretch")

    st.subheader("每日持仓快照")
    dates = snapshot.get("position_snapshot_dates") or list_daily_position_snapshot_dates(user_id, output_dir=output_dir)
    if not dates:
        st.info("暂无每日持仓快照。")
    else:
        selected_date = st.selectbox("选择日期", options=dates, index=0)
        raw_position_snapshot = load_cached_daily_position_snapshot(user_id, selected_date, output_dir)
        if raw_position_snapshot.empty and isinstance(snapshot.get("positions"), pd.DataFrame):
            raw_position_snapshot = snapshot.get("positions")
        st.dataframe(build_current_position_table(raw_position_snapshot), width="stretch")

    st.subheader("组合风险")
    risk_rows = [
        {"项目": "单股集中度", "数值": _format_weight(risk_report.get("max_single_position", ""))},
        {"项目": "行业集中度", "数值": _format_structured_value(risk_report.get("industry_concentration", {}))},
        {"项目": "高风险资产占比", "数值": _format_weight(risk_report.get("high_risk_position_ratio", ""))},
        {"项目": "现金比例", "数值": _format_weight(risk_report.get("cash_ratio", ""))},
        {"项目": "组合风险等级", "数值": risk_level_label(risk_report.get("risk_level"))},
        {"项目": "风险提示", "数值": "；".join(str(item) for item in risk_report.get("risk_warnings", []) or [])},
    ]
    st.dataframe(pd.DataFrame(risk_rows).astype(str), width="stretch")


# Alias for app.py import
render_ai_paper_trading_page = render
