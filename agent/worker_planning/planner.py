"""LLM planner that selects only tools authorized for one Worker capability."""

from __future__ import annotations

import json
from typing import Any

from core.llm import LLMService

from agent.collaboration.models import GraphAgentTask
from agent.worker_tools.registry import WorkerToolDirectory

from .contracts import WorkerExecutionPlan
from .validator import WorkerPlanValidator


class WorkerPlanPlanner:
    """Generate a private-tool DAG without exposing it to the Main Agent."""

    def __init__(
        self,
        *,
        llm_service: LLMService,
        directory: WorkerToolDirectory,
    ) -> None:
        self.llm_service = llm_service
        self.directory = directory
        self.validator = WorkerPlanValidator(directory)

    def plan(
        self,
        *,
        task: GraphAgentTask,
        user_request: str,
        dependency_results: dict[str, dict[str, Any]],
        memory_values: dict[str, Any] | None = None,
        language: str = "zh",
    ) -> WorkerExecutionPlan:
        capability_id = str(task.capability_id or "").strip()
        catalog = self.directory.safe_catalog(capability_id)
        if not catalog:
            raise RuntimeError(
                f"worker_capability_has_no_private_tools:{capability_id}"
            )

        def validate(payload: dict[str, Any]) -> None:
            self.validator.parse_and_validate(
                payload,
                capability_id=capability_id,
            )

        payload = self.llm_service.generate_json(
            stage="worker_private_tool_planner",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a specialist Worker Agent. Build a minimal DAG "
                        "using only the private tools in the supplied catalog. "
                        "Choose tools from their descriptions and output contracts, "
                        "not from hard-coded task names. Do not invent arguments: "
                        "registered tools bind inputs deterministically from the "
                        "task, GraphRefs, approved context, and upstream results. "
                        "Only proposal tools may receive proposed_arguments; "
                        "never include user_id, account_id, approval credentials, "
                        "or confirmation tokens. Never select write tools. "
                        "Independent steps may run in "
                        "parallel; dependent steps must list dependency_step_ids. "
                        "Return strict JSON: "
                        '{"steps":[{"step_id":"step_1","tool_name":"...",'
                        '"objective":"...","dependency_step_ids":[],'
                        '"required_outputs":[],"proposed_arguments":{}}]}.'
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "capability_id": capability_id,
                            "capability_objective": task.objective,
                            "user_request": str(user_request or ""),
                            "focus_refs": [
                                ref.to_dict() for ref in task.focus_refs
                            ],
                            "context_refs": [
                                ref.to_dict() for ref in task.context_refs
                            ],
                            "dependency_results": dependency_results,
                            "confirmed_context_keys": sorted(
                                dict(memory_values or {})
                            ),
                            "required_capability_outputs": (
                                self.directory.required_outputs(capability_id)
                            ),
                            "max_plan_steps": self.directory.max_steps(
                                capability_id
                            ),
                            "private_tool_catalog": catalog,
                            "reply_language": language,
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                },
            ],
            max_output_tokens=1800,
            validator=validate,
            operation=f"worker_tool_plan:{capability_id}",
        )
        return self.validator.parse_and_validate(
            payload,
            capability_id=capability_id,
        )


__all__ = ["WorkerPlanPlanner"]
