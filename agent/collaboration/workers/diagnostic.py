"""Execute W07 bounded runtime/system diagnostics."""

from __future__ import annotations

from agent.graph.provider_adapter import GraphProviderAdapter

from ..models import GraphAgentTask, GraphWorkerResult, ResultStatus
from .common import materialize_promised_slots


def run_diagnostic(
    provider: GraphProviderAdapter,
    task: GraphAgentTask,
) -> GraphWorkerResult:
    provider.identity.store.verify_connectivity()
    diagnostic = {
        "diagnostic_target": str(task.args.get("diagnostic_target") or task.objective),
        "checked_components": ["neo4j_financial_graph"],
        "findings": [
            {
                "kind": "neo4j_connectivity",
                "status": "ok",
                "graph_id": provider.identity.store.graph_id,
            }
        ],
        "root_cause": "",
    }
    slots = materialize_promised_slots(task, diagnostic)
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=ResultStatus.COMPLETED,
        output_type="DiagnosticResult",
        data={**diagnostic, "slots": slots},
        error=None,
        focus_refs=task.focus_refs,
        summary="Neo4j 金融事实图连接正常。",
        findings=list(diagnostic["findings"]),
        confidence=1.0,
    )


__all__ = ["run_diagnostic"]
