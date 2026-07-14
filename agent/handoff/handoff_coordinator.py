from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from agent.communication.integration import publish_agent_message
from agent.communication.message_types import MessageType

from .handoff_policy import HandoffPolicy
from .handoff_router import HandoffRouter
from .handoff_sanitizer import HandoffSanitizer
from .handoff_types import AgentRole, HandoffPriority, HandoffRequest, HandoffResult, HandoffStatus, HandoffTrace
from .specialist_adapter import SpecialistAdapter


Runner = Callable[[HandoffRequest], HandoffResult]


class HandoffCoordinator:
    def __init__(
        self,
        *,
        user_id: str = "default",
        output_dir: str | Path = "outputs",
        conversation_id: str = "",
        run_id: str = "",
        policy: HandoffPolicy | None = None,
        router: HandoffRouter | None = None,
        sanitizer: HandoffSanitizer | None = None,
        adapter: SpecialistAdapter | None = None,
        max_handoff_depth: int = 2,
        max_specialists_per_run: int = 3,
        same_role_repeat: int = 1,
    ) -> None:
        self.user_id = str(user_id or "default")
        self.output_dir = output_dir
        self.conversation_id = str(conversation_id or "")
        self.run_id = str(run_id or "")
        self.policy = policy or HandoffPolicy(default_max_depth=max_handoff_depth)
        self.router = router or HandoffRouter(self.policy)
        self.sanitizer = sanitizer or HandoffSanitizer(self.policy)
        self.adapter = adapter or SpecialistAdapter(self.policy, self.sanitizer)
        self.max_specialists_per_run = max(1, int(max_specialists_per_run))
        self.same_role_repeat = max(1, int(same_role_repeat))
        self.trace = HandoffTrace(run_id=self.run_id)
        self.results: list[HandoffResult] = []

    def plan_handoff(
        self,
        *,
        source_role: AgentRole | str = AgentRole.COORDINATOR,
        target_role: AgentRole | str,
        reason: str,
        task_id: str = "",
        input_summary: dict[str, Any] | None = None,
        tool_names: list[str] | None = None,
        context_refs: list[dict[str, Any]] | None = None,
        message_refs: list[dict[str, Any]] | None = None,
        observation_refs: list[dict[str, Any]] | None = None,
        replan_refs: list[dict[str, Any]] | None = None,
        critic_refs: list[dict[str, Any]] | None = None,
        memory_refs: list[dict[str, Any]] | None = None,
        artifact_refs: list[dict[str, Any]] | None = None,
        approval_refs: list[dict[str, Any]] | None = None,
        priority: HandoffPriority | str = HandoffPriority.NORMAL,
        metadata: dict[str, Any] | None = None,
    ) -> HandoffRequest:
        request = self.router.build_request(
            source_role=source_role,
            target_role=target_role,
            reason=reason,
            conversation_id=self.conversation_id,
            run_id=self.run_id,
            task_id=task_id,
            input_summary=dict(input_summary or {}),
            context_refs=list(context_refs or []),
            message_refs=list(message_refs or []),
            observation_refs=list(observation_refs or []),
            replan_refs=list(replan_refs or []),
            critic_refs=list(critic_refs or []),
            memory_refs=list(memory_refs or []),
            artifact_refs=list(artifact_refs or []),
            approval_refs=list(approval_refs or []),
            priority=priority,
            tool_names=list(tool_names or []),
            metadata=dict(metadata or {}),
        )
        return HandoffRequest.from_dict(self.sanitizer.sanitize_request(request, target="llm"))

    def execute_handoff(self, request: HandoffRequest, runner: Runner) -> HandoffResult:
        blocked = self._block_reason(request)
        self._publish_request(request, blocked_reason=blocked)
        if blocked:
            result = HandoffResult(
                handoff_id=request.handoff_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                task_id=request.task_id,
                target_role=request.target_role,
                status=HandoffStatus.BLOCKED,
                summary=f"handoff_blocked:{blocked}",
                errors=[blocked],
            )
            self._record_result(request, result, blocked=True)
            return result

        self._publish_accepted(request)
        try:
            result = runner(request)
        except Exception as exc:
            result = HandoffResult(
                handoff_id=request.handoff_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                task_id=request.task_id,
                target_role=request.target_role,
                status=HandoffStatus.FAILED,
                summary=f"handoff_runner_failed:{type(exc).__name__}",
                errors=[type(exc).__name__],
            )
        result = HandoffResult.from_dict(self.sanitizer.sanitize_result(result, target="llm"))
        self._record_result(request, result, blocked=result.status == HandoffStatus.BLOCKED)
        return result

    def merge_handoff_results(self, results: list[HandoffResult] | None = None) -> dict[str, Any]:
        rows = list(results or self.results)
        statuses = [row.status.value for row in rows]
        roles = [row.target_role.value for row in rows]
        blocked_count = sum(1 for row in rows if row.status == HandoffStatus.BLOCKED)
        role_summaries = [
            {
                "handoff_id": row.handoff_id,
                "target_role": row.target_role.value,
                "status": row.status.value,
                "summary": row.summary[:240],
            }
            for row in rows
        ]
        summary = {
            "handoff_available": bool(rows),
            "trace_id": self.trace.trace_id,
            "run_id": self.run_id,
            "handoff_count": len(rows),
            "roles_used": sorted(set(roles)),
            "latest_handoff_status": statuses[-1] if statuses else "",
            "blocked_handoff_count": blocked_count,
            "handoff_refs": [
                {
                    "handoff_id": row.handoff_id,
                    "target_role": row.target_role.value,
                    "status": row.status.value,
                }
                for row in rows
            ],
            "handoff_role_summaries": role_summaries,
            "trace": self.trace.to_dict(),
            "safety": {
                "secrets_redacted": True,
                "raw_paths_hidden": True,
                "raw_payload_hidden": True,
                "write_gateway_required": True,
            },
        }
        return self.sanitizer.sanitize_for_ui(summary)

    def stop_on_blocking_result(self, results: list[HandoffResult] | None = None) -> bool:
        return any(row.status == HandoffStatus.BLOCKED for row in (results or self.results))

    def limit_handoff_depth(self, depth: int) -> bool:
        return int(depth) < self.policy.max_handoff_depth()

    def _block_reason(self, request: HandoffRequest) -> str:
        if len(self.results) >= self.max_specialists_per_run:
            return "max_specialists_per_run_exceeded"
        role_count = sum(1 for row in self.results if row.target_role == request.target_role)
        if role_count >= self.same_role_repeat:
            return "same_role_repeat_exceeded"
        errors = self.policy.validate_request(request)
        if errors:
            return ";".join(errors)
        if request.target_role != AgentRole.COORDINATOR and any(
            tool in self.policy.blocked_tools_for_role(request.target_role) for tool in request.allowed_tools
        ):
            return "blocked_tool_requested"
        return ""

    def _record_result(self, request: HandoffRequest, result: HandoffResult, *, blocked: bool = False) -> None:
        self.trace.add_request(request)
        self.results.append(result)
        self._publish_result(result, blocked=blocked)

    def _publish_request(self, request: HandoffRequest, *, blocked_reason: str = "") -> None:
        payload = self.sanitizer.sanitize_request(
            {
                "handoff_id": request.handoff_id,
                "source_role": request.source_role.value,
                "target_role": request.target_role.value,
                "status": "blocked" if blocked_reason else "requested",
                "reason": request.reason[:240],
                "refs": {
                    "context": len(request.context_refs),
                    "message": len(request.message_refs),
                    "artifact": len(request.artifact_refs),
                    "approval": len(request.approval_refs),
                },
                "blocked_reason": blocked_reason,
            },
            target="ui",
        )
        publish_agent_message(
            output_dir=self.output_dir,
            user_id=self.user_id,
            conversation_id=self.conversation_id,
            run_id=self.run_id,
            task_id=request.task_id,
            sender=request.source_role.value,
            receiver=request.target_role.value,
            message_type=MessageType.HANDOFF_BLOCKED if blocked_reason else MessageType.HANDOFF_REQUESTED,
            payload=payload,
            payload_schema="phase17.handoff_request.v1",
            context_refs=request.context_refs,
            artifact_refs=request.artifact_refs,
            approval_refs=request.approval_refs,
        )

    def _publish_accepted(self, request: HandoffRequest) -> None:
        publish_agent_message(
            output_dir=self.output_dir,
            user_id=self.user_id,
            conversation_id=self.conversation_id,
            run_id=self.run_id,
            task_id=request.task_id,
            sender=request.target_role.value,
            receiver=request.source_role.value,
            message_type=MessageType.HANDOFF_ACCEPTED,
            payload={
                "handoff_id": request.handoff_id,
                "target_role": request.target_role.value,
                "status": "accepted",
                "summary": "specialist accepted safe handoff request",
            },
            payload_schema="phase17.handoff_accepted.v1",
            context_refs=request.context_refs,
        )

    def _publish_result(self, result: HandoffResult, *, blocked: bool = False) -> None:
        payload = self.sanitizer.sanitize_result(
            {
                "handoff_id": result.handoff_id,
                "target_role": result.target_role.value,
                "status": result.status.value,
                "summary": result.summary[:360],
                "refs": {
                    "artifact": len(result.artifact_refs),
                    "message": len(result.message_refs),
                    "observation": len(result.observation_refs),
                    "critic": len(result.critic_refs),
                    "approval": len(result.approval_refs),
                },
            },
            target="ui",
        )
        publish_agent_message(
            output_dir=self.output_dir,
            user_id=self.user_id,
            conversation_id=self.conversation_id,
            run_id=self.run_id,
            task_id=result.task_id,
            sender=result.target_role.value,
            receiver=AgentRole.COORDINATOR.value,
            message_type=MessageType.HANDOFF_BLOCKED if blocked else MessageType.HANDOFF_RESULT,
            payload=payload,
            payload_schema="phase17.handoff_result.v1",
            artifact_refs=result.artifact_refs,
            approval_refs=result.approval_refs,
        )
