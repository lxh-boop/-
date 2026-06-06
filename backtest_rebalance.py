from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RebalanceResult:
    current_codes: set[str]
    held_codes: set[str]
    bought_codes: set[str]
    sold_codes: set[str]
    buy_turnover: float
    sell_turnover: float
    turnover: float


def _normalize_codes(codes) -> set[str]:
    return {str(code).zfill(6) for code in (codes or [])}


def calculate_topk_rebalance(previous_codes, current_codes) -> RebalanceResult:
    previous = _normalize_codes(previous_codes)
    current = _normalize_codes(current_codes)

    held = previous & current
    bought = current - previous
    sold = previous - current

    if not current:
        return RebalanceResult(
            current_codes=current,
            held_codes=held,
            bought_codes=bought,
            sold_codes=sold,
            buy_turnover=0.0,
            sell_turnover=0.0,
            turnover=0.0,
        )

    if not previous:
        return RebalanceResult(
            current_codes=current,
            held_codes=held,
            bought_codes=bought,
            sold_codes=sold,
            buy_turnover=1.0,
            sell_turnover=0.0,
            turnover=1.0,
        )

    buy_turnover = len(bought) / max(len(current), 1)
    sell_turnover = len(sold) / max(len(previous), 1)

    return RebalanceResult(
        current_codes=current,
        held_codes=held,
        bought_codes=bought,
        sold_codes=sold,
        buy_turnover=float(buy_turnover),
        sell_turnover=float(sell_turnover),
        turnover=float(max(buy_turnover, sell_turnover)),
    )


def format_code_set(codes: set[str]) -> str:
    return ",".join(sorted(str(code).zfill(6) for code in codes))
