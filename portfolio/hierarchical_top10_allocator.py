from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from portfolio.target_weight_allocator import TRADE_LOT_SIZE
from portfolio.trading_cost_config import TradingCostConfig, calculate_trade_cost, default_trading_cost_config
from scoring.normalizers import calculate_position_adjustment


TOP10_TARGET_RATIO = 0.80
TOP1_TO_TOP5_BASE_SCORE = 12.0
TOP6_TO_TOP10_BASE_SCORE = 5.0
TOP1_TO_TOP5_BASE_WEIGHT = 0.12
TOP6_TO_TOP10_BASE_WEIGHT = 0.05
TOP10_BASE_SCORE_TOTAL = TOP1_TO_TOP5_BASE_SCORE * 5 + TOP6_TO_TOP10_BASE_SCORE * 5
MAXIMUM_FINAL_POSITION_WEIGHT = 0.30
MINIMUM_TARGET_POSITION_COUNT = 5
PREFERRED_TARGET_POSITION_COUNT = 10
BACKUP_POOL_MAX_RANK = 30
BUFFER_SINGLE_CAP = 0.10
BUFFER_BUCKET_CAP = 0.15


def _stock_code(value: Any) -> str:
    text = str(value or "").strip().split(".")[0]
    if not text or text.lower() == "nan":
        return ""
    return text.zfill(6)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in [None, ""]:
            return default
        result = float(value)
        return result if math.isfinite(result) else default
    except Exception:
        return default


def _rank(value: Any, default: int = 9999) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _price(candidate: dict[str, Any]) -> float:
    for key in ["current_price", "close", "price", "executed_price"]:
        value = _safe_float(candidate.get(key), 0.0)
        if value > 0:
            return value
    return 0.0


def _final_score(candidate: dict[str, Any]) -> float:
    for key in ["final_score", "score", "pred_score", "model_score"]:
        if candidate.get(key) not in [None, ""]:
            return _safe_float(candidate.get(key), 0.0)
    return 0.0


def _model_confidence(candidate: dict[str, Any]) -> float:
    for key in ["model_confidence", "confidence", "reliability_score"]:
        if candidate.get(key) not in [None, ""]:
            return _safe_float(candidate.get(key), 0.0)
    return _final_score(candidate)


def base_allocation_score(rank: int) -> float:
    """Return the Stage 5O base allocation score for a ranking position."""

    rank = _rank(rank)
    if 1 <= rank <= 5:
        return TOP1_TO_TOP5_BASE_SCORE
    if 6 <= rank <= 10:
        return TOP6_TO_TOP10_BASE_SCORE
    return 0.0


def base_allocation_weight(rank: int) -> float:
    """Return the Stage 5Q pre-normalization base weight for a ranking position."""

    rank = _rank(rank)
    if 1 <= rank <= 5:
        return TOP1_TO_TOP5_BASE_WEIGHT
    if 6 <= rank <= 10:
        return TOP6_TO_TOP10_BASE_WEIGHT
    return 0.0


def normalize_base_scores(candidates: list[dict[str, Any]], target_ratio: float = TOP10_TARGET_RATIO) -> dict[str, float]:
    """Normalize Top10 12:5 scores into target weights.

    The 12 and 5 numbers are allocation scores, not account percentages.
    With ten available names, Top1-5 receive about 11.2941% each and
    Top6-10 receive about 4.7059% each, summing to 80%.
    """

    scored: list[tuple[str, float]] = []
    for index, candidate in enumerate(candidates, start=1):
        rank = _rank(candidate.get("final_rank") or candidate.get("rank") or candidate.get("pred_rank") or candidate.get("original_rank"), index)
        score = base_allocation_score(rank)
        code = _stock_code(candidate.get("stock_code") or candidate.get("code") or index)
        if code and score > 0:
            scored.append((code, score))
    total_score = sum(score for _, score in scored)
    if total_score <= 0:
        return {}
    return {code: max(0.0, float(target_ratio)) * score / total_score for code, score in scored}


def effective_news_multiplier(raw_multiplier: Any = 1.0, ai_reliability_weight: Any = 0.0) -> float:
    """Apply cold-start reliability gating to a news multiplier."""

    raw = _safe_float(raw_multiplier, 1.0)
    reliability = max(0.0, min(1.0, _safe_float(ai_reliability_weight, 0.0)))
    return 1.0 + (raw - 1.0) * reliability


def _raw_news_multiplier(candidate: dict[str, Any]) -> float:
    for key in ["raw_news_multiplier", "news_weight_multiplier", "news_multiplier"]:
        if candidate.get(key) not in [None, ""]:
            return _safe_float(candidate.get(key), 1.0)
    score = _safe_float(candidate.get("news_adjustment_score"), 0.0)
    if abs(score) > 0:
        return max(0.5, min(1.5, 1.0 + score))
    return 1.0


def _stored_target_weight(candidate: dict[str, Any]) -> float | None:
    for key in ["stored_target_weight", "target_weight", "final_target_weight"]:
        if candidate.get(key) not in [None, ""]:
            value = _safe_float(candidate.get(key), -1.0)
            if value >= 0:
                return value
    return None


def _first_present(candidate: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    for key in keys:
        value = candidate.get(key)
        if value not in [None, ""]:
            return value
    return default


def _eligible_for_entry(candidate: dict[str, Any]) -> bool:
    tradable = candidate.get("is_tradable")
    price_valid = candidate.get("price_valid")
    if tradable is not None and str(tradable).lower() in {"0", "false", "no"}:
        return False
    if price_valid is not None and str(price_valid).lower() in {"0", "false", "no"}:
        return False
    return _price(candidate) > 0


def _one_lot_total_cost(price: float, lot_size: int, config: TradingCostConfig) -> float:
    gross = max(0.0, float(price or 0.0) * float(lot_size or 0))
    return abs(float(calculate_trade_cost("buy", gross, config).get("net_cash_change") or 0.0))


def _quantity_from_cash(cash: float, one_lot_total_cost: float, lot_size: int) -> float:
    if cash <= 0 or one_lot_total_cost <= 0:
        return 0.0
    lots = math.floor(float(cash) / float(one_lot_total_cost))
    return max(0.0, lots * lot_size)


def _removal_sort_key(item: "HierarchicalAllocationResult") -> tuple[Any, ...]:
    return (
        -int(item.original_rank or item.final_rank),
        float(item.target_weight),
        float(item.final_score),
        str(item.stock_code),
    )


def _redistribution_sort_key(item: "HierarchicalAllocationResult") -> tuple[Any, ...]:
    return (
        int(item.final_rank),
        -float(item.final_score),
        -float(item.effective_news_multiplier),
        -float(item.model_confidence),
        str(item.stock_code),
    )


@dataclass
class HierarchicalAllocationResult:
    stock_code: str
    stock_name: str = ""
    original_rank: int = 9999
    final_rank: int = 9999
    final_score: float = 0.0
    model_confidence: float = 0.0
    base_allocation_score: float = 0.0
    initial_base_weight: float = 0.0
    raw_news_multiplier: float = 1.0
    effective_news_multiplier: float = 1.0
    user_adjustment_multiplier: float = 1.0
    risk_adjustment_multiplier: float = 1.0
    adjusted_allocation_score: float = 0.0
    ai_adjusted_weight: float = 0.0
    pre_cap_weight: float = 0.0
    target_weight: float = 0.0
    final_target_weight: float = 0.0
    capped_overflow_weight: float = 0.0
    redistributed_weight_received: float = 0.0
    price: float = 0.0
    one_lot_total_cost: float = 0.0
    current_quantity: float = 0.0
    current_weight: float = 0.0
    initial_quantity: float = 0.0
    final_quantity: float = 0.0
    executable_quantity: float = 0.0
    executable_target_amount: float = 0.0
    final_weight: float = 0.0
    removed_due_to_lot_constraint: bool = False
    removed_round: int = 0
    removed_reason: str = ""
    released_weight: float = 0.0
    received_redistribution: float = 0.0
    cannot_execute_reason: str = ""
    is_backup_candidate: bool = False
    backup_reason: str = ""
    target_investment_ratio: float = TOP10_TARGET_RATIO
    actual_investment_ratio: float = 0.0
    unallocated_ratio: float = 0.0
    unallocated_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HierarchicalAllocationDiagnostics:
    strategy_mode: str = "hierarchical_top10"
    target_ratio: float = TOP10_TARGET_RATIO
    base_weight_note: str = "Top1-5 use score 12 and Top6-10 use score 5; these are allocation scores, not final account percentages."
    maximum_final_position_weight: float = MAXIMUM_FINAL_POSITION_WEIGHT
    minimum_target_position_count: int = MINIMUM_TARGET_POSITION_COUNT
    preferred_target_position_count: int = PREFERRED_TARGET_POSITION_COUNT
    candidate_count: int = 0
    initial_top10_count: int = 0
    backup_candidate_count: int = 0
    backup_candidates: list[dict[str, Any]] = field(default_factory=list)
    replacement_candidates: list[dict[str, Any]] = field(default_factory=list)
    lot_execution_rounds: list[dict[str, Any]] = field(default_factory=list)
    active_candidate_count: int = 0
    removed_candidate_count: int = 0
    removed_candidates: list[dict[str, Any]] = field(default_factory=list)
    target_position_count: int = 0
    executable_candidate_count: int = 0
    maximum_position_weight: float = 0.0
    over_30_position_count: int = 0
    insufficient_diversified_candidates: bool = False
    normalized_target_weight_sum: float = 0.0
    actual_top10_ratio: float = 0.0
    top10_target_unachievable: bool = False
    top10_target_unachievable_reason: str = ""
    total_asset: float = 0.0
    reserved_cash: float = 0.0
    planned_investable_cash: float = 0.0
    spendable_cash: float = 0.0
    initial_allocated_cash: float = 0.0
    redistributed_cash: float = 0.0
    actual_invested_cash: float = 0.0
    unavoidable_residual_cash: float = 0.0
    unallocated_ratio: float = 0.0
    unallocated_reason: str = ""
    capital_utilization_rate: float = 0.0
    allocation_details: list[dict[str, Any]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _candidate_to_result(
    candidate: dict[str, Any],
    index: int,
    ai_reliability_weight: float | None,
    lot_size: int,
    config: TradingCostConfig,
    is_backup_candidate: bool = False,
) -> HierarchicalAllocationResult:
    original_rank = _rank(candidate.get("original_rank") or candidate.get("original_pred_rank") or candidate.get("pred_rank") or candidate.get("rank") or candidate.get("final_rank"), index)
    rank = original_rank
    raw_news_from_stored = _raw_news_multiplier(candidate)
    news_adj = _safe_float(candidate.get("news_adjustment") or candidate.get("news_adjustment_score"), 0.0)
    if abs(news_adj) < 1e-9 and abs(raw_news_from_stored - 1.0) > 1e-9:
        news_adj = raw_news_from_stored - 1.0
    user_adj = _safe_float(candidate.get("user_adjustment") or candidate.get("user_adjustment_score"), 0.0)
    rel_val = candidate.get("ai_reliability_weight")
    if rel_val is not None and rel_val != "":
        reliability = max(0.0, min(1.0, _safe_float(rel_val, 1.0)))
    elif ai_reliability_weight is not None:
        reliability = max(0.0, min(1.0, ai_reliability_weight))
    else:
        reliability = 1.0
    adj = calculate_position_adjustment(news_adjustment=news_adj, user_adjustment=user_adj, ai_reliability_weight=reliability)
    raw_news = 1.0 + adj.news_adjustment
    effective_news = 1.0 + adj.effective_news_adjustment
    user_multiplier = 1.0 + adj.user_adjustment
    risk_multiplier = _safe_float(_first_present(candidate, ["risk_adjustment_multiplier", "risk_weight_multiplier"], 1.0), 1.0)
    base_score = base_allocation_score(rank)
    base_weight = base_allocation_weight(rank)
    if is_backup_candidate and base_score <= 0:
        base_score = TOP6_TO_TOP10_BASE_SCORE
        base_weight = TOP6_TO_TOP10_BASE_WEIGHT
    price = _price(candidate)
    stored_weight = _stored_target_weight(candidate)
    if stored_weight is not None:
        adjusted_score = max(0.0, stored_weight)
        ai_adjusted_weight = adjusted_score
    else:
        adjusted_score = max(0.0, base_weight * max(0.0, effective_news) * max(0.0, user_multiplier) * max(0.0, risk_multiplier))
        ai_adjusted_weight = adjusted_score
    return HierarchicalAllocationResult(
        stock_code=_stock_code(candidate.get("stock_code") or candidate.get("code")),
        stock_name=str(candidate.get("stock_name") or candidate.get("name") or ""),
        original_rank=original_rank,
        final_rank=rank,
        final_score=_final_score(candidate),
        model_confidence=_model_confidence(candidate),
        base_allocation_score=base_score,
        initial_base_weight=base_weight,
        raw_news_multiplier=raw_news,
        effective_news_multiplier=effective_news,
        user_adjustment_multiplier=user_multiplier,
        risk_adjustment_multiplier=risk_multiplier,
        adjusted_allocation_score=adjusted_score,
        ai_adjusted_weight=ai_adjusted_weight,
        price=price,
        one_lot_total_cost=_one_lot_total_cost(price, lot_size, config) if price > 0 else 0.0,
        current_quantity=_safe_float(candidate.get("current_quantity") or candidate.get("quantity"), 0.0),
        current_weight=_safe_float(candidate.get("current_weight") or candidate.get("position_ratio"), 0.0),
        is_backup_candidate=False,
        backup_reason="",
    )


def _renormalize_active(
    active: list[HierarchicalAllocationResult],
    target_ratio: float,
    maximum_final_position_weight: float = MAXIMUM_FINAL_POSITION_WEIGHT,
) -> None:
    total_score = sum(max(0.0, item.adjusted_allocation_score) for item in active)
    if total_score <= 0:
        for item in active:
            item.target_weight = 0.0
            item.pre_cap_weight = 0.0
            item.final_target_weight = 0.0
        return
    for item in active:
        item.pre_cap_weight = max(0.0, float(target_ratio)) * max(0.0, item.adjusted_allocation_score) / total_score
        item.target_weight = item.pre_cap_weight
        item.final_target_weight = item.target_weight
        item.capped_overflow_weight = 0.0
        item.redistributed_weight_received = 0.0

    cap = max(0.0, min(1.0, float(maximum_final_position_weight or MAXIMUM_FINAL_POSITION_WEIGHT)))
    if cap <= 0:
        for item in active:
            item.target_weight = 0.0
            item.final_target_weight = 0.0
        return

    for _ in range(max(1, len(active) + 2)):
        overflow = 0.0
        receivers: list[HierarchicalAllocationResult] = []
        for item in active:
            if item.target_weight > cap:
                excess = item.target_weight - cap
                item.capped_overflow_weight += excess
                item.target_weight = cap
                item.final_target_weight = cap
                overflow += excess
            elif item.target_weight < cap - 1e-12 and item.adjusted_allocation_score > 0:
                receivers.append(item)
        if overflow <= 1e-12 or not receivers:
            break
        receiver_score = sum(max(0.0, item.adjusted_allocation_score) for item in receivers)
        if receiver_score <= 0:
            break
        undistributed = 0.0
        for item in receivers:
            room = cap - item.target_weight
            share = overflow * max(0.0, item.adjusted_allocation_score) / receiver_score
            received = min(room, share)
            item.target_weight += received
            item.final_target_weight = item.target_weight
            item.redistributed_weight_received += received
            undistributed += max(0.0, share - received)
        if undistributed <= 1e-12:
            break
    for item in active:
        item.final_target_weight = item.target_weight


def allocate_hierarchical_top10(
    candidates: list[dict[str, Any]],
    total_assets: float,
    cash: float | None = None,
    trading_cost_config: TradingCostConfig | None = None,
    target_ratio: float = TOP10_TARGET_RATIO,
    lot_size: int = TRADE_LOT_SIZE,
    ai_reliability_weight: float | None = None,
    min_cash_ratio: float | None = None,
) -> tuple[list[HierarchicalAllocationResult], HierarchicalAllocationDiagnostics]:
    """Allocate Top10 paper targets with Stage 5O 12:5 hierarchy and lot pruning."""

    total_assets = max(0.0, _safe_float(total_assets, 0.0))
    cash = total_assets if cash is None else max(0.0, _safe_float(cash, total_assets))
    config = trading_cost_config or default_trading_cost_config()
    reserve_ratio = max(0.0, _safe_float(min_cash_ratio, getattr(config, "target_cash_ratio", 0.05)))
    reserved_cash = total_assets * reserve_ratio
    spendable_cash = max(0.0, cash - reserved_cash)
    target_ratio = max(0.0, min(1.0 - reserve_ratio, _safe_float(target_ratio, TOP10_TARGET_RATIO)))

    results = [
        _candidate_to_result(
            candidate,
            index,
            ai_reliability_weight,
            lot_size,
            config,
            is_backup_candidate=False,
        )
        for index, candidate in enumerate(candidates, start=1)
        if _eligible_for_entry(candidate)
    ]
    top10 = [
        item
        for item in results
        if item.stock_code
        and 1 <= item.final_rank <= 10
        and item.adjusted_allocation_score > 0
        and item.price > 0
    ]
    top10 = sorted(top10, key=lambda item: (item.final_rank, -item.final_score, item.stock_code))[:10]
    active = list(top10)
    removed: list[dict[str, Any]] = []
    replacements: list[dict[str, Any]] = []
    lot_rounds: list[dict[str, Any]] = []
    removal_round = 0

    while active:
        _renormalize_active(active, target_ratio, MAXIMUM_FINAL_POSITION_WEIGHT)
        for item in active:
            target_amount = total_assets * item.target_weight
            item.initial_quantity = _quantity_from_cash(target_amount, item.one_lot_total_cost, lot_size)
            item.final_quantity = item.initial_quantity
            item.executable_quantity = item.initial_quantity
            item.executable_target_amount = item.initial_quantity * item.price
            item.final_weight = item.executable_target_amount / total_assets if total_assets > 0 else 0.0
            item.cannot_execute_reason = "" if item.initial_quantity > 0 else "target amount cannot buy one A-share lot"
        unaffordable = [item for item in active if item.initial_quantity <= 0 and item.current_quantity <= 0]
        if not unaffordable:
            break
        removal_round += 1
        weights_before = {item.stock_code: item.target_weight for item in active}
        amounts_before = {item.stock_code: total_assets * item.target_weight for item in active}
        quantities_before = {item.stock_code: item.initial_quantity for item in active}
        worst = sorted(unaffordable, key=_removal_sort_key)[0]
        worst.removed_due_to_lot_constraint = True
        worst.removed_round = removal_round
        worst.removed_reason = "target amount cannot buy one A-share lot; removed from fixed original Top10 without backup replacement"
        worst.released_weight = worst.target_weight
        worst.target_weight = 0.0
        worst.final_target_weight = 0.0
        worst.final_quantity = 0.0
        worst.executable_quantity = 0.0
        worst.executable_target_amount = 0.0
        worst.final_weight = 0.0
        worst.cannot_execute_reason = worst.removed_reason
        removed.append(worst.to_dict())
        active = [item for item in active if item.stock_code != worst.stock_code]
        _renormalize_active(active, target_ratio, MAXIMUM_FINAL_POSITION_WEIGHT)
        for item in active:
            target_amount = total_assets * item.target_weight
            item.initial_quantity = _quantity_from_cash(target_amount, item.one_lot_total_cost, lot_size)
            item.final_quantity = item.initial_quantity
            item.executable_quantity = item.initial_quantity
            item.executable_target_amount = item.initial_quantity * item.price
            item.final_weight = item.executable_target_amount / total_assets if total_assets > 0 else 0.0
            item.cannot_execute_reason = "" if item.initial_quantity > 0 else "target amount cannot buy one A-share lot"
        weights_after = {item.stock_code: item.target_weight for item in active}
        amounts_after = {item.stock_code: total_assets * item.target_weight for item in active}
        quantities_after = {item.stock_code: item.initial_quantity for item in active}
        stop_after_round = False
        if len(active) < MINIMUM_TARGET_POSITION_COUNT:
            for item in active:
                item.unallocated_reason = "fewer than preferred fixed Top10 names remain after lot pruning"
        lot_rounds.append(
            {
                "round_no": removal_round,
                "candidate_stock_codes": sorted(weights_before),
                "candidate_codes_before": sorted(weights_before),
                "unaffordable_stock_codes": [item.stock_code for item in unaffordable],
                "unaffordable_codes": [item.stock_code for item in unaffordable],
                "removed_stock_code": worst.stock_code,
                "removed_original_rank": worst.original_rank,
                "removed_target_weight": worst.released_weight,
                "removed_reason": worst.removed_reason,
                "released_weight": worst.released_weight,
                "redistributed_weights": weights_after,
                "candidate_codes_after": sorted(weights_after),
                "weights_before": weights_before,
                "target_weights_before": weights_before,
                "target_amounts_before": amounts_before,
                "target_quantities_before": quantities_before,
                "weights_after": weights_after,
                "target_weights_after": weights_after,
                "target_amounts_after": amounts_after,
                "target_quantities_after": quantities_after,
                "remaining_unallocated_weight": max(0.0, target_ratio - sum(weights_after.values())),
            }
        )
        if stop_after_round:
            continue

    _renormalize_active(active, target_ratio, MAXIMUM_FINAL_POSITION_WEIGHT)
    initial_allocated_cash = 0.0
    for item in active:
        target_amount = total_assets * item.target_weight
        quantity = _quantity_from_cash(target_amount, item.one_lot_total_cost, lot_size)
        item.initial_quantity = quantity
        item.final_quantity = quantity
        item.executable_quantity = quantity
        item.executable_target_amount = quantity * item.price
        item.final_weight = item.executable_target_amount / total_assets if total_assets > 0 else 0.0
        initial_allocated_cash += (quantity / lot_size) * item.one_lot_total_cost if lot_size > 0 else quantity * item.price

    remaining_cash = max(0.0, spendable_cash - initial_allocated_cash)
    redistributed_cash = 0.0
    while active:
        legal = [
            item
            for item in active
            if item.one_lot_total_cost > 0
            and remaining_cash + 1e-9 >= item.one_lot_total_cost
            and ((item.final_quantity + lot_size) * item.price / total_assets if total_assets > 0 else 0.0) <= MAXIMUM_FINAL_POSITION_WEIGHT + 1e-9
            and (sum(other.final_quantity * other.price for other in active) + lot_size * item.price) <= total_assets * target_ratio + 1e-9
        ]
        if not legal:
            break
        chosen = sorted(
            legal,
            key=lambda item: (
                -max(0.0, item.target_weight - item.final_weight),
                -float(item.adjusted_allocation_score),
                int(item.original_rank or item.final_rank),
                str(item.stock_code),
            ),
        )[0]
        chosen.final_quantity += lot_size
        chosen.executable_quantity = chosen.final_quantity
        chosen.executable_target_amount = chosen.final_quantity * chosen.price
        chosen.final_weight = chosen.executable_target_amount / total_assets if total_assets > 0 else 0.0
        chosen.received_redistribution += chosen.price * lot_size
        chosen.redistributed_weight_received += chosen.price * lot_size / total_assets if total_assets > 0 else 0.0
        remaining_cash = max(0.0, remaining_cash - chosen.one_lot_total_cost)
        redistributed_cash += chosen.price * lot_size

    for item in active:
        item.cannot_execute_reason = "" if item.final_quantity > 0 else item.cannot_execute_reason
        item.actual_investment_ratio = item.final_weight
        item.target_investment_ratio = target_ratio
    inactive = [item for item in top10 if item.stock_code not in {active_item.stock_code for active_item in active}]
    actual_ratio = sum(item.executable_target_amount for item in active) / total_assets if total_assets > 0 else 0.0
    target_ceiling = min(target_ratio, len([item for item in active if item.final_quantity > 0]) * MAXIMUM_FINAL_POSITION_WEIGHT)
    target_unachievable = bool(top10 and (not active or actual_ratio + 1e-9 < min(target_ceiling, spendable_cash / total_assets if total_assets > 0 else 0.0) - 0.02))
    insufficient = len([item for item in active if item.final_quantity > 0]) < MINIMUM_TARGET_POSITION_COUNT and len(results) >= MINIMUM_TARGET_POSITION_COUNT
    reasons: list[str] = []
    if target_unachievable:
        reasons.append("top10_target_unachievable")
    if insufficient:
        reasons.append("insufficient_diversified_candidates")
    reason = "; ".join(reasons)
    unallocated_ratio = max(0.0, target_ratio - actual_ratio)

    ordered_results = sorted(active + inactive, key=lambda item: (item.final_rank, item.stock_code))
    diagnostics = HierarchicalAllocationDiagnostics(
        candidate_count=len(candidates),
        initial_top10_count=len(top10),
        backup_candidate_count=0,
        backup_candidates=[],
        replacement_candidates=replacements,
        lot_execution_rounds=lot_rounds,
        active_candidate_count=len(active),
        removed_candidate_count=len(removed),
        removed_candidates=removed,
        target_position_count=len([item for item in active if item.target_weight > 0]),
        executable_candidate_count=len([item for item in active if item.final_quantity > 0]),
        maximum_position_weight=max([item.final_weight for item in active] or [0.0]),
        over_30_position_count=sum(1 for item in active if item.final_weight > MAXIMUM_FINAL_POSITION_WEIGHT + (item.price * lot_size / total_assets if total_assets > 0 else 0.0) + 1e-9),
        insufficient_diversified_candidates=insufficient,
        normalized_target_weight_sum=sum(item.target_weight for item in active),
        actual_top10_ratio=actual_ratio,
        top10_target_unachievable=target_unachievable,
        top10_target_unachievable_reason=reason,
        total_asset=total_assets,
        reserved_cash=reserved_cash,
        planned_investable_cash=spendable_cash,
        spendable_cash=spendable_cash,
        initial_allocated_cash=initial_allocated_cash,
        redistributed_cash=redistributed_cash,
        actual_invested_cash=sum(item.executable_target_amount for item in active),
        unavoidable_residual_cash=remaining_cash,
        unallocated_ratio=unallocated_ratio,
        unallocated_reason=reason,
        capital_utilization_rate=actual_ratio / target_ratio if target_ratio > 0 else 0.0,
        allocation_details=[item.to_dict() for item in ordered_results],
        reasons=sorted(set(reasons)),
    )
    return ordered_results, diagnostics
