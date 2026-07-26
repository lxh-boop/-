"""GraphRef backend adapter for registered atomic Worker tools."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import GraphRef
from .evidence_ingestion import EvidenceIngestionService
from .identity import GraphEntityIdentityService
from .portfolio_graph import PortfolioGraphService
from .providers import (
    EvidenceGraphProvider,
    PortfolioGraphProvider,
    PortfolioRiskProvider,
    ProviderIdentityResolver,
)


@dataclass
class GraphProviderAdapter:
    """Expose narrow domain operations without composite Worker workflows."""

    identity: GraphEntityIdentityService
    evidence_ingestion: EvidenceIngestionService
    portfolio_graph: PortfolioGraphService

    def __post_init__(self) -> None:
        self._identity_resolver = ProviderIdentityResolver(self.identity)
        self._evidence_provider = EvidenceGraphProvider(
            identity_resolver=self._identity_resolver,
            evidence_ingestion=self.evidence_ingestion,
        )
        self._portfolio_provider = PortfolioGraphProvider(self.portfolio_graph)
        self._risk_provider = PortfolioRiskProvider()

    def provider_symbol(self, ref: GraphRef) -> str:
        return self._identity_resolver.provider_symbol(ref)

    def analyze_entities(
        self,
        refs: list[GraphRef],
        *,
        user_id: str,
        output_dir: str | Path,
        db_path: str | Path | None,
    ) -> dict[str, Any]:
        return self._evidence_provider.analyze_entities(
            refs,
            user_id=user_id,
            output_dir=output_dir,
            db_path=db_path,
        )

    def check_connectivity(self) -> dict[str, Any]:
        self.identity.store.verify_connectivity()
        return {
            "success": True,
            "status": "ok",
            "graph_id": self.identity.store.graph_id,
        }

    def search_evidence(
        self,
        refs: list[GraphRef],
        *,
        query: str,
        top_k: int,
        output_dir: str | Path,
        db_path: str | Path | None,
        as_of_time: str = "",
    ) -> dict[str, Any]:
        return self._evidence_provider.search_evidence(
            refs,
            query=query,
            top_k=top_k,
            output_dir=output_dir,
            db_path=db_path,
            as_of_time=as_of_time,
        )

    def ingest_evidence(
        self,
        search_results: list[dict[str, Any]],
        *,
        source_task_id: str,
        source_agent_id: str,
    ) -> dict[str, Any]:
        return self._evidence_provider.ingest_evidence(
            search_results,
            source_task_id=source_task_id,
            source_agent_id=source_agent_id,
        )

    def read_portfolio_state(
        self,
        *,
        user_id: str,
        output_dir: str | Path,
        db_path: str | Path | None,
    ) -> dict[str, Any]:
        return self._portfolio_provider.read_portfolio_state(
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
        return self._portfolio_provider.materialize_portfolio_snapshot(
            portfolio_payload,
            user_id=user_id,
            as_of_time=as_of_time,
            source_task_id=source_task_id,
            source_agent_id=source_agent_id,
        )

    def analyze_risk(
        self,
        *,
        user_id: str,
        output_dir: str | Path,
        db_path: str | Path | None,
        portfolio_ref: GraphRef | None = None,
    ) -> dict[str, Any]:
        return self._risk_provider.analyze_risk(
            user_id=user_id,
            output_dir=output_dir,
            db_path=db_path,
            portfolio_ref=portfolio_ref,
        )


__all__ = ["GraphProviderAdapter"]
