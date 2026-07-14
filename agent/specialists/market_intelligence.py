from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.agent_protocol import AgentOutput, make_message_id, output_summary
from agent.agent_specs import MARKET_INTELLIGENCE, get_agent_spec, validate_tool_allowed
from agent.mcp.registry_bridge import is_mcp_tool_name, validate_mcp_tool_allowed_for_role
from agent.orchestration.multi_task_executor import execute_multi_intent_plan


def _collect_evidence(task_results: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for task_id, result in task_results.items():
        data = result.get("data") if isinstance(result, dict) else {}
        if not isinstance(data, dict):
            continue
        for key in ("records", "events", "chunks", "items"):
            rows = data.get(key) or []
            if not isinstance(rows, list):
                continue
            for row in rows[:20]:
                evidence.append(
                    {
                        "task_id": str(task_id),
                        "kind": key,
                        "record": row,
                    }
                )
    return evidence[:60]


def _collect_sources(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for item in evidence:
        record = item.get("record")
        if not isinstance(record, dict):
            continue
        source_id = (
            record.get("chunk_id")
            or record.get("news_id")
            or record.get("stock_code")
            or record.get("code")
            or ""
        )
        if not source_id:
            continue
        sources.append(
            {
                "source_type": str(item.get("kind") or "market"),
                "source_id": str(source_id),
                "title": str(
                    record.get("title")
                    or record.get("stock_name")
                    or record.get("name")
                    or source_id
                )[:160],
            }
        )
    return sources[:30]


class MarketIntelligenceAgent:
    role = MARKET_INTELLIGENCE

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
        handoff_from: str = "supervisor",
        handoff_to: str = "portfolio_analysis",
    ) -> tuple[AgentOutput, dict[str, Any]]:
        for task in tasks:
            intent = str(task.get("intent") or "")
            if is_mcp_tool_name(intent):
                validate_mcp_tool_allowed_for_role(self.role, intent, context)
            else:
                validate_tool_allowed(self.role, intent)

        if not tasks:
            message_id = make_message_id(self.role)
            output = AgentOutput(
                role=self.role,
                message_id=message_id,
                status="skipped",
                analysis={"reason": "no_market_tasks"},
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
            context={**dict(context or {}), "agent_role": self.role},
        )
        task_results = dict(orchestration.get("task_results") or {})
        evidence = _collect_evidence(task_results)
        sources = _collect_sources(evidence)
        message_id = make_message_id(self.role)
        output = AgentOutput(
            role=self.role,
            message_id=message_id,
            status="succeeded" if orchestration.get("success") else "failed",
            evidence=evidence,
            analysis={
                "task_count": len(tasks),
                "execution_status": orchestration.get("execution_status"),
                "execution_batches": orchestration.get("execution_batches") or [],
                "task_result_summary": {
                    task_id: {
                        "intent": result.get("intent"),
                        "success": bool(result.get("success")),
                        "status": result.get("step_status"),
                    }
                    for task_id, result in task_results.items()
                },
            },
            proposal={},
            risks=list(orchestration.get("errors") or []),
            next_actions=[
                "handoff_market_evidence_to_portfolio",
            ],
            sources=sources,
            tool_calls=list(orchestration.get("tool_calls") or []),
            handoff_from=handoff_from,
            handoff_to=handoff_to,
        )
        orchestration["agent_output_summary"] = output_summary(output)
        return output, orchestration
