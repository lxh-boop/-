from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.decision_log_tool import summarize_decisions
from agent.pipeline_tool import get_latest_pipeline_status
from agent.recommendation_tool import get_latest_recommendations
from agent.report_tool import read_latest_report
from scoring.schemas import COMPLIANCE_DISCLAIMER


class ModelMonitorAgent:
    name = "model_monitor"

    def answer(
        self,
        query: str,
        user_id: str = "default",
        trade_date: str | None = None,
        stock_code: str | None = None,
        output_dir: str | Path = "outputs",
        db_path: str | Path | None = None,
        top_k: int = 20,
    ) -> dict[str, Any]:
        recommendations = get_latest_recommendations(output_dir=output_dir, top_k=top_k)
        pipeline = get_latest_pipeline_status(output_dir=output_dir)
        decisions = summarize_decisions(user_id=user_id, trade_date=trade_date, db_path=db_path)
        report = read_latest_report(output_dir=output_dir)
        answer = self._compose_answer(recommendations, pipeline, decisions, report)
        return {
            "agent": self.name,
            "answer": answer,
            "data": {
                "recommendations": recommendations,
                "pipeline": pipeline,
                "decisions": decisions,
                "report": report,
            },
            "tool_calls": [
                "recommendation_tool.get_latest_recommendations",
                "pipeline_tool.get_latest_pipeline_status",
                "decision_log_tool.summarize_decisions",
                "report_tool.read_latest_report",
            ],
            "risk_warning": "Model monitoring is a simple artifact and rule check, not drift detection.",
            "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
        }

    def _compose_answer(
        self,
        recommendations: dict[str, Any],
        pipeline: dict[str, Any],
        decisions: dict[str, Any],
        report: dict[str, Any],
    ) -> str:
        lines = ["Model monitor summary:"]
        lines.append(f"- Final recommendations: {recommendations.get('total_count', 0)}.")
        lines.append(f"- Numeric adjustment counts: {recommendations.get('adjustment_counts') or {}}.")
        lines.append(f"- Pipeline artifacts available: {pipeline.get('ok')}.")
        lines.append(f"- Decision logs: {decisions.get('count', 0)}.")
        if not recommendations.get("ok"):
            lines.append("- Anomaly hint: final recommendation file is missing or empty.")
        if not pipeline.get("latest_report"):
            lines.append("- Anomaly hint: latest pipeline report is missing.")
        if report.get("ok"):
            lines.append(f"- Latest report path: {report.get('path')}.")
        lines.append("- This is a simple rule/status monitor and does not claim statistical model drift detection.")
        lines.append(f"- Compliance: {COMPLIANCE_DISCLAIMER}")
        return "\n".join(lines)
