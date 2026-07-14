from __future__ import annotations

from typing import Any

from portfolio.paper_position import create_position
from portfolio.schemas import PaperAccount, PaperPosition, now_text


def _stock_code(value: Any) -> str:
    return str(value or "").split(".")[0].zfill(6)


def is_valid_mark_price(value: Any) -> bool:
    try:
        price = float(value)
    except Exception:
        return False
    return price > 0


def price_lookup_from_candidates(candidates: list[dict[str, Any]]) -> dict[str, float]:
    lookup: dict[str, float] = {}
    for item in candidates:
        code = _stock_code(item.get("stock_code") or item.get("code"))
        for key in ["current_price", "close", "price", "executed_price"]:
            value = item.get(key)
            if is_valid_mark_price(value):
                lookup[code] = float(value)
                break
    return lookup


def mark_to_market_positions(
    positions: list[PaperPosition],
    price_lookup: dict[str, float] | None,
    total_assets: float,
) -> list[PaperPosition]:
    marked: list[PaperPosition] = []
    for position in positions:
        code = _stock_code(position.stock_code)
        price = float(position.current_price or 0.0)
        if price_lookup and is_valid_mark_price(price_lookup.get(code)):
            price = float(price_lookup[code])
        marked.append(
            create_position(
                user_id=position.user_id,
                stock_code=code,
                stock_name=position.stock_name,
                quantity=position.quantity,
                cost_price=position.cost_price,
                current_price=price,
                total_assets=total_assets,
                industry=position.industry,
                position_id=position.position_id,
            )
        )
    return marked


def build_nav_record(
    account: PaperAccount,
    trade_date: str,
    positions: list[PaperPosition],
    previous_total_assets: float | None = None,
    previous_twr: float | None = None,
    previous_nav_peak: float | None = None,
    daily_deposit: float = 0.0,
    daily_withdrawal: float = 0.0,
    daily_fee: float = 0.0,
) -> dict[str, Any]:
    position_market_value = sum(float(item.market_value or 0.0) for item in positions)
    cash = float(account.cash or 0.0)
    total_assets = cash + position_market_value
    net_contribution = (
        float(account.initial_cash or 0.0)
        + float(account.cumulative_deposit or 0.0)
        - float(account.cumulative_withdrawal or 0.0)
    )
    previous = float(previous_total_assets if previous_total_assets is not None else account.total_assets or total_assets)
    external_cash_flow = float(daily_deposit or 0.0) - float(daily_withdrawal or 0.0)
    daily_profit = total_assets - external_cash_flow - previous
    daily_return = daily_profit / previous if previous > 0 else 0.0
    prior_twr = float(previous_twr if previous_twr is not None else account.time_weighted_return or 0.0)
    twr = (1.0 + prior_twr) * (1.0 + daily_return) - 1.0
    absolute_profit = total_assets - net_contribution
    cumulative_return = absolute_profit / net_contribution if net_contribution > 0 else 0.0
    composite_nav = 1.0 + twr
    nav = composite_nav
    peak = max(float(previous_nav_peak or 1.0), composite_nav)
    drawdown = composite_nav / peak - 1.0 if peak > 0 else 0.0
    return {
        "nav_id": f"paper_nav_{account.user_id}_{str(trade_date).replace('-', '')}",
        "user_id": account.user_id,
        "account_id": account.account_id,
        "trade_date": trade_date,
        "cash": cash,
        "position_market_value": position_market_value,
        "total_assets": total_assets,
        "net_contribution": net_contribution,
        "daily_deposit": float(daily_deposit or 0.0),
        "daily_withdrawal": float(daily_withdrawal or 0.0),
        "daily_fee": float(daily_fee or 0.0),
        "cumulative_fee": float(account.cumulative_fee or 0.0),
        "daily_profit": daily_profit,
        "daily_return": daily_return,
        "cumulative_return": cumulative_return,
        "time_weighted_return": twr,
        "composite_nav": composite_nav,
        "nav": nav,
        "nav_peak": peak,
        "drawdown": drawdown,
        "position_count": len([item for item in positions if float(item.quantity or 0.0) > 0]),
        "updated_at": now_text(),
    }


def apply_nav_to_account(account: PaperAccount, nav_record: dict[str, Any]) -> PaperAccount:
    total_assets = float(nav_record.get("total_assets") or account.total_assets or 0.0)
    net_contribution = float(nav_record.get("net_contribution") or account.net_contribution or 0.0)
    return PaperAccount(
        account_id=account.account_id,
        user_id=account.user_id,
        initial_cash=account.initial_cash,
        cash=float(nav_record.get("cash") or account.cash or 0.0),
        total_assets=total_assets,
        daily_return=float(nav_record.get("daily_return") or 0.0),
        cumulative_return=float(nav_record.get("cumulative_return") or 0.0),
        max_drawdown=min(float(account.max_drawdown or 0.0), float(nav_record.get("drawdown") or 0.0)),
        cumulative_deposit=account.cumulative_deposit,
        cumulative_withdrawal=account.cumulative_withdrawal,
        net_contribution=net_contribution,
        absolute_profit=total_assets - net_contribution,
        time_weighted_return=float(nav_record.get("time_weighted_return") or 0.0),
        daily_fee=float(nav_record.get("daily_fee") or 0.0),
        cumulative_fee=float(nav_record.get("cumulative_fee") or account.cumulative_fee or 0.0),
        position_market_value=float(nav_record.get("position_market_value") or 0.0),
        composite_nav=float(nav_record.get("composite_nav") or nav_record.get("nav") or 1.0),
        nav=float(nav_record.get("composite_nav") or nav_record.get("nav") or 1.0),
        drawdown=float(nav_record.get("drawdown") or 0.0),
        is_paper_trading=True,
        updated_at=now_text(),
    )
