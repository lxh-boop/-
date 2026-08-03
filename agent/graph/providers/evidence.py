"""Evidence-domain bridge from GraphRefs to external evidence services.

Collection and persistence are deliberately separated. W01 uses the read-only
collection path. W08 may later persist a supplied collection into the financial
graph through the explicit write method.
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
    """Evidence operations behind the GraphRef boundary."""

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
        """Compatibility read path retained for older callers.

        W01 no longer exposes analysis as a public capability. New entity-level
        interpretation belongs to W09.
        """
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

    def collect_external_evidence(
        self,
        refs: list[GraphRef],
        *,
        query: str,
        top_k: int,
        output_dir: str | Path,
        db_path: str | Path | None,
        as_of_time: str = "",
    ) -> dict[str, Any]:
        """Collect external evidence without writing Neo4j or business state."""
        from agent.services.evidence_service import EvidenceService

        service = EvidenceService()
        results: list[dict[str, Any]] = []
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
            results.append(
                {
                    "focus_ref": ref.to_dict(),
                    "success": bool(raw.get("success")),
                    "message": str(raw.get("message") or ""),
                    "records": records_from_payload(raw),
                    "sources": sources_from_payload(raw),
                    "warnings": list(raw.get("warnings") or []),
                    "errors": list(raw.get("errors") or []),
                }
            )
        return {
            "success": bool(results) and any(item["success"] for item in results),
            "results": results,
            "write_performed": False,
        }

    def retrieve_evidence(
        self,
        refs: list[GraphRef],
        *,
        query: str,
        top_k: int,
        output_dir: str | Path,
        db_path: str | Path | None,
        source_task_id: str = "",
        source_agent_id: str = "",
        as_of_time: str = "",
    ) -> dict[str, Any]:
        """Backward-compatible alias for the read-only collection path."""
        del source_task_id, source_agent_id
        return self.collect_external_evidence(
            refs,
            query=query,
            top_k=top_k,
            output_dir=output_dir,
            db_path=db_path,
            as_of_time=as_of_time,
        )

    def materialize_evidence_graph(
        self,
        *,
        evidence_collection: dict[str, Any],
        source_task_id: str,
        source_agent_id: str,
    ) -> dict[str, Any]:
        """Persist a supplied evidence collection as derived Neo4j graph state."""
        evidence_refs: list[dict[str, Any]] = []
        ingestion_results: list[dict[str, Any]] = []
        for result in evidence_collection.get("results") or []:
            if not isinstance(result, dict) or not isinstance(result.get("focus_ref"), dict):
                continue
            focus_ref = GraphRef.from_dict(result["focus_ref"])
            code = self.identity_resolver.provider_symbol(focus_ref)
            for index, row in enumerate(result.get("records") or [], start=1):
                if not isinstance(row, dict):
                    continue
                evidence_class = str(
                    row.get("evidence_type") or row.get("source_type") or "news"
                )
                try:
                    applied = self.evidence_ingestion.ingest(
                        record=row,
                        evidence_class=evidence_class,
                        source_task_id=source_task_id,
                        source_agent_id=source_agent_id,
                        mentions=[
                            ExtractedMention(
                                mention_text=str(
                                    row.get("stock_name") or row.get("name") or code
                                ),
                                resolved_ref=focus_ref,
                                role="about",
                                confidence=1.0,
                            )
                        ],
                        assertions=[],
                        source_ref=str(
                            row.get("source_id")
                            or row.get("news_id")
                            or f"provider:{code}:{index}"
                        ),
                    )
                    ingestion_results.append(applied)
                    evidence_refs.extend(
                        item
                        for item in applied.get("evidence_refs") or []
                        if isinstance(item, dict)
                    )
                except Exception as exc:  # retain partial writes and explicit failures
                    ingestion_results.append(
                        {
                            "error": f"{type(exc).__name__}:{exc}",
                            "record_index": index,
                            "focus_ref": focus_ref.to_dict(),
                        }
                    )
        errors = [item for item in ingestion_results if item.get("error")]
        return {
            "success": bool(ingestion_results) and len(errors) < len(ingestion_results),
            "evidence_refs": evidence_refs,
            "ingestion_results": ingestion_results,
            "written_record_count": len(ingestion_results) - len(errors),
            "failed_record_count": len(errors),
        }
