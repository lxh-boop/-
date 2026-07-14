from __future__ import annotations

from pathlib import Path
from typing import Any
import json


PERMISSION_MAIN_BOARD = "main_board"
PERMISSION_CHINEXT = "chinext"
PERMISSION_STAR_MARKET = "star_market"
PERMISSION_BSE = "bse"
PERMISSION_RISK_WARNING = "risk_warning"
PERMISSION_STOCK_CONNECT = "stock_connect"

TRADING_PERMISSION_KEYS = (
    PERMISSION_MAIN_BOARD,
    PERMISSION_CHINEXT,
    PERMISSION_STAR_MARKET,
    PERMISSION_BSE,
    PERMISSION_RISK_WARNING,
    PERMISSION_STOCK_CONNECT,
)

TRADING_PERMISSION_LABELS = {
    PERMISSION_MAIN_BOARD: "沪深主板",
    PERMISSION_CHINEXT: "创业板",
    PERMISSION_STAR_MARKET: "科创板",
    PERMISSION_BSE: "北交所",
    PERMISSION_RISK_WARNING: "风险警示股票",
    PERMISSION_STOCK_CONNECT: "港股通",
}

DEFAULT_TRADING_PERMISSIONS = {
    PERMISSION_MAIN_BOARD: True,
    PERMISSION_CHINEXT: False,
    PERMISSION_STAR_MARKET: False,
    PERMISSION_BSE: False,
    PERMISSION_RISK_WARNING: False,
    PERMISSION_STOCK_CONNECT: False,
}


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "是", "已开通", "允许"}:
        return True
    if text in {"0", "false", "no", "n", "off", "否", "未开通", "禁止"}:
        return False
    return default


def normalize_trading_permissions(
    value: Any,
) -> dict[str, bool]:
    permissions = dict(DEFAULT_TRADING_PERMISSIONS)

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            value = parsed
        elif isinstance(parsed, list):
            value = parsed

    if isinstance(value, dict):
        aliases = {
            "main": PERMISSION_MAIN_BOARD,
            "mainboard": PERMISSION_MAIN_BOARD,
            "main_board": PERMISSION_MAIN_BOARD,
            "a_share": PERMISSION_MAIN_BOARD,
            "chinext": PERMISSION_CHINEXT,
            "gem": PERMISSION_CHINEXT,
            "创业板": PERMISSION_CHINEXT,
            "star": PERMISSION_STAR_MARKET,
            "star_market": PERMISSION_STAR_MARKET,
            "科创板": PERMISSION_STAR_MARKET,
            "bse": PERMISSION_BSE,
            "beijing": PERMISSION_BSE,
            "北交所": PERMISSION_BSE,
            "risk_warning": PERMISSION_RISK_WARNING,
            "st": PERMISSION_RISK_WARNING,
            "风险警示": PERMISSION_RISK_WARNING,
            "stock_connect": PERMISSION_STOCK_CONNECT,
            "港股通": PERMISSION_STOCK_CONNECT,
        }
        for raw_key, raw_value in value.items():
            key = aliases.get(
                str(raw_key or "").strip().lower(),
                str(raw_key or "").strip(),
            )
            if key in permissions:
                permissions[key] = _as_bool(
                    raw_value,
                    permissions[key],
                )
        return permissions

    if isinstance(value, (list, tuple, set)):
        enabled = {
            str(item or "").strip().lower()
            for item in value
        }
        permissions = {
            key: False
            for key in TRADING_PERMISSION_KEYS
        }
        aliases = {
            "main": PERMISSION_MAIN_BOARD,
            "mainboard": PERMISSION_MAIN_BOARD,
            "main_board": PERMISSION_MAIN_BOARD,
            "沪深主板": PERMISSION_MAIN_BOARD,
            "chinext": PERMISSION_CHINEXT,
            "创业板": PERMISSION_CHINEXT,
            "star_market": PERMISSION_STAR_MARKET,
            "star": PERMISSION_STAR_MARKET,
            "科创板": PERMISSION_STAR_MARKET,
            "bse": PERMISSION_BSE,
            "北交所": PERMISSION_BSE,
            "risk_warning": PERMISSION_RISK_WARNING,
            "st": PERMISSION_RISK_WARNING,
            "风险警示股票": PERMISSION_RISK_WARNING,
            "stock_connect": PERMISSION_STOCK_CONNECT,
            "港股通": PERMISSION_STOCK_CONNECT,
        }
        for item in enabled:
            key = aliases.get(item, item)
            if key in permissions:
                permissions[key] = True
        return permissions

    return permissions


def enabled_permission_labels(
    permissions: Any,
) -> list[str]:
    normalized = normalize_trading_permissions(
        permissions
    )
    return [
        TRADING_PERMISSION_LABELS[key]
        for key in TRADING_PERMISSION_KEYS
        if normalized.get(key, False)
    ]


def format_permission_summary(
    permissions: Any,
) -> str:
    labels = enabled_permission_labels(permissions)
    return "、".join(labels) if labels else "未开通任何股票买入权限"


def _explicit_board_text(
    metadata: dict[str, Any] | None,
) -> str:
    metadata = metadata or {}
    values = []
    for key in [
        "market_board",
        "board",
        "board_name",
        "list_board",
        "market_type",
        "exchange",
        "market",
        "security_type",
    ]:
        value = metadata.get(key)
        if value not in (None, ""):
            values.append(str(value))
    return " ".join(values).strip().lower()


def _code_text(stock_code: Any) -> str:
    return str(stock_code or "").strip().upper()


def classify_stock_board(
    stock_code: Any,
    stock_name: Any = "",
    metadata: dict[str, Any] | None = None,
) -> str:
    explicit = _explicit_board_text(metadata)
    code_text = _code_text(stock_code)

    if any(
        token in explicit
        for token in [
            "港股通",
            "hong kong",
            "stock connect",
            "hkex",
            " hk",
        ]
    ) or code_text.endswith(".HK"):
        return PERMISSION_STOCK_CONNECT

    if any(
        token in explicit
        for token in ["创业板", "chinext", "gem"]
    ):
        return PERMISSION_CHINEXT

    if any(
        token in explicit
        for token in ["科创板", "star market", "star_market"]
    ):
        return PERMISSION_STAR_MARKET

    if any(
        token in explicit
        for token in ["北交所", "beijing stock", "bse"]
    ):
        return PERMISSION_BSE

    if any(
        token in explicit
        for token in ["主板", "main board", "main_board"]
    ):
        return PERMISSION_MAIN_BOARD

    raw_code = code_text.split(".")[0]
    digits = "".join(
        char for char in raw_code
        if char.isdigit()
    )

    if digits.startswith(("300", "301")):
        return PERMISSION_CHINEXT

    if digits.startswith(("688", "689")):
        return PERMISSION_STAR_MARKET

    if digits.startswith("92") or (
        digits
        and digits[0] in {"4", "8"}
        and not digits.startswith(("688", "689"))
    ):
        return PERMISSION_BSE

    return PERMISSION_MAIN_BOARD


def is_risk_warning_stock(
    stock_name: Any = "",
    metadata: dict[str, Any] | None = None,
) -> bool:
    metadata = metadata or {}

    for key in [
        "is_st",
        "is_risk_warning_stock",
        "risk_warning_stock",
        "special_treatment",
    ]:
        if key in metadata and _as_bool(
            metadata.get(key),
            False,
        ):
            return True

    status_text = " ".join(
        str(metadata.get(key) or "")
        for key in [
            "security_status",
            "listing_status",
            "special_status",
        ]
    ).strip().upper()

    if any(
        token in status_text
        for token in ["*ST", "ST", "退市整理"]
    ):
        return True

    name = str(stock_name or "").strip().upper()
    compact = name.replace(" ", "")
    return (
        compact.startswith("*ST")
        or compact.startswith("ST")
        or compact.startswith("退市")
    )


def required_permissions_for_stock(
    stock_code: Any,
    stock_name: Any = "",
    metadata: dict[str, Any] | None = None,
) -> list[str]:
    board_permission = classify_stock_board(
        stock_code,
        stock_name,
        metadata,
    )
    required = [board_permission]

    if (
        board_permission != PERMISSION_STOCK_CONNECT
        and is_risk_warning_stock(
            stock_name,
            metadata,
        )
    ):
        required.append(PERMISSION_RISK_WARNING)

    return required


def evaluate_stock_buy_permission(
    stock_code: Any,
    stock_name: Any = "",
    permissions: Any = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = normalize_trading_permissions(
        permissions
    )
    required = required_permissions_for_stock(
        stock_code,
        stock_name,
        metadata,
    )
    missing = [
        key
        for key in required
        if not normalized.get(key, False)
    ]
    board = classify_stock_board(
        stock_code,
        stock_name,
        metadata,
    )
    reason_code = (
        ""
        if not missing
        else "permission_denied:" + ",".join(missing)
    )

    return {
        "allowed": not missing,
        "stock_code": str(stock_code or ""),
        "stock_name": str(stock_name or ""),
        "market_board": board,
        "market_board_label": TRADING_PERMISSION_LABELS.get(
            board,
            board,
        ),
        "required_permissions": required,
        "required_permission_labels": [
            TRADING_PERMISSION_LABELS.get(key, key)
            for key in required
        ],
        "missing_permissions": missing,
        "missing_permission_labels": [
            TRADING_PERMISSION_LABELS.get(key, key)
            for key in missing
        ],
        "reason_code": reason_code,
    }


def user_profile_json_path(
    user_id: str,
    output_dir: str | Path = "outputs",
) -> Path:
    return (
        Path(output_dir)
        / "users"
        / str(user_id or "default")
        / "user_profile.json"
    )


def load_user_trading_permissions(
    user_id: str,
    output_dir: str | Path = "outputs",
) -> dict[str, bool]:
    path = user_profile_json_path(
        user_id,
        output_dir,
    )
    if not path.exists():
        return dict(DEFAULT_TRADING_PERMISSIONS)

    try:
        data = json.loads(
            path.read_text(encoding="utf-8")
        )
    except Exception:
        return dict(DEFAULT_TRADING_PERMISSIONS)

    if not isinstance(data, dict):
        return dict(DEFAULT_TRADING_PERMISSIONS)

    return normalize_trading_permissions(
        data.get("trading_permissions")
    )
