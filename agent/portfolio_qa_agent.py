from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent.decision_log_tool import get_decision_by_stock
from agent.portfolio_tool import summarize_portfolio
from agent.rag_tool import search_evidence
from agent.recommendation_tool import get_latest_recommendations, get_recommendation_by_stock
from scoring.schemas import COMPLIANCE_DISCLAIMER


def _extract_stock_code(text: str) -> str:
    match = re.search(r"(?<!\d)(\d{6})(?:\.(?:SH|SZ))?(?!\d)", text or "", re.I)
    return match.group(1) if match else ""


class PortfolioQAAgent:
    name = "portfolio_qa"

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
        tool_calls = []
        if stock_code:
            recommendation = get_recommendation_by_stock(stock_code, output_dir=output_dir)
            decision = get_decision_by_stock(user_id=user_id, stock_code=stock_code, trade_date=trade_date, db_path=db_path)
            evidence = search_evidence(query, filters={"stock_code": stock_code, "trade_date": trade_date}, db_path=db_path, top_k=top_k)
            tool_calls.extend(["recommendation_tool.get_recommendation_by_stock", "decision_log_tool.get_decision_by_stock", "rag_tool.search_evidence"])
        else:
            recommendation = get_latest_recommendations(output_dir=output_dir, top_k=top_k)
            decision = {"ok": False, "decision": {}, "message": "no stock code was supplied"}
            evidence = search_evidence(query, filters={"trade_date": trade_date}, db_path=db_path, top_k=top_k)
            tool_calls.extend(["recommendation_tool.get_latest_recommendations", "rag_tool.search_evidence"])
        portfolio = summarize_portfolio(user_id=user_id, output_dir=output_dir)
        tool_calls.append("portfolio_tool.summarize_portfolio")

        answer = self._compose_answer(stock_code, recommendation, decision, evidence, portfolio)
        return {
            "agent": self.name,
            "answer": answer,
            "data": {
                "recommendation": recommendation,
                "decision": decision,
                "evidence": evidence,
                "portfolio": portfolio,
            },
            "tool_calls": tool_calls,
            "risk_warning": "No deterministic buy/sell advice is provided.",
            "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
        }

    def _compose_answer(
        self,
        stock_code: str,
        recommendation: dict[str, Any],
        decision: dict[str, Any],
        evidence: dict[str, Any],
        portfolio: dict[str, Any],
    ) -> str:
        if stock_code:
            record = recommendation.get("record") or {}
            lines = [f"Portfolio QA for {stock_code}:"]
            if record:
                lines.extend(
                    [
                        f"- Model signal: score={record.get('original_pred_score')} rank={record.get('original_pred_rank')}.",
                        f"- News adjustment: {record.get('news_adjustment')}; effective news adjustment: {record.get('effective_news_adjustment')}.",
                        f"- User adjustment: {record.get('user_adjustment')}; combined adjustment: {record.get('combined_adjustment')}.",
                        f"- Position adjustment ratio: {record.get('position_adjustment_ratio')} with confidence={record.get('confidence')}.",
                        f"- Triggered rules: {record.get('triggered_rules') or []}.",
                        f"- Reason: {record.get('reason') or 'No reason text recorded.'}",
                    ]
                )
            else:
                lines.append("- No recommendation record was found for this stock.")
            if decision.get("ok"):
                log = decision.get("decision") or {}
                lines.append(f"- Decision log evidence chunks: {log.get('evidence_chunk_ids') or []}.")
            else:
                lines.append("- No decision log evidence was found.")
        else:
            lines = [f"Portfolio QA over latest TopK recommendations: {recommendation.get('display_count', 0)} rows loaded."]
            lines.append(f"- Numeric adjustment summary: {recommendation.get('adjustment_counts') or {}}.")

        if evidence.get("evidence"):
            ids = [row.get("chunk_id") for row in evidence.get("evidence", [])]
            lines.append(f"- RAG/news evidence chunk ids: {ids}.")
        else:
            lines.append("- No evidence was found in RAG/news chunks for this question.")
        lines.append(f"- Holding risk: {portfolio.get('risk_warnings') or 'no stored portfolio warning'}")
        lines.append("- Numeric adjustments are not real buy/sell instructions; paper trading execution remains simulated.")
        lines.append(f"- Compliance: {COMPLIANCE_DISCLAIMER}")
        return "\n".join(lines)
