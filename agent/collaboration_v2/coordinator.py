from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from core.llm import LLMService

from .agent_directory import (
    AgentDirectory,
    EVIDENCE_RETRIEVER,
    PORTFOLIO_ANALYST,
    REPORT_WRITER,
    RISK_ANALYST,
    SYSTEM_DIAGNOSTIC,
)
from .context_service import ContextService
from .control_gateway import ControlGateway
from .entry_decision import EntryDecisionError, MainEntryDecisionPlanner, RequestMode
from .models import AgentResult, AgentTask, MemoryUpdate, MissingContextItem, ResultStatus, TaskStatus
from .planner import CoordinatorPlanner
from .requirements import RequirementEngine
from .session_memory import SessionMemoryStore
from .specialist_runtime import SpecialistRuntime


MAX_CONTEXT_RECOVERY_ROUNDS = 2
MAX_PARALLEL_SPECIALISTS = 4
_STOCK_CODE = re.compile(r"(?<!\d)(\d{6})(?:\.(?:SH|SZ|BJ))?(?!\d)", re.IGNORECASE)


def _relation_type(context: dict[str, Any] | None) -> str:
    raw = dict(context or {})
    state = raw.get("conversation_state") if isinstance(raw.get("conversation_state"), dict) else {}
    turn = raw.get("turn_resolution") if isinstance(raw.get("turn_resolution"), dict) else {}
    return str(state.get("relation_type") or turn.get("relation_type") or raw.get("relation_type") or "")


def _safe_result_for_compatibility(task: AgentTask, result: AgentResult) -> dict[str, Any]:
    safe = result.safe_for_coordinator()
    success = result.status in {ResultStatus.COMPLETED, ResultStatus.PARTIAL, ResultStatus.PROPOSAL_READY}
    step_status = {
        ResultStatus.COMPLETED: "succeeded",
        ResultStatus.PARTIAL: "partial",
        ResultStatus.NEED_CONTEXT: "waiting_context",
        ResultStatus.PROPOSAL_READY: "succeeded",
        ResultStatus.BLOCKED: "failed",
        ResultStatus.FAILED: "failed",
    }[result.status]
    data = {
        "summary": result.summary,
        "findings": result.findings,
        "recommendations": result.recommendations,
        "evidence_refs": result.evidence_refs,
        "artifact_refs": result.artifact_refs,
        "missing_items": [item.to_dict() for item in result.missing_items],
    }
    for key in ("plan_id", "proposal_id", "requires_approval"):
        if result.metadata.get(key) not in (None, ""):
            data[key] = result.metadata.get(key)
    return {
        **safe,
        "success": success,
        "intent": task.task_type,  # Agent-level task type, never a Tool name.
        "step_status": step_status,
        "execution_mode": "agent_handoff",
        "message": result.summary,
        "data": data,
        "errors": [item.description for item in result.missing_items] if result.status == ResultStatus.NEED_CONTEXT else [],
    }


def _clarification_question(missing: list[MissingContextItem], language: str) -> str:
    unique: list[MissingContextItem] = []
    seen: set[str] = set()
    for item in missing:
        if item.key in seen:
            continue
        seen.add(item.key)
        unique.append(item)
    if not unique:
        return "Please provide the missing information." if language == "en" else "请补充完成任务所需的信息。"
    if language == "en":
        if len(unique) == 1:
            item = unique[0]
            suffix = f" Expected format: {item.expected_format}." if item.expected_format else ""
            return f"I still need {item.description}.{suffix}"
        details = "; ".join(
            f"{item.description}" + (f" ({item.expected_format})" if item.expected_format else "")
            for item in unique[:3]
        )
        return f"I still need the following information: {details}."
    if len(unique) == 1:
        item = unique[0]
        suffix = f"，格式可以是：{item.expected_format}" if item.expected_format else ""
        return f"还缺少{item.description}{suffix}。请补充后我会继续原任务。"
    details = "；".join(
        f"{item.description}" + (f"（{item.expected_format}）" if item.expected_format else "")
        for item in unique[:3]
    )
    return f"还缺少以下信息：{details}。请补充后我会继续原任务。"


class CoordinatorReporter:
    def __init__(self, *, llm_service: LLMService) -> None:
        self.llm_service = llm_service

    def build(self, query: str, results: dict[str, dict[str, Any]], *, language: str) -> str:
        report_results = [
            value
            for value in results.values()
            if str(value.get("agent_id") or "") == REPORT_WRITER
            and value.get("status") in {"completed", "partial", "proposal_ready"}
        ]
        if report_results:
            summary = str(report_results[-1].get("summary") or "").strip()
            if summary:
                return summary
        safe_results = {
            key: {
                "agent_id": value.get("agent_id"),
                "status": value.get("status"),
                "summary": value.get("summary"),
                "findings": value.get("findings") or [],
                "recommendations": value.get("recommendations") or [],
                "warnings": value.get("warnings") or [],
                "evidence_refs": value.get("evidence_refs") or [],
            }
            for key, value in results.items()
        }
        system = (
            "你是主协调 Agent 的最终汇总器。只能依据专业 Agent 的标准 AgentResult 汇总，"
            "不得调用或提及 Tool、内部函数、数据库表或原始返回。说明哪些任务完成、哪些存在不足；"
            "模拟盘 Proposal 不等于已经执行。"
        )
        return self.llm_service.generate_text(
            stage="main_coordinator_report",
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "user_request": query,
                            "specialist_results": safe_results,
                            "reply_language": language,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            temperature=0.0,
            max_output_tokens=2600,
            operation="aggregate_standard_agent_results",
        )


class AgentCollaborationCoordinator:
    def __init__(
        self,
        *,
        output_dir: str | Path,
        db_path: str | Path | None,
        llm_service: LLMService,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.db_path = db_path
        self.llm_service = llm_service
        self.directory = AgentDirectory()
        self.memory = SessionMemoryStore(output_dir=self.output_dir)
        self.planner = CoordinatorPlanner(self.directory, llm_service=llm_service)
        requirement_engine = RequirementEngine(llm_service=llm_service)
        self.specialist_runtime = SpecialistRuntime(
            requirement_engine=requirement_engine,
            llm_service=llm_service,
        )
        self.reporter = CoordinatorReporter(llm_service=llm_service)
        self.entry_planner = MainEntryDecisionPlanner(llm_service=llm_service)
        self.control_gateway = ControlGateway(output_dir=self.output_dir, db_path=self.db_path)

    def execute(
        self,
        *,
        query: str,
        decomposition: dict[str, Any],
        user_id: str,
        default_top_k: int,
        session_id: str,
        run_id: str,
        language: str,
        execution_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = str(session_id or f"session_{user_id}")
        self._ingest_user_turn(
            query=query,
            user_id=user_id,
            session_id=session,
            run_id=run_id,
            execution_context=execution_context,
        )
        memory_summary = self.memory.build_summary(session, task_objective=query, max_chars=6000)
        try:
            entry_decision = self.entry_planner.decide(
                query=query,
                memory_summary=memory_summary,
                execution_context=execution_context,
                language=language,
            )
        except EntryDecisionError as exc:
            return self._entry_failure(
                query=query,
                session=session,
                error=str(exc),
                language=language,
            )

        if entry_decision.mode in {RequestMode.CONFIRM, RequestMode.REJECT, RequestMode.LANGUAGE}:
            control = self.control_gateway.execute(
                decision=entry_decision,
                query=query,
                user_id=user_id,
                session_id=session,
                run_id=run_id,
                language=language,
                execution_context=execution_context,
            )
            control["agent_collaboration_v2"] = {
                "enabled": True,
                "single_entry": True,
                "entry_decision": entry_decision.to_dict(),
                "planner": {"planner": "control_gateway", "fallback_used": False},
                "agent_capability_catalog": self.directory.safe_catalog(),
                "session_memory": self.memory.stats(session),
                "session_memory_summary": self.memory.build_summary(session, task_objective=query, max_chars=3000),
                "waiting_tasks": [],
                "boundary": {
                    "main_agent_sees_tools": False,
                    "specialists_share_session_memory": True,
                    "full_memory_auto_injected": False,
                    "missing_context_classification": "unified",
                    "legacy_router_reachable": False,
                    "single_entry_only": True,
                },
            }
            return control

        if entry_decision.mode == RequestMode.UNSUPPORTED:
            return self._unsupported_response(
                query=query,
                session=session,
                decision=entry_decision.to_dict(),
                language=language,
            )

        request_mode = "proposal" if entry_decision.mode == RequestMode.PROPOSAL else "analysis"
        try:
            tasks, planner_metadata = self.planner.plan(
                query=query,
                request_mode=request_mode,
                session_id=session,
                run_id=run_id,
                memory_summary=memory_summary,
                language=language,
            )
        except Exception as exc:
            return self._entry_failure(
                query=query,
                session=session,
                error=f"coordinator_plan_failed:{type(exc).__name__}:{exc}",
                language=language,
                entry_decision=entry_decision.to_dict(),
            )
        planner_metadata["entry_decision"] = entry_decision.to_dict()
        results, batches, handoffs = self._run_dag(
            tasks,
            query=query,
            user_id=user_id,
            default_top_k=default_top_k,
            language=language,
            execution_context=execution_context,
        )

        results, recovery_audit = self._recover_missing_context(
            tasks=tasks,
            results=results,
            query=query,
            user_id=user_id,
            default_top_k=default_top_k,
            language=language,
            execution_context=execution_context,
        )
        missing = [
            item
            for result in results.values()
            if result.status == ResultStatus.NEED_CONTEXT
            for item in result.missing_items
            if item.blocking
        ]
        need_clarification = bool(missing)
        clarification_question = _clarification_question(missing, language) if missing else ""
        if need_clarification:
            for task in tasks:
                result = results.get(task.task_id)
                if result and result.status == ResultStatus.NEED_CONTEXT:
                    task.status = TaskStatus.WAITING_CONTEXT
                    self.memory.register_waiting_task(task, [item.key for item in result.missing_items])
            answer = clarification_question
            execution_status = "waiting_context"
        else:
            safe_results = {task_id: result.safe_for_coordinator() for task_id, result in results.items()}
            try:
                answer = self.reporter.build(query, safe_results, language=language)
            except Exception as exc:
                return self._entry_failure(
                    query=query,
                    session=session,
                    error=f"coordinator_report_failed:{type(exc).__name__}:{exc}",
                    language=language,
                    entry_decision=entry_decision.to_dict(),
                )
            success_count = sum(
                1 for result in results.values() if result.status in {ResultStatus.COMPLETED, ResultStatus.PARTIAL, ResultStatus.PROPOSAL_READY}
            )
            failed_count = sum(1 for result in results.values() if result.status in {ResultStatus.FAILED, ResultStatus.BLOCKED})
            execution_status = "completed" if failed_count == 0 else ("partially_completed" if success_count else "failed")

        safe_task_results = {
            task.task_id: _safe_result_for_compatibility(task, results[task.task_id])
            for task in tasks
            if task.task_id in results
        }
        success = not need_clarification and any(item.get("success") for item in safe_task_results.values())
        warnings = list(
            dict.fromkeys(
                ([str(planner_metadata.get("warning"))] if planner_metadata.get("warning") else [])
                + [warning for result in results.values() for warning in result.warnings]
            )
        )
        errors = [
            result.summary
            for result in results.values()
            if result.status in {ResultStatus.FAILED, ResultStatus.BLOCKED}
        ]
        memory_stats = self.memory.stats(session)
        return {
            "success": bool(success),
            "answer": answer,
            "task_results": safe_task_results,
            "tool_calls": [],  # Hard boundary: coordinator never receives specialist Tool details.
            "internal_tool_call_count": sum(int(result.metadata.get("internal_call_count") or 0) for result in results.values()),
            "execution_order": [task.task_id for task in tasks if task.task_id in results],
            "execution_batches": batches,
            "warnings": warnings,
            "errors": errors,
            "execution_status": execution_status,
            "need_clarification": need_clarification,
            "clarification_question": clarification_question,
            "missing_context": [item.to_dict() for item in missing],
            "observations": [
                {
                    "task_id": task_id,
                    "agent_id": result.agent_id,
                    "status": result.status.value,
                    "summary": result.summary[:500],
                }
                for task_id, result in results.items()
            ],
            "replan_audit": recovery_audit,
            "replan_count": len(recovery_audit),
            "invalid_replan_block_count": 0,
            "replan_limits": {"max_rounds": MAX_CONTEXT_RECOVERY_ROUNDS},
            "agent_outputs": {task_id: result.safe_for_coordinator() for task_id, result in results.items()},
            "agent_timeline": [
                {
                    "step_id": task.task_id,
                    "role": task.assigned_agent,
                    "status": results[task.task_id].status.value if task.task_id in results else task.status.value,
                    "input_summary": task.objective[:300],
                    "output_summary": results[task.task_id].summary[:500] if task.task_id in results else "",
                    "depends_on": list(task.dependency_task_ids),
                }
                for task in tasks
            ],
            "handoff": {
                "handoff_available": bool(handoffs),
                "handoff_count": len(handoffs),
                "handoff_refs": handoffs,
                "safety": {
                    "coordinator_tool_visibility": "none",
                    "raw_payload_hidden": True,
                    "write_gateway_required": True,
                },
            },
            "agent_collaboration_v2": {
                "enabled": True,
                "planner": planner_metadata,
                "llm_runtime": {
                    "profile_id": self.llm_service.profile_id,
                    "config_hash": self.llm_service.config_hash,
                    "single_service_identity": True,
                },
                "agent_capability_catalog": self.directory.safe_catalog(),
                "session_memory": memory_stats,
                "session_memory_summary": self.memory.build_summary(session, task_objective=query, max_chars=3000),
                "waiting_tasks": [
                    {"task_id": row.get("task_id"), "missing_keys": row.get("missing_keys"), "attempt": row.get("attempt")}
                    for row in self.memory.list_waiting_tasks(session)
                ],
                "boundary": {
                    "main_agent_sees_tools": False,
                    "specialists_share_session_memory": True,
                    "full_memory_auto_injected": False,
                    "missing_context_classification": "unified",
                    "legacy_router_reachable": False,
                    "single_entry_only": True,
                },
                "single_entry": True,
                "entry_decision": entry_decision.to_dict(),
            },
        }

    def _entry_failure(
        self,
        *,
        query: str,
        session: str,
        error: str,
        language: str,
        entry_decision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        answer = (
            "The Main Coordinator could not reliably understand this request. No legacy router or keyword fallback was used."
            if language == "en"
            else "主 Agent 当前无法可靠理解本次请求。本次没有调用旧路由，也没有使用关键词业务兜底。"
        )
        return {
            "success": False,
            "answer": answer,
            "task_results": {},
            "tool_calls": [],
            "internal_tool_call_count": 0,
            "execution_order": [],
            "execution_batches": [],
            "warnings": [],
            "errors": [str(error)],
            "execution_status": "failed",
            "need_clarification": False,
            "clarification_question": "",
            "missing_context": [],
            "observations": [],
            "replan_audit": [],
            "replan_count": 0,
            "invalid_replan_block_count": 0,
            "replan_limits": {"max_rounds": 0},
            "agent_outputs": {},
            "agent_timeline": [],
            "handoff": {"handoff_available": False, "handoff_count": 0, "handoff_refs": []},
            "effective_intent": "agent_collaboration_v2",
            "agent_collaboration_v2": {
                "enabled": True,
                "single_entry": True,
                "entry_decision": dict(entry_decision or {}),
                "planner": {"planner": "unavailable", "fallback_used": False},
                "agent_capability_catalog": self.directory.safe_catalog(),
                "session_memory": self.memory.stats(session),
                "session_memory_summary": self.memory.build_summary(session, task_objective=query, max_chars=3000),
                "waiting_tasks": [],
                "boundary": {
                    "main_agent_sees_tools": False,
                    "legacy_router_reachable": False,
                    "keyword_business_fallback_used": False,
                    "single_entry_only": True,
                },
            },
        }

    def _unsupported_response(
        self,
        *,
        query: str,
        session: str,
        decision: dict[str, Any],
        language: str,
    ) -> dict[str, Any]:
        answer = (
            "This request is outside the currently connected Agent capabilities."
            if language == "en"
            else "该请求超出当前已接入的专业 Agent 能力范围。"
        )
        result = self._entry_failure(
            query=query,
            session=session,
            error="unsupported_by_main_coordinator",
            language=language,
            entry_decision=decision,
        )
        result["answer"] = answer
        result["execution_status"] = "partially_completed"
        return result

    def _ingest_user_turn(
        self,
        *,
        query: str,
        user_id: str,
        session_id: str,
        run_id: str,
        execution_context: dict[str, Any] | None,
    ) -> None:
        self.memory.put(
            session_id=session_id,
            key="last_user_message",
            value=str(query or ""),
            value_type="text",
            summary=str(query or "")[:500],
            source_type="user_message",
            source_ref=run_id,
            confirmed=True,
            confidence=1.0,
        )
        self.memory.put(
            session_id=session_id,
            key=f"turn:{run_id}:user_message",
            value={"user_id": user_id, "message": str(query or "")},
            value_type="conversation_turn",
            summary=str(query or "")[:500],
            source_type="user_message",
            source_ref=run_id,
            confirmed=True,
            confidence=1.0,
        )
        codes = list(dict.fromkeys(_STOCK_CODE.findall(str(query or ""))))
        if len(codes) >= 2:
            self.memory.put(
                session_id=session_id,
                key="comparison_targets",
                value=codes,
                value_type="stock_list",
                summary="用户明确提供的股票比较对象：" + "、".join(codes),
                source_type="user_message",
                source_ref=run_id,
                confirmed=True,
                confidence=1.0,
            )
        elif len(codes) == 1:
            self.memory.put(
                session_id=session_id,
                key="stock_target",
                value=codes[0],
                value_type="stock_code",
                summary=f"用户明确提供的股票对象：{codes[0]}",
                source_type="user_message",
                source_ref=run_id,
                confirmed=True,
                confidence=1.0,
            )

        if _relation_type(execution_context) == "clarification_answer":
            for waiting in self.memory.list_waiting_tasks(session_id):
                for key in waiting.get("missing_keys") or []:
                    value: Any = str(query or "")
                    if key == "comparison_targets" and len(codes) >= 2:
                        value = codes
                    elif key in {"stock_target", "stock_code"} and codes:
                        value = codes[0]
                    self.memory.put(
                        session_id=session_id,
                        key=str(key),
                        value=value,
                        value_type="user_clarification",
                        summary=f"用户对缺失项 {key} 的补充：{str(query or '')[:300]}",
                        source_type="user_clarification",
                        source_ref=run_id,
                        confirmed=True,
                        confidence=1.0,
                    )
                self.memory.mark_waiting_resumed(str(waiting.get("waiting_id") or ""), new_run_id=run_id)

    def _run_dag(
        self,
        tasks: list[AgentTask],
        *,
        query: str,
        user_id: str,
        default_top_k: int,
        language: str,
        execution_context: dict[str, Any] | None,
    ) -> tuple[dict[str, AgentResult], list[dict[str, Any]], list[dict[str, Any]]]:
        results: dict[str, AgentResult] = {}
        pending = {task.task_id: task for task in tasks}
        batches: list[dict[str, Any]] = []
        handoffs: list[dict[str, Any]] = []
        while pending:
            ready = [
                task
                for task in pending.values()
                if all(dep in results for dep in task.dependency_task_ids)
            ]
            if not ready:
                for task in pending.values():
                    results[task.task_id] = AgentResult(
                        task_id=task.task_id,
                        agent_id=task.assigned_agent,
                        status=ResultStatus.FAILED,
                        summary="Agent 任务依赖无法满足。",
                        warnings=["agent_task_dependency_cycle_or_missing_result"],
                    )
                break
            ready.sort(key=lambda item: (item.priority, item.task_id))
            batch_info = {
                "batch_index": len(batches) + 1,
                "task_ids": [task.task_id for task in ready],
                "agents": [task.assigned_agent for task in ready],
                "parallel": len(ready) > 1,
            }
            with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_SPECIALISTS, len(ready))) as pool:
                futures = {
                    pool.submit(
                        self._run_one,
                        task,
                        query=query,
                        user_id=user_id,
                        default_top_k=default_top_k,
                        language=language,
                        dependency_results={dep: results[dep].safe_for_coordinator() for dep in task.dependency_task_ids},
                        execution_context=execution_context,
                    ): task
                    for task in ready
                }
                for future in as_completed(futures):
                    task = futures[future]
                    try:
                        result, handoff = future.result()
                    except Exception as exc:
                        result = AgentResult(
                            task_id=task.task_id,
                            agent_id=task.assigned_agent,
                            status=ResultStatus.FAILED,
                            summary="专业 Agent 运行失败。",
                            warnings=[f"specialist_runtime_failed:{type(exc).__name__}"],
                        )
                        handoff = {
                            "task_id": task.task_id,
                            "target_role": task.assigned_agent,
                            "status": "FAILED",
                        }
                    results[task.task_id] = result
                    handoffs.append(handoff)
                    self._apply_memory_updates(task, result)
                    pending.pop(task.task_id, None)
            batches.append(batch_info)
        return results, batches, handoffs

    def _run_one(
        self,
        task: AgentTask,
        *,
        query: str,
        user_id: str,
        default_top_k: int,
        language: str,
        dependency_results: dict[str, dict[str, Any]],
        execution_context: dict[str, Any] | None,
    ) -> tuple[AgentResult, dict[str, Any]]:
        context_service = ContextService(self.memory, dependency_results=dependency_results)
        handoff_ref = {
            "task_id": task.task_id,
            "target_role": task.assigned_agent,
            "status": "REQUESTED",
            "input_summary": {
                "objective": task.objective[:300],
                "task_type": task.task_type,
                "dependency_count": len(task.dependency_task_ids),
            },
            "memory_ref": {"session_id": task.session_id, "kind": "session_working_memory"},
            "tool_names_exposed": [],
        }
        # Reuse the existing HandoffCoordinator for trace/messages when available.
        try:
            from agent.handoff import AgentRole, HandoffCoordinator
            from agent.handoff.handoff_types import HandoffResult, HandoffStatus

            coordinator = HandoffCoordinator(
                user_id=user_id,
                output_dir=self.output_dir,
                conversation_id=task.session_id,
                run_id=task.run_id,
                max_specialists_per_run=8,
                same_role_repeat=4,
            )
            request = coordinator.plan_handoff(
                source_role=AgentRole.COORDINATOR,
                target_role=AgentRole.from_value(task.assigned_agent),
                reason="agent_level_specialist_task",
                task_id=task.task_id,
                input_summary=handoff_ref["input_summary"],
                tool_names=[],
                memory_refs=[handoff_ref["memory_ref"]],
                metadata={"task_type": task.task_type, "attempt": task.attempt},
            )
            holder: dict[str, AgentResult] = {}

            def runner(_request):
                result = self.specialist_runtime.run(
                    task,
                    current_user_request=query,
                    context_service=context_service,
                    dependency_results=dependency_results,
                    user_id=user_id,
                    output_dir=self.output_dir,
                    db_path=self.db_path,
                    default_top_k=default_top_k,
                    language=language,
                    execution_context=execution_context,
                )
                holder["result"] = result
                status = HandoffStatus.SUCCEEDED if result.status in {ResultStatus.COMPLETED, ResultStatus.PARTIAL, ResultStatus.PROPOSAL_READY} else HandoffStatus.FAILED
                return HandoffResult(
                    handoff_id=_request.handoff_id,
                    conversation_id=task.session_id,
                    run_id=task.run_id,
                    task_id=task.task_id,
                    target_role=AgentRole.from_value(task.assigned_agent),
                    status=status,
                    summary=result.summary[:600],
                    findings=result.findings[:10],
                    artifact_refs=result.artifact_refs[:20],
                    warnings=result.warnings[:10],
                    errors=[item.description for item in result.missing_items[:10]],
                    metadata={
                        "agent_result_status": result.status.value,
                        "context_access_count": result.metadata.get("context_access_count", 0),
                    },
                )

            handoff_result = coordinator.execute_handoff(request, runner)
            result = holder.get("result") or AgentResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.FAILED,
                summary=handoff_result.summary,
                warnings=list(handoff_result.warnings or []),
            )
            handoff_ref.update(
                {
                    "handoff_id": handoff_result.handoff_id,
                    "status": handoff_result.status.value,
                    "agent_result_status": result.status.value,
                }
            )
            return result, handoff_ref
        except Exception:
            result = self.specialist_runtime.run(
                task,
                current_user_request=query,
                context_service=context_service,
                dependency_results=dependency_results,
                user_id=user_id,
                output_dir=self.output_dir,
                db_path=self.db_path,
                default_top_k=default_top_k,
                language=language,
                execution_context=execution_context,
            )
            handoff_ref.update({"status": "COMPLETED", "agent_result_status": result.status.value})
            return result, handoff_ref

    def _apply_memory_updates(self, task: AgentTask, result: AgentResult) -> None:
        for update in result.memory_updates:
            self.memory.put(
                session_id=task.session_id,
                key=update.key,
                value=update.value,
                value_type=update.value_type,
                summary=update.summary,
                source_type=update.source_type,
                source_ref=update.source_ref or task.task_id,
                confirmed=update.confirmed,
                confidence=update.confidence,
            )
        if result.status in {ResultStatus.COMPLETED, ResultStatus.PARTIAL, ResultStatus.PROPOSAL_READY}:
            self.memory.put(
                session_id=task.session_id,
                key=f"agent_result:{task.task_id}",
                value=result.safe_for_coordinator(),
                value_type="agent_result",
                summary=result.summary[:600],
                source_type="agent_result",
                source_ref=task.task_id,
                confirmed=False,
                confidence=result.confidence,
            )

    def _select_recovery_role(self, item: MissingContextItem, requester: str) -> str:
        cards = [
            card
            for card in self.directory.safe_catalog()
            if card.get("agent_id") != requester and "resolve_context" in (card.get("accepted_task_types") or [])
        ]
        if not cards:
            return ""

        def validate(payload: dict[str, Any]) -> None:
            role = str(payload.get("assigned_agent") or "").upper()
            allowed = {str(card.get("agent_id") or "") for card in cards}
            if role not in allowed and role != "NONE":
                raise RuntimeError(f"invalid_context_recovery_agent:{role}")

        try:
            payload = self.llm_service.generate_json(
                stage="context_recovery_planner",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "根据缺失上下文和专业 Agent 能力卡，选择一个最适合尝试补齐该事实的专业 Agent。"
                            "不能选择原请求 Agent，不能看到或输出 Tool。若任何 Agent 都不适合，返回 NONE。"
                            "严格输出 JSON：{\"assigned_agent\":\"AGENT_ID|NONE\",\"reason\":\"\"}。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "missing_context": item.to_dict(),
                                "requesting_agent": requester,
                                "candidate_agents": cards,
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                max_output_tokens=500,
                validator=validate,
                operation="select_context_recovery_agent",
            )
        except Exception:
            return ""
        role = str(payload.get("assigned_agent") or "").upper()
        return "" if role == "NONE" else role

    def _recover_missing_context(
        self,
        *,
        tasks: list[AgentTask],
        results: dict[str, AgentResult],
        query: str,
        user_id: str,
        default_top_k: int,
        language: str,
        execution_context: dict[str, Any] | None,
    ) -> tuple[dict[str, AgentResult], list[dict[str, Any]]]:
        task_map = {task.task_id: task for task in tasks}
        audit: list[dict[str, Any]] = []
        for round_index in range(1, MAX_CONTEXT_RECOVERY_ROUNDS + 1):
            waiting = [result for result in results.values() if result.status == ResultStatus.NEED_CONTEXT]
            if not waiting:
                break
            progress = False
            for waiting_result in waiting:
                original = task_map.get(waiting_result.task_id)
                if original is None:
                    continue
                for missing in waiting_result.missing_items:
                    role = self._select_recovery_role(missing, original.assigned_agent)
                    if not role:
                        continue
                    recovery_id = f"{original.task_id}_recovery_{round_index}_{len(audit) + 1}"
                    recovery_task = AgentTask(
                        task_id=recovery_id,
                        run_id=original.run_id,
                        session_id=original.session_id,
                        assigned_agent=role,
                        objective=f"尝试从系统现有数据中补齐上下文：{missing.description}。不得向用户提问。",
                        task_type="resolve_context",
                        constraints=["只能返回标准结果；找不到则返回 NEED_CONTEXT"],
                        expected_output_type="context_resolution",
                        priority=0,
                        status=TaskStatus.READY,
                    )
                    recovery_result, _ = self._run_one(
                        recovery_task,
                        query=query,
                        user_id=user_id,
                        default_top_k=default_top_k,
                        language=language,
                        dependency_results={},
                        execution_context=execution_context,
                    )
                    audit.append(
                        {
                            "round": round_index,
                            "source_task_id": original.task_id,
                            "missing_key": missing.key,
                            "recovery_agent": role,
                            "recovery_task_id": recovery_id,
                            "status": recovery_result.status.value,
                        }
                    )
                    if recovery_result.status not in {ResultStatus.COMPLETED, ResultStatus.PARTIAL}:
                        continue
                    self.memory.put(
                        session_id=original.session_id,
                        key=missing.key,
                        value=recovery_result.safe_for_coordinator(),
                        value_type="context_resolution",
                        summary=recovery_result.summary[:600],
                        source_type="agent_result",
                        source_ref=recovery_id,
                        confirmed=False,
                        confidence=recovery_result.confidence,
                    )
                    original.attempt += 1
                    original.status = TaskStatus.READY
                    retried, _ = self._run_one(
                        original,
                        query=query,
                        user_id=user_id,
                        default_top_k=default_top_k,
                        language=language,
                        dependency_results={
                            dep: results[dep].safe_for_coordinator()
                            for dep in original.dependency_task_ids
                            if dep in results
                        },
                        execution_context=execution_context,
                    )
                    results[original.task_id] = retried
                    self._apply_memory_updates(original, retried)
                    progress = retried.status != ResultStatus.NEED_CONTEXT
                    if progress:
                        break
            if not progress:
                break
        return results, audit
