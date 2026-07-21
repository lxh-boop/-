from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from portfolio.paper_strategy_config import DEFAULT_MAXIMUM_CASH_RATIO, DEFAULT_TARGET_CASH_RATIO


DEFAULT_ENTRY_TOP_K = 10
DEFAULT_HOLD_BUFFER_RANK = 15
DEFAULT_MAX_POSITIONS = 10
DEFAULT_MINIMUM_CASH_RATIO = 0.05
DEFAULT_MIN_REBALANCE_WEIGHT_DELTA = 0.01
DEFAULT_BUY_COST_RATE = 0.0003
DEFAULT_SELL_COST_RATE = 0.0008


def now_text() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


@dataclass(frozen=True)
class TradingCostConfig:
    user_id: str = "default"
    entry_top_k: int = DEFAULT_ENTRY_TOP_K
    hold_buffer_rank: int = DEFAULT_HOLD_BUFFER_RANK
    max_positions: int = DEFAULT_MAX_POSITIONS
    target_invested_weight: float = 0.80
    minimum_cash_ratio: float = DEFAULT_MINIMUM_CASH_RATIO
    target_cash_ratio: float = DEFAULT_TARGET_CASH_RATIO
    maximum_cash_ratio: float = DEFAULT_MAXIMUM_CASH_RATIO
    min_rebalance_weight_delta: float = DEFAULT_MIN_REBALANCE_WEIGHT_DELTA
    strategy_mode: str = "hierarchical_top10"
    buy_cost_rate: float = DEFAULT_BUY_COST_RATE
    sell_cost_rate: float = DEFAULT_SELL_COST_RATE
    minimum_fee: float = 0.0
    slippage_rate: float = 0.0
    execution_price_type: str = "close"
    effective_date: str = ""
    updated_at: str = field(default_factory=now_text)

    def __post_init__(self) -> None:
        target = float(self.target_cash_ratio)
        maximum = float(self.maximum_cash_ratio)
        if not (0.0 <= target <= maximum <= DEFAULT_MAXIMUM_CASH_RATIO):
            raise ValueError("cash ratios must satisfy 0 <= target_cash_ratio <= maximum_cash_ratio <= 0.30")

    @property
    def settings_id(self) -> str:
        suffix = self.effective_date or "default"
        return f"paper_trading_settings_{self.user_id}_{suffix}"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["settings_id"] = self.settings_id
        return data


def default_trading_cost_config(user_id: str = "default") -> TradingCostConfig:
    return TradingCostConfig(user_id=user_id)


def cost_config_from_dict(data: dict[str, Any] | None, user_id: str = "default") -> TradingCostConfig:
    if not data:
        return default_trading_cost_config(user_id)
    target_cash_ratio = float(data.get("target_cash_ratio") or data.get("minimum_cash_ratio") or DEFAULT_TARGET_CASH_RATIO)
    maximum_cash_ratio = float(data.get("maximum_cash_ratio") or DEFAULT_MAXIMUM_CASH_RATIO)
    maximum_cash_ratio = min(DEFAULT_MAXIMUM_CASH_RATIO, max(target_cash_ratio, maximum_cash_ratio))
    return TradingCostConfig(
        user_id=str(data.get("user_id") or user_id),
        entry_top_k=int(float(data.get("entry_top_k") or DEFAULT_ENTRY_TOP_K)),
        hold_buffer_rank=int(float(data.get("hold_buffer_rank") or DEFAULT_HOLD_BUFFER_RANK)),
        max_positions=int(float(data.get("max_positions") or DEFAULT_MAX_POSITIONS)),
        target_invested_weight=float(
            data.get("target_invested_weight")
            or data.get("target_ratio")
            or 0.80
        ),
        minimum_cash_ratio=target_cash_ratio,
        target_cash_ratio=target_cash_ratio,
        maximum_cash_ratio=maximum_cash_ratio,
        min_rebalance_weight_delta=float(
            data.get("min_rebalance_weight_delta") or DEFAULT_MIN_REBALANCE_WEIGHT_DELTA
        ),
        strategy_mode=str(data.get("strategy_mode") or "hierarchical_top10"),
        buy_cost_rate=float(data.get("buy_cost_rate") or DEFAULT_BUY_COST_RATE),
        sell_cost_rate=float(data.get("sell_cost_rate") or DEFAULT_SELL_COST_RATE),
        minimum_fee=float(data.get("minimum_fee") or 0.0),
        slippage_rate=float(data.get("slippage_rate") or 0.0),
        execution_price_type=str(data.get("execution_price_type") or "close"),
        effective_date=str(data.get("effective_date") or ""),
        updated_at=str(data.get("updated_at") or now_text()),
    )


def normalize_order_action(action: str) -> str:
    text = str(action or "").lower()
    if text in {"sell", "reduce", "paper_sell", "paper_reduce"}:
        return "sell"
    if text in {"buy", "paper_buy"}:
        return "buy"
    return text


def calculate_trade_cost(
    action: str,
    gross_amount: float,
    config: TradingCostConfig | None = None,
) -> dict[str, float]:
    cfg = config or default_trading_cost_config()
    normalized = normalize_order_action(action)
    gross = max(0.0, float(gross_amount or 0.0))
    applied_buy_rate = float(cfg.buy_cost_rate if normalized == "buy" else 0.0)
    applied_sell_rate = float(cfg.sell_cost_rate if normalized == "sell" else 0.0)
    rate = applied_buy_rate if normalized == "buy" else applied_sell_rate
    commission = gross * rate
    if gross > 0 and cfg.minimum_fee > 0:
        commission = max(commission, float(cfg.minimum_fee))
    slippage = gross * max(0.0, float(cfg.slippage_rate or 0.0))
    total_fee = commission + slippage
    if normalized == "buy":
        net_cash_change = -(gross + total_fee)
    elif normalized == "sell":
        net_cash_change = gross - total_fee
    else:
        net_cash_change = 0.0
        total_fee = 0.0
        commission = 0.0
        slippage = 0.0
    return {
        "gross_amount": gross,
        "commission_fee": commission,
        "other_fee": 0.0,
        "slippage_cost": slippage,
        "total_fee": total_fee,
        "net_cash_change": net_cash_change,
        "applied_buy_cost_rate": applied_buy_rate,
        "applied_sell_cost_rate": applied_sell_rate,
    }
