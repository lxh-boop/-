"""Atomic read-only tools for the W04 Risk Analyst.

These tools calculate or expose structured facts only. They do not decide the
user-facing risk conclusion, choose a proposal, or mutate business state. W04's
LLM interprets their structured outputs under its prompt and schema.
"""

from __future__ import annotations

from typing import Any

from agent.collaboration.worker_directory import RISK_ANALYST
from agent.tool_runtime import (
    OP_READ,
    TOOL_VISIBILITY_WORKER_PRIVATE,
    ToolDefinition,
    description,
    result_schema,
    schema,
)

RISK_CALCULATE_CONCENTRATION = "risk.calculate_concentration"
RISK_READ_ACCOUNT_RISK_FACTS = "risk.read_account_risk_facts"
RISK_SUMMARIZE_EXPOSURE = "risk.summarize_exposure"
RISK_FINALIZE_FACTS = "risk.finalize_facts"


def _unwrap(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    data = value.get("data")
    if isinstance(data, dict):
        return data
    return value


def _positions(value: Any) -> list[dict[str, Any]]:
    root = _unwrap(value)
    for key in ("display_positions", "positions", "holdings"):
        rows = root.get(key)
        if isinstance(rows, list):
            return [dict(item) for item in rows if isinstance(item, dict)]
    nested = root.get("portfolio_state")
    if isinstance(nested, dict):
        return _positions(nested)
    return []


def _number(row: dict[str, Any], *keys: str) -> float:
    for key in keys:
        raw = row.get(key)
        if raw in (None, ""):
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return 0.0


def build_risk_tool_definitions() -> list[ToolDefinition]:
    def concentration(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        del context
        rows = _positions(arguments.get("portfolio_state"))
        values = [max(0.0, _number(row, "market_value", "position_market_value")) for row in rows]
        total = sum(values)
        weights = [value / total for value in values] if total > 0 else []
        sorted_weights = sorted(weights, reverse=True)
        return {
            "success": True,
            "message": "Portfolio concentration facts calculated.",
            "data": {
                "position_count": len(rows),
                "position_market_value": total,
                "largest_position_weight": sorted_weights[0] if sorted_weights else 0.0,
                "top3_weight": sum(sorted_weights[:3]),
                "herfindahl_index": sum(weight * weight for weight in weights),
                "weights": [
                    {
                        "security_ref": str(row.get("security_ref") or row.get("graph_ref") or row.get("stock_code") or ""),
                        "weight": weights[index] if index < len(weights) else 0.0,
                    }
                    for index, row in enumerate(rows)
                ],
                "business_empty": not bool(rows),
            },
            "warnings": [],
            "errors": [],
            "sources": [{"source_id": "upstream_portfolio_state"}],
        }

    def account_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        del context
        root = _unwrap(arguments.get("portfolio_state"))
        account = root.get("account_snapshot") if isinstance(root.get("account_snapshot"), dict) else {}
        totals = root.get("portfolio_totals") if isinstance(root.get("portfolio_totals"), dict) else {}
        summary = root.get("portfolio_summary") if isinstance(root.get("portfolio_summary"), dict) else {}
        merged = {**summary, **totals, **account}
        keys = (
            "cash", "available_cash", "uninvested_cash", "total_assets", "position_market_value_sum",
            "position_market_value", "cash_ratio", "position_ratio", "max_drawdown", "daily_return",
            "total_return", "time_weighted_return",
        )
        facts = {key: merged.get(key) for key in keys if key in merged}
        return {
            "success": True,
            "message": "Account and portfolio risk facts read.",
            "data": {
                "account_risk_facts": facts,
                "as_of_time": str(root.get("as_of_time") or account.get("as_of_time") or ""),
                "business_empty": not bool(root),
            },
            "warnings": [],
            "errors": [],
            "sources": [{"source_id": "upstream_account_snapshot"}],
        }

    def exposure(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        del context
        rows = _positions(arguments.get("portfolio_state"))
        by_industry: dict[str, float] = {}
        by_market: dict[str, float] = {}
        unresolved = 0
        for row in rows:
            value = max(0.0, _number(row, "market_value", "position_market_value"))
            industry = str(row.get("industry") or row.get("sector") or "").strip()
            market = str(row.get("exchange") or row.get("market") or "").strip()
            if industry:
                by_industry[industry] = by_industry.get(industry, 0.0) + value
            else:
                unresolved += 1
            if market:
                by_market[market] = by_market.get(market, 0.0) + value
        total = sum(max(0.0, _number(row, "market_value", "position_market_value")) for row in rows)
        normalize = lambda mapping: {
            key: (value / total if total > 0 else 0.0) for key, value in mapping.items()
        }
        return {
            "success": True,
            "message": "Portfolio exposure facts summarized.",
            "data": {
                "industry_exposure": normalize(by_industry),
                "market_exposure": normalize(by_market),
                "unresolved_industry_count": unresolved,
                "position_count": len(rows),
                "business_empty": not bool(rows),
            },
            "warnings": (["industry_metadata_incomplete"] if unresolved else []),
            "errors": [],
            "sources": [{"source_id": "upstream_portfolio_positions"}],
        }

    def finalize(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        del context
        collections = arguments.get("collections") or []
        if not isinstance(collections, list):
            collections = [collections]
        facts: list[dict[str, Any]] = []
        source_refs: list[str] = []
        limitations: list[str] = []
        successful = 0
        for item in collections:
            if not isinstance(item, dict):
                continue
            data = item.get("data") if isinstance(item.get("data"), dict) else item
            success = bool(item.get("success", True))
            if success:
                successful += 1
                facts.append(dict(data or {}))
            source_refs.extend(str(src.get("source_id") or "") for src in item.get("sources") or [] if isinstance(src, dict))
            limitations.extend(str(w) for w in item.get("warnings") or [])
        return {
            "success": successful > 0,
            "message": "Risk facts finalized." if successful else "No risk fact tool completed.",
            "data": {
                "risk_facts": facts,
                "source_refs": list(dict.fromkeys(item for item in source_refs if item)),
                "limitations": list(dict.fromkeys(limitations)),
                "source_tool_count": len(collections),
                "successful_tool_count": successful,
                "business_empty": bool(facts) and all(bool(item.get("business_empty")) for item in facts),
            },
            "warnings": list(dict.fromkeys(limitations)),
            "errors": [] if successful else ["risk_fact_tools_failed"],
            "error_type": "risk_fact_tools_failed" if not successful else "",
            "failure_kind": "tool_failure" if not successful else "",
            "retryable": bool(not successful),
            "sources": [{"source_id": item} for item in list(dict.fromkeys(source_refs)) if item],
        }

    common_input = schema({"portfolio_state": {"type": "object"}}, required=["portfolio_state"])
    common = dict(
        operation_type=OP_READ,
        allowed_agent_types=[RISK_ANALYST],
        permission_scope=OP_READ,
        visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
        side_effects=[],
        mutates_business_state=False,
        audit_level="full",
    )
    return [
        ToolDefinition(
            name=RISK_CALCULATE_CONCENTRATION,
            display_name="Calculate Portfolio Concentration",
            description=description(
                "Calculate concentration metrics from the supplied portfolio snapshot.",
                "W04 needs position weights, largest-position share, top-three share, or HHI.",
                "Business risk judgment, proposal generation, persistence, or execution.",
                "A structured upstream portfolio_state.",
                "Deterministic concentration facts.",
            ),
            input_schema=common_input,
            output_schema=result_schema(["largest_position_weight", "top3_weight", "herfindahl_index"]),
            execution_handler=concentration,
            produced_outputs=["largest_position_weight", "top3_weight", "herfindahl_index"],
            idempotency="pure_transform",
            tags=["risk", "concentration", "atomic", "read_only"],
            **common,
        ),
        ToolDefinition(
            name=RISK_READ_ACCOUNT_RISK_FACTS,
            display_name="Read Account Risk Facts",
            description=description(
                "Read structured cash, asset, return and drawdown facts already present in the upstream snapshot.",
                "W04 needs account-level risk facts without another business-state query.",
                "Interpretation, proposals, persistence, or execution.",
                "A structured upstream portfolio_state.",
                "Account risk facts and as-of time.",
            ),
            input_schema=common_input,
            output_schema=result_schema(["account_risk_facts", "as_of_time"]),
            execution_handler=account_risk,
            produced_outputs=["account_risk_facts", "as_of_time"],
            idempotency="read_only",
            tags=["risk", "account", "atomic", "read_only"],
            **common,
        ),
        ToolDefinition(
            name=RISK_SUMMARIZE_EXPOSURE,
            display_name="Summarize Portfolio Exposure",
            description=description(
                "Summarize industry and market exposure from structured positions.",
                "W04 needs exposure facts and metadata coverage limitations.",
                "Business judgment, proposals, persistence, or execution.",
                "A structured upstream portfolio_state.",
                "Exposure maps and unresolved metadata counts.",
            ),
            input_schema=common_input,
            output_schema=result_schema(["industry_exposure", "market_exposure", "unresolved_industry_count"]),
            execution_handler=exposure,
            produced_outputs=["industry_exposure", "market_exposure", "unresolved_industry_count"],
            idempotency="pure_transform",
            tags=["risk", "exposure", "atomic", "read_only"],
            **common,
        ),
        ToolDefinition(
            name=RISK_FINALIZE_FACTS,
            display_name="Finalize Risk Facts",
            description=description(
                "Merge selected atomic risk-tool results into one structured fact bundle for W04 interpretation.",
                "W04 has completed one or more risk fact calculations.",
                "Risk conclusion, recommendation, proposal, persistence, or execution.",
                "collections of normalized Tool results.",
                "risk_facts, source_refs and limitations.",
            ),
            input_schema=schema({"collections": {"type": "array"}}, required=["collections"]),
            output_schema=result_schema(["risk_facts", "source_refs", "limitations"]),
            execution_handler=finalize,
            produced_outputs=["risk_facts", "source_refs", "limitations"],
            idempotency="pure_transform",
            tags=["risk", "finalizer", "atomic", "read_only"],
            **common,
        ),
    ]


__all__ = [
    "RISK_CALCULATE_CONCENTRATION",
    "RISK_READ_ACCOUNT_RISK_FACTS",
    "RISK_SUMMARIZE_EXPOSURE",
    "RISK_FINALIZE_FACTS",
    "build_risk_tool_definitions",
]
