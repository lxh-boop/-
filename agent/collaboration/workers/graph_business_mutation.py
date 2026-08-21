"""Deterministic business-Graph mutation adapter for approved Proposals."""
from __future__ import annotations

from typing import Any

from agent.proposals import ProposalArtifact
from agent.tool_runtime.contracts import AGENT_WRITE, OP_WRITE, ToolDefinition
from agent.tool_runtime.executor import ToolExecutor
from agent.tool_runtime.registry import ToolRegistry
from agent.tool_runtime.validation import description, result_schema, schema


class BusinessGraphMutationAdapter:
    mutation_scope = "graph.business.write"
    can_mutate = True
    execution_stage = "mutation"

    def __init__(self, validator: Any) -> None:
        self.validator = validator

    def execute(self, *, proposal: ProposalArtifact) -> dict[str, Any]:
        if proposal.proposal_type != "business_graph_mutation":
            return {"success": False, "code": "unsupported_graph_proposal_type", "business_effect_applied": False}
        if proposal.status.value != "executing":
            return {"success": False, "code": "proposal_not_executing", "business_effect_applied": False}
        patch_payload = (proposal.payload or {}).get("graph_patch")
        if not isinstance(patch_payload, dict) or not patch_payload:
            return {"success": False, "code": "graph_patch_required", "business_effect_applied": False}

        def apply_patch(args: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
            from agent.graph.contracts import GraphPatch

            result = self.validator.validate_and_apply(GraphPatch.from_dict(dict(args["graph_patch"])))
            if hasattr(result, "to_dict"):
                result = result.to_dict()
            data = dict(result or {}) if isinstance(result, dict) else {"result": str(result)}
            success = bool(data.get("success", True))
            return {
                "success": success,
                "message": str(data.get("message") or ""),
                "data": data,
                "errors": [] if success else [str(data.get("code") or "graph_commit_failed")],
                "warnings": [],
            }

        definition = ToolDefinition(
            name="runtime.graph.apply_approved_patch",
            display_name="Apply Approved Business Graph Patch",
            description=description(
                "Validate and apply one canonical approved business Graph patch.",
                "The WRITE Runtime has atomically claimed an approved canonical Graph Proposal.",
                "Graph reads, planning, or unapproved patches.",
                "proposal_id and graph_patch.",
                "graph commit result.",
                "May mutate the formal business Graph after validation.",
            ),
            input_schema=schema(
                {
                    "proposal_id": {"type": "string"},
                    "graph_patch": {"type": "object", "additionalProperties": True},
                },
                required=["proposal_id", "graph_patch"],
            ),
            output_schema=result_schema(),
            execution_handler=apply_patch,
            supported_actions=["apply_approved_proposal"],
            supported_objects=["business_graph"],
            produced_outputs=["graph_commit_result"],
            operation_type=OP_WRITE,
            allowed_agent_types=[AGENT_WRITE],
            permission_scope=OP_WRITE,
            requires_approval=True,
            mutates_business_state=True,
            idempotency="exactly_once_by_canonical_proposal",
            audit_level="high",
            visibility="system_private",
        )
        committed = ToolExecutor(ToolRegistry([definition])).execute(
            definition.name,
            {"proposal_id": proposal.proposal_id, "graph_patch": dict(patch_payload)},
            context={"canonical_proposal_id": proposal.proposal_id},
            agent_type=AGENT_WRITE,
            approval_granted=True,
        )
        plain = committed.to_legacy_dict()
        success = bool(plain.get("success"))
        return {
            "success": success,
            "code": "graph_commit_completed" if success else "graph_commit_failed",
            "data": dict(plain.get("data") or {}),
            "errors": [str(item) for item in plain.get("errors") or []],
            "warnings": [str(item) for item in plain.get("warnings") or []],
            "business_effect_applied": success,
            "canonical_proposal_id": proposal.proposal_id,
            "canonical_proposal_version": proposal.current_version,
        }


__all__ = ["BusinessGraphMutationAdapter"]
