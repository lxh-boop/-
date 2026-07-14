from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from database.repositories import NewsRepository
from database.sqlite_store import SQLiteStore
from agent.rag_tool import search_evidence
from scoring.schemas import COMPLIANCE_DISCLAIMER


def _extract_stock_code(text: str) -> str:
    match = re.search(r"(?<!\d)(\d{6})(?:\.(?:SH|SZ))?(?!\d)", text or "", re.I)
    return match.group(1) if match else ""


class EventImpactAgent:
    name = "event_impact"

    def answer(
        self,
        query: str,
        user_id: str = "default",
        trade_date: str | None = None,
        stock_code: str | None = None,
        output_dir: str | Path = "outputs",
        db_path: str | Path | None = None,
        top_k: int = 5,
    ) -> dict[str, Any]:
        stock_code = stock_code or _extract_stock_code(query)
        filters = {"trade_date": trade_date}
        if stock_code:
            filters["stock_code"] = stock_code
        evidence = search_evidence(query, filters=filters, db_path=db_path, top_k=top_k)
        mappings = self._load_mappings(stock_code=stock_code, db_path=db_path)
        rules = self._load_industry_rules(db_path=db_path)
        answer = self._compose_answer(query, stock_code, evidence, mappings, rules)
        return {
            "agent": self.name,
            "answer": answer,
            "data": {"evidence": evidence, "news_stock_mappings": mappings, "industry_event_rules": rules},
            "tool_calls": ["rag_tool.search_evidence", "database.news_stock_mapping", "database.industry_event_rule"],
            "risk_warning": "Event impact is uncertain and is not a buy/sell instruction.",
            "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
        }

    def _load_mappings(self, stock_code: str | None, db_path: str | Path | None) -> list[dict[str, Any]]:
        try:
            repo = NewsRepository(db_path)
            if stock_code:
                return repo.list_news_stock_mappings(stock_code=stock_code)
            return repo.list_news_stock_mappings()
        except Exception:
            return []

    def _load_industry_rules(self, db_path: str | Path | None) -> list[dict[str, Any]]:
        try:
            return SQLiteStore(db_path).list("industry_event_rule")
        except Exception:
            return []

    def _compose_answer(
        self,
        query: str,
        stock_code: str,
        evidence: dict[str, Any],
        mappings: list[dict[str, Any]],
        rules: list[dict[str, Any]],
    ) -> str:
        lines = [f"Event impact review for query: {query}"]
        if evidence.get("evidence"):
            event_types = sorted({str(row.get("event_type") or "unknown") for row in evidence["evidence"]})
            industries = sorted({str(row.get("industry") or "unknown") for row in evidence["evidence"]})
            lines.append(f"- Event types: {event_types}.")
            lines.append(f"- Affected industries from evidence: {industries}.")
            lines.append(f"- Evidence chunk ids: {[row.get('chunk_id') for row in evidence['evidence']]}.")
        else:
            lines.append("- No evidence was found for this event query.")
        if mappings:
            affected = sorted({str(row.get("stock_code") or "") for row in mappings if row.get("stock_code")})
            directions = sorted({str(row.get("impact_direction") or "neutral") for row in mappings})
            confidence = max(float(row.get("mapping_confidence") or 0.0) for row in mappings)
            lines.append(f"- Direct/indirect affected stocks in mappings: {affected[:20]}.")
            lines.append(f"- Direction labels: {directions}; max mapping confidence={confidence:.3f}.")
        else:
            lines.append("- No news_stock_mapping rows were found.")
        if rules:
            lines.append(f"- Industry event rules available: {len(rules)}.")
        else:
            lines.append("- No industry_event_rule rows were found.")
        if stock_code:
            lines.append(f"- Focus stock: {stock_code}.")
        lines.append("- Uncertainty: event direction and mapping confidence should be reviewed with source evidence.")
        lines.append(f"- Compliance: {COMPLIANCE_DISCLAIMER}")
        return "\n".join(lines)
