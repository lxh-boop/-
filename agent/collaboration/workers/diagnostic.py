"""Execute the system-diagnostic Worker's bounded graph connectivity check.

The current capability verifies the Neo4j financial graph and returns a
``GraphWorkerResult``. It does not inspect the full application runtime, repair
services, or change graph and business state.
"""

from __future__ import annotations

from agent.graph.provider_adapter import GraphProviderAdapter

from ..models import GraphAgentTask, GraphWorkerResult, ResultStatus


def run_diagnostic(
    provider: GraphProviderAdapter,
    task: GraphAgentTask,
) -> GraphWorkerResult:
    provider.identity.store.verify_connectivity()
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=ResultStatus.COMPLETED,
        focus_refs=task.focus_refs,
        summary="Neo4j 金融事实图连接正常。",
        findings=[
            {
                "kind": "neo4j_connectivity",
                "status": "ok",
                "graph_id": provider.identity.store.graph_id,
            }
        ],
        confidence=1.0,
    )
