from __future__ import annotations

import re
from typing import Any

from agent.top_k import DEFAULT_TOOL_TOP_K, resolve_business_top_k, resolve_requested_top_k


_SOURCE_PATTERN = re.compile(
    r"^\$(context|(?:task|replan)_[A-Za-z0-9_-]+)(?:\.(.+))?$"
)

_FIELD_ALIASES = {
    "stock_code": ["stock_code", "code", "ts_code", "symbol"],
    "stock_name": ["stock_name", "name"],
    "rank": ["rank", "ranking", "pred_rank"],
    "records": ["records", "rows", "items", "results"],
    "positions": ["positions", "holdings"],
    "items": ["items", "records", "rows", "results"],
}

_STOCK_CODE_REQUIRED_INTENTS = {
    "stock_analysis",
    "stock_news",
    "stock_rag",
    "news_search",
    "rag_search",
    "evidence.search_news",
    "evidence.search_rag",
    "evidence.get_stock_evidence",
    "position_recommendation",
    "replacement_recommendation",
    "adjust_position",
}

_STOCK_CONTAINER_KEYS = (
    "records",
    "rows",
    "items",
    "results",
    "positions",
    "holdings",
    "candidates",
    "ranking",
    "top_stocks",
    "stocks",
)

_WRAPPER_KEYS = (
    "data",
    "result",
    "payload",
    "output",
)


def _unique(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()

    for value in values:
        marker = repr(value)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(value)

    return result


def _dict_value(
    data: dict[str, Any],
    field: str,
) -> Any:
    candidates = _FIELD_ALIASES.get(field, [field])

    for candidate in candidates:
        if candidate in data:
            return data[candidate]

    # Tool results normally place business output under ``data``.
    nested = data.get("data")
    if isinstance(nested, dict):
        for candidate in candidates:
            if candidate in nested:
                return nested[candidate]

    return None


def _split_path(path: str) -> list[str]:
    """Split a source path while keeping ``field[0]``/``field[*]`` tokens."""
    return [
        item.strip()
        for item in str(path or "").split(".")
        if item.strip()
    ]


def _token_parts(token: str) -> tuple[str, str | int | None]:
    text = str(token or "").strip()
    match = re.fullmatch(r"([A-Za-z0-9_]+)(?:\[(\*|\d+)\])?", text)
    if not match:
        return text, None

    field = match.group(1)
    index_text = match.group(2)
    if index_text is None:
        return field, None
    if index_text == "*":
        return field, "*"
    return field, int(index_text)


def _read_token(
    current: Any,
    token: str,
) -> Any:
    field, selector = _token_parts(token)

    if isinstance(current, list):
        collected: list[Any] = []
        for item in current:
            value = _read_token(item, field)
            if isinstance(value, list):
                collected.extend(value)
            elif value is not None:
                collected.append(value)
        current = _unique(collected)
        if selector == "*":
            return current
        if isinstance(selector, int):
            return current[selector] if 0 <= selector < len(current) else None
        return current

    if not isinstance(current, dict):
        return None

    value = _dict_value(current, field)

    if selector == "*":
        if isinstance(value, list):
            return value
        if value is None:
            return []
        return [value]

    if isinstance(selector, int):
        if not isinstance(value, list):
            return None
        return value[selector] if 0 <= selector < len(value) else None

    return value


def resolve_source(
    expression: str,
    *,
    task_results: dict[str, dict[str, Any]],
    context: dict[str, Any],
) -> Any:
    """Resolve ``$context`` and dependency-result references.

    Supported examples:

    - ``$context.user_id``
    - ``$task_1.records[*].stock_code``
    - ``$task_1.records[0].stock_code``
    - ``$task_market_ranking.data.records[0].stock_code``
    """
    text = str(expression or "").strip()
    match = _SOURCE_PATTERN.match(text)

    if not match:
        return expression

    root_name = match.group(1)
    path = str(match.group(2) or "").strip()

    if root_name == "context":
        current: Any = context
    else:
        current = task_results.get(root_name)

    if current is None:
        return None

    if not path:
        return current

    for token in _split_path(path):
        current = _read_token(current, token)
        if current is None:
            return None

    return current


def _normalise_stock_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""

    # Accept 000001, 000001.SZ, SZ000001, SH.600000 and similar forms.
    groups = re.findall(r"(?<!\d)(\d{6})(?!\d)", text)
    if groups:
        return groups[-1]

    digits = "".join(char for char in text if char.isdigit())
    if len(digits) == 6:
        return digits
    return ""


def _collect_stock_codes(
    value: Any,
    *,
    depth: int = 0,
    max_depth: int = 8,
) -> list[str]:
    """Collect stock codes without losing ranking/list order."""
    if depth > max_depth:
        return []

    codes: list[str] = []

    if isinstance(value, dict):
        # Direct stock-code fields have highest priority.
        for key in _FIELD_ALIASES["stock_code"]:
            if key not in value:
                continue
            raw = value.get(key)
            if isinstance(raw, list):
                for item in raw:
                    code = _normalise_stock_code(item)
                    if code:
                        codes.append(code)
            else:
                code = _normalise_stock_code(raw)
                if code:
                    codes.append(code)

        # Preserve the order of ranking/position containers.
        for key in _STOCK_CONTAINER_KEYS:
            nested = value.get(key)
            if nested is not None:
                codes.extend(
                    _collect_stock_codes(
                        nested,
                        depth=depth + 1,
                        max_depth=max_depth,
                    )
                )

        # Normalized tool results commonly wrap business data here.
        for key in _WRAPPER_KEYS:
            nested = value.get(key)
            if nested is not None:
                codes.extend(
                    _collect_stock_codes(
                        nested,
                        depth=depth + 1,
                        max_depth=max_depth,
                    )
                )

    elif isinstance(value, (list, tuple)):
        for item in value:
            codes.extend(
                _collect_stock_codes(
                    item,
                    depth=depth + 1,
                    max_depth=max_depth,
                )
            )

    return [
        str(item)
        for item in _unique(codes)
        if str(item).strip()
    ]


def _dependency_results(
    task: dict[str, Any],
    task_results: dict[str, dict[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    dependencies = [
        str(item)
        for item in (task.get("depends_on") or [])
        if str(item or "").strip()
    ]

    rows: list[tuple[str, dict[str, Any]]] = []
    for task_id in dependencies:
        result = task_results.get(task_id)
        if isinstance(result, dict):
            rows.append((task_id, result))
    return rows


def _wants_batch_stock_codes(
    task: dict[str, Any],
    raw_parameters: dict[str, Any],
) -> bool:
    for key, value in raw_parameters.items():
        if str(key).endswith("_source") and isinstance(value, str):
            if "[*]" in value:
                return True

    if "stock_codes" in raw_parameters:
        return True

    for key in ("foreach", "for_each", "batch", "batch_mode"):
        value = raw_parameters.get(key)
        if value is True:
            return True
        if str(value or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "all",
            "each",
            "foreach",
        }:
            return True

    execution_mode = str(task.get("execution_mode") or "").strip().lower()
    return execution_mode in {"batch", "foreach", "map"}


def _infer_stock_code_from_dependencies(
    task: dict[str, Any],
    *,
    task_results: dict[str, dict[str, Any]],
    raw_parameters: dict[str, Any],
) -> str | list[str] | None:
    """Bridge a dependency's ranked/position output into the next stock task.

    This is deliberately limited to declared ``depends_on`` tasks. It does not
    scan unrelated context or historic memory, so a stock code cannot be taken
    from the wrong request.
    """
    all_codes: list[str] = []

    for _task_id, result in _dependency_results(task, task_results):
        # Failed dependencies must not supply business parameters.
        if result.get("success") is False:
            continue
        all_codes.extend(_collect_stock_codes(result))

    codes = [
        str(item)
        for item in _unique(all_codes)
        if str(item).strip()
    ]
    if not codes:
        return None

    if _wants_batch_stock_codes(task, raw_parameters) or (
        str(task.get("intent") or "") == "stock_analysis" and len(codes) > 1
    ):
        return codes

    # A singular downstream analysis (for example “分析排名最高的股票”)
    # receives only the first record, preserving ranking order.
    return codes[0]


def resolve_task_arguments(
    task: dict[str, Any],
    *,
    task_results: dict[str, dict[str, Any]],
    context: dict[str, Any],
    default_top_k: int,
) -> dict[str, Any]:
    intent = str(task.get("intent") or "")
    raw_parameters = dict(task.get("parameters") or {})
    resolved: dict[str, Any] = {}

    for key, value in raw_parameters.items():
        name = str(key or "").strip()
        if not name:
            continue

        if name.endswith("_source"):
            target_name = name[:-7]
            if isinstance(value, str):
                resolved[target_name] = resolve_source(
                    value,
                    task_results=task_results,
                    context=context,
                )
            else:
                resolved[target_name] = value
            continue

        if isinstance(value, str) and value.startswith("$"):
            resolved[name] = resolve_source(
                value,
                task_results=task_results,
                context=context,
            )
        else:
            resolved[name] = value

    user_scoped_intents = {
        "portfolio_state",
        "portfolio_risk",
        "portfolio.get_state",
        "portfolio.get_account_summary",
        "portfolio.get_positions",
        "portfolio.get_orders",
        "portfolio.analyze_risk",
        "stock_analysis",
        "position_recommendation",
        "replacement_recommendation",
        "adjust_position",
        "user_profile",
    }
    if intent in user_scoped_intents:
        resolved.setdefault(
            "user_id",
            context.get("user_id"),
        )

    top_k_intents = {
        "ranking",
        "stock_analysis",
        "stock_rag",
        "rag_search",
        "evidence.search_rag",
        "evidence.get_stock_evidence",
        "position_recommendation",
    }
    if intent in top_k_intents:
        if context.get("business_target_position_count") not in (None, ""):
            resolved["top_k"] = resolve_business_top_k(
                user_explicit_top_k=context.get("user_explicit_top_k"),
                task_top_k=resolved.get("top_k"),
                target_position_count=context.get("business_target_position_count"),
                candidate_redundancy_factor=context.get("candidate_redundancy_factor"),
                request_default_top_k=context.get("default_top_k", default_top_k),
                tool_default_top_k=DEFAULT_TOOL_TOP_K,
            )
        else:
            resolved["top_k"] = resolve_requested_top_k(
                user_explicit_top_k=context.get("user_explicit_top_k"),
                task_top_k=resolved.get("top_k"),
                request_default_top_k=context.get("default_top_k", default_top_k),
                tool_default_top_k=DEFAULT_TOOL_TOP_K,
            )

    # Priority:
    # 1. Keep an explicit stock_code that resolved successfully.
    # 2. If the explicit source was absent or resolved to None, infer it only
    #    from declared dependency results.
    if (
        intent in _STOCK_CODE_REQUIRED_INTENTS
        and resolved.get("stock_code") in ("", None, [])
    ):
        inferred = _infer_stock_code_from_dependencies(
            task,
            task_results=task_results,
            raw_parameters=raw_parameters,
        )
        if inferred not in ("", None, []):
            resolved["stock_code"] = inferred

    return {
        key: value
        for key, value in resolved.items()
        if value not in ("", None)
    }
