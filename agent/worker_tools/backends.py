"""Narrow dependency protocols for Worker-private atomic tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from agent.graph.contracts import GraphPathRef, GraphRef


class EvidenceToolBackend(Protocol):
    def analyze_entities(
        self,
        refs: list[GraphRef],
        *,
        user_id: str,
        output_dir: str | Path,
        db_path: str | Path | None,
    ) -> dict[str, Any]: ...

    def search_evidence(
        self,
        refs: list[GraphRef],
        *,
        query: str,
        top_k: int,
        output_dir: str | Path,
        db_path: str | Path | None,
        as_of_time: str = "",
    ) -> dict[str, Any]: ...

    def ingest_evidence(
        self,
        search_results: list[dict[str, Any]],
        *,
        source_task_id: str,
        source_agent_id: str,
    ) -> dict[str, Any]: ...


class PortfolioToolBackend(Protocol):
    def read_portfolio_snapshot(
        self,
        *,
        user_id: str,
        output_dir: str | Path,
        db_path: str | Path | None,
    ) -> dict[str, Any]: ...

    def materialize_portfolio_snapshot(
        self,
        portfolio_payload: dict[str, Any],
        *,
        user_id: str,
        as_of_time: str,
        source_task_id: str,
        source_agent_id: str,
    ) -> dict[str, Any]: ...


class MarketToolBackend(Protocol):
    def resolve_stock_query(self, ref: GraphRef) -> str: ...

    def read_ranking(
        self,
        *,
        stock_code: str = "",
        top_k: int = 20,
        output_dir: str | Path = "outputs",
        model_name: str = "",
    ) -> dict[str, Any]: ...

    def lookup_stock(
        self,
        query: str,
        *,
        user_id: str,
        output_dir: str | Path,
    ) -> dict[str, Any]: ...

    def read_signal_summary(
        self,
        *,
        user_id: str,
        output_dir: str | Path,
        sort_by: str = "original_rank",
    ) -> dict[str, Any]: ...


class RiskToolBackend(Protocol):
    def analyze_risk(
        self,
        *,
        user_id: str,
        output_dir: str | Path,
        db_path: str | Path | None,
        portfolio_ref: GraphRef | None = None,
    ) -> dict[str, Any]: ...


class DiagnosticToolBackend(Protocol):
    def check_connectivity(self) -> dict[str, Any]: ...


class ImpactToolBackend(Protocol):
    def find_paths(
        self,
        *,
        cause_refs: list[GraphRef],
        portfolio_ref: GraphRef,
        as_of_time: str = "",
    ) -> list[GraphPathRef]: ...

    def summarize_paths(
        self,
        paths: list[GraphPathRef],
    ) -> dict[str, Any]: ...


__all__ = [
    "DiagnosticToolBackend",
    "EvidenceToolBackend",
    "ImpactToolBackend",
    "MarketToolBackend",
    "PortfolioToolBackend",
    "RiskToolBackend",
]
