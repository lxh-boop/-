from __future__ import annotations

from typing import Any


def extract_parameters(*_: Any, **__: Any) -> dict[str, Any]:
    """Fail fast when a removed legacy planner reaches parameter extraction.

    The formal runtime resolves financial objects through Neo4j and passes
    GraphRef contracts. This module exists only to make stale imports fail with
    a precise architecture error instead of silently rebuilding stock_code
    parameters.
    """

    raise RuntimeError(
        "legacy_parameter_extractor_disabled: use financial_graph_agent and GraphRef contracts"
    )


__all__ = ["extract_parameters"]
