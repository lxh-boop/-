"""Domain-scoped Worker executors used by the collaboration runtime.

Executors are imported lazily so one Worker can be loaded/tested without
importing every unrelated business integration (RAG, MCP, portfolio, etc.).
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "run_diagnostic": (".diagnostic", "run_diagnostic"),
    "run_entity_analysis": (".entity_analysis", "run_entity_analysis"),
    "run_evidence": (".evidence", "run_evidence"),
    "run_graph_context": (".graph_context", "run_graph_context"),
    "run_graph_impact": (".graph_impact", "run_graph_impact"),
    "run_internal_system": (".internal_system", "run_internal_system"),
    "run_report_writer": (".report_writer", "run_report_writer"),
    "run_risk": (".risk", "run_risk"),
    "run_strategy_guard": (".strategy_guard", "run_strategy_guard"),
}


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    value = getattr(import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS)
