"""Generic business-data name helpers for the ContextBundle Working Memory."""

from __future__ import annotations

from copy import deepcopy
from fnmatch import fnmatchcase
import json
import re
from typing import Any, Iterable


_DATA_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")


class DataNameError(ValueError):
    def __init__(self, code: str, *, name: str = "", detail: str = "") -> None:
        self.code = str(code or "data_name_error")
        self.name = str(name or "")
        self.detail = str(detail or "")
        message = self.code
        if self.name:
            message += f":{self.name}"
        if self.detail:
            message += f":{self.detail}"
        super().__init__(message)


def normalize_data_name(value: Any) -> str:
    return str(value or "").strip().lower()


def validate_data_name(value: Any) -> str:
    name = normalize_data_name(value)
    if not name or not _DATA_NAME_RE.fullmatch(name):
        raise DataNameError("invalid_business_data_name", name=name)
    return name


def data_name_matches_patterns(name: str, patterns: Iterable[str]) -> bool:
    key = normalize_data_name(name)
    wanted = [str(item or "").strip().lower() for item in patterns if str(item or "").strip()]
    return bool(key and any(fnmatchcase(key, pattern) for pattern in wanted))


def _segments(path: str) -> list[tuple[str, bool]]:
    text = str(path or "").strip()
    if text.startswith("$."):
        text = text[2:]
    elif text == "$":
        return []
    result: list[tuple[str, bool]] = []
    for raw in [item for item in text.split(".") if item]:
        result.append((raw[:-3], True) if raw.endswith("[*]") else (raw, False))
    return result


def path_exists(value: Any, path: str) -> bool:
    segments = _segments(path)
    if not segments:
        return value is not None

    def exists(node: Any, index: int) -> bool:
        key, wildcard = segments[index]
        if not isinstance(node, dict) or key not in node:
            return False
        child = node[key]
        is_last = index == len(segments) - 1
        if wildcard:
            if not isinstance(child, list):
                return False
            if not child:
                return True
            if is_last:
                return True
            return all(exists(item, index + 1) for item in child)
        if is_last:
            return child is not None
        return exists(child, index + 1)

    return exists(value, 0)


def missing_required_paths(value: Any, required_paths: Iterable[str]) -> list[str]:
    return [
        str(path) for path in required_paths
        if str(path or "").strip() and not path_exists(value, str(path))
    ]


def _merge_projected(target: Any, source: Any, segments: list[tuple[str, bool]]) -> Any:
    if not segments:
        return deepcopy(source)
    if not isinstance(source, dict):
        return target
    if not isinstance(target, dict):
        target = {}
    key, wildcard = segments[0]
    if key not in source:
        return target
    child = source[key]
    tail = segments[1:]
    if wildcard:
        if not isinstance(child, list):
            return target
        existing = target.get(key)
        if not isinstance(existing, list):
            existing = [{} for _ in child]
        if len(existing) < len(child):
            existing.extend({} for _ in range(len(child) - len(existing)))
        target[key] = [
            _merge_projected(existing[i] if i < len(existing) else {}, item, tail)
            for i, item in enumerate(child)
        ]
        return target
    if not tail:
        target[key] = deepcopy(child)
        return target
    target[key] = _merge_projected(target.get(key, {}), child, tail)
    return target


def project_paths(value: Any, paths: Iterable[str]) -> Any:
    selected = [str(item).strip() for item in paths if str(item or "").strip()]
    if not selected:
        return deepcopy(value)
    projected: Any = {}
    for path in selected:
        projected = _merge_projected(projected, value, _segments(path))
    return projected


def estimate_json_chars(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":")))
    except Exception:
        return len(str(value))


def estimate_tokens(value: Any) -> int:
    chars = estimate_json_chars(value)
    return max(1, (chars + 3) // 4) if chars else 0


# Private Tool output keys are normalized at the Worker boundary.  These names
# are not exposed as cross-Worker transport contracts.
LEGACY_OUTPUT_NAME_MAP: dict[str, str] = {
    "entity_external_evidence": "evidence",
    "evidence_source_records": "evidence_sources",
    "entity_model_signals": "prediction",
    "market_ranking_signals": "ranking",
    "model_quality_metrics": "model_metrics",
    "backtest_summary": "backtest",
    "selected_strategy_state": "strategy",
    "current_portfolio_state": "portfolio",
    "portfolio_positions": "positions",
    "account_financial_state": "account",
    "user_profile_state": "user_profile",
    "user_constraints": "user_constraints",
    "financial_relation_paths": "relations",
    "graph_relation_facts": "relations",
    "entity_fundamentals": "financial",
    "market_snapshot": "market",
    "peer_valuation_context": "valuation",
    "market_flow_context": "market_flow",
    "entity_analysis": "analysis",
    "entity_analysis_uncertainty": "analysis_uncertainty",
    "portfolio_risk_result": "risk",
    "risk_constraint_review": "risk_constraints",
    "reviewed_proposal": "proposal",
    "proposal.rebalance": "rebalance",
    "system_diagnosis": "diagnosis",
    "runtime_status": "runtime_status",
    "user_facing_report": "report",
    "goal_completion_summary": "goal_summary",
    "portfolio_graph_context": "portfolio_graph_context",
    "evidence_graph_context": "evidence_graph_context",
}


def normalize_worker_output_name(value: str) -> str:
    raw = str(value or "").strip()
    return LEGACY_OUTPUT_NAME_MAP.get(raw, normalize_data_name(raw))


__all__ = [
    "DataNameError", "LEGACY_OUTPUT_NAME_MAP", "data_name_matches_patterns",
    "estimate_json_chars", "estimate_tokens", "missing_required_paths",
    "normalize_data_name", "normalize_worker_output_name", "path_exists",
    "project_paths", "validate_data_name",
]
