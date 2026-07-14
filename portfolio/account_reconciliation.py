from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


RECONCILIATION_PASSED = "passed"
RECONCILIATION_FAILED = "failed"
RECONCILIATION_INVALID = "invalid"
RECONCILIATION_MISSING_SOURCE = "missing_source"


def _stock_code(value: Any) -> str:
    text = str(value or "").strip().split(".")[0]
    if not text or text.lower() == "nan":
        return ""
    return text.zfill(6)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in [None, ""]:
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in [None, ""]:
            return default
        return int(float(value))
    except Exception:
        return default


def _to_dict(item: Any) -> dict[str, Any]:
    if item is None:
        return {}
    if isinstance(item, dict):
        return dict(item)
    if hasattr(item, "to_dict"):
        return dict(item.to_dict())
    if hasattr(item, "__dict__"):
        return dict(item.__dict__)
    return {}


def _action(row: dict[str, Any]) -> str:
    return str(row.get("paper_action") or row.get("action") or "").lower()


def _is_buy(row: dict[str, Any]) -> bool:
    return _action(row) in {"buy", "paper_buy"}


def _is_sell(row: dict[str, Any]) -> bool:
    return _action(row) in {"sell", "paper_sell", "reduce", "paper_reduce"}


def _flow_type(row: dict[str, Any]) -> str:
    return str(row.get("flow_type") or row.get("type") or "").lower()


def calculate_position_market_value(
    positions: list[dict[str, Any] | Any],
    price_lookup: dict[str, float] | None = None,
) -> tuple[float, int]:
    total = 0.0
    missing = 0
    lookup = {_stock_code(key): _safe_float(value) for key, value in (price_lookup or {}).items()}
    for raw in positions or []:
        row = _to_dict(raw)
        quantity = _safe_float(row.get("quantity"), 0.0)
        if quantity <= 0:
            continue
        code = _stock_code(row.get("stock_code") or row.get("code") or row.get("asset_code"))
        price = lookup.get(code, 0.0)
        if price <= 0:
            price = _safe_float(row.get("current_price") or row.get("close") or row.get("price"), 0.0)
        if price <= 0:
            missing += 1
            continue
        total += quantity * price
    return total, missing


def summarize_orders(orders: list[dict[str, Any] | Any]) -> dict[str, float | int]:
    buy_gross = 0.0
    buy_fee = 0.0
    sell_gross = 0.0
    sell_fee = 0.0
    buy_count = 0
    sell_count = 0
    for raw in orders or []:
        row = _to_dict(raw)
        quantity = _safe_float(row.get("quantity"), 0.0)
        if quantity <= 0:
            continue
        gross = _safe_float(row.get("gross_amount") or row.get("order_amount"), 0.0)
        if gross <= 0:
            gross = quantity * _safe_float(row.get("executed_price") or row.get("price"), 0.0)
        fee = _safe_float(row.get("total_fee"), 0.0)
        if _is_buy(row):
            buy_gross += gross
            buy_fee += fee
            buy_count += 1
        elif _is_sell(row):
            sell_gross += gross
            sell_fee += fee
            sell_count += 1
    return {
        "buy_gross": buy_gross,
        "buy_fee": buy_fee,
        "sell_gross": sell_gross,
        "sell_fee": sell_fee,
        "buy_order_count": buy_count,
        "sell_order_count": sell_count,
    }


def _position_quantity_map(positions: list[dict[str, Any] | Any] | None) -> dict[str, float]:
    result: dict[str, float] = {}
    for raw in positions or []:
        row = _to_dict(raw)
        code = _stock_code(row.get("stock_code") or row.get("code") or row.get("asset_code"))
        quantity = _safe_float(row.get("quantity"), 0.0)
        if code:
            result[code] = result.get(code, 0.0) + max(0.0, quantity)
    return result


def _sell_quantity_map(orders: list[dict[str, Any] | Any] | None) -> dict[str, float]:
    result: dict[str, float] = {}
    for raw in orders or []:
        row = _to_dict(raw)
        if not _is_sell(row):
            continue
        code = _stock_code(row.get("stock_code") or row.get("code") or row.get("asset_code"))
        quantity = _safe_float(row.get("quantity") or row.get("order_quantity"), 0.0)
        if code:
            result[code] = result.get(code, 0.0) + max(0.0, quantity)
    return result


def _date_token(value: Any) -> str:
    text = str(value or "").replace("-", "").replace("/", "")[:8]
    return text if len(text) == 8 and text.isdigit() else ""


def summarize_cash_flows(cash_flows: list[dict[str, Any] | Any], trade_date: str | None = None) -> dict[str, float]:
    deposit = 0.0
    withdrawal = 0.0
    trade_token = _date_token(trade_date)
    for raw in cash_flows or []:
        row = _to_dict(raw)
        status = str(row.get("status") or "").lower()
        if status and status not in {"applied", "done", "completed"}:
            continue
        if trade_token:
            effective_token = _date_token(row.get("effective_date"))
            applied_token = _date_token(row.get("applied_at"))
            row_token = applied_token or effective_token
            if row_token and row_token != trade_token:
                continue
        amount = _safe_float(row.get("amount"), 0.0)
        flow_type = _flow_type(row)
        if flow_type == "deposit":
            deposit += amount
        elif flow_type == "withdrawal":
            withdrawal += amount
    return {"deposit": deposit, "withdrawal": withdrawal}


@dataclass(frozen=True)
class AccountReconciliationResult:
    trade_date: str
    is_trading_day: bool
    cash: float
    position_market_value: float
    recalculated_total_asset: float
    stored_total_asset: float
    asset_difference: float
    deposit: float = 0.0
    withdrawal: float = 0.0
    cumulative_deposit: float = 0.0
    cumulative_withdrawal: float = 0.0
    buy_gross: float = 0.0
    buy_fee: float = 0.0
    sell_gross: float = 0.0
    sell_fee: float = 0.0
    market_pnl: float = 0.0
    position_count: int = 0
    buy_order_count: int = 0
    sell_order_count: int = 0
    price_missing_count: int = 0
    reconciliation_status: str = RECONCILIATION_PASSED
    data_source: str = ""
    no_business_event_violation: bool = False
    invalid_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def reconcile_account_day(
    trade_date: str,
    account: dict[str, Any] | Any | None,
    positions: list[dict[str, Any] | Any] | None = None,
    orders: list[dict[str, Any] | Any] | None = None,
    cash_flows: list[dict[str, Any] | Any] | None = None,
    price_lookup: dict[str, float] | None = None,
    previous_row: dict[str, Any] | AccountReconciliationResult | None = None,
    previous_positions: list[dict[str, Any] | Any] | None = None,
    is_trading_day: bool = True,
    data_source: str = "portfolio_history",
    tolerance: float = 0.01,
) -> AccountReconciliationResult:
    account_row = _to_dict(account)
    if not account_row and not positions and not orders and not cash_flows:
        return AccountReconciliationResult(
            trade_date=str(trade_date),
            is_trading_day=bool(is_trading_day),
            cash=0.0,
            position_market_value=0.0,
            recalculated_total_asset=0.0,
            stored_total_asset=0.0,
            asset_difference=0.0,
            reconciliation_status=RECONCILIATION_MISSING_SOURCE,
            data_source=data_source,
            invalid_reason="missing account, position, order, and cash-flow sources",
        )

    previous = _to_dict(previous_row)
    order_summary = summarize_orders(orders or [])
    flow_summary = summarize_cash_flows(cash_flows or [], str(trade_date))
    cumulative_deposit = _safe_float(account_row.get("cumulative_deposit"), 0.0)
    cumulative_withdrawal = _safe_float(account_row.get("cumulative_withdrawal"), 0.0)
    previous_cumulative_deposit = _safe_float(previous.get("cumulative_deposit"), 0.0)
    previous_cumulative_withdrawal = _safe_float(previous.get("cumulative_withdrawal"), 0.0)
    account_deposit_delta = max(0.0, cumulative_deposit - previous_cumulative_deposit) if previous else cumulative_deposit
    account_withdrawal_delta = max(0.0, cumulative_withdrawal - previous_cumulative_withdrawal) if previous else cumulative_withdrawal
    deposit = flow_summary["deposit"] if abs(flow_summary["deposit"]) > tolerance else account_deposit_delta
    withdrawal = flow_summary["withdrawal"] if abs(flow_summary["withdrawal"]) > tolerance else account_withdrawal_delta
    position_value, missing_prices = calculate_position_market_value(positions or [], price_lookup)
    stored_total = _safe_float(account_row.get("total_assets"), 0.0)
    stored_cash = _safe_float(account_row.get("cash"), 0.0)
    previous_cash = _safe_float(previous.get("cash"), stored_cash)

    expected_cash = previous_cash + deposit - withdrawal
    expected_cash -= float(order_summary["buy_gross"]) + float(order_summary["buy_fee"])
    expected_cash += float(order_summary["sell_gross"]) - float(order_summary["sell_fee"])
    cash = expected_cash if previous else stored_cash
    if abs(stored_cash - expected_cash) > tolerance and previous:
        cash = expected_cash

    recalculated = cash + position_value
    difference = stored_total - recalculated
    position_count = sum(1 for raw in positions or [] if _safe_float(_to_dict(raw).get("quantity"), 0.0) > 0)
    previous_position_value = _safe_float(previous.get("position_market_value"), 0.0)
    market_pnl = (
        position_value
        - previous_position_value
        - float(order_summary["buy_gross"])
        + float(order_summary["sell_gross"])
    )

    previous_position_count = _safe_int(previous.get("position_count"), 0)
    previous_total = _safe_float(previous.get("recalculated_total_asset") or previous.get("stored_total_asset"), stored_total)
    has_no_business = (
        previous
        and previous_position_count == 0
        and position_count == 0
        and abs(float(order_summary["buy_gross"])) <= tolerance
        and abs(float(order_summary["sell_gross"])) <= tolerance
        and abs(float(order_summary["buy_fee"])) <= tolerance
        and abs(float(order_summary["sell_fee"])) <= tolerance
        and abs(deposit) <= tolerance
        and abs(withdrawal) <= tolerance
    )
    reported_total = stored_total if stored_total > 0 else recalculated
    no_business_violation = bool(
        has_no_business
        and (abs(recalculated - previous_total) > tolerance or abs(reported_total - previous_total) > tolerance)
    )

    status = RECONCILIATION_PASSED
    reasons: list[str] = []
    if missing_prices > 0:
        status = "missing_price"
        reasons.append("missing valid mark price")
    if abs(difference) > tolerance:
        status = RECONCILIATION_FAILED
        reasons.append("stored total asset does not equal cash plus position market value")
    if no_business_violation:
        status = RECONCILIATION_FAILED
        reasons.append("asset changed without position, order, fee, deposit, or withdrawal")
    previous_quantities = _position_quantity_map(previous_positions)
    current_quantities = _position_quantity_map(positions)
    sell_quantities = _sell_quantity_map(orders)
    invalid_position_transitions: list[str] = []
    for code, previous_quantity in previous_quantities.items():
        current_quantity = current_quantities.get(code, 0.0)
        if previous_quantity > tolerance and current_quantity <= tolerance:
            sold_quantity = sell_quantities.get(code, 0.0)
            if sold_quantity + tolerance < previous_quantity:
                invalid_position_transitions.append(code)
    if invalid_position_transitions:
        status = RECONCILIATION_FAILED
        reasons.append(
            "previous_position_nonzero current_position_zero sell_order_quantity_zero: "
            + ",".join(sorted(invalid_position_transitions))
        )

    return AccountReconciliationResult(
        trade_date=str(trade_date),
        is_trading_day=bool(is_trading_day),
        cash=cash,
        position_market_value=position_value,
        recalculated_total_asset=recalculated,
        stored_total_asset=stored_total,
        asset_difference=difference,
        deposit=deposit,
        withdrawal=withdrawal,
        cumulative_deposit=cumulative_deposit,
        cumulative_withdrawal=cumulative_withdrawal,
        buy_gross=float(order_summary["buy_gross"]),
        buy_fee=float(order_summary["buy_fee"]),
        sell_gross=float(order_summary["sell_gross"]),
        sell_fee=float(order_summary["sell_fee"]),
        market_pnl=market_pnl,
        position_count=position_count,
        buy_order_count=int(order_summary["buy_order_count"]),
        sell_order_count=int(order_summary["sell_order_count"]),
        price_missing_count=missing_prices,
        reconciliation_status=status,
        data_source=data_source,
        no_business_event_violation=no_business_violation,
        invalid_reason="; ".join(reasons),
    )


def is_valid_curve_point(row: dict[str, Any] | AccountReconciliationResult) -> bool:
    data = _to_dict(row)
    return bool(data.get("is_trading_day", True)) and str(data.get("reconciliation_status") or "") == RECONCILIATION_PASSED
