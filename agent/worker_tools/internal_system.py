"""Private read-only tools for W02 internal system data queries."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import pandas as pd

from agent.collaboration.agent_directory import PORTFOLIO_ANALYST
from agent.graph.provider_adapter import GraphProviderAdapter
from agent.services.market_analysis_service import market_analysis_service
from agent.services.portfolio_service import portfolio_service
from agent.services.user_profile_service import user_profile_service
from agent.tool_runtime import (
    OP_READ,
    TOOL_VISIBILITY_WORKER_PRIVATE,
    ToolDefinition,
    description,
    result_schema,
    schema,
)
from application.web_read_service import web_read_service
from core.config.paths import BACKTEST_MASTER_TABLE_PATH


INTERNAL_PREDICTION_GET_STOCK = "internal.prediction.get_stock"
INTERNAL_RANKING_GET_LATEST = "internal.ranking.get_latest"
INTERNAL_MODEL_GET_METRICS = "internal.model.get_metrics"
INTERNAL_BACKTEST_GET_SUMMARY = "internal.backtest.get_summary"
INTERNAL_STRATEGY_GET_SELECTED = "internal.strategy.get_selected"
INTERNAL_PORTFOLIO_GET_STATE = "internal.portfolio.get_state"
INTERNAL_ACCOUNT_GET_STATE = "internal.account.get_state"
INTERNAL_USER_PROFILE_GET = "internal.user_profile.get"


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.DataFrame):
        return [_jsonable(row) for row in value.to_dict(orient="records")]
    if isinstance(value, pd.Series):
        return _jsonable(value.to_dict())
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _jsonable(value.item())
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)



def _prediction_record(row: dict[str, Any]) -> dict[str, Any]:
    result = _jsonable(dict(row or {}))
    if not isinstance(result, dict):
        return {}
    for key in (
        "pred_5d_ret", "up_prob", "score", "confidence", "ret_5",
        "ret_20", "vol_20", "drawdown_20", "risk_score", "pred_score",
    ):
        if key not in result or result[key] in (None, ""):
            continue
        try:
            result[key] = float(result[key])
        except (TypeError, ValueError):
            pass
    for key in ("rank", "pred_rank"):
        if key not in result or result[key] in (None, ""):
            continue
        try:
            result[key] = int(float(result[key]))
        except (TypeError, ValueError):
            pass
    return result

def _output_dir(context: dict[str, Any]) -> str | Path:
    return context.get("output_dir") or "outputs"


def _stock_code(arguments: dict[str, Any]) -> str:
    text = str(arguments.get("security_node_id") or "")
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", text)
    if not match:
        raise ValueError("authoritative_security_graph_ref_required")
    return match.group(1)


def _read_backtest_frame() -> pd.DataFrame:
    path = Path(BACKTEST_MASTER_TABLE_PATH)
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(path)


def build_internal_system_tool_definitions(
    provider: GraphProviderAdapter,
) -> list[ToolDefinition]:
    """Bind W02 private tools to current project services."""

    def get_prediction(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        code = _stock_code(arguments)
        top_k = max(1, min(int(arguments.get("top_k") or 10), 500))
        result = market_analysis_service.get_ranking(
            stock_code=code,
            top_k="all_rows",
            output_dir=_output_dir(context),
            model_name=str(arguments.get("model_name") or "") or None,
        )
        records = [dict(row) for row in result.get("records") or [] if isinstance(row, dict)]
        total_count = int(result.get("total_count") or 0)
        if not result.get("success"):
            return {
                "success": False,
                "message": str(result.get("message") or "Latest ranking is unavailable."),
                "data": {
                    "found": False,
                    "record": {},
                    "data_date": str(result.get("as_of_date") or ""),
                    "rank": None,
                    "is_topk": False,
                    "total_count": total_count,
                    "source_id": "ranking_latest",
                    "reason": "ranking_data_unavailable",
                },
                "warnings": [],
                "errors": ["ranking_data_unavailable"],
                "sources": [{"source_id": "ranking_latest"}],
            }
        record = records[0] if records else {}
        raw_rank = record.get("rank", record.get("pred_rank"))
        try:
            rank = int(float(raw_rank)) if raw_rank not in (None, "") else None
        except (TypeError, ValueError):
            rank = None
        return {
            "success": True,
            "message": "Stock prediction queried." if record else "Stock is not present in the latest prediction universe.",
            "data": {
                "found": bool(record),
                "record": _prediction_record(record),
                "data_date": str(result.get("as_of_date") or ""),
                "rank": rank,
                "is_topk": bool(rank is not None and rank <= top_k),
                "total_count": total_count,
                "source_id": "ranking_latest",
                "reason": "" if record else "stock_not_in_prediction_universe",
            },
            "warnings": [],
            "errors": [],
            "sources": [{"source_id": "ranking_latest", "as_of_date": str(result.get("as_of_date") or "")}],
        }

    def get_ranking(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        top_k = max(1, min(int(arguments.get("top_k") or 10), 500))
        result = market_analysis_service.get_ranking(
            top_k=top_k,
            output_dir=_output_dir(context),
            model_name=str(arguments.get("model_name") or "") or None,
        )
        return {
            "success": bool(result.get("success")),
            "message": str(result.get("message") or ""),
            "data": {
                "records": _jsonable(result.get("records") or []),
                "summary": _jsonable(result.get("summary") or {}),
                "data_date": str(result.get("as_of_date") or ""),
                "source_id": "ranking_latest",
            },
            "warnings": [],
            "errors": [] if result.get("success") else [str(result.get("status") or "ranking_data_unavailable")],
            "sources": [{"source_id": "ranking_latest"}],
        }

    def get_metrics(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        value = _jsonable(web_read_service.metrics())
        model_name = str(arguments.get("model_name") or "").strip().lower()
        if model_name and isinstance(value, list):
            selected = [row for row in value if model_name in str(row.get("model_name") or row.get("model") or "").lower()]
            if selected:
                value = selected
        found = value not in (None, {}, [])
        return {
            "success": found,
            "message": "Model metrics queried." if found else "Model metrics are unavailable.",
            "data": {"metrics": value if found else {}, "model_name": str(arguments.get("model_name") or ""), "source_id": "model_metrics"},
            "warnings": [],
            "errors": [] if found else ["model_metrics_unavailable"],
            "sources": [{"source_id": "model_metrics"}],
        }

    def get_backtest(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        frame = _read_backtest_frame()
        if frame.empty:
            return {
                "success": False,
                "message": "Backtest summary is unavailable.",
                "data": {"records": [], "summary": {}, "source_id": "backtest_master_table"},
                "warnings": [],
                "errors": ["backtest_data_unavailable"],
                "sources": [{"source_id": "backtest_master_table"}],
            }
        data = frame.copy()
        model_name = str(arguments.get("model_name") or "").strip().lower()
        if model_name:
            for column in ("model_name", "model", "backend"):
                if column in data.columns:
                    matched = data[data[column].astype(str).str.lower().str.contains(model_name, regex=False, na=False)]
                    if not matched.empty:
                        data = matched
                        break
        for arg_name, columns in {
            "top_k": ("top_k", "topk", "k"),
            "holding_period": ("holding_period", "hold_days", "holding_days"),
        }.items():
            raw = arguments.get(arg_name)
            if raw in (None, ""):
                continue
            for column in columns:
                if column in data.columns:
                    matched = data[pd.to_numeric(data[column], errors="coerce") == int(raw)]
                    if not matched.empty:
                        data = matched
                        break
        records = _jsonable(data.head(100))
        return {
            "success": True,
            "message": "Backtest summary queried.",
            "data": {"records": records, "summary": {"returned_count": len(records)}, "source_id": "backtest_master_table"},
            "warnings": [],
            "errors": [],
            "sources": [{"source_id": "backtest_master_table"}],
        }

    def get_strategy(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        value = _jsonable(web_read_service.selected_strategy())
        found = bool(value)
        return {
            "success": True,
            "message": "Selected strategy queried." if found else "No selected strategy is configured.",
            "data": {"found": found, "strategy": value or {}, "source_id": "selected_strategy"},
            "warnings": [], "errors": [], "sources": [{"source_id": "selected_strategy"}],
        }

    def get_portfolio(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        return provider.load_portfolio_snapshot(
            user_id=str(arguments.get("user_id") or context.get("user_id") or "default"),
            output_dir=_output_dir(context),
            db_path=context.get("db_path"),
            as_of_time=str(arguments.get("as_of_time") or ""),
            source_task_id=str(context.get("task_id") or ""),
            source_agent_id=str(context.get("agent_role") or ""),
        )

    def get_account(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        value = portfolio_service.get_account_summary(
            str(arguments.get("user_id") or context.get("user_id") or "default"),
            output_dir=_output_dir(context),
            db_path=context.get("db_path"),
        )
        return {"success": True, "message": "Account state queried.", "data": _jsonable(value), "warnings": [], "errors": [], "sources": []}

    def get_profile(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        return user_profile_service.get_user_profile(
            str(arguments.get("user_id") or context.get("user_id") or "default"),
            output_dir=_output_dir(context),
            db_path=context.get("db_path"),
        )

    specs = [
        (INTERNAL_PREDICTION_GET_STOCK, "Query Stock Prediction", get_prediction, ["security_node_id"], ["prediction"]),
        (INTERNAL_RANKING_GET_LATEST, "Query Latest Ranking", get_ranking, [], ["ranking"]),
        (INTERNAL_MODEL_GET_METRICS, "Query Model Metrics", get_metrics, [], ["model_metrics"]),
        (INTERNAL_BACKTEST_GET_SUMMARY, "Query Backtest Summary", get_backtest, [], ["backtest_summary"]),
        (INTERNAL_STRATEGY_GET_SELECTED, "Query Selected Strategy", get_strategy, [], ["selected_strategy"]),
        (INTERNAL_PORTFOLIO_GET_STATE, "Query Portfolio State", get_portfolio, ["user_id"], ["portfolio_state"]),
        (INTERNAL_ACCOUNT_GET_STATE, "Query Account State", get_account, ["user_id"], ["account_state"]),
        (INTERNAL_USER_PROFILE_GET, "Query User Profile", get_profile, ["user_id"], ["user_profile"]),
    ]
    definitions: list[ToolDefinition] = []
    for name, display, handler, required, outputs in specs:
        properties = {
            "security_node_id": {"type": "string"},
            "user_id": {"type": "string"},
            "top_k": {"type": "integer"},
            "model_name": {"type": "string"},
            "trade_date": {"type": "string"},
            "holding_period": {"type": "integer"},
            "as_of_time": {"type": "string"},
        }
        definitions.append(
            ToolDefinition(
                name=name,
                display_name=display,
                description=description(
                    "Read authoritative structured data already produced by this application.",
                    "W02 needs one internal system fact for a declared task contract.",
                    "External news retrieval, risk conclusions, recommendations, proposals, or writes.",
                    "Only task-contract fields and runtime-bound identity values.",
                    "A normalized read-only internal data result.",
                ),
                input_schema=schema(properties, required=required),
                output_schema=result_schema([]),
                execution_handler=handler,
                supported_actions=[name.rsplit(".", 1)[-1]],
                supported_objects=["internal_system_data"],
                produced_outputs=outputs,
                operation_type=OP_READ,
                allowed_agent_types=[PORTFOLIO_ANALYST],
                permission_scope=OP_READ,
                visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
                side_effects=[],
                mutates_business_state=False,
                idempotency="read_only",
                audit_level="full",
                tags=["worker_private", "internal_system", "read_only"],
            )
        )
    return definitions


__all__ = [
    "INTERNAL_PREDICTION_GET_STOCK",
    "INTERNAL_RANKING_GET_LATEST",
    "INTERNAL_MODEL_GET_METRICS",
    "INTERNAL_BACKTEST_GET_SUMMARY",
    "INTERNAL_STRATEGY_GET_SELECTED",
    "INTERNAL_PORTFOLIO_GET_STATE",
    "INTERNAL_ACCOUNT_GET_STATE",
    "INTERNAL_USER_PROFILE_GET",
    "build_internal_system_tool_definitions",
]
