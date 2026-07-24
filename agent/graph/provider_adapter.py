from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import GraphNodeKind, GraphRef
from .evidence_ingestion import EvidenceIngestionService, ExtractedMention
from .identity import GraphEntityIdentityService
from .portfolio_graph import PortfolioGraphService


def _records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    rows = data.get("records") or payload.get("records") or data.get("events") or data.get("chunks") or []
    return [dict(item) for item in rows if isinstance(item, dict)]


def _sources(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    rows = data.get("sources") or payload.get("sources") or []
    return [dict(item) for item in rows if isinstance(item, dict)]


@dataclass
class GraphProviderAdapter:
    """Private boundary from GraphRefs to existing data-provider APIs.

    Public Agents and Tools never accept or return provider-specific stock_code
    fields. Codes only exist inside this adapter because the underlying CSV/API
    providers still require them.
    """

    identity: GraphEntityIdentityService
    evidence_ingestion: EvidenceIngestionService
    portfolio_graph: PortfolioGraphService

    def provider_symbol(self, ref: GraphRef) -> str:
        if ref.node_kind != GraphNodeKind.OBJECT:
            raise ValueError("provider_symbol_requires_object_ref")
        value = self.identity.get_identity_value(
            ref,
            namespaces=["symbol", "exchange_symbol", "tushare", "local_symbol"],
        )
        if not value:
            raise RuntimeError(f"provider_identifier_missing:{ref.node_id}")
        return value.split(".")[0]

    def analyze_entities(
        self,
        refs: list[GraphRef],
        *,
        user_id: str,
        output_dir: str | Path,
        db_path: str | Path | None,
    ) -> dict[str, Any]:
        from agent.services.market_analysis_service import MarketAnalysisService

        service = MarketAnalysisService()
        results: list[dict[str, Any]] = []
        for ref in refs:
            code = self.provider_symbol(ref)
            raw = service.analyze_stock(
                stock_query=code,
                user_id=user_id,
                output_dir=output_dir,
                db_path=db_path,
            )
            results.append(
                {
                    "focus_ref": ref.to_dict(),
                    "success": bool(raw.get("success")),
                    "status": str(raw.get("status") or ""),
                    "message": str(raw.get("message") or ""),
                    "data": raw.get("data") if isinstance(raw.get("data"), dict) else {},
                    "records": _records(raw),
                    "sources": _sources(raw),
                    "warnings": list(raw.get("warnings") or []),
                    "errors": list(raw.get("errors") or []),
                }
            )
        return {
            "success": bool(results) and any(item["success"] for item in results),
            "results": results,
        }

    def retrieve_evidence(
        self,
        refs: list[GraphRef],
        *,
        query: str,
        top_k: int,
        output_dir: str | Path,
        db_path: str | Path | None,
        source_task_id: str,
        source_agent_id: str,
        as_of_time: str = "",
    ) -> dict[str, Any]:
        from agent.services.evidence_service import EvidenceService

        service = EvidenceService()
        graph_evidence_refs: list[GraphRef] = []
        results: list[dict[str, Any]] = []
        ingestion_results: list[dict[str, Any]] = []
        for ref in refs:
            code = self.provider_symbol(ref)
            raw = service.get_stock_evidence(
                code,
                query=query,
                as_of_date=as_of_time or None,
                top_k=top_k,
                output_dir=output_dir,
                db_path=db_path,
            )
            rows = _records(raw)
            for index, row in enumerate(rows, start=1):
                evidence_class = str(row.get("evidence_type") or row.get("source_type") or "news")
                try:
                    result = self.evidence_ingestion.ingest(
                        record=row,
                        evidence_class=evidence_class,
                        source_task_id=source_task_id,
                        source_agent_id=source_agent_id,
                        mentions=[
                            ExtractedMention(
                                mention_text=str(row.get("stock_name") or row.get("name") or code),
                                resolved_ref=ref,
                                role="about",
                                confidence=1.0,
                            )
                        ],
                        assertions=[],
                        source_ref=str(row.get("source_id") or row.get("news_id") or f"provider:{code}:{index}"),
                    )
                    ingestion_results.append(result)
                    patch_id = str(result.get("patch_id") or result.get("applied", {}).get("patch_id") or "")
                    for raw_ref in result.get("evidence_refs") or []:
                        if isinstance(raw_ref, dict):
                            graph_evidence_refs.append(GraphRef.from_dict(raw_ref))
                    if patch_id:
                        ingestion_results[-1]["patch_id"] = patch_id
                except Exception as exc:
                    ingestion_results.append({"error": f"{type(exc).__name__}:{exc}", "record_index": index})
            results.append(
                {
                    "focus_ref": ref.to_dict(),
                    "success": bool(raw.get("success")),
                    "message": str(raw.get("message") or ""),
                    "records": rows,
                    "sources": _sources(raw),
                    "warnings": list(raw.get("warnings") or []),
                    "errors": list(raw.get("errors") or []),
                }
            )
        return {
            "success": bool(results) and any(item["success"] for item in results),
            "results": results,
            "evidence_refs": [item.to_dict() for item in graph_evidence_refs],
            "ingestion_results": ingestion_results,
        }

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

    def analyze_risk(
        self,
        *,
        user_id: str,
        output_dir: str | Path,
        db_path: str | Path | None,
        portfolio_ref: GraphRef | None = None,
    ) -> dict[str, Any]:
        from agent.services.portfolio_risk_service import PortfolioRiskService

        raw = PortfolioRiskService().analyze_current_risk(
            user_id=user_id,
            output_dir=output_dir,
            db_path=db_path,
        )
        return {
            "success": bool(raw.get("success")),
            "portfolio_ref": portfolio_ref.to_dict() if portfolio_ref else None,
            "message": str(raw.get("message") or ""),
            "data": raw.get("data") if isinstance(raw.get("data"), dict) else {},
            "records": _records(raw),
            "sources": _sources(raw),
            "warnings": list(raw.get("warnings") or []),
            "errors": list(raw.get("errors") or []),
        }
