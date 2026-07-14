from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.decision_log_tool import summarize_decisions
from agent.portfolio_tool import get_paper_orders, summarize_portfolio
from agent.recommendation_tool import get_latest_recommendations
from agent.report_tool import read_latest_report
from scoring.schemas import COMPLIANCE_DISCLAIMER


class PortfolioReviewAgent:
    name = "portfolio_review"

    def answer(
        self,
        query: str,
        user_id: str = "default",
        trade_date: str | None = None,
        stock_code: str | None = None,
        output_dir: str | Path = "outputs",
        db_path: str | Path | None = None,
        top_k: int = 10,
    ) -> dict[str, Any]:
        portfolio = summarize_portfolio(user_id=user_id, output_dir=output_dir)
        recommendations = get_latest_recommendations(output_dir=output_dir, top_k=top_k)
        decisions = summarize_decisions(user_id=user_id, trade_date=trade_date, db_path=db_path)
        orders = get_paper_orders(user_id=user_id, output_dir=output_dir)
        report = read_latest_report(output_dir=output_dir)
        answer = self._compose_answer(portfolio, recommendations, decisions, orders, report)
        return {
            "agent": self.name,
            "answer": answer,
            "data": {
                "portfolio": portfolio,
                "recommendations": recommendations,
                "decisions": decisions,
                "orders": orders,
                "report": report,
            },
            "tool_calls": [
                "portfolio_tool.summarize_portfolio",
                "recommendation_tool.get_latest_recommendations",
                "decision_log_tool.summarize_decisions",
                "report_tool.read_latest_report",
            ],
            "risk_warning": "Portfolio review is for paper trading and risk inspection only.",
            "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
        }

    def _compose_answer(
        self,
        portfolio: dict[str, Any],
        recommendations: dict[str, Any],
        decisions: dict[str, Any],
        orders: dict[str, Any],
        report: dict[str, Any],
    ) -> str:
        lines = ["Paper portfolio review:"]
        account = portfolio.get("account") or {}
        lines.append(
            f"- PnL source: total_assets={account.get('total_assets')} cash={account.get('cash')} cumulative_return={account.get('cumulative_return')}."
        )
        lines.append(f"- Industry exposure: {portfolio.get('industry_exposure') or {}}.")
        lines.append(f"- Position ratio: {portfolio.get('position_ratio', 0):.2%}.")
        lines.append(f"- Latest paper order count: {orders.get('count', 0)}.")
        lines.append(f"- Recommendation numeric adjustment counts: {recommendations.get('adjustment_counts') or {}}.")
        lines.append(f"- Decision numeric adjustment counts: {decisions.get('adjustment_counts') or {}}.")
        if portfolio.get("risk_warnings"):
            lines.append(f"- Risk warnings: {portfolio.get('risk_warnings')}.")
        else:
            lines.append("- No stored portfolio risk warning was found.")
        lines.append("- Follow-up: inspect concentration, cash ratio, high-risk holdings, and evidence chunk ids before changing any paper setup.")
        if not report.get("ok"):
            lines.append("- No latest pipeline report was found.")
        lines.append(f"- Compliance: {COMPLIANCE_DISCLAIMER}")
        return "\n".join(lines)
