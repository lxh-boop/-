from __future__ import annotations

from typing import Any

from portfolio.hierarchical_top10_allocator import (
    BUFFER_BUCKET_CAP,
    BUFFER_SINGLE_CAP,
    MAXIMUM_FINAL_POSITION_WEIGHT,
    MINIMUM_TARGET_POSITION_COUNT,
    TOP10_TARGET_RATIO,
    allocate_hierarchical_top10,
)
from portfolio.paper_position import position_from_dict
from portfolio.schemas import PaperAccount, PaperPosition, RebalanceDecision, RebalancePlan
from portfolio.target_weight_allocator import TRADE_LOT_SIZE, allocate_target_weights
from portfolio.trading_cost_config import TradingCostConfig
from portfolio.user_profile import PROFILE_CONSTRAINTS
from portfolio.trading_permissions import (
    evaluate_stock_buy_permission,
    normalize_trading_permissions,
)


HIGH_RISK_LEVELS = {"high", "very_high", "extreme", "C5"}
MINIMUM_HOLDING_DAYS = 5


def _stock_code(value: Any) -> str:
    return str(value or "").split(".")[0].zfill(6)


def _score(candidate: dict[str, Any]) -> float:
    for key in ["original_score", "original_pred_score", "score", "pred_score", "model_score"]:
        if candidate.get(key) not in [None, ""]:
            return float(candidate[key])
    return 0.0


def _adjustment_fields(candidate: dict[str, Any], rank: int) -> dict[str, Any]:
    news_adj = float(candidate.get("news_adjustment") or candidate.get("news_adjustment_score") or 0.0)
    user_adj = float(candidate.get("user_adjustment") or candidate.get("user_adjustment_score") or 0.0)
    rel_raw = candidate.get("ai_reliability_weight")
    if rel_raw is not None and rel_raw != "":
        reliability = min(1.0, max(0.0, float(rel_raw) if float(rel_raw) == float(rel_raw) else 1.0))
    else:
        reliability = 1.0
    effective_news = reliability * news_adj
    combined = effective_news + user_adj
    ratio = min(2.0, max(0.0, 1.0 + combined))
    return {
        "original_rank": rank,
        "original_score": float(candidate.get("original_score") or candidate.get("original_pred_score") or candidate.get("_score") or 0.0),
        "news_adjustment": news_adj,
        "user_adjustment": user_adj,
        "effective_news_adjustment": effective_news,
        "combined_adjustment": combined,
        "position_adjustment_ratio": ratio,
    }


def _as_position(position: PaperPosition | dict[str, Any], total_assets: float = 0.0) -> PaperPosition:
    if isinstance(position, PaperPosition):
        return position
    return position_from_dict(position, total_assets=total_assets)


def _current_position_map(
    positions: list[PaperPosition | dict[str, Any]] | None,
    account: PaperAccount | None,
) -> dict[str, PaperPosition]:
    total_assets = float(account.total_assets) if account else 0.0
    result = {}
    for item in positions or []:
        position = _as_position(item, total_assets=total_assets)
        result[_stock_code(position.stock_code)] = position
    return result


def _ranked_candidates(candidates: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for index, candidate in enumerate(sorted(candidates, key=_score, reverse=True), start=1):
        item = dict(candidate)
        try:
            rank = int(float(item.get("rank") or item.get("pred_rank") or item.get("original_rank") or index))
        except Exception:
            rank = index
        item["stock_code"] = _stock_code(item.get("stock_code") or item.get("code"))
        item["_rank"] = rank
        item["_score"] = _score(item)
        ranked.append(item)
    return ranked[: max(1, limit)]


def _permission_result(
    candidate: dict[str, Any],
    permissions: dict[str, Any],
) -> dict[str, Any]:
    return evaluate_stock_buy_permission(
        candidate.get("stock_code")
        or candidate.get("code"),
        candidate.get("stock_name")
        or candidate.get("name")
        or "",
        permissions,
        metadata=candidate,
    )


def _permission_warning(
    result: dict[str, Any],
) -> str:
    reason_code = str(
        result.get("reason_code") or ""
    )
    labels = "、".join(
        result.get("missing_permission_labels")
        or []
    )
    if labels:
        return (
            f"{reason_code}; 未开通{labels}，禁止新增买入或加仓，"
            "已有持仓仅允许持有、减仓或卖出"
        )
    return reason_code


def _hard_block(candidate: dict[str, Any], allow_high_volatility: bool) -> bool:
    tradable = candidate.get("is_tradable")
    price_valid = candidate.get("price_valid")
    if tradable is not None and str(tradable).lower() in {"0", "false", "no"}:
        return True
    if price_valid is not None and str(price_valid).lower() in {"0", "false", "no"}:
        return True
    return False


def _price(candidate: dict[str, Any]) -> float:
    for key in ["current_price", "close", "price", "executed_price"]:
        value = candidate.get(key)
        if value not in [None, ""]:
            try:
                price = float(value)
            except Exception:
                price = 0.0
            if price > 0:
                return price
    return 0.0


def _rank(candidate: dict[str, Any], default: int = 9999) -> int:
    try:
        return int(float(candidate.get("rank") or candidate.get("pred_rank") or candidate.get("original_rank") or candidate.get("final_rank") or default))
    except Exception:
        return default


def _holding_days(candidate: dict[str, Any]) -> int:
    for key in ["holding_days", "current_holding_days", "days_held"]:
        try:
            if candidate.get(key) not in [None, ""]:
                return int(float(candidate.get(key)))
        except Exception:
            continue
    return 9999


def _minimum_holding_exception(candidate: dict[str, Any], rank: int, hold_buffer_rank: int) -> bool:
    if rank > hold_buffer_rank:
        return True
    return False


def _block_short_holding_sell(candidate: dict[str, Any], rank: int, hold_buffer_rank: int, current_weight: float, target_weight: float) -> bool:
    if current_weight <= 0 or target_weight > 0:
        return False
    if _holding_days(candidate) >= MINIMUM_HOLDING_DAYS:
        return False
    return not _minimum_holding_exception(candidate, rank, hold_buffer_rank)


def _ranked_candidates_by_rank(candidates: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        item = dict(candidate)
        rank = _rank(item, index)
        item["stock_code"] = _stock_code(item.get("stock_code") or item.get("code"))
        item["_rank"] = rank
        item["_score"] = _score(item)
        ranked.append(item)
    return sorted(ranked, key=lambda item: (int(item.get("_rank") or 9999), -float(item.get("_score") or 0.0), str(item.get("stock_code") or "")))[: max(1, limit)]


def _buffer_targets(
    ranked_by_code: dict[str, dict[str, Any]],
    position_map: dict[str, PaperPosition],
    hold_buffer_rank: int,
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    targets: dict[str, float] = {}
    details: list[dict[str, Any]] = []
    for code, position in position_map.items():
        candidate = ranked_by_code.get(code)
        rank = int(candidate.get("_rank") if candidate else 9999)
        if 11 <= rank <= hold_buffer_rank:
            targets[code] = min(float(position.position_ratio or 0.0), BUFFER_SINGLE_CAP)
    total = sum(targets.values())
    excess = max(0.0, total - BUFFER_BUCKET_CAP)
    if excess > 0:
        ordered = sorted(targets, key=lambda code: int(ranked_by_code.get(code, {}).get("_rank") or 9999), reverse=True)
        for code in ordered:
            if excess <= 0:
                break
            before = targets[code]
            reduction = min(before, excess)
            targets[code] = before - reduction
            excess -= reduction
            details.append(
                {
                    "stock_code": code,
                    "rank": int(ranked_by_code.get(code, {}).get("_rank") or 9999),
                    "before_weight": before,
                    "after_weight": targets[code],
                    "reduction": reduction,
                    "reason": "Top11-15 buffer bucket cap is 15%; compression starts from the worst rank.",
                }
            )
    return targets, details


def _build_hierarchical_top10_plan(
    user_id: str,
    trade_date: str,
    candidates: list[dict[str, Any]],
    constraints: dict[str, Any],
    current_positions: list[PaperPosition | dict[str, Any]] | None,
    account: PaperAccount | None,
    top_k: int,
    entry_top_k: int,
    hold_buffer_rank: int,
    minimum_cash_ratio: float,
    min_rebalance_weight_delta: float,
    trading_cost_config: TradingCostConfig | None,
    job_id: str,
    run_id: str,
    execution_source: str,
) -> RebalancePlan:
    allow_high_volatility = bool(constraints.get("allow_high_volatility", False))
    trading_permissions = normalize_trading_permissions(
        constraints.get("trading_permissions")
    )
    position_map = _current_position_map(current_positions, account)
    total_assets = float(account.total_assets or account.initial_cash or 0.0) if account else 100000.0
    cash = float(account.cash or 0.0) if account else total_assets
    entry_top_k = max(1, int(entry_top_k or 10))
    hold_buffer_rank = max(entry_top_k, int(hold_buffer_rank or 15))
    effective_top_k = max(int(top_k or hold_buffer_rank), hold_buffer_rank, entry_top_k)
    min_delta = max(0.0, float(min_rebalance_weight_delta or 0.0))
    ranked = _ranked_candidates_by_rank(candidates, effective_top_k)
    ranked_by_code = {item["stock_code"]: item for item in ranked if item.get("stock_code")}
    permission_blocked_candidates: list[dict[str, Any]] = []
    permission_frozen_weight = 0.0
    for item in ranked:
        current = position_map.get(
            _stock_code(item.get("stock_code"))
        )
        if current:
            item["current_quantity"] = float(
                current.quantity or 0.0
            )
            item["current_weight"] = float(
                current.position_ratio or 0.0
            )

        permission = _permission_result(
            item,
            trading_permissions,
        )
        item["_permission_allowed"] = bool(
            permission.get("allowed")
        )
        item["_permission_result"] = permission

        if not permission.get("allowed"):
            permission_blocked_candidates.append(
                {
                    **permission,
                    "rank": int(
                        item.get("_rank") or 9999
                    ),
                    "current_weight": float(
                        current.position_ratio or 0.0
                    ) if current else 0.0,
                }
            )
            if (
                current
                and int(item.get("_rank") or 9999)
                <= entry_top_k
            ):
                permission_frozen_weight += min(
                    float(current.position_ratio or 0.0),
                    MAXIMUM_FINAL_POSITION_WEIGHT,
                )

    permission_adjusted_target_ratio = max(
        0.0,
        TOP10_TARGET_RATIO
        - permission_frozen_weight,
    )
    allocation_candidates = [
        item
        for item in ranked
        if int(item.get("_rank") or 9999) <= entry_top_k
        and not _hard_block(item, allow_high_volatility)
        and bool(item.get("_permission_allowed", True))
        and _price(item) > 0
    ]
    allocations, allocation_diagnostics = allocate_hierarchical_top10(
        allocation_candidates,
        total_assets=total_assets,
        cash=cash,
        trading_cost_config=trading_cost_config,
        target_ratio=permission_adjusted_target_ratio,
        min_cash_ratio=minimum_cash_ratio,
    )
    allocation_by_code = {item.stock_code: item for item in allocations}
    buffer_target_by_code, buffer_reductions = _buffer_targets(ranked_by_code, position_map, hold_buffer_rank)

    decisions: list[RebalanceDecision] = []
    warnings: list[str] = []
    retained_codes: set[str] = set()
    reason_base = (
        "Hierarchical Top10 paper strategy: Top1-5 use allocation score 12, "
        "Top6-10 use allocation score 5, normalized to an 80% Top10 target."
    )

    for candidate in ranked:
        code = _stock_code(candidate.get("stock_code"))
        if not code:
            continue
        rank = int(candidate.get("_rank") or 9999)
        current = position_map.get(code)
        current_weight = float(current.position_ratio or 0.0) if current else 0.0
        stock_name = str(candidate.get("stock_name") or candidate.get("name") or (current.stock_name if current else ""))
        industry = str(candidate.get("industry") or (current.industry if current else ""))
        source_reason = str(candidate.get("reason") or "")
        risk_warning = str(candidate.get("risk_warning") or "")
        allocation = allocation_by_code.get(code)
        target_weight = 0.0
        executable_quantity = 0.0
        executable_target_amount = 0.0
        cannot_execute_reason = ""
        action = "hold"
        stored_action = str(candidate.get("final_action") or candidate.get("action") or "").lower()
        has_zero_stored_target = candidate.get("target_weight") not in [None, ""] and float(candidate.get("target_weight") or 0.0) <= 0.0

        permission = dict(
            candidate.get("_permission_result") or {}
        )
        permission_allowed = bool(
            permission.get("allowed", True)
        )

        if _hard_block(candidate, allow_high_volatility):
            action = "sell" if current and current_weight > min_delta else "hold"
            risk_warning = "; ".join(filter(None, [risk_warning, "hard risk forces Top10/Top15 paper exit or entry block"]))
        elif not permission_allowed:
            cannot_execute_reason = str(
                permission.get("reason_code") or ""
            )
            permission_text = _permission_warning(
                permission
            )
            risk_warning = "; ".join(
                filter(
                    None,
                    [risk_warning, permission_text],
                )
            )
            if current and rank <= entry_top_k:
                target_weight = min(
                    current_weight,
                    MAXIMUM_FINAL_POSITION_WEIGHT,
                )
                executable_quantity = float(
                    current.quantity or 0.0
                )
                executable_target_amount = (
                    total_assets * target_weight
                )
                action = (
                    "sell"
                    if current_weight - target_weight
                    > min_delta
                    else "hold"
                )
            elif current and rank <= hold_buffer_rank:
                target_weight = buffer_target_by_code.get(
                    code,
                    min(
                        current_weight,
                        BUFFER_SINGLE_CAP,
                    ),
                )
                executable_quantity = float(
                    current.quantity or 0.0
                )
                executable_target_amount = (
                    total_assets * target_weight
                )
                action = (
                    "sell"
                    if current_weight - target_weight
                    > min_delta
                    else "hold"
                )
            elif current and current_weight > min_delta:
                target_weight = 0.0
                action = "sell"
            else:
                target_weight = 0.0
                action = "hold"
        elif rank <= entry_top_k:
            if current and stored_action in {"hold", "exclude", "risk_alert"} and has_zero_stored_target:
                target_weight = 0.0
                executable_quantity = 0.0
                executable_target_amount = 0.0
                action = "sell" if current_weight > min_delta else "hold"
                risk_warning = "; ".join(filter(None, [risk_warning, f"stored final_action={stored_action} requests zero target weight."]))
            elif allocation and not allocation.removed_due_to_lot_constraint and allocation.target_weight > 0:
                target_weight = allocation.target_weight
                executable_quantity = allocation.executable_quantity
                executable_target_amount = allocation.executable_target_amount
                cannot_execute_reason = allocation.cannot_execute_reason
                delta = target_weight - current_weight
                if current and delta < -min_delta:
                    action = "sell"
                elif current and abs(delta) <= min_delta:
                    action = "hold"
                elif executable_quantity > 0:
                    action = "buy"
                elif current:
                    action = "hold"
                else:
                    action = "hold"
                    risk_warning = "; ".join(filter(None, [risk_warning, "target amount cannot buy one A-share lot"]))
            else:
                cannot_execute_reason = (
                    allocation.cannot_execute_reason
                    if allocation
                    else "Top10 candidate was removed by lot-size or price constraint."
                )
                if current and current_weight > min_delta:
                    action = "sell"
                    risk_warning = "; ".join(filter(None, [risk_warning, cannot_execute_reason]))
                else:
                    action = "hold"
                    risk_warning = "; ".join(filter(None, [risk_warning, cannot_execute_reason]))
        elif rank <= hold_buffer_rank:
            if current:
                target_weight = buffer_target_by_code.get(code, 0.0)
                if target_weight <= 0:
                    action = "sell"
                    risk_warning = "; ".join(filter(None, [risk_warning, "Top11-15 buffer bucket cap compression reduced this holding to zero."]))
                elif current_weight - target_weight > min_delta:
                    action = "sell"
                else:
                    action = "hold"
                executable_quantity = float(current.quantity or 0.0)
                executable_target_amount = total_assets * target_weight
            else:
                action = "hold"
                risk_warning = "; ".join(filter(None, [risk_warning, "Top11-15 buffer allows existing holdings only; no new paper position."]))
        else:
            if current and current_weight > min_delta:
                action = "sell"
                risk_warning = "; ".join(filter(None, [risk_warning, f"rank {rank} is below Top{hold_buffer_rank}; full paper exit."]))
            else:
                action = "hold"
                risk_warning = "; ".join(filter(None, [risk_warning, f"rank {rank} is outside Top{entry_top_k} entry list."]))

        if current and action in {"buy", "sell", "hold"} and rank <= hold_buffer_rank:
            retained_codes.add(code)
        if action == "sell" and current and _block_short_holding_sell(candidate, rank, hold_buffer_rank, current_weight, target_weight):
            action = "hold"
            target_weight = current_weight
            executable_quantity = float(current.quantity or 0.0)
            executable_target_amount = total_assets * current_weight
            risk_warning = "; ".join(
                filter(
                    None,
                    [
                        risk_warning,
                        f"minimum_holding_days={MINIMUM_HOLDING_DAYS}; no exception found, so full liquidation is blocked.",
                    ],
                )
            )
            retained_codes.add(code)
        if risk_warning:
            warnings.append(f"{code}: {risk_warning}")
        reason = reason_base
        if source_reason:
            reason = f"{reason} Source adjustment reason: {source_reason}"
        decisions.append(
            RebalanceDecision(
                stock_code=code,
                stock_name=stock_name,
                action=action,
                target_weight=max(0.0, float(target_weight)),
                reason=reason,
                risk_warning=risk_warning,
                industry=industry,
                final_score=float(candidate.get("_score") or 0.0),
                risk_level=str(candidate.get("risk_level") or "medium"),
                current_price=_price(candidate) or (float(current.current_price) if current else 0.0),
                executable_quantity=float(executable_quantity or 0.0),
                executable_target_amount=float(executable_target_amount or 0.0),
                cannot_execute_reason=str(cannot_execute_reason or ""),
                source_decision_id=str(candidate.get("decision_id") or ""),
                current_weight=current_weight,
                triggered_rules=str(
                    (
                        candidate.get(
                            "_permission_result",
                            {},
                        )
                        or {}
                    ).get("reason_code")
                    or ""
                ),
                **_adjustment_fields(candidate, rank),
                is_paper_trading=True,
            )
        )

    for code, position in position_map.items():
        if position.quantity <= 0 or code in retained_codes:
            continue
        candidate = ranked_by_code.get(code)
        rank = int(candidate.get("_rank") if candidate else 9999)
        if rank > hold_buffer_rank:
            warning = f"rank {rank} is below Top{hold_buffer_rank}; full paper exit."
            warnings.append(f"{code}: {warning}")
            decisions.append(
                RebalanceDecision(
                    stock_code=code,
                    stock_name=position.stock_name,
                    action="sell",
                    target_weight=0.0,
                    reason="Hierarchical Top10 paper strategy sells positions below the Top15 buffer.",
                    risk_warning=warning,
                    industry=position.industry,
                    current_price=position.current_price,
                    current_weight=float(position.position_ratio or 0.0),
                    final_score=float(candidate.get("_score") if candidate else 0.0),
                    original_rank=rank,
                    original_score=float(candidate.get("original_score") or candidate.get("original_pred_score") or candidate.get("_score") or 0.0) if candidate else 0.0,
                    news_adjustment=float(candidate.get("news_adjustment") or 0.0) if candidate else 0.0,
                    user_adjustment=float(candidate.get("user_adjustment") or 0.0) if candidate else 0.0,
                    effective_news_adjustment=float(candidate.get("effective_news_adjustment") or 0.0) if candidate else 0.0,
                    combined_adjustment=float(candidate.get("combined_adjustment") or 0.0) if candidate else 0.0,
                    position_adjustment_ratio=float(candidate.get("position_adjustment_ratio") or 1.0) if candidate else 1.0,
                    is_paper_trading=True,
                )
            )

    entry_ranked = [item for item in ranked if int(item.get("_rank") or 9999) <= entry_top_k]
    missing_price_reasons = [
        "缺少有效市场价格"
        for item in entry_ranked
        if _price(item) <= 0
    ]
    diagnostics = allocation_diagnostics.to_dict()
    diagnostics.update(
        {
            "strategy_mode": "hierarchical_top10",
            "entry_top_k": entry_top_k,
            "hold_buffer_rank": hold_buffer_rank,
            "valid_price_count": sum(1 for item in entry_ranked if _price(item) > 0),
            "positive_target_weight_count": sum(1 for item in decisions if float(item.target_weight or 0.0) > 0),
            "executable_order_count": sum(1 for item in decisions if float(item.executable_quantity or 0.0) > 0),
            "reasons": sorted(set((diagnostics.get("reasons") or []) + missing_price_reasons)),
            "top10_target_ratio": TOP10_TARGET_RATIO,
            "top10_target_weight_sum": diagnostics.get("normalized_target_weight_sum", 0.0),
            "top11_15_single_cap": BUFFER_SINGLE_CAP,
            "top11_15_bucket_cap": BUFFER_BUCKET_CAP,
            "maximum_final_position_weight": MAXIMUM_FINAL_POSITION_WEIGHT,
            "minimum_target_position_count": MINIMUM_TARGET_POSITION_COUNT,
            "backup_pool_max_rank": 0,
            "minimum_holding_days": MINIMUM_HOLDING_DAYS,
            "top11_15_bucket_weight": sum(buffer_target_by_code.values()),
            "top11_15_reductions": buffer_reductions,
            "execution_order": "sell_first_then_buffer_then_fixed_original_top10_recursive_lot_cap_30",
            "trading_permissions": trading_permissions,
            "permission_blocked_count": len(
                permission_blocked_candidates
            ),
            "permission_blocked_candidates": (
                permission_blocked_candidates
            ),
            "permission_frozen_weight": (
                permission_frozen_weight
            ),
            "allocation_target_ratio_after_permission": (
                permission_adjusted_target_ratio
            ),
        }
    )
    if permission_blocked_candidates:
        diagnostics["reasons"] = sorted(
            set(
                list(diagnostics.get("reasons") or [])
                + ["permission_restricted_candidates"]
            )
        )
    return RebalancePlan(
        user_id=user_id,
        trade_date=trade_date,
        decisions=decisions,
        total_target_weight=sum(float(item.target_weight) for item in decisions if item.action in {"buy", "hold"}),
        risk_warnings=warnings,
        execution_diagnostics=diagnostics,
        job_id=job_id,
        run_id=run_id,
        execution_source=execution_source,
        is_paper_trading=True,
    )


def build_rebalance_plan(
    user_id: str,
    trade_date: str,
    candidates: list[dict[str, Any]],
    user_constraints: dict[str, Any] | None = None,
    current_positions: list[PaperPosition | dict[str, Any]] | None = None,
    account: PaperAccount | None = None,
    top_k: int = 10,
    target_invested_weight: float = 0.80,
    entry_top_k: int = 10,
    hold_buffer_rank: int = 15,
    max_positions: int = 10,
    minimum_cash_ratio: float = 0.05,
    min_rebalance_weight_delta: float = 0.01,
    strategy_mode: str = "top10_score_weighted",
    trading_cost_config: TradingCostConfig | None = None,
    job_id: str = "",
    run_id: str = "",
    execution_source: str = "",
) -> RebalancePlan:
    """Build a Top10 paper-trading plan with a Top15 holding buffer."""

    constraints = user_constraints or {
        "max_single_position": 0.08,
        "max_industry_position": 0.30,
        "max_drawdown_tolerance": 0.15,
        "allow_high_volatility": False,
    }
    max_single = float(constraints.get("max_single_position", 0.08))
    max_industry = float(constraints.get("max_industry_position", 0.30))
    allow_high_volatility = bool(constraints.get("allow_high_volatility", False))
    profile_type = str(constraints.get("profile_type") or "default")
    avoided_industries = set(constraints.get("avoided_industries") or [])
    trading_permissions = normalize_trading_permissions(
        constraints.get("trading_permissions")
    )

    entry_top_k = max(1, int(entry_top_k or top_k or 10))
    hold_buffer_rank = max(entry_top_k, int(hold_buffer_rank or entry_top_k))
    max_positions = max(1, int(max_positions or entry_top_k))
    effective_top_k = max(entry_top_k, hold_buffer_rank, int(top_k or entry_top_k))
    min_delta = max(0.0, float(min_rebalance_weight_delta or 0.0))
    investable_weight = min(float(target_invested_weight), max(0.0, 1.0 - float(minimum_cash_ratio or 0.0)))

    if str(strategy_mode or "").lower() in {"hierarchical_top10", "fixed_original_top10_ai_weight"}:
        return _build_hierarchical_top10_plan(
            user_id=user_id,
            trade_date=trade_date,
            candidates=candidates,
            constraints=constraints,
            current_positions=current_positions,
            account=account,
            top_k=top_k,
            entry_top_k=entry_top_k,
            hold_buffer_rank=hold_buffer_rank,
            minimum_cash_ratio=minimum_cash_ratio,
            min_rebalance_weight_delta=min_rebalance_weight_delta,
            trading_cost_config=trading_cost_config,
            job_id=job_id,
            run_id=run_id,
            execution_source=execution_source,
        )

    position_map = _current_position_map(current_positions, account)
    total_assets = float(account.total_assets or account.initial_cash or 0.0) if account else 100000.0
    cash = float(account.cash or 0.0) if account else total_assets
    ranked = _ranked_candidates(candidates, effective_top_k)
    ranked_by_code = {item["stock_code"]: item for item in ranked if item.get("stock_code")}
    permission_blocked_candidates: list[dict[str, Any]] = []
    permission_frozen_weight = 0.0
    for item in ranked:
        code = _stock_code(item.get("stock_code"))
        current = position_map.get(code)
        permission = _permission_result(
            item,
            trading_permissions,
        )
        item["_permission_allowed"] = bool(
            permission.get("allowed")
        )
        item["_permission_result"] = permission
        if not permission.get("allowed"):
            permission_blocked_candidates.append(
                {
                    **permission,
                    "rank": int(
                        item.get("_rank") or 9999
                    ),
                    "current_weight": float(
                        current.position_ratio or 0.0
                    ) if current else 0.0,
                }
            )
            if (
                current
                and int(item.get("_rank") or 9999)
                <= entry_top_k
            ):
                permission_frozen_weight += min(
                    float(current.position_ratio or 0.0),
                    max_single,
                )

    investable_weight = max(
        0.0,
        investable_weight - permission_frozen_weight,
    )

    eligible_entries = [
        item
        for item in ranked
        if int(item["_rank"]) <= entry_top_k
        and not _hard_block(item, allow_high_volatility)
        and bool(item.get("_permission_allowed", True))
        and _price(item) > 0
    ][:max_positions]

    score_sum = sum(max(0.0, float(item["_score"])) for item in eligible_entries)
    equal_weight = min(max_single, investable_weight / max(1, len(eligible_entries)))
    target_weights: dict[str, float] = {}
    existing_industry_weights: dict[str, float] = {}
    for position in position_map.values():
        if position.industry:
            existing_industry_weights[position.industry] = existing_industry_weights.get(position.industry, 0.0) + float(position.position_ratio or 0.0)
    industry_used = dict(existing_industry_weights)
    for item in eligible_entries:
        code = item["stock_code"]
        industry = str(item.get("industry") or "")
        raw_target = item.get("target_weight")
        if raw_target not in [None, ""]:
            target = float(raw_target)
        elif strategy_mode == "top10_score_weighted" and score_sum > 0:
            target = investable_weight * max(0.0, float(item["_score"])) / score_sum
        else:
            target = equal_weight
        ratio = item.get("position_adjustment_ratio")
        if ratio not in [None, ""]:
            target *= max(0.0, min(2.0, float(ratio or 1.0)))
        if str(item.get("risk_level") or "medium") in HIGH_RISK_LEVELS and not allow_high_volatility:
            target = min(target, max_single * 0.5)
            item["risk_warning"] = "; ".join(
                filter(None, [str(item.get("risk_warning") or ""), "high risk target was reduced for user suitability"])
            )
        if industry in avoided_industries:
            target = min(target, max_single * 0.3)
        used = industry_used.get(industry, 0.0)
        if industry:
            target = min(target, max(0.0, max_industry - used))
            industry_used[industry] = used + max(0.0, target)
            if target <= 0:
                item["_cannot_enter_reason"] = "琛屼笟 concentration limit reached."
        target_weights[code] = max(0.0, min(target, max_single))

    allocation_candidates = []
    for item in eligible_entries:
        clone = dict(item)
        code = item["stock_code"]
        current = position_map.get(code)
        clone["target_weight"] = target_weights.get(code, 0.0)
        clone["current_weight"] = float(current.position_ratio or 0.0) if current else 0.0
        clone["current_market_value"] = float(current.market_value or 0.0) if current else 0.0
        allocation_candidates.append(clone)
    allocations, allocation_diagnostics = allocate_target_weights(
        allocation_candidates,
        total_assets=total_assets,
        cash=cash,
        max_single_position=max_single,
        max_industry_position=max_industry,
        min_cash_ratio=minimum_cash_ratio,
        lot_size=TRADE_LOT_SIZE,
        existing_industry_weights=existing_industry_weights,
        trading_cost_config=trading_cost_config,
        entry_top_k=entry_top_k,
        target_cash_ratio=float(getattr(trading_cost_config, "target_cash_ratio", minimum_cash_ratio) if trading_cost_config else minimum_cash_ratio),
        maximum_cash_ratio=float(getattr(trading_cost_config, "maximum_cash_ratio", 0.30) if trading_cost_config else 0.30),
    )
    allocation_by_code = {item.stock_code: item for item in allocations}

    decisions: list[RebalanceDecision] = []
    warnings: list[str] = []
    retained_codes: set[str] = set()

    for candidate in ranked:
        code = _stock_code(candidate.get("stock_code"))
        if not code:
            continue
        allocation = allocation_by_code.get(code)
        stock_name = str(candidate.get("stock_name") or candidate.get("name") or "")
        industry = str(candidate.get("industry") or "")
        rank = int(candidate.get("_rank") or 9999)
        current = position_map.get(code)
        current_weight = float(current.position_ratio) if current else 0.0
        target_weight = target_weights.get(code, 0.0)
        risk_warning = str(candidate.get("risk_warning") or "")
        source_reason = str(candidate.get("reason") or "")
        action = "hold"
        reason = "Top10 paper strategy: buy entries are limited to Top10; existing holdings may stay until Top15."

        permission = dict(
            candidate.get("_permission_result") or {}
        )
        permission_allowed = bool(
            permission.get("allowed", True)
        )

        if _hard_block(candidate, allow_high_volatility):
            target_weight = 0.0
            if current and current_weight > min_delta:
                action = "sell"
                risk_warning = "; ".join(filter(None, [risk_warning, "hard risk or excluded action forces paper sell"]))
            else:
                action = "hold"
                risk_warning = "; ".join(filter(None, [risk_warning, "hard risk or excluded action blocks entry"]))
        elif not permission_allowed:
            permission_text = _permission_warning(
                permission
            )
            risk_warning = "; ".join(
                filter(
                    None,
                    [risk_warning, permission_text],
                )
            )
            if current and rank <= hold_buffer_rank:
                target_weight = min(
                    current_weight,
                    max_single,
                )
                action = (
                    "sell"
                    if current_weight - target_weight
                    > min_delta
                    else "hold"
                )
                retained_codes.add(code)
            elif current and current_weight > min_delta:
                target_weight = 0.0
                action = "sell"
            else:
                target_weight = 0.0
                action = "hold"
        elif current and rank <= hold_buffer_rank:
            retained_codes.add(code)
            if target_weight <= 0:
                target_weight = min(current_weight, max_single)
            weight_delta = target_weight - current_weight
            if abs(weight_delta) < min_delta:
                action = "hold"
            elif weight_delta > 0 and allocation and allocation.executable_quantity > 0:
                action = "buy"
            elif weight_delta < 0:
                action = "sell"
            else:
                action = "hold"
        elif current and rank > hold_buffer_rank:
            action = "sell"
            target_weight = 0.0
            risk_warning = "; ".join(filter(None, [risk_warning, f"rank {rank} is outside Top{hold_buffer_rank} hold buffer"]))
        elif rank <= entry_top_k and _price(candidate) <= 0:
            action = "hold"
            target_weight = 0.0
            risk_warning = "; ".join(filter(None, [risk_warning, "缺少有效市场价格"]))
        elif rank <= entry_top_k and target_weight > 0:
            if allocation and allocation.cannot_execute_reason:
                action = "hold"
                risk_warning = "; ".join(filter(None, [risk_warning, allocation.cannot_execute_reason]))
            elif allocation and allocation.executable_quantity > 0:
                action = "buy"
                retained_codes.add(code)
            else:
                action = "hold"
                risk_warning = "; ".join(filter(None, [risk_warning, "target amount cannot buy one A-share lot"]))
        else:
            target_weight = 0.0
            fallback_reason = str(candidate.get("_cannot_enter_reason") or f"rank {rank} is outside Top{entry_top_k} entry list")
            if "concentration limit reached" in fallback_reason:
                fallback_reason = "行业 concentration limit reached."
            risk_warning = "; ".join(filter(None, [risk_warning, fallback_reason]))

        if risk_warning:
            warnings.append(f"{code}: {risk_warning}")
        if source_reason:
            reason = f"{reason} Source adjustment reason: {source_reason}"

        decisions.append(
            RebalanceDecision(
                stock_code=code,
                stock_name=stock_name,
                action=action,
                target_weight=max(0.0, min(float(target_weight), max_single)),
                reason=reason,
                risk_warning=risk_warning,
                industry=industry,
                final_score=float(candidate.get("_score") or 0.0),
                risk_level=str(candidate.get("risk_level") or "medium"),
                current_price=_price(candidate) or (float(current.current_price) if current else 0.0),
                executable_quantity=float(allocation.executable_quantity if allocation else 0.0),
                executable_target_amount=float(allocation.executable_target_amount if allocation else 0.0),
                cannot_execute_reason=str(allocation.cannot_execute_reason if allocation else ""),
                source_decision_id=str(candidate.get("decision_id") or ""),
                current_weight=current_weight,
                triggered_rules=str(
                    (
                        candidate.get(
                            "_permission_result",
                            {},
                        )
                        or {}
                    ).get("reason_code")
                    or ""
                ),
                **_adjustment_fields(candidate, rank),
                is_paper_trading=True,
            )
        )

    for code, position in position_map.items():
        if position.quantity <= 0 or code in retained_codes:
            continue
        candidate = ranked_by_code.get(code)
        rank = int(candidate.get("_rank") if candidate else 9999)
        if rank > hold_buffer_rank or float(position.position_ratio or 0.0) > max_single:
            warning = f"Existing position is outside Top{hold_buffer_rank} buffer or above {profile_type} single-position cap."
            warnings.append(f"{code}: {warning}")
            decisions.append(
                RebalanceDecision(
                    stock_code=code,
                    stock_name=position.stock_name,
                    action="sell",
                    target_weight=0.0,
                    reason="Top10 paper strategy sells positions outside the hold buffer or above the risk cap.",
                    risk_warning=warning,
                    industry=position.industry,
                    current_price=position.current_price,
                    current_weight=float(position.position_ratio or 0.0),
                    final_score=float(candidate.get("_score") if candidate else 0.0),
                    original_rank=rank,
                    original_score=float(candidate.get("original_score") or candidate.get("original_pred_score") or candidate.get("_score") or 0.0) if candidate else 0.0,
                    news_adjustment=float(candidate.get("news_adjustment") or 0.0) if candidate else 0.0,
                    user_adjustment=float(candidate.get("user_adjustment") or 0.0) if candidate else 0.0,
                    effective_news_adjustment=float(candidate.get("effective_news_adjustment") or 0.0) if candidate else 0.0,
                    combined_adjustment=float(candidate.get("combined_adjustment") or 0.0) if candidate else 0.0,
                    position_adjustment_ratio=float(candidate.get("position_adjustment_ratio") or 1.0) if candidate else 1.0,
                    is_paper_trading=True,
                )
            )

    return RebalancePlan(
        user_id=user_id,
        trade_date=trade_date,
        decisions=decisions,
        total_target_weight=sum(float(item.target_weight) for item in decisions if item.action in {"buy", "hold"}),
        risk_warnings=warnings,
        execution_diagnostics={
            **{
                **allocation_diagnostics.to_dict(),
                "reasons": sorted(
                    set(
                        allocation_diagnostics.to_dict().get("reasons", [])
                        + [
                            "缺少有效市场价格"
                            for item in ranked
                            if int(item.get("_rank") or 9999) <= entry_top_k and _price(item) <= 0
                        ]
                    )
                ),
            },
            "strategy_mode": strategy_mode,
            "entry_top_k": entry_top_k,
            "hold_buffer_rank": hold_buffer_rank,
            "max_positions": max_positions,
            "minimum_cash_ratio": minimum_cash_ratio,
            "target_cash_ratio": float(getattr(trading_cost_config, "target_cash_ratio", minimum_cash_ratio) if trading_cost_config else minimum_cash_ratio),
            "maximum_cash_ratio": float(getattr(trading_cost_config, "maximum_cash_ratio", 0.30) if trading_cost_config else 0.30),
            "min_rebalance_weight_delta": min_rebalance_weight_delta,
            "trading_permissions": trading_permissions,
            "permission_blocked_count": len(
                permission_blocked_candidates
            ),
            "permission_blocked_candidates": (
                permission_blocked_candidates
            ),
            "permission_frozen_weight": (
                permission_frozen_weight
            ),
        },
        job_id=job_id,
        run_id=run_id,
        execution_source=execution_source,
        is_paper_trading=True,
    )
