from __future__ import annotations

from portfolio.schemas import PaperPosition, now_text


def create_position(
    user_id: str,
    stock_code: str,
    stock_name: str = "",
    quantity: float = 0.0,
    cost_price: float = 0.0,
    current_price: float = 0.0,
    total_assets: float = 0.0,
    industry: str = "",
    position_id: str | None = None,
) -> PaperPosition:
    stock_code = str(stock_code).split(".")[0].zfill(6)
    market_value = float(quantity) * float(current_price)
    cost_value = float(quantity) * float(cost_price)
    unrealized_pnl = market_value - cost_value
    ratio = market_value / float(total_assets) if total_assets and total_assets > 0 else 0.0
    return PaperPosition(
        position_id=position_id or f"pos_{user_id}_{stock_code}",
        user_id=user_id,
        stock_code=stock_code,
        stock_name=stock_name,
        quantity=float(quantity),
        cost_price=float(cost_price),
        current_price=float(current_price),
        market_value=market_value,
        position_ratio=ratio,
        industry=industry,
        unrealized_pnl=unrealized_pnl,
        updated_at=now_text(),
    )


def position_from_dict(data: dict, total_assets: float = 0.0) -> PaperPosition:
    return create_position(
        user_id=str(data.get("user_id") or "default_user"),
        stock_code=str(data.get("stock_code") or data.get("asset_code") or ""),
        stock_name=str(data.get("stock_name") or data.get("asset_name") or ""),
        quantity=float(data.get("quantity") or 0.0),
        cost_price=float(data.get("cost_price") or 0.0),
        current_price=float(data.get("current_price") or 0.0),
        total_assets=float(total_assets or 0.0),
        industry=str(data.get("industry") or ""),
        position_id=str(data.get("position_id") or ""),
    )
