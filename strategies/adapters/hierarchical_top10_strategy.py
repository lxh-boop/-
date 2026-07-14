from __future__ import annotations

from typing import Any

from portfolio.hierarchical_top10_allocator import (
    TOP10_TARGET_RATIO,
    allocate_hierarchical_top10,
)
from strategies.base import (
    PortfolioStrategy,
    StrategyContext,
    StrategyResult,
    normalize_target_weights,
)


def _records(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if hasattr(value, "to_dict"):
        try:
            rows = value.to_dict("records")
            if isinstance(rows, list):
                return [dict(row or {}) for row in rows]
        except TypeError:
            pass
    if isinstance(value, dict):
        rows = value.get("records") or value.get("rows") or value.get("items")
        if isinstance(rows, list):
            return [dict(row or {}) for row in rows if isinstance(row, dict)]
        return [dict(value)]
    if isinstance(value, list):
        return [dict(row or {}) for row in value if isinstance(row, dict)]
    return []


def _rank(row: dict[str, Any], default: int) -> int:
    for key in ["rank", "final_rank", "pred_rank", "original_rank"]:
        try:
            return int(float(row.get(key)))
        except (TypeError, ValueError):
            continue
    return default


class HierarchicalTop10Strategy(PortfolioStrategy):
    strategy_id = "hierarchical_top10_allocator"
    strategy_name = "Hierarchical Top10 allocator"
    version = "adapter_v1"

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "top_n": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 10,
                },
                "target_ratio": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "default": TOP10_TARGET_RATIO,
                },
                "min_cash_ratio": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "default": 0.05,
                },
            },
            "required": [],
            "additionalProperties": True,
        }

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        try:
            top_n = int(config.get("top_n", 10))
        except (TypeError, ValueError):
            top_n = 0
        if not 1 <= top_n <= 10:
            errors.append("top_n_must_be_between_1_and_10")

        for field in ["target_ratio", "min_cash_ratio"]:
            try:
                value = float(config.get(field, 0.0))
            except (TypeError, ValueError):
                errors.append(f"{field}_must_be_number")
                continue
            if not 0.0 <= value <= 1.0:
                errors.append(f"{field}_must_be_between_0_and_1")
        return errors

    def generate_target(
        self,
        context: StrategyContext,
        config: dict[str, Any],
    ) -> StrategyResult:
        errors = self.validate_config(config)
        if errors:
            return StrategyResult(
                strategy_id=self.strategy_id,
                strategy_version=self.version,
                trade_date=context.trade_date,
                target_weights={},
                cash_weight=1.0,
                warnings=errors,
                metadata={"validation_status": "failed"},
            )

        top_n = int(config.get("top_n", 10))
        target_ratio = float(config.get("target_ratio", TOP10_TARGET_RATIO))
        min_cash_ratio = float(config.get("min_cash_ratio", 0.05))
        candidates = [
            row
            for index, row in enumerate(_records(context.predictions), start=1)
            if _rank(row, index) <= top_n
        ]

        total_assets = float(
            context.runtime_config.get("total_assets")
            or context.current_cash
            + sum(
                float((position or {}).get("market_value") or 0.0)
                for position in context.current_positions.values()
                if isinstance(position, dict)
            )
        )
        cash = float(context.current_cash or 0.0)
        allocations, diagnostics = allocate_hierarchical_top10(
            candidates,
            total_assets=total_assets,
            cash=cash,
            target_ratio=target_ratio,
            min_cash_ratio=min_cash_ratio,
        )

        target_weights = {
            item.stock_code: float(item.target_weight or 0.0)
            for item in allocations
            if item.stock_code
            and float(item.target_weight or 0.0) > 0
            and not item.removed_due_to_lot_constraint
        }
        normalized, cash_weight, warnings = normalize_target_weights(
            target_weights,
            cash_weight=max(0.0, 1.0 - sum(target_weights.values())),
        )
        warnings.extend(list(getattr(diagnostics, "reasons", []) or []))
        return StrategyResult(
            strategy_id=self.strategy_id,
            strategy_version=self.version,
            trade_date=context.trade_date,
            target_weights=normalized,
            cash_weight=cash_weight,
            signals={
                item.stock_code: float(item.final_score or 0.0)
                for item in allocations
                if item.stock_code
            },
            reasons={
                item.stock_code: "hierarchical_top10_allocator_adapter"
                for item in allocations
                if item.stock_code
            },
            warnings=warnings,
            metadata={
                "adapter": "portfolio.hierarchical_top10_allocator",
                "diagnostics": diagnostics.to_dict(),
                "config": dict(config),
            },
        )
