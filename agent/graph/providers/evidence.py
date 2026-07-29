"""Evidence-domain bridge from GraphRefs to existing evidence services.

Entity analysis and evidence retrieval stay behind this private adapter so
provider symbols never enter public Agent contracts. The current retrieval path
also ingests returned evidence into the financial graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.graph.contracts import GraphRef
from agent.graph.evidence_ingestion import EvidenceIngestionService, ExtractedMention

from .common import ProviderIdentityResolver, records_from_payload, sources_from_payload


@dataclass
class EvidenceGraphProvider:
    """Evidence-domain provider operations behind the GraphRef boundary."""

    identity_resolver: ProviderIdentityResolver
    evidence_ingestion: EvidenceIngestionService

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
            code = self.identity_resolver.provider_symbol(ref)
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
                    "records": records_from_payload(raw),
                    "sources": sources_from_payload(raw),
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
            code = self.identity_resolver.provider_symbol(ref)
            raw = service.get_stock_evidence(
                code,
                query=query,
                as_of_date=as_of_time or None,
                top_k=top_k,
                output_dir=output_dir,
                db_path=db_path,
            )
            rows = records_from_payload(raw)
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
                    "sources": sources_from_payload(raw),
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
