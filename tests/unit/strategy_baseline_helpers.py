from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from portfolio.paper_account import create_default_account
from portfolio.paper_position import create_position
from portfolio.paper_trading_engine import execute_paper_rebalance
from portfolio.rebalance_rules import build_rebalance_plan


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "strategy_default_golden.json"
)


def load_strategy_golden() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def build_strategy_golden_result() -> tuple[dict[str, Any], Any, dict[str, Any]]:
    fixture = load_strategy_golden()
    account_data = fixture["account"]
    account = replace(
        create_default_account("baseline_user", initial_cash=100000.0),
        cash=float(account_data["cash"]),
        total_assets=float(account_data["total_assets"]),
        position_market_value=float(account_data["position_market_value"]),
    )
    positions = [
        create_position(
            "baseline_user",
            item["stock_code"],
            item["stock_name"],
            quantity=float(item["quantity"]),
            cost_price=float(item["cost_price"]),
            current_price=float(item["current_price"]),
            total_assets=float(account_data["total_assets"]),
            industry=item["industry"],
        )
        for item in fixture["positions"]
    ]
    candidates = [
        {
            "stock_code": item["stock_code"],
            "stock_name": f"S{item['rank']}",
            "rank": int(item["rank"]),
            "original_rank": int(item["rank"]),
            "final_score": float(item["score"]),
            "original_score": float(item["score"]),
            "current_price": float(item["price"]),
            "industry": item["industry"],
            "risk_level": "low",
            "is_tradable": True,
            "price_valid": True,
        }
        for item in fixture["ranking"]
    ]
    defaults = fixture["defaults"]
    plan = build_rebalance_plan(
        "baseline_user",
        fixture["trade_date"],
        candidates,
        current_positions=positions,
        account=account,
        top_k=int(defaults["hold_buffer_rank"]),
        target_invested_weight=float(defaults["target_invested_weight"]),
        entry_top_k=int(defaults["entry_top_k"]),
        hold_buffer_rank=int(defaults["hold_buffer_rank"]),
        max_positions=int(defaults["max_positions"]),
        minimum_cash_ratio=float(defaults["minimum_cash_ratio"]),
        min_rebalance_weight_delta=float(
            defaults["min_rebalance_weight_delta"]
        ),
        strategy_mode=defaults["strategy_mode"],
    )
    result = execute_paper_rebalance(account, positions, plan)
    return fixture, plan, result


def normalized_target(plan: Any) -> list[dict[str, Any]]:
    return [
        {
            "stock_code": item.stock_code,
            "action": item.action,
            "target_weight": round(float(item.target_weight), 12),
            "executable_quantity": float(item.executable_quantity),
        }
        for item in plan.decisions
    ]


def normalized_orders(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "stock_code": item.stock_code,
            "action": item.action,
            "quantity": float(item.quantity),
            "executed_price": float(item.executed_price),
            "total_fee": round(float(item.total_fee), 6),
            "net_cash_change": round(float(item.net_cash_change), 6),
        }
        for item in result["orders"]
    ]
