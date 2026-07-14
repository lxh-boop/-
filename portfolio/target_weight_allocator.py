from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from portfolio.trading_cost_config import TradingCostConfig, calculate_trade_cost, default_trading_cost_config


TRADE_LOT_SIZE = 100
ALLOW_FRACTIONAL_SHARES = False


def _stock_code(value: Any) -> str:
    return str(value or "").split(".")[0].zfill(6)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in [None, ""]:
            return default
        result = float(value)
        if not math.isfinite(result):
            return default
        return result
    except Exception:
        return default


def is_valid_price(value: Any) -> bool:
    return _safe_float(value, 0.0) > 0


def round_a_share_quantity(raw_quantity: float, lot_size: int = TRADE_LOT_SIZE, allow_fractional: bool = False) -> float:
    if allow_fractional:
        return max(0.0, float(raw_quantity))
    if lot_size <= 1:
        return max(0.0, math.floor(raw_quantity))
    return max(0.0, math.floor(float(raw_quantity) / lot_size) * lot_size)


@dataclass(frozen=True)
class AllocationResult:
    stock_code: str
    stock_name: str = ""
    final_action: str = ""
    final_score: float = 0.0
    original_target_weight: float = 0.0
    adjusted_target_weight: float = 0.0
    executable_target_amount: float = 0.0
    executable_quantity: float = 0.0
    price: float = 0.0
    industry: str = ""
    cannot_execute_reason: str = ""
    final_rank: int = 9999
    ideal_target_weight: float = 0.0
    ideal_target_amount: float = 0.0
    required_buy_amount: float = 0.0
    initial_target_amount: float = 0.0
    initial_quantity: float = 0.0
    final_quantity: float = 0.0
    final_weight: float = 0.0
    one_lot_total_cost: float = 0.0
    released_budget: float = 0.0
    received_redistribution: float = 0.0
    allocation_priority_score: float = 0.0
    unexecuted_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "original_target_weight": self.original_target_weight,
            "adjusted_target_weight": self.adjusted_target_weight,
            "executable_target_amount": self.executable_target_amount,
            "executable_quantity": self.executable_quantity,
            "price": self.price,
            "industry": self.industry,
            "cannot_execute_reason": self.cannot_execute_reason,
            "final_rank": self.final_rank,
            "ideal_target_weight": self.ideal_target_weight,
            "ideal_target_amount": self.ideal_target_amount,
            "required_buy_amount": self.required_buy_amount,
            "initial_target_amount": self.initial_target_amount,
            "initial_quantity": self.initial_quantity,
            "final_quantity": self.final_quantity,
            "final_weight": self.final_weight,
            "one_lot_total_cost": self.one_lot_total_cost,
            "released_budget": self.released_budget,
            "received_redistribution": self.received_redistribution,
            "allocation_priority_score": self.allocation_priority_score,
            "unexecuted_reason": self.unexecuted_reason,
        }


@dataclass(frozen=True)
class AllocationDiagnostics:
    candidate_count: int = 0
    keep_count: int = 0
    down_weight_count: int = 0
    hold_count: int = 0
    risk_alert_count: int = 0
    exclude_count: int = 0
    positive_target_weight_count: int = 0
    valid_price_count: int = 0
    affordable_lot_count: int = 0
    executable_order_count: int = 0
    reasons: list[str] = field(default_factory=list)
    total_asset: float = 0.0
    reserved_cash: float = 0.0
    planned_investable_cash: float = 0.0
    planned_investable_asset: float = 0.0
    initial_allocated_cash: float = 0.0
    released_budget: float = 0.0
    redistributed_cash: float = 0.0
    actual_invested_cash: float = 0.0
    unavoidable_residual_cash: float = 0.0
    capital_utilization_rate: float = 0.0
    target_cash_ratio: float = 0.05
    maximum_cash_ratio: float = 0.30
    final_cash: float = 0.0
    cash_ratio_after_allocation: float = 0.0
    cash_cap_exception: bool = False
    cash_cap_exception_reason: str = ""
    legal_candidate_count_after_allocation: int = 0
    allocation_details: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_count": self.candidate_count,
            "positive_target_weight_count": self.positive_target_weight_count,
            "valid_price_count": self.valid_price_count,
            "affordable_lot_count": self.affordable_lot_count,
            "executable_order_count": self.executable_order_count,
            "reasons": self.reasons,
            "total_asset": self.total_asset,
            "reserved_cash": self.reserved_cash,
            "planned_investable_cash": self.planned_investable_cash,
            "planned_investable_asset": self.planned_investable_asset,
            "initial_allocated_cash": self.initial_allocated_cash,
            "released_budget": self.released_budget,
            "redistributed_cash": self.redistributed_cash,
            "actual_invested_cash": self.actual_invested_cash,
            "unavoidable_residual_cash": self.unavoidable_residual_cash,
            "capital_utilization_rate": self.capital_utilization_rate,
            "target_cash_ratio": self.target_cash_ratio,
            "maximum_cash_ratio": self.maximum_cash_ratio,
            "final_cash": self.final_cash,
            "cash_ratio_after_allocation": self.cash_ratio_after_allocation,
            "cash_cap_exception": self.cash_cap_exception,
            "cash_cap_exception_reason": self.cash_cap_exception_reason,
            "legal_candidate_count_after_allocation": self.legal_candidate_count_after_allocation,
            "allocation_details": self.allocation_details,
        }


@dataclass
class _AllocationState:
    stock_code: str
    stock_name: str
    final_action: str
    final_score: float
    rank: int
    price: float
    industry: str
    ideal_target_weight: float
    original_target_weight: float
    current_weight: float
    current_market_value: float
    one_lot_total_cost: float
    one_lot_gross: float
    confidence: float = 0.0
    target_amount: float = 0.0
    required_buy_amount: float = 0.0
    initial_budget: float = 0.0
    initial_quantity: float = 0.0
    final_quantity: float = 0.0
    released_budget: float = 0.0
    received_redistribution: float = 0.0
    cannot_execute_reason: str = ""
    priority_score: float = 0.0

    @property
    def final_market_value(self) -> float:
        return self.current_market_value + self.final_quantity * self.price

    def final_weight(self, total_assets: float) -> float:
        return self.final_market_value / total_assets if total_assets > 0 else 0.0


def _rank(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _one_lot_total_cost(price: float, lot_size: int, config: TradingCostConfig) -> float:
    gross = max(0.0, float(price or 0.0) * float(lot_size or 0))
    costs = calculate_trade_cost("buy", gross, config)
    return abs(float(costs.get("net_cash_change") or 0.0))


def _quantity_from_budget(budget: float, one_lot_total_cost: float, lot_size: int, allow_fractional: bool) -> float:
    if budget <= 0 or one_lot_total_cost <= 0:
        return 0.0
    if allow_fractional:
        return max(0.0, budget / one_lot_total_cost * lot_size)
    lots = math.floor(float(budget) / float(one_lot_total_cost))
    return max(0.0, lots * lot_size)


def _priority(
    state: _AllocationState,
    total_assets: float,
    entry_top_k: int,
) -> float:
    normalized_final_score = max(0.0, min(1.0, state.final_score))
    model_confidence = max(0.0, min(1.0, state.confidence))
    rank_priority = max(0.0, (entry_top_k - state.rank + 1) / max(1, entry_top_k))
    target_value = total_assets * max(0.0, state.ideal_target_weight)
    gap = max(0.0, target_value - state.final_market_value)
    underweight_ratio = min(1.0, gap / max(target_value, state.one_lot_gross, 1.0))
    efficiency = state.one_lot_gross / state.one_lot_total_cost if state.one_lot_total_cost > 0 else 0.0
    return (
        0.35 * normalized_final_score
        + 0.20 * rank_priority
        + 0.20 * underweight_ratio
        + 0.15 * model_confidence
        + 0.10 * efficiency
    )


def _can_add_one_lot(
    state: _AllocationState,
    spendable_cash: float,
    total_assets: float,
    max_single_position: float,
    max_industry_position: float,
    industry_used: dict[str, float],
) -> bool:
    if state.price <= 0 or state.one_lot_total_cost <= 0:
        return False
    if spendable_cash + 1e-9 < state.one_lot_total_cost:
        return False
    new_value = state.final_market_value + state.one_lot_gross
    if new_value > total_assets * max_single_position + 1e-9:
        return False
    if state.industry:
        new_industry = industry_used.get(state.industry, 0.0) + state.one_lot_gross / max(total_assets, 1.0)
        if new_industry > max_industry_position + 1e-9:
            return False
    return True


def allocate_target_weights(
    candidates: list[dict[str, Any]],
    total_assets: float,
    cash: float,
    max_single_position: float,
    max_industry_position: float = 0.30,
    min_cash_ratio: float = 0.05,
    lot_size: int = TRADE_LOT_SIZE,
    allow_fractional_shares: bool = ALLOW_FRACTIONAL_SHARES,
    existing_industry_weights: dict[str, float] | None = None,
    trading_cost_config: TradingCostConfig | None = None,
    entry_top_k: int = 10,
    target_cash_ratio: float | None = None,
    maximum_cash_ratio: float | None = None,
) -> tuple[list[AllocationResult], AllocationDiagnostics]:
    total_assets = max(0.0, _safe_float(total_assets, 0.0))
    cash = max(0.0, _safe_float(cash, 0.0))
    max_single_position = max(0.0, _safe_float(max_single_position, 0.08))
    max_industry_position = max(0.0, _safe_float(max_industry_position, 0.30))
    min_cash_ratio = max(0.0, _safe_float(min_cash_ratio, 0.05))
    config_was_provided = trading_cost_config is not None
    config = trading_cost_config or default_trading_cost_config()
    target_cash_ratio = _safe_float(
        target_cash_ratio
        if target_cash_ratio is not None
        else (getattr(config, "target_cash_ratio", min_cash_ratio) if config_was_provided else min_cash_ratio),
        min_cash_ratio,
    )
    maximum_cash_ratio = _safe_float(
        maximum_cash_ratio if maximum_cash_ratio is not None else getattr(config, "maximum_cash_ratio", 0.30),
        0.30,
    )
    target_cash_ratio = max(0.0, min(target_cash_ratio, 0.30))
    maximum_cash_ratio = max(target_cash_ratio, min(maximum_cash_ratio, 0.30))
    min_cash_ratio = target_cash_ratio
    reserved_cash = total_assets * target_cash_ratio
    spendable_cash = max(0.0, cash - reserved_cash)
    planned_investable_asset = max(0.0, total_assets - reserved_cash)
    industry_base: dict[str, float] = {
        str(key): max(0.0, _safe_float(value, 0.0))
        for key, value in (existing_industry_weights or {}).items()
        if str(key)
    }
    industry_used = dict(industry_base)
    states: list[_AllocationState] = []
    results_by_code: dict[str, AllocationResult] = {}
    reasons: list[str] = []

    ordered = sorted(
        enumerate(candidates, start=1),
        key=lambda pair: (
            _rank(pair[1].get("rank") or pair[1].get("pred_rank") or pair[1].get("original_rank"), pair[0]),
            -_safe_float(pair[1].get("final_score") or pair[1].get("score"), 0.0),
            _stock_code(pair[1].get("stock_code") or pair[1].get("code")),
        ),
    )

    for order_index, item in ordered:
        code = _stock_code(item.get("stock_code") or item.get("code"))
        score = _safe_float(item.get("final_score") or item.get("score"), 0.0)
        confidence = _safe_float(item.get("confidence") or item.get("model_confidence"), score)
        rank = _rank(item.get("rank") or item.get("pred_rank") or item.get("original_rank"), order_index)
        price = _safe_float(item.get("current_price") or item.get("close") or item.get("price"), 0.0)
        target_weight = min(
            max_single_position,
            max(0.0, _safe_float(item.get("target_weight") or item.get("adjusted_target_weight"), 0.0)),
        )
        original_target_weight = max(0.0, _safe_float(item.get("original_target_weight"), target_weight))
        current_weight = max(0.0, _safe_float(item.get("current_weight"), 0.0))
        current_market_value = max(
            0.0,
            _safe_float(item.get("current_market_value"), current_weight * total_assets),
        )
        industry = str(item.get("industry") or "")
        one_lot_gross = max(0.0, price * lot_size)
        one_lot_cost = _one_lot_total_cost(price, lot_size, config) if price > 0 else 0.0
        state = _AllocationState(
            stock_code=code,
            stock_name=str(item.get("stock_name") or item.get("name") or ""),
            final_action="",
            final_score=score,
            rank=rank,
            price=price,
            industry=industry,
            ideal_target_weight=target_weight,
            original_target_weight=original_target_weight,
            current_weight=current_weight,
            current_market_value=current_market_value,
            one_lot_total_cost=one_lot_cost,
            one_lot_gross=one_lot_gross,
            confidence=confidence,
        )

        if target_weight <= 0:
            state.cannot_execute_reason = "target_weight is 0."
        elif not is_valid_price(price):
            state.cannot_execute_reason = "缺少有效市场价格; cannot execute paper order."
        elif total_assets <= 0:
            state.cannot_execute_reason = "Account total_assets is 0."
        else:
            state.target_amount = total_assets * target_weight
            state.required_buy_amount = max(state.target_amount - current_market_value, 0.0)
            single_room = max(0.0, total_assets * max_single_position - current_market_value)
            industry_room = (
                max(0.0, (max_industry_position - industry_used.get(industry, 0.0)) * total_assets)
                if industry
                else total_assets * max_industry_position
            )
            state.initial_budget = min(state.required_buy_amount, single_room, industry_room, spendable_cash)
            state.initial_quantity = _quantity_from_budget(
                state.initial_budget,
                state.one_lot_total_cost,
                lot_size,
                allow_fractional_shares,
            )
            state.final_quantity = state.initial_quantity
            initial_cost = (state.initial_quantity / lot_size) * state.one_lot_total_cost if lot_size > 0 else 0.0
            initial_gross = state.initial_quantity * state.price
            spendable_cash = max(0.0, spendable_cash - initial_cost)
            if industry and initial_gross > 0:
                industry_used[industry] = industry_used.get(industry, 0.0) + initial_gross / max(total_assets, 1.0)
            if state.initial_quantity <= 0:
                if state.initial_budget > 0:
                    state.released_budget = state.initial_budget
                    state.cannot_execute_reason = (
                        "目标预算不足以买入一手；预算释放给其他可执行 Top10 候选。"
                    )
                else:
                    state.cannot_execute_reason = "No investable room after cash, single-position, or industry constraints."
            else:
                unused_budget = max(0.0, state.initial_budget - initial_cost)
                state.released_budget = unused_budget
            states.append(state)

    redistributed_cash = 0.0
    while True:
        legal = [
            state
            for state in states
            if _can_add_one_lot(
                state,
                spendable_cash,
                total_assets,
                max_single_position,
                max_industry_position,
                industry_used,
            )
        ]
        if not legal:
            break
        for state in legal:
            state.priority_score = _priority(state, total_assets, int(entry_top_k or 10))
        chosen = sorted(legal, key=lambda item: (-item.priority_score, item.rank, item.stock_code))[0]
        chosen.final_quantity += lot_size
        chosen.received_redistribution += chosen.one_lot_gross
        redistributed_cash += chosen.one_lot_gross
        spendable_cash = max(0.0, spendable_cash - chosen.one_lot_total_cost)
        if chosen.industry:
            industry_used[chosen.industry] = industry_used.get(chosen.industry, 0.0) + chosen.one_lot_gross / max(total_assets, 1.0)

    for state in states:
        final_gross = state.final_quantity * state.price
        final_weight = state.final_weight(total_assets)
        if state.final_quantity > 0:
            state.cannot_execute_reason = ""
        elif state.cannot_execute_reason:
            reasons.append(state.cannot_execute_reason)
        result = AllocationResult(
            stock_code=state.stock_code,
            stock_name=state.stock_name,
            final_action=state.final_action,
            final_score=state.final_score,
            original_target_weight=state.original_target_weight,
            adjusted_target_weight=final_weight,
            executable_target_amount=final_gross,
            executable_quantity=state.final_quantity,
            price=state.price,
            industry=state.industry,
            cannot_execute_reason=state.cannot_execute_reason,
            final_rank=state.rank,
            ideal_target_weight=state.ideal_target_weight,
            ideal_target_amount=state.target_amount,
            required_buy_amount=state.required_buy_amount,
            initial_target_amount=state.initial_budget,
            initial_quantity=state.initial_quantity,
            final_quantity=state.final_quantity,
            final_weight=final_weight,
            one_lot_total_cost=state.one_lot_total_cost,
            released_budget=state.released_budget,
            received_redistribution=state.received_redistribution,
            allocation_priority_score=state.priority_score,
            unexecuted_reason=state.cannot_execute_reason,
        )
        results_by_code[state.stock_code] = result

    results: list[AllocationResult] = []
    for order_index, item in ordered:
        code = _stock_code(item.get("stock_code") or item.get("code"))
        if code in results_by_code:
            results.append(results_by_code[code])

    actual_invested_cash = sum(item.executable_target_amount for item in results)
    initial_allocated_cash = sum(item.initial_quantity * item.price for item in results)
    released_budget = sum(item.released_budget for item in results)
    unavoidable_residual_cash = spendable_cash
    final_cash = reserved_cash + spendable_cash
    cash_ratio_after_allocation = final_cash / total_assets if total_assets > 0 else 0.0
    legal_after = [
        state
        for state in states
        if _can_add_one_lot(
            state,
            spendable_cash,
            total_assets,
            max_single_position,
            max_industry_position,
            industry_used,
        )
    ]
    cash_cap_exception = cash_ratio_after_allocation > maximum_cash_ratio + 1e-9 and not legal_after
    cash_cap_exception_reason = ""
    if cash_cap_exception:
        if not states:
            cash_cap_exception_reason = "当前现金比例超过 30%，但没有 Top10 候选。"
        elif all(state.price <= 0 for state in states):
            cash_cap_exception_reason = "当前现金比例超过 30%，但 Top10 候选缺少有效价格。"
        elif spendable_cash <= 0:
            cash_cap_exception_reason = "当前现金比例超过 30%，但最低现金保留约束下没有可用现金。"
        else:
            cash_cap_exception_reason = "当前现金比例超过 30%，但不存在可合法执行的 Top10 买入候选。"
        reasons.append(cash_cap_exception_reason)
    diagnostics = AllocationDiagnostics(
        candidate_count=len(candidates),
        keep_count=0,
        down_weight_count=0,
        hold_count=0,
        risk_alert_count=0,
        exclude_count=0,
        positive_target_weight_count=sum(1 for item in candidates if _safe_float(item.get("target_weight"), 0.0) > 0),
        valid_price_count=sum(1 for item in candidates if is_valid_price(item.get("current_price") or item.get("close") or item.get("price"))),
        affordable_lot_count=sum(1 for result in results if result.executable_quantity > 0),
        executable_order_count=sum(1 for result in results if result.executable_quantity > 0),
        reasons=sorted(set(reasons)),
        total_asset=total_assets,
        reserved_cash=reserved_cash,
        planned_investable_cash=max(0.0, cash - reserved_cash),
        planned_investable_asset=planned_investable_asset,
        initial_allocated_cash=initial_allocated_cash,
        released_budget=released_budget,
        redistributed_cash=redistributed_cash,
        actual_invested_cash=actual_invested_cash,
        unavoidable_residual_cash=unavoidable_residual_cash,
        capital_utilization_rate=actual_invested_cash / planned_investable_asset if planned_investable_asset > 0 else 0.0,
        target_cash_ratio=target_cash_ratio,
        maximum_cash_ratio=maximum_cash_ratio,
        final_cash=final_cash,
        cash_ratio_after_allocation=cash_ratio_after_allocation,
        cash_cap_exception=cash_cap_exception,
        cash_cap_exception_reason=cash_cap_exception_reason,
        legal_candidate_count_after_allocation=len(legal_after),
        allocation_details=[item.to_dict() for item in results],
    )
    return results, diagnostics
