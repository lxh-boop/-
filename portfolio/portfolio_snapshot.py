from __future__ import annotations

from dataclasses import asdict, is_dataclass
from hashlib import sha256
import json
import math
from typing import Any


DEFAULT_ROUNDING_TOLERANCE = 0.01
CASH_SEMANTICS_UNINVESTED_CASH = "uninvested_cash"


class PortfolioSnapshotConsistencyError(ValueError):
    """Raised when account and position inputs cannot be safely combined."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = str(code)


def _record(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return dict(value.to_dict())
    if is_dataclass(value):
        return dict(asdict(value))
    if isinstance(value, dict):
        return dict(value)
    return {}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _finite_number(value: Any, *, code: str, message: str) -> float:
    """Return a finite asset value or reject the whole snapshot.

    Silently coercing malformed balances to zero can turn a data issue into a
    seemingly valid investment recommendation, so only optional *legacy
    comparison* fields use ``_number``.  Inputs to the live asset equation use
    this strict parser.
    """

    try:
        number = float(value)
    except (TypeError, ValueError):
        raise PortfolioSnapshotConsistencyError(code, message) from None
    if not math.isfinite(number):
        raise PortfolioSnapshotConsistencyError(code, message)
    return number


def _snapshot_identifier(
    *,
    user_id: str,
    account_id: str,
    as_of_date: str,
    cash: float,
    positions: list[dict[str, Any]],
) -> str:
    """Create a stable ID for the exact normalized asset inputs.

    State, risk and preview calls may be made by separate read-only tools.
    Giving all of them this identifier lets callers prove they used the same
    input snapshot even when the service object is not shared.
    """

    payload = {
        "user_id": user_id,
        "account_id": account_id,
        "as_of_date": as_of_date,
        "cash": cash,
        "positions": [
            {
                "stock_code": str(item.get("stock_code") or ""),
                "quantity": item.get("quantity"),
                "current_price": item.get("current_price"),
                "market_value": item.get("market_value"),
            }
            for item in positions
        ],
    }
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    return f"portfolio_snapshot_{sha256(canonical.encode('utf-8')).hexdigest()[:16]}"


def _calculation_trace(
    *,
    cash: float,
    positions: list[dict[str, Any]],
    position_market_value: float,
    total_assets: float,
    tolerance: float,
) -> dict[str, Any]:
    """Expose the exact, non-mutating asset calculation used by the snapshot."""

    return {
        "cash_semantics": CASH_SEMANTICS_UNINVESTED_CASH,
        "cash_used": cash,
        "position_components": [
            {
                "stock_code": str(item.get("stock_code") or ""),
                "quantity": item.get("quantity"),
                "current_price": item.get("current_price"),
                "market_value": item.get("market_value"),
            }
            for item in positions
        ],
        "position_market_value_sum": position_market_value,
        "total_assets_formula": "uninvested_cash + position_market_value_sum",
        "total_assets": total_assets,
        "rounding_tolerance": tolerance,
    }


def _snapshot_time(record: dict[str, Any]) -> str:
    return str(
        record.get("snapshot_id")
        or record.get("as_of_date")
        or record.get("trade_date")
        or ""
    ).strip()


def _display_time(record: dict[str, Any]) -> str:
    return _snapshot_time(record) or str(record.get("updated_at") or "").strip()


def _validate_identity(
    *,
    account: dict[str, Any],
    positions: list[dict[str, Any]],
    user_id: str,
    account_id: str,
    as_of_date: str,
) -> None:
    account_user = str(account.get("user_id") or "").strip()
    account_identifier = str(account.get("account_id") or account.get("id") or "").strip()
    if account_user and account_user != user_id:
        raise PortfolioSnapshotConsistencyError("cross_user_account", "account user_id does not match requested user_id")
    if account_identifier and account_id and account_identifier != account_id:
        raise PortfolioSnapshotConsistencyError("cross_account_account", "account_id does not match requested account")

    account_time = _snapshot_time(account)
    expected_time = str(as_of_date or account_time or "").strip()
    for position in positions:
        position_user = str(position.get("user_id") or "").strip()
        position_account = str(position.get("account_id") or "").strip()
        position_time = _snapshot_time(position)
        if position_user and position_user != user_id:
            raise PortfolioSnapshotConsistencyError("cross_user_position", "position user_id does not match requested user_id")
        if position_account and account_id and position_account != account_id:
            raise PortfolioSnapshotConsistencyError("cross_account_position", "position account_id does not match requested account")
        if expected_time and position_time and position_time != expected_time:
            raise PortfolioSnapshotConsistencyError("cross_time_snapshot", "position timestamp does not match account snapshot")


def build_portfolio_snapshot(
    account: Any,
    positions: list[Any] | None,
    *,
    user_id: str,
    account_id: str | None = None,
    as_of_date: str | None = None,
    sources: list[dict[str, Any]] | None = None,
    tolerance: float = DEFAULT_ROUNDING_TOLERANCE,
) -> dict[str, Any]:
    """Build one read-only, internally consistent portfolio snapshot.

    Raw latest account and position records remain unchanged.  Derived balances
    always use the provided position detail so a stale account summary cannot
    leak into Agent state or risk analysis.
    """

    account_record = _record(account)
    position_records = [_record(item) for item in (positions or [])]
    user = str(user_id or account_record.get("user_id") or "default")
    identifier = str(account_id or account_record.get("account_id") or f"paper_{user}")
    resolved_as_of = str(as_of_date or _display_time(account_record) or "")

    if not account_record:
        trace = _calculation_trace(
            cash=0.0,
            positions=[],
            position_market_value=0.0,
            total_assets=0.0,
            tolerance=tolerance,
        )
        return {
            "user_id": user,
            "account_id": identifier,
            "as_of_date": resolved_as_of,
            "account": {},
            "positions": [],
            "cash": 0.0,
            "position_market_value": 0.0,
            "total_assets": 0.0,
            "cash_ratio": 0.0,
            "cash_semantics": CASH_SEMANTICS_UNINVESTED_CASH,
            "calculation_trace": trace,
            "snapshot_id": _snapshot_identifier(
                user_id=user,
                account_id=identifier,
                as_of_date=resolved_as_of,
                cash=0.0,
                positions=[],
            ),
            "consistency_status": "missing_account",
            "warnings": [],
            "errors": ["missing_account"],
            "source_metadata": list(sources or []),
            "raw_account_summary": {},
        }

    _validate_identity(
        account=account_record,
        positions=position_records,
        user_id=user,
        account_id=identifier,
        as_of_date=resolved_as_of,
    )

    cash = _finite_number(
        account_record.get("cash"),
        code="invalid_cash_value",
        message="account cash must be a finite number",
    )
    if cash < 0:
        raise PortfolioSnapshotConsistencyError("negative_cash", "account cash cannot be negative")
    normalized_positions: list[dict[str, Any]] = []
    warnings: list[str] = []
    for raw_position in position_records:
        quantity = _finite_number(
            raw_position.get("quantity"),
            code="invalid_position_quantity",
            message="position quantity must be a finite number",
        )
        if quantity < 0:
            raise PortfolioSnapshotConsistencyError("negative_position_quantity", "position quantity cannot be negative")
        if quantity <= 0:
            continue
        price = _finite_number(
            raw_position.get("current_price") or raw_position.get("last_price") or raw_position.get("close_price"),
            code="missing_position_price",
            message="active position has no valid current price",
        )
        stored_market_value = _number(raw_position.get("market_value"))
        if price <= 0:
            raise PortfolioSnapshotConsistencyError(
                "missing_position_price",
                "active position has no valid current price",
            )
        market_value = quantity * price
        position = dict(raw_position)
        position["quantity"] = quantity
        position["current_price"] = price
        position["market_value"] = market_value
        if abs(stored_market_value - market_value) > tolerance:
            warnings.append(f"recomputed_position_market_value:{position.get('stock_code') or ''}")
        normalized_positions.append(position)

    position_market_value = sum(_number(item.get("market_value")) for item in normalized_positions)
    total_assets = cash + position_market_value
    if total_assets < 0 or not math.isfinite(total_assets):
        raise PortfolioSnapshotConsistencyError("invalid_total_assets", "derived total assets are invalid")
    cash_ratio = cash / total_assets if total_assets > 0 else 0.0
    for position in normalized_positions:
        position["position_ratio"] = _number(position.get("market_value")) / total_assets if total_assets > 0 else 0.0

    stored_position_market_value = _number(account_record.get("position_market_value"))
    stored_total_assets = _number(account_record.get("total_assets"), cash)
    if abs(stored_position_market_value - position_market_value) > tolerance:
        warnings.append("recomputed_stale_position_market_value")
    if abs(stored_total_assets - total_assets) > tolerance:
        warnings.append("recomputed_stale_total_assets")

    normalized_account = dict(account_record)
    normalized_account.update(
        {
            "user_id": user,
            "account_id": identifier,
            "cash": cash,
            "position_market_value": position_market_value,
            "total_assets": total_assets,
        }
    )
    status = "consistent" if not warnings else "recomputed_stale_summary"
    trace = _calculation_trace(
        cash=cash,
        positions=normalized_positions,
        position_market_value=position_market_value,
        total_assets=total_assets,
        tolerance=tolerance,
    )
    return {
        "user_id": user,
        "account_id": identifier,
        "as_of_date": resolved_as_of,
        "account": normalized_account,
        "positions": normalized_positions,
        "cash": cash,
        "position_market_value": position_market_value,
        "total_assets": total_assets,
        "cash_ratio": cash_ratio,
        "cash_semantics": CASH_SEMANTICS_UNINVESTED_CASH,
        "calculation_trace": trace,
        "snapshot_id": _snapshot_identifier(
            user_id=user,
            account_id=identifier,
            as_of_date=resolved_as_of,
            cash=cash,
            positions=normalized_positions,
        ),
        "consistency_status": status,
        "warnings": list(dict.fromkeys(warnings)),
        "errors": [],
        "source_metadata": list(sources or []),
        "raw_account_summary": {
            "position_market_value": stored_position_market_value,
            "total_assets": stored_total_assets,
        },
    }
