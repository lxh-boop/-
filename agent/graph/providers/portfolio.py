"""Portfolio-domain bridge from application state to graph snapshots.

The adapter reads the authoritative paper-portfolio state and materializes a
traceable portfolio snapshot in the financial graph. It does not modify account
cash, positions, orders, strategy bindings, or trading state.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.graph.portfolio_graph import PortfolioGraphService


@dataclass
class PortfolioGraphProvider:
    """Portfolio-domain provider operations behind the GraphRef boundary."""

    portfolio_graph: PortfolioGraphService

    def read_portfolio_snapshot(
        self,
        *,
        user_id: str,
        output_dir: str | Path,
        db_path: str | Path | None,
    ) -> dict[str, Any]:
        from agent.services.portfolio_service import PortfolioService

        return PortfolioService().read_portfolio_snapshot(
            user_id=user_id,
            output_dir=output_dir,
            db_path=db_path,
        )

    def materialize_portfolio_snapshot(
        self,
        portfolio_payload: dict[str, Any],
        *,
        user_id: str,
        as_of_time: str,
        source_task_id: str,
        source_agent_id: str,
    ) -> dict[str, Any]:
        raw = dict(portfolio_payload or {})
        if not raw.get("success"):
            return {
                "success": False,
                "message": str(raw.get("message") or "Portfolio state unavailable."),
                "warnings": list(raw.get("warnings") or []),
                "errors": list(raw.get("errors") or []),
            }
        ref, graph_result = self.portfolio_graph.upsert_snapshot(
            user_id=user_id,
            portfolio_payload=raw,
            as_of_time=as_of_time,
            source_task_id=source_task_id,
            source_agent_id=source_agent_id,
        )
        return {
            "success": True,
            "portfolio_ref": ref.to_dict(),
            "holding_refs": graph_result.get("holding_refs") or [],
            "unresolved_positions": graph_result.get("unresolved_positions") or [],
            "portfolio": raw,
            "graph_write": graph_result.get("applied") or {},
        }
