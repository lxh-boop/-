from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


DEFAULT_ENTRY_TOP_K = 10
DEFAULT_HOLD_BUFFER_RANK = 15
DEFAULT_TARGET_CASH_RATIO = 0.05
DEFAULT_MAXIMUM_CASH_RATIO = 0.30
DEFAULT_MAX_POSITIONS = 10
DEFAULT_TARGET_INVESTED_WEIGHT = 0.80
DEFAULT_MIN_REBALANCE_WEIGHT_DELTA = 0.01


@dataclass(frozen=True)
class PaperStrategyConfig:
    user_id: str = "default"
    entry_top_k: int = DEFAULT_ENTRY_TOP_K
    hold_buffer_rank: int = DEFAULT_HOLD_BUFFER_RANK
    target_cash_ratio: float = DEFAULT_TARGET_CASH_RATIO
    maximum_cash_ratio: float = DEFAULT_MAXIMUM_CASH_RATIO
    max_positions: int = DEFAULT_MAX_POSITIONS
    target_invested_weight: float = DEFAULT_TARGET_INVESTED_WEIGHT
    min_rebalance_weight_delta: float = DEFAULT_MIN_REBALANCE_WEIGHT_DELTA

    def __post_init__(self) -> None:
        target = float(self.target_cash_ratio)
        maximum = float(self.maximum_cash_ratio)
        invested = float(self.target_invested_weight)
        if not (0.0 <= target <= maximum <= DEFAULT_MAXIMUM_CASH_RATIO):
            raise ValueError("cash ratios must satisfy 0 <= target_cash_ratio <= maximum_cash_ratio <= 0.30")
        if not 0.0 <= invested <= 1.0:
            raise ValueError("target_invested_weight must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_paper_strategy_config(user_id: str = "default") -> PaperStrategyConfig:
    return PaperStrategyConfig(user_id=user_id)


def paper_strategy_config_from_dict(data: dict[str, Any] | None, user_id: str = "default") -> PaperStrategyConfig:
    data = data or {}
    target = float(data.get("target_cash_ratio") or data.get("minimum_cash_ratio") or DEFAULT_TARGET_CASH_RATIO)
    target_invested_weight = float(
        data.get("target_invested_weight")
        or data.get("target_ratio")
        or DEFAULT_TARGET_INVESTED_WEIGHT
    )
    top_n = int(float(data.get("top_n") or DEFAULT_ENTRY_TOP_K))
    maximum = float(data.get("maximum_cash_ratio") or DEFAULT_MAXIMUM_CASH_RATIO)
    maximum = min(DEFAULT_MAXIMUM_CASH_RATIO, max(target, maximum))
    return PaperStrategyConfig(
        user_id=str(data.get("user_id") or user_id),
        entry_top_k=int(float(data.get("entry_top_k") or top_n)),
        hold_buffer_rank=int(float(data.get("hold_buffer_rank") or DEFAULT_HOLD_BUFFER_RANK)),
        target_cash_ratio=target,
        maximum_cash_ratio=maximum,
        max_positions=int(float(data.get("max_positions") or top_n)),
        target_invested_weight=target_invested_weight,
        min_rebalance_weight_delta=float(data.get("min_rebalance_weight_delta") or DEFAULT_MIN_REBALANCE_WEIGHT_DELTA),
    )
