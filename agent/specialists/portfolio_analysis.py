from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.agent_protocol import AgentOutput, make_message_id, output_summary
from agent.agent_specs import PORTFOLIO_ANALYSIS, get_agent_spec, validate_tool_allowed
from agent.orchestration.multi_task_executor import execute_multi_intent_plan


def _portfolio_analysis(task_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    analysis: dict[str, Any] = {
        "task_count": len(task_results),
        "position_count": None,
        "risk_source": "",
        "risk_level": "",
    }
    for result in task_results.values():
        if result.get("intent") == "portfolio_state":
            data = dict(result.get("data") or {})
            analysis["position_count"] = data.get("position_count")
            analysis["cash"] = data.get("cash")
            analysis["total_assets"] = data.get("total_assets")
        if result.get("intent") == "portfolio_risk":
            data = dict(result.get("data") or {})
            report = dict(data.get("risk_report") or {})
            analysis["risk_source"] = data.get("source", "")
            analysis["risk_level"] = (
                report.get("risk_level")
                or report.get("overall_risk_level")
                or report.get("portfolio_risk_level")
                or ""
            )
            analysis["risk_report_keys"] = sorted(report.keys())[:20]
    return analysis


class PortfolioAnalysisAgent:
    role = PORTFOLIO_ANALYSIS

    def __init__(self) -> None:
        self.spec = get_agent_spec(self.role)

    def run(
        self,
        *,
        tasks: list[dict[str, Any]],
        user_id: str,
        output_dir: str | Path,
        db_path: str | Path | None,
        default_top_k: int,
        session_id: str,
        language: str,
        context: dict[str, Any] | None = None,
        market_output: dict[str, Any] | None = None,
        handoff_from: str = "market_intelligence",
        handoff_to: str = "reporting",
    ) -> tuple[AgentOutput, dict[str, Any]]:
        for task in tasks:
            validate_tool_allowed(self.role, str(task.get("intent") or ""))

        if not tasks:
            message_id = make_message_id(self.role)
            output = AgentOutput(
                role=self.role,
                message_id=message_id,
                status="skipped",
                analysis={"reason": "no_portfolio_tasks"},
                handoff_from=handoff_from,
                handoff_to=handoff_to,
            )
            return output, {
                "success": True,
                "answer": "",
                "task_results": {},
                "tool_calls": [],
                "execution_batches": [],
                "warnings": [],
                "errors": [],
                "execution_status": "skipped",
            }

        orchestration = execute_multi_intent_plan(
            {"tasks": tasks},
            user_id=user_id,
            output_dir=output_dir,
            db_path=db_path,
            default_top_k=default_top_k,
            session_id=session_id,
            language=language,
            context={
                **dict(context or {}),
                "agent_role": self.role,
                "market_output": dict(market_output or {}),
            },
        )
        task_results = dict(orchestration.get("task_results") or {})
        message_id = make_message_id(self.role)
        analysis = _portfolio_analysis(task_results)
        output = AgentOutput(
            role=self.role,
            message_id=message_id,
            status="succeeded" if orchestration.get("success") else "failed",
            evidence=[],
            analysis={
                **analysis,
                "execution_status": orchestration.get("execution_status"),
                "market_handoff_status": (market_output or {}).get("status", ""),
            },
            proposal={},
            risks=list(orchestration.get("errors") or []),
            next_actions=[
                "handoff_portfolio_analysis_to_report",
            ],
            sources=[],
            tool_calls=list(orchestration.get("tool_calls") or []),
            handoff_from=handoff_from,
            handoff_to=handoff_to,
        )
        orchestration["agent_output_summary"] = output_summary(output)
        return output, orchestration
