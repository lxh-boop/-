from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any


def _clean_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    if "." in text:
        left, right = text.split(".", 1)
        text = left if left.isdigit() else right if right.isdigit() else text
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits[-6:].zfill(6) if digits else ""


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def normalize_target_weights(
    target_weights: dict[str, Any],
    cash_weight: Any = 0.0,
    *,
    max_total_weight: float = 1.0,
) -> tuple[dict[str, float], float, list[str]]:
    warnings: list[str] = []
    cleaned: dict[str, float] = {}

    for raw_code, raw_weight in dict(target_weights or {}).items():
        code = _clean_code(raw_code)
        if not code:
            warnings.append(f"invalid_stock_code:{raw_code}")
            continue
        weight = max(0.0, _finite_float(raw_weight, 0.0))
        if weight <= 0:
            continue
        cleaned[code] = cleaned.get(code, 0.0) + weight

    cash = max(0.0, _finite_float(cash_weight, 0.0))
    total = sum(cleaned.values()) + cash
    limit = max(0.0, min(1.0, _finite_float(max_total_weight, 1.0)))

    if total <= 0:
        return {}, 1.0, warnings + ["empty_target_weights"]

    if total > limit + 1e-9:
        scale = limit / total if total > 0 else 0.0
        cleaned = {code: weight * scale for code, weight in cleaned.items()}
        cash *= scale
        warnings.append("target_weights_normalized_to_one")

    residual = max(0.0, 1.0 - sum(cleaned.values()) - cash)
    cash += residual

    rounded = {
        code: float(weight)
        for code, weight in cleaned.items()
        if weight > 1e-12
    }
    return rounded, float(cash), warnings


@dataclass(frozen=True)
class StrategyContext:
    user_id: str
    account_id: str
    trade_date: str
    decision_time: str
    market_data: Any = None
    historical_data: Any = None
    predictions: Any = None
    news_adjustments: Any = None
    user_adjustments: Any = None
    instrument_metadata: Any = None
    current_cash: float = 0.0
    current_positions: dict[str, Any] = field(default_factory=dict)
    stock_pool: list[str] = field(default_factory=list)
    runtime_config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StrategyResult:
    strategy_id: str
    strategy_version: str
    trade_date: str
    target_weights: dict[str, float]
    cash_weight: float
    signals: dict[str, float] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_target_portfolio(
        self,
        *,
        user_id: str,
        account_id: str,
        source_type: str,
        source_id: str,
        requires_confirmation: bool = True,
        confirmation_token: str | None = None,
    ) -> "TargetPortfolio":
        return TargetPortfolio(
            user_id=user_id,
            account_id=account_id,
            trade_date=self.trade_date,
            target_weights=dict(self.target_weights),
            cash_weight=float(self.cash_weight),
            source_type=source_type,
            source_id=source_id,
            base_strategy_id=self.strategy_id,
            base_strategy_version=self.strategy_version,
            warnings=list(self.warnings),
            validation_status=(
                "passed" if not self.warnings else "passed_with_warnings"
            ),
            requires_confirmation=requires_confirmation,
            confirmation_token=confirmation_token,
        )


@dataclass(frozen=True)
class TargetPortfolio:
    user_id: str
    account_id: str
    trade_date: str
    target_weights: dict[str, float]
    cash_weight: float
    source_type: str
    source_id: str
    base_strategy_id: str | None = None
    base_strategy_version: str | None = None
    warnings: list[str] = field(default_factory=list)
    validation_status: str = "pending"
    requires_confirmation: bool = True
    confirmation_token: str | None = None
    expires_after_execution: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PortfolioStrategy(ABC):
    strategy_id: str
    strategy_name: str
    version: str

    @abstractmethod
    def get_config_schema(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def validate_config(self, config: dict[str, Any]) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def generate_target(
        self,
        context: StrategyContext,
        config: dict[str, Any],
    ) -> StrategyResult:
        raise NotImplementedError
