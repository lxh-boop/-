"""Business-function backends used by Worker-private atomic tools."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent.graph.contracts import GraphRef
from agent.services.market_analysis_service import market_analysis_service


class ApplicationMarketToolBackend:
    """Expose atomic market reads without exposing application services to Workers."""

    def __init__(
        self,
        *,
        stock_ref_resolver: Callable[[GraphRef], str] | None = None,
    ) -> None:
        self._stock_ref_resolver = stock_ref_resolver

    def resolve_stock_query(self, ref: GraphRef) -> str:
        if self._stock_ref_resolver is not None:
            value = str(self._stock_ref_resolver(ref) or "").strip()
            if value:
                return value
        return str(ref.node_id or "").strip()

    def read_ranking(
        self,
        *,
        stock_code: str = "",
        top_k: int = 20,
        output_dir: str | Path = "outputs",
        model_name: str = "",
    ) -> dict[str, Any]:
        return market_analysis_service.get_ranking(
            stock_code=stock_code or None,
            top_k=max(1, min(int(top_k), 100)),
            output_dir=output_dir,
            model_name=model_name or None,
        )

    def lookup_stock(
        self,
        query: str,
        *,
        user_id: str,
        output_dir: str | Path,
    ) -> dict[str, Any]:
        return market_analysis_service.lookup_stock(
            query,
            user_id=user_id,
            output_dir=output_dir,
        )

    def read_signal_summary(
        self,
        *,
        user_id: str,
        output_dir: str | Path,
        sort_by: str = "original_rank",
    ) -> dict[str, Any]:
        payload = dict(
            market_analysis_service.get_signal_summary(
                output_dir=output_dir,
                user_id=user_id,
                sort_by=sort_by,
                include_dataframe=False,
            )
        )
        data = dict(payload.get("data") or {})
        data.pop("dataframe", None)
        payload["data"] = data
        return payload


__all__ = ["ApplicationMarketToolBackend"]
