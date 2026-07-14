from __future__ import annotations

from typing import Any

from agent.agent_protocol import AgentOutput, make_message_id, output_summary
from agent.agent_specs import REPORTING, get_agent_spec
from agent.orchestration.result_aggregator import aggregate_multi_task_answer


def _line(label: str, value: Any) -> str:
    if value in (None, "", []):
        return ""
    return f"- {label}: {value}"


class ReportingAgent:
    role = REPORTING

    def __init__(self) -> None:
        self.spec = get_agent_spec(self.role)

    def run(
        self,
        *,
        market_output: dict[str, Any],
        portfolio_output: dict[str, Any],
        task_results: dict[str, dict[str, Any]] | None = None,
        language: str = "zh",
        handoff_from: str = "portfolio_analysis",
        handoff_to: str = "",
    ) -> tuple[AgentOutput, str]:
        market_analysis = dict(market_output.get("analysis") or {})
        portfolio_analysis = dict(portfolio_output.get("analysis") or {})
        market_status = market_output.get("status", "")
        portfolio_status = portfolio_output.get("status", "")
        evidence_count = len(market_output.get("evidence") or [])
        source_count = len(market_output.get("sources") or []) + len(portfolio_output.get("sources") or [])

        structured_answer = ""
        if task_results:
            structured_answer = aggregate_multi_task_answer(
                dict(task_results or {}),
                language=language,
            )
            intents = {
                str(result.get("intent") or "")
                for result in (task_results or {}).values()
                if isinstance(result, dict)
            }
            if (
                language != "en"
                and {"portfolio_state", "portfolio_risk", "ranking"}.issubset(intents)
                and "推荐方案" not in structured_answer
            ):
                structured_answer = "\n".join(
                    [
                        structured_answer,
                        "",
                        "推荐方案：优先参考当前模型排名和组合风险，后续如需调整，应先生成待确认预案。",
                        "",
                        "为什么更稳健：该方案先检查当前持仓集中度、现金比例和风险约束，再结合排名候选做只读比较，不自动执行，也不会直接改动模拟盘。",
                    ]
                ).strip()

        if structured_answer:
            lines = [
                structured_answer,
                "",
                "Traceability:" if language == "en" else "可追溯信息：",
                _line("source records" if language == "en" else "来源记录数", source_count),
                (
                    "No write, approval, or commit operation was executed."
                    if language == "en"
                    else "本次只生成只读分析，不执行写入、审批或 Commit。"
                ),
            ]
        elif language == "en":
            lines = [
                "Read-only multi-agent analysis completed.",
                "",
                "Market Intelligence:",
                _line("status", market_status),
                _line("evidence records", evidence_count),
                _line("execution batches", market_analysis.get("execution_batches")),
                "",
                "Portfolio Analysis:",
                _line("status", portfolio_status),
                _line("positions", portfolio_analysis.get("position_count")),
                _line("risk level", portfolio_analysis.get("risk_level")),
                "",
                "Traceability:",
                _line("source records", source_count),
                "No write, approval, or commit operation was executed.",
            ]
        else:
            lines = [
                "Read-only multi-agent analysis completed.",
                "",
                "Market Intelligence:",
                _line("status", market_status),
                _line("evidence records", evidence_count),
                _line("execution batches", market_analysis.get("execution_batches")),
                "",
                "Portfolio Analysis:",
                _line("status", portfolio_status),
                _line("positions", portfolio_analysis.get("position_count")),
                _line("risk level", portfolio_analysis.get("risk_level")),
                "",
                "Traceability:",
                _line("source records", source_count),
                "No write, approval, or commit operation was executed.",
            ]
        answer = "\n".join(line for line in lines if line)
        message_id = make_message_id(self.role)
        risks = [
            *[str(item) for item in (market_output.get("risks") or [])],
            *[str(item) for item in (portfolio_output.get("risks") or [])],
        ]
        output = AgentOutput(
            role=self.role,
            message_id=message_id,
            status="succeeded",
            evidence=list(market_output.get("evidence") or [])[:20],
            analysis={
                "market_status": market_status,
                "portfolio_status": portfolio_status,
                "evidence_count": evidence_count,
                "source_count": source_count,
            },
            proposal={
                "summary": "read_only_report",
                "write_operations": 0,
            },
            risks=risks,
            next_actions=[
                "review_sources_before_any_future_paper_action",
            ],
            sources=[
                *list(market_output.get("sources") or []),
                *list(portfolio_output.get("sources") or []),
            ][:30],
            tool_calls=[],
            handoff_from=handoff_from,
            handoff_to=handoff_to,
        )
        _ = output_summary(output)
        return output, answer
