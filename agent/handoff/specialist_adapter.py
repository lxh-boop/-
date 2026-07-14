from __future__ import annotations

from typing import Any

from .handoff_policy import HandoffPolicy
from .handoff_sanitizer import HandoffSanitizer
from .handoff_types import AgentRole, HandoffRequest, HandoffResult, HandoffStatus


class SpecialistAdapter:
    def __init__(self, policy: HandoffPolicy | None = None, sanitizer: HandoffSanitizer | None = None) -> None:
        self.policy = policy or HandoffPolicy.default()
        self.sanitizer = sanitizer or HandoffSanitizer(self.policy)

    def run_portfolio_analyst(self, request: HandoffRequest, agent_output: dict[str, Any] | None = None) -> HandoffResult:
        return self._from_agent_output(request, agent_output or {}, role=AgentRole.PORTFOLIO_ANALYST)

    def run_risk_analyst(self, request: HandoffRequest, agent_output: dict[str, Any] | None = None) -> HandoffResult:
        return self._from_agent_output(request, agent_output or {}, role=AgentRole.RISK_ANALYST)

    def run_evidence_retriever(self, request: HandoffRequest, agent_output: dict[str, Any] | None = None) -> HandoffResult:
        return self._from_agent_output(request, agent_output or {}, role=AgentRole.EVIDENCE_RETRIEVER)

    def run_strategy_guard(self, request: HandoffRequest, agent_output: dict[str, Any] | None = None) -> HandoffResult:
        return self._from_agent_output(request, agent_output or {}, role=AgentRole.STRATEGY_GUARD)

    def run_report_writer(self, request: HandoffRequest, agent_output: dict[str, Any] | None = None) -> HandoffResult:
        return self._from_agent_output(request, agent_output or {}, role=AgentRole.REPORT_WRITER)

    def run_system_diagnostic(self, request: HandoffRequest, agent_output: dict[str, Any] | None = None) -> HandoffResult:
        return self._from_agent_output(request, agent_output or {}, role=AgentRole.SYSTEM_DIAGNOSTIC)

    def result_from_agent_output(
        self,
        request: HandoffRequest,
        agent_output: dict[str, Any] | Any,
        *,
        role: AgentRole | str | None = None,
        orchestration: dict[str, Any] | None = None,
    ) -> HandoffResult:
        output = agent_output.to_dict() if hasattr(agent_output, "to_dict") else dict(agent_output or {})
        if orchestration:
            output = {
                **output,
                "orchestration_status": orchestration.get("execution_status"),
                "warnings": list(output.get("warnings") or []) + list(orchestration.get("warnings") or []),
                "errors": list(output.get("errors") or []) + list(orchestration.get("errors") or []),
            }
        return self._from_agent_output(request, output, role=role or request.target_role)

    def _from_agent_output(
        self,
        request: HandoffRequest,
        agent_output: dict[str, Any],
        *,
        role: AgentRole | str,
    ) -> HandoffResult:
        target_role = AgentRole.from_value(role)
        status_text = str(agent_output.get("status") or "succeeded").lower()
        status = HandoffStatus.SUCCEEDED if status_text in {"succeeded", "success", "completed"} else HandoffStatus.FAILED
        if status_text == "skipped":
            status = HandoffStatus.SKIPPED
        if request.requires_approval:
            status = HandoffStatus.REQUIRES_APPROVAL
        summary = self._summary_for(agent_output, target_role)
        findings = self._findings_for(agent_output)
        recommended_action = {
            "next_actions": list(agent_output.get("next_actions") or [])[:8],
            "write_allowed": False,
            "requires_approval": bool(request.requires_approval),
        }
        result = HandoffResult(
            handoff_id=request.handoff_id,
            conversation_id=request.conversation_id,
            run_id=request.run_id,
            task_id=request.task_id,
            target_role=target_role,
            status=status,
            summary=summary,
            findings=findings,
            recommended_action=recommended_action,
            artifact_refs=list(request.artifact_refs or []),
            message_refs=list(request.message_refs or []),
            observation_refs=list(request.observation_refs or []),
            critic_refs=list(request.critic_refs or []),
            approval_refs=list(request.approval_refs or []),
            errors=[str(item) for item in (agent_output.get("errors") or agent_output.get("risks") or [])][:10],
            warnings=[str(item) for item in (agent_output.get("warnings") or [])][:10],
            metadata={
                "source_message_id": str(agent_output.get("message_id") or ""),
                "tool_call_count": len(agent_output.get("tool_calls") or []),
                "source_role": str(agent_output.get("role") or target_role.value),
            },
        )
        return HandoffResult.from_dict(self.sanitizer.sanitize_result(result, target="llm"))

    @staticmethod
    def _summary_for(agent_output: dict[str, Any], role: AgentRole) -> str:
        analysis = agent_output.get("analysis") if isinstance(agent_output.get("analysis"), dict) else {}
        evidence_count = len(agent_output.get("evidence") or [])
        source_count = len(agent_output.get("sources") or [])
        proposal = agent_output.get("proposal") if isinstance(agent_output.get("proposal"), dict) else {}
        parts = [f"role={role.value}", f"status={agent_output.get('status') or 'unknown'}"]
        if analysis:
            parts.append("analysis_keys=" + ",".join(sorted(str(key) for key in analysis.keys())[:8]))
        if evidence_count:
            parts.append(f"evidence={evidence_count}")
        if source_count:
            parts.append(f"sources={source_count}")
        if proposal:
            parts.append("proposal_keys=" + ",".join(sorted(str(key) for key in proposal.keys())[:8]))
        return " | ".join(parts)[:600]

    @staticmethod
    def _findings_for(agent_output: dict[str, Any]) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        analysis = agent_output.get("analysis") if isinstance(agent_output.get("analysis"), dict) else {}
        if analysis:
            findings.append({"kind": "analysis_summary", "keys": sorted(str(key) for key in analysis.keys())[:12]})
        if agent_output.get("evidence"):
            findings.append({"kind": "evidence_summary", "count": len(agent_output.get("evidence") or [])})
        if agent_output.get("sources"):
            findings.append({"kind": "source_summary", "count": len(agent_output.get("sources") or [])})
        proposal = agent_output.get("proposal") if isinstance(agent_output.get("proposal"), dict) else {}
        if proposal:
            findings.append(
                {
                    "kind": "proposal_summary",
                    "requires_confirmation": bool(proposal.get("requires_confirmation")),
                    "operation_type": str(proposal.get("operation_type") or proposal.get("summary") or ""),
                }
            )
        return findings[:10]
