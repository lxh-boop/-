from __future__ import annotations

import math
from typing import Any

from portfolio.paper_account import update_account_metrics
from portfolio.paper_order import create_paper_order
from portfolio.paper_position import create_position, position_from_dict
from portfolio.performance_metrics import mark_to_market_positions
from portfolio.schemas import PaperAccount, PaperOrder, PaperPosition, RebalanceDecision, RebalancePlan
from portfolio.target_weight_allocator import TRADE_LOT_SIZE
from portfolio.trading_cost_config import TradingCostConfig, calculate_trade_cost, default_trading_cost_config
from portfolio.trading_permissions import (
    evaluate_stock_buy_permission,
    normalize_trading_permissions,
)


def _stock_code(value: Any) -> str:
    return str(value or "").split(".")[0].zfill(6)


def _as_position(position: PaperPosition | dict[str, Any], total_assets: float = 0.0) -> PaperPosition:
    if isinstance(position, PaperPosition):
        return position
    return position_from_dict(position, total_assets=total_assets)


def _round_quantity(quantity: float, lot_size: int) -> float:
    if lot_size <= 1:
        return max(0.0, math.floor(quantity))
    return max(0.0, math.floor(quantity / lot_size) * lot_size)


def _decision_price(decision: RebalanceDecision, price_lookup: dict[str, float] | None) -> float:
    code = _stock_code(decision.stock_code)
    if price_lookup and code in price_lookup:
        return float(price_lookup[code])
    return float(decision.current_price or 0.0)


def _source_decision_id(plan: RebalancePlan, decision: RebalanceDecision) -> str:
    return decision.source_decision_id or f"paper_decision_{plan.user_id}_{plan.trade_date}_{_stock_code(decision.stock_code)}"


def _paper_action(action: str) -> str:
    return {
        "buy": "paper_buy",
        "sell": "paper_sell",
        "reduce": "paper_reduce",
        "hold": "paper_hold",
        "watchlist": "paper_watchlist",
    }.get(action, "paper_watchlist")


def _order_meta(
    plan: RebalancePlan,
    decision: RebalanceDecision,
    action: str,
    price: float,
    quantity: float,
    costs: dict[str, float] | None = None,
    decision_time: str = "",
) -> dict[str, Any]:
    costs = costs or calculate_trade_cost(action, float(price or 0.0) * float(quantity or 0.0))
    return {
        "decision_id": _source_decision_id(plan, decision),
        "decision_time": decision_time,
        "paper_action": _paper_action(action),
        "current_weight": decision.current_weight,
        "order_amount": costs["gross_amount"],
        "gross_amount": costs["gross_amount"],
        "commission_fee": costs["commission_fee"],
        "other_fee": costs["other_fee"],
        "slippage_cost": costs["slippage_cost"],
        "total_fee": costs["total_fee"],
        "net_cash_change": costs["net_cash_change"],
        "applied_buy_cost_rate": costs["applied_buy_cost_rate"],
        "applied_sell_cost_rate": costs["applied_sell_cost_rate"],
        "risk_warning": decision.risk_warning,
        "triggered_rules": decision.triggered_rules,
        "job_id": plan.job_id,
        "run_id": plan.run_id,
        "execution_source": plan.execution_source,
        "strategy_id": plan.strategy_id,
        "strategy_version": plan.strategy_version,
        "binding_id": plan.binding_id,
        "config_hash": plan.config_hash,
        "resolved_config": dict(plan.resolved_config or {}),
    }


def _affordable_buy_quantity(raw_quantity: float, cash: float, price: float, config: TradingCostConfig, lot_size: int) -> float:
    quantity = _round_quantity(raw_quantity, lot_size)
    while quantity > 0:
        costs = calculate_trade_cost("buy", quantity * price, config)
        if abs(costs["net_cash_change"]) <= cash + 1e-9:
            return quantity
        quantity -= lot_size if lot_size > 1 else 1
    return 0.0


def _execution_priority(decision: RebalanceDecision, position_map: dict[str, PaperPosition]) -> tuple[int, str]:
    code = _stock_code(decision.stock_code)
    current = position_map.get(code)
    current_weight = float(current.position_ratio or 0.0) if current else 0.0
    target_weight = float(decision.target_weight or 0.0)
    action = str(decision.action or "").lower()
    if action in {"sell", "reduce"} or (current and target_weight < current_weight):
        return (0, code)
    if action == "buy":
        return (1, code)
    return (2, code)


def execute_paper_rebalance(
    account: PaperAccount,
    positions: list[PaperPosition | dict[str, Any]],
    plan: RebalancePlan,
    price_lookup: dict[str, float] | None = None,
    lot_size: int = TRADE_LOT_SIZE,
    decision_time: str = "",
    cost_config: TradingCostConfig | None = None,
    mark_price_lookup: dict[str, float] | None = None,
    persist: bool = False,
    storage: Any | None = None,
    trading_permissions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a rebalance plan in paper-trading mode only."""

    cost_config = cost_config or default_trading_cost_config(account.user_id)
    normalized_permissions = (
        normalize_trading_permissions(
            trading_permissions
        )
    )
    cash = float(account.cash)
    total_assets = float(account.total_assets or account.initial_cash or cash)
    position_map = {
        _stock_code(item.stock_code): item
        for item in (_as_position(position, total_assets=total_assets) for position in positions)
        if item.quantity > 0
    }
    orders: list[PaperOrder] = []
    permission_blocked_orders: list[dict[str, Any]] = []
    daily_fee = 0.0

    ordered_decisions = sorted(plan.decisions, key=lambda item: _execution_priority(item, position_map))
    for decision in ordered_decisions:
        code = _stock_code(decision.stock_code)
        price = _decision_price(decision, price_lookup)
        if price <= 0:
            continue

        current = position_map.get(code)
        current_quantity = float(current.quantity) if current else 0.0
        current_cost = float(current.cost_price) if current else price
        target_value = max(0.0, float(decision.target_weight)) * total_assets
        target_quantity = (
            float(decision.executable_quantity)
            if float(getattr(decision, "executable_quantity", 0.0) or 0.0) > 0
            else _round_quantity(target_value / price, lot_size)
        )
        action = decision.action if decision.action in {"buy", "sell", "hold", "reduce", "watchlist"} else "watchlist"

        if action in {"watchlist"}:
            continue

        if action == "sell" and float(decision.target_weight or 0.0) <= 0:
            target_quantity = 0.0

        delta_quantity = target_quantity - current_quantity
        if action == "reduce" and delta_quantity > 0:
            delta_quantity = 0.0
            target_quantity = current_quantity

        if delta_quantity > 0:
            permission = evaluate_stock_buy_permission(
                code,
                decision.stock_name,
                normalized_permissions,
            )
            if not permission.get("allowed"):
                permission_blocked_orders.append(
                    {
                        **permission,
                        "requested_delta_quantity": (
                            delta_quantity
                        ),
                        "decision_action": action,
                    }
                )
                continue

            buy_quantity = _affordable_buy_quantity(delta_quantity, cash, price, cost_config, lot_size)
            if buy_quantity <= 0:
                continue
            costs = calculate_trade_cost("buy", buy_quantity * price, cost_config)
            cash += costs["net_cash_change"]
            daily_fee += costs["total_fee"]
            new_quantity = current_quantity + buy_quantity
            new_cost = (
                (current_quantity * current_cost + buy_quantity * price) / new_quantity
                if new_quantity > 0
                else price
            )
            position_map[code] = create_position(
                user_id=account.user_id,
                stock_code=code,
                stock_name=decision.stock_name or (current.stock_name if current else ""),
                quantity=new_quantity,
                cost_price=new_cost,
                current_price=price,
                total_assets=total_assets,
                industry=decision.industry or (current.industry if current else ""),
            )
            orders.append(
                create_paper_order(
                    user_id=plan.user_id,
                    account_id=account.account_id,
                    trade_date=plan.trade_date,
                    stock_code=code,
                    stock_name=decision.stock_name,
                    action="buy",
                    target_weight=decision.target_weight,
                    executed_price=price,
                    quantity=buy_quantity,
                    reason=decision.reason,
                    **_order_meta(plan, decision, "buy", price, buy_quantity, costs, decision_time),
                )
            )
        elif delta_quantity < 0:
            sell_quantity = _round_quantity(min(current_quantity, abs(delta_quantity)), lot_size)
            if sell_quantity <= 0:
                continue
            costs = calculate_trade_cost("sell", sell_quantity * price, cost_config)
            cash += costs["net_cash_change"]
            daily_fee += costs["total_fee"]
            new_quantity = current_quantity - sell_quantity
            if new_quantity > 0:
                position_map[code] = create_position(
                    user_id=account.user_id,
                    stock_code=code,
                    stock_name=decision.stock_name or (current.stock_name if current else ""),
                    quantity=new_quantity,
                    cost_price=current_cost,
                    current_price=price,
                    total_assets=total_assets,
                    industry=decision.industry or (current.industry if current else ""),
                )
            else:
                position_map.pop(code, None)
            order_action = "reduce" if action == "reduce" else "sell"
            reason = decision.reason
            if action == "reduce" and "reduce" not in reason.lower():
                reason = f"{reason} reduce intent converted to paper_reduce."
            orders.append(
                create_paper_order(
                    user_id=plan.user_id,
                    account_id=account.account_id,
                    trade_date=plan.trade_date,
                    stock_code=code,
                    stock_name=decision.stock_name,
                    action=order_action,
                    target_weight=decision.target_weight,
                    executed_price=price,
                    quantity=sell_quantity,
                    reason=reason,
                    **_order_meta(plan, decision, order_action, price, sell_quantity, costs, decision_time),
                )
            )
        else:
            continue

    refreshed_positions = []
    temporary_account = PaperAccount(
        account_id=account.account_id,
        user_id=account.user_id,
        initial_cash=account.initial_cash,
        cash=cash,
        total_assets=account.total_assets,
        daily_return=account.daily_return,
        cumulative_return=account.cumulative_return,
        max_drawdown=account.max_drawdown,
        cumulative_deposit=account.cumulative_deposit,
        cumulative_withdrawal=account.cumulative_withdrawal,
        net_contribution=account.net_contribution,
        absolute_profit=account.absolute_profit,
        time_weighted_return=account.time_weighted_return,
        is_paper_trading=True,
    )
    for position in position_map.values():
        refreshed_positions.append(position)

    refreshed_positions = mark_to_market_positions(
        refreshed_positions,
        mark_price_lookup or price_lookup,
        total_assets=total_assets,
    )

    positions_value = sum(float(item.market_value) for item in refreshed_positions)
    updated_account = update_account_metrics(
        temporary_account,
        positions_value=positions_value,
        previous_total_assets=account.total_assets,
        daily_fee=daily_fee,
        cumulative_fee=float(account.cumulative_fee or 0.0) + daily_fee,
    )
    refreshed_positions = [
        create_position(
            user_id=item.user_id,
            stock_code=item.stock_code,
            stock_name=item.stock_name,
            quantity=item.quantity,
            cost_price=item.cost_price,
            current_price=item.current_price,
            total_assets=updated_account.total_assets,
            industry=item.industry,
        )
        for item in refreshed_positions
    ]

    if persist:
        if storage is None:
            from portfolio.storage import PortfolioStorage

            storage = PortfolioStorage()
        storage.save_account(updated_account)
        storage.save_positions(refreshed_positions)
        storage.save_orders(orders)

    return {
        "account": updated_account,
        "positions": refreshed_positions,
        "orders": orders,
        "permission_blocked_orders": (
            permission_blocked_orders
        ),
        "is_paper_trading": True,
        "disclaimer": plan.disclaimer,
    }


def generate_paper_orders(
    account: PaperAccount,
    positions: list[PaperPosition | dict[str, Any]],
    plan: RebalancePlan,
    price_lookup: dict[str, float] | None = None,
    lot_size: int = TRADE_LOT_SIZE,
    trading_permissions: dict[str, Any] | None = None,
) -> list[PaperOrder]:
    return execute_paper_rebalance(
        account=account,
        positions=positions,
        plan=plan,
        price_lookup=price_lookup,
        lot_size=lot_size,
        persist=False,
        trading_permissions=trading_permissions,
    )["orders"]
