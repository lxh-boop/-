from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from agent.tools._common import normalize_stock_code


_CHINESE_TOP_K = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十五": 15,
    "二十": 20,
    "三十": 30,
    "五十": 50,
}


def _extract_amount(text: str) -> float | None:
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(万元|万|w|元)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    value = float(match.group(1))
    unit = (match.group(2) or "").lower()
    if unit in {"万", "万元", "w"}:
        value *= 10000.0
    return value


def _extract_weight(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if match:
        return float(match.group(1)) / 100.0

    match = re.search(
        r"(?:仓位|目标仓位|weight)\s*[:=：]?\s*(0?\.\d+)",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return float(match.group(1))

    return None


def _extract_position_adjustment_ratio(text: str) -> float | None:
    lower = str(text or "").lower()
    if any(token in lower for token in ["减半", "砍半", "一半", "half"]):
        return 0.5
    if any(token in lower for token in ["清仓", "卖光", "全部卖", "全部减掉", "full exit", "exit all"]):
        return 0.0
    if re.search(r"(?:减到|降到|降低到|调到)\s*\d+(?:\.\d+)?\s*%", text):
        return None
    if any(token in lower for token in ["减半", "砍半", "一半", "half"]):
        return 0.5
    if any(token in lower for token in ["清仓", "卖光", "全部卖", "全部减掉", "full exit", "exit all"]):
        return 0.0
    if re.search(r"(?:减到|降到|降低到|调到)\s*\d+(?:\.\d+)?\s*%", text):
        return None
    return None


def _extract_trade_quantity(text: str) -> float | None:
    lower = str(text or "").lower()
    if any(token in lower for token in ["卖出", "减仓", "减掉", "减少", "sell", "reduce"]):
        match = re.search(r"(?:卖出|减仓|减掉|减少|sell|reduce)\s*(\d+(?:\.\d+)?)\s*股", text, flags=re.IGNORECASE)
        if not match:
            match = re.search(r"(\d+(?:\.\d+)?)\s*股", text)
        if match:
            return float(match.group(1))
    if not any(token in lower for token in ["卖出", "减仓", "减掉", "减", "sell", "reduce"]):
        return None
    match = re.search(r"(?:卖出|减仓|减掉|减|sell|reduce)\s*(\d+(?:\.\d+)?)\s*股", text, flags=re.IGNORECASE)
    if not match:
        match = re.search(r"(\d+(?:\.\d+)?)\s*股", text)
    if not match:
        return None
    return float(match.group(1))


def _extract_top_k(text: str) -> int | None:
    patterns = [
        r"\btop\s*[-_]?\s*(\d{1,3})\b",
        r"排名前\s*(\d{1,3})",
        r"前\s*(\d{1,3})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = int(match.group(1))
            return max(1, min(value, 300))

    chinese_match = re.search(r"(?:排名)?前(十五|二十|三十|五十|[一二三四五六七八九十])", text)
    if chinese_match:
        return _CHINESE_TOP_K.get(chinese_match.group(1))
    return None


def _extract_cash_weight(text: str) -> float | None:
    if "现金" not in text and "cash" not in text.lower():
        return None
    match = re.search(r"(?:现金|cash)\D{0,8}(\d+(?:\.\d+)?)\s*%", text, flags=re.IGNORECASE)
    if match:
        return max(0.0, min(1.0, float(match.group(1)) / 100.0))
    return None


def _operation_flags(text: str) -> tuple[str, bool | None, bool | None]:
    lower = str(text or "").lower()
    if any(
        token in lower
        for token in [
            "以后",
            "今后",
            "后续",
            "长期",
            "每次",
            "从现在开始",
            "从下次",
            "新增策略",
            "持仓策略",
            "调仓策略",
        ]
    ):
        return "strategy_change", True, False
    if any(token in lower for token in ["今天", "这次", "本次", "临时", "当前持仓", "本轮"]):
        return "one_time_position_operation", False, True
    if any(
        token in lower
        for token in [
            "以后",
            "今后",
            "后续",
            "长期",
            "每次",
            "从现在开始",
            "从下次",
            "新增策略",
            "持仓策略",
            "调仓策略",
        ]
    ):
        return "strategy_change", True, False
    if any(token in lower for token in ["今天", "这次", "本次", "临时", "当前持仓", "本轮"]):
        return "one_time_position_operation", False, True
    return "", None, None


def extract_parameters(query: str) -> dict[str, Any]:
    text = str(query or "")
    operation_type, persistent, apply_now = _operation_flags(text)

    code_match = re.search(r"(?<!\d)(\d{6})(?!\d)", text)
    stock_code = normalize_stock_code(code_match.group(1)) if code_match else ""
    plan_match = re.search(r"(agent_plan_[A-Za-z0-9_]+)", text)
    token_match = re.search(
        r"(?:token|令牌|confirmation_token)\s*[:=：]?\s*([A-Za-z0-9_\-]+)",
        text,
        flags=re.IGNORECASE,
    )

    dates = re.findall(r"20\d{2}[-/]?\d{2}[-/]?\d{2}", text)
    normalized_dates: list[str] = []
    for item in dates:
        token = item.replace("/", "-")
        if "-" not in token and len(token) == 8:
            token = f"{token[:4]}-{token[4:6]}-{token[6:]}"
        normalized_dates.append(token)

    lower_text = text.lower()
    flow_type = ""
    if any(token in lower_text for token in ["withdraw", "提现", "出金"]):
        flow_type = "withdrawal"
    elif any(token in lower_text for token in ["deposit", "追加", "入金", "加资金"]):
        flow_type = "deposit"

    top_k = _extract_top_k(text)
    cash_weight = _extract_cash_weight(text)

    return {
        "stock_code": stock_code,
        "plan_id": plan_match.group(1) if plan_match else "",
        "confirmation_token": token_match.group(1) if token_match else "",
        "requested_weight": _extract_weight(text),
        "position_adjustment_ratio": _extract_position_adjustment_ratio(text),
        "requested_quantity": _extract_trade_quantity(text),
        "cash_weight": cash_weight,
        "amount": _extract_amount(text),
        "top_k": top_k,
        "target_position_count": top_k if any(token in text for token in ["只持有", "持有前", "前"]) else None,
        "flow_type": flow_type,
        "effective_date": normalized_dates[0] if normalized_dates else datetime.now().strftime("%Y-%m-%d"),
        "start_date": normalized_dates[0] if normalized_dates else "",
        "end_date": normalized_dates[1] if len(normalized_dates) > 1 else "latest",
        "operation_type": operation_type,
        "persistent": persistent,
        "apply_now": apply_now,
    }
