from __future__ import annotations

from portfolio.schemas import PaperOrder, now_text
from portfolio.trading_cost_config import calculate_trade_cost, normalize_order_action


VALID_ACTIONS = {"buy", "sell", "hold", "reduce"}


def create_paper_order(
    user_id: str,
    trade_date: str,
    stock_code: str,
    action: str,
    target_weight: float,
    executed_price: float,
    quantity: float,
    reason: str,
    stock_name: str = "",
    account_id: str = "",
    order_id: str | None = None,
    decision_id: str = "",
    decision_time: str = "",
    paper_action: str = "",
    current_weight: float = 0.0,
    order_amount: float | None = None,
    risk_warning: str = "",
    triggered_rules: str = "",
    job_id: str = "",
    run_id: str = "",
    execution_source: str = "",
    gross_amount: float | None = None,
    commission_fee: float | None = None,
    other_fee: float | None = None,
    slippage_cost: float | None = None,
    total_fee: float | None = None,
    net_cash_change: float | None = None,
    applied_buy_cost_rate: float | None = None,
    applied_sell_cost_rate: float | None = None,
) -> PaperOrder:
    if action not in VALID_ACTIONS:
        raise ValueError(f"invalid paper order action: {action}")
    normalized_action = normalize_order_action(action)
    if normalized_action not in {"buy", "sell", "hold"}:
        normalized_action = action
    stock_code = str(stock_code).split(".")[0].zfill(6)
    order_id = order_id or f"paper_order_{user_id}_{trade_date}_{stock_code}_{normalized_action}"
    gross = float(gross_amount if gross_amount is not None else float(executed_price) * float(quantity))
    costs = calculate_trade_cost(normalized_action, gross)
    costs["commission_fee"] = float(commission_fee if commission_fee is not None else costs["commission_fee"])
    costs["other_fee"] = float(other_fee if other_fee is not None else costs["other_fee"])
    costs["slippage_cost"] = float(slippage_cost if slippage_cost is not None else costs["slippage_cost"])
    costs["total_fee"] = float(total_fee if total_fee is not None else costs["total_fee"])
    costs["net_cash_change"] = float(net_cash_change if net_cash_change is not None else costs["net_cash_change"])
    costs["applied_buy_cost_rate"] = float(
        applied_buy_cost_rate if applied_buy_cost_rate is not None else costs["applied_buy_cost_rate"]
    )
    costs["applied_sell_cost_rate"] = float(
        applied_sell_cost_rate if applied_sell_cost_rate is not None else costs["applied_sell_cost_rate"]
    )
    return PaperOrder(
        order_id=order_id,
        user_id=user_id,
        account_id=account_id,
        trade_date=trade_date,
        stock_code=stock_code,
        stock_name=stock_name,
        action=normalized_action,
        target_weight=float(target_weight),
        executed_price=float(executed_price),
        quantity=float(quantity),
        reason=reason,
        decision_id=decision_id,
        decision_time=decision_time,
        paper_action=paper_action or f"paper_{normalized_action}",
        current_weight=float(current_weight or 0.0),
        order_amount=float(order_amount if order_amount is not None else gross),
        gross_amount=float(costs["gross_amount"]),
        commission_fee=float(costs["commission_fee"]),
        other_fee=float(costs["other_fee"]),
        slippage_cost=float(costs["slippage_cost"]),
        total_fee=float(costs["total_fee"]),
        net_cash_change=float(costs["net_cash_change"]),
        applied_buy_cost_rate=float(costs["applied_buy_cost_rate"]),
        applied_sell_cost_rate=float(costs["applied_sell_cost_rate"]),
        risk_warning=risk_warning,
        triggered_rules=triggered_rules,
        job_id=job_id,
        run_id=run_id,
        execution_source=execution_source,
        is_paper_trading=True,
        created_at=now_text(),
    )
