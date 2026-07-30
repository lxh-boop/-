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

    def load_portfolio_snapshot(
        self,
        *,
        user_id: str,
        output_dir: str | Path,
        db_path: str | Path | None,
        as_of_time: str,
        source_task_id: str,
        source_agent_id: str,
    ) -> dict[str, Any]:
        from agent.services.portfolio_service import PortfolioService

        raw = PortfolioService().get_portfolio_state(
            user_id=user_id,
            output_dir=output_dir,
            db_path=db_path,
        )
        if raw.get("success") is False:
            message = str(raw.get("message") or "Portfolio state unavailable.")
            return {
                "success": False,
                "message": message,
                "error_type": str(raw.get("error_type") or "portfolio_snapshot_inconsistent"),
                "error_message": str(raw.get("error_message") or message),
                "failure_kind": str(raw.get("failure_kind") or "business_logic_error"),
                "retryable": bool(raw.get("retryable", False)),
                "warnings": list(raw.get("warnings") or []),
                "errors": list(raw.get("errors") or []),
            }
        if raw.get("found") is False or not raw.get("account"):
            message = str(raw.get("message") or "Portfolio account is not initialized.")
            return {
                "success": False,
                "message": message,
                "error_type": "portfolio_account_not_initialized",
                "error_message": message,
                "failure_kind": "business_result_empty",
                "retryable": False,
                "warnings": list(raw.get("warnings") or []),
                "errors": list(raw.get("errors") or ["missing_account"]),
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
