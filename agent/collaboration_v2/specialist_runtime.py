from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from core.llm import LLMService

from .agent_directory import REPORT_WRITER, STRATEGY_GUARD
from .context_service import ContextService
from .contracts import is_system_queryable_context_key
from .models import AgentResult, AgentTask, MemoryUpdate, MissingContextItem, ResultStatus, TaskStatus
from .requirements import ContextRequirement, RequirementEngine
from .tool_runtime import ScopedBusinessToolRuntime


_MISSING_PATTERN = re.compile(r"(?:missing_required:|missing_)([a-zA-Z0-9_.-]+)")
_STOCK_PATTERN = re.compile(r"(?<!\d)(\d{6})(?:\.(?:SH|SZ|BJ))?(?!\d)", re.IGNORECASE)
_RAW_KEYS = {
    "raw_payload",
    "raw_tool_payload",
    "raw_positions",
    "raw_evidence",
    "tool_calls",
    "arguments",
    "sql",
    "traceback",
    "stack_trace",
    "confirmation_token",
    "confirmation_token_hash",
    "db_path",
    "output_dir",
    "local_path",
    "private_chain_of_thought",
    "chain_of_thought",
    "reasoning_content",
}


def _safe_scalar(value: Any, max_chars: int = 500) -> Any:
    if isinstance(value, str):
        return value[:max_chars] + ("…" if len(value) > max_chars else "")
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:max_chars]


def _safe_outline(value: Any, *, depth: int = 0) -> Any:
    if depth > 3:
        return "<summarized>"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        preferred_keys = {
            "status",
            "success",
            "message",
            "summary",
            "stock_code",
            "stock_name",
            "code",
            "name",
            "position_count",
            "order_count",
            "cash",
            "total_assets",
            "market_value",
            "risk_level",
            "overall_risk_level",
            "portfolio_risk_level",
            "returned_count",
            "event_count",
            "chunk_count",
            "score",
            "rank",
            "original_rank",
            "adjusted_rank",
            "news_adjustment",
            "user_adjustment",
            "plan_id",
            "proposal_id",
            "artifact_id",
            "source_id",
            "title",
            "date",
            "trade_date",
        }
        for key, item in value.items():
            name = str(key)
            if name.lower() in _RAW_KEYS:
                continue
            if name in preferred_keys:
                if isinstance(item, (dict, list)):
                    result[name] = _safe_outline(item, depth=depth + 1)
                else:
                    result[name] = _safe_scalar(item)
        for list_key in ("records", "positions", "orders", "events", "chunks", "items", "sources"):
            items = value.get(list_key)
            if isinstance(items, list):
                result[f"{list_key}_count"] = len(items)
                result[f"{list_key}_sample"] = [_safe_outline(item, depth=depth + 1) for item in items[:3]]
        if not result:
            result["available_keys"] = [str(key) for key in value.keys() if str(key).lower() not in _RAW_KEYS][:20]
        return result
    if isinstance(value, list):
        return {"count": len(value), "sample": [_safe_outline(item, depth=depth + 1) for item in value[:3]]}
    return _safe_scalar(value)


def _result_has_material_data(orchestration: dict[str, Any]) -> bool:
    if str(orchestration.get("answer") or "").strip():
        return True
    for result in (orchestration.get("task_results") or {}).values():
        if not isinstance(result, dict) or not result.get("success"):
            continue
        data = result.get("data")
        if isinstance(data, dict) and data:
            return True
    return False


def _missing_values(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [str(key) for key, present in value.items() if present not in (False, None, "", [], {})]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item or "").strip()]
    if value not in (None, ""):
        return [str(value)]
    return []


def _missing_item(
    *,
    key: str,
    category: str,
    description: str = "",
    expected_format: str = "",
    reason: str = "",
    origin_status: str = "",
    retryable: bool = True,
    searched_sources: list[str] | None = None,
) -> MissingContextItem:
    normalized_key = str(key or "required_context").strip()
    normalized_category = str(category or "unknown").strip().lower()
    if normalized_category == "unknown" and is_system_queryable_context_key(normalized_key):
        normalized_category = "system_data"
    if not description:
        if normalized_key in {"stock_target", "stock_code"}:
            description = "需要分析的股票"
        elif normalized_category == "system_data":
            description = f"系统中的 {normalized_key.replace('_', ' ')} 数据"
        elif normalized_category == "tool_failure":
            description = "当前专业能力或数据源"
        elif normalized_category == "upstream_result":
            description = "上游专业 Agent 结果"
        else:
            description = normalized_key.replace("_", " ")
    if not expected_format and normalized_category == "user_input":
        expected_format = "股票名称或股票代码" if normalized_key in {"stock_target", "stock_code", "comparison_targets"} else "可识别的具体值"
    return MissingContextItem(
        key=normalized_key,
        description=description,
        expected_format=expected_format,
        reason=reason,
        searched_sources=list(dict.fromkeys(searched_sources or [])),
        blocking=True,
        category=normalized_category,
        ask_user=normalized_category == "user_input",
        retryable=bool(retryable),
        system_queryable=normalized_category == "system_data",
        origin_status=origin_status,
    )


def _missing_from_orchestration(orchestration: dict[str, Any]) -> list[MissingContextItem]:
    """Preserve business-level missing/failure categories across the Agent boundary."""
    collected: list[MissingContextItem] = []
    seen: set[tuple[str, str]] = set()

    def add(item: MissingContextItem) -> None:
        signature = (item.key, item.category)
        if signature in seen:
            return
        seen.add(signature)
        collected.append(item)

    top_errors = [str(item) for item in orchestration.get("errors") or []]
    result_rows = orchestration.get("task_results") or {}
    if not isinstance(result_rows, dict):
        result_rows = {}

    for task_id, raw_result in result_rows.items():
        if not isinstance(raw_result, dict):
            continue
        data = raw_result.get("data") if isinstance(raw_result.get("data"), dict) else {}
        status = str(raw_result.get("status") or data.get("status") or "").strip().lower()
        retryable = bool(data.get("retryable", raw_result.get("retryable", True)))
        searched = ["task_input", "session_memory", "dependency_results", "specialist_business_capabilities"]

        user_missing = _missing_values(data.get("missing_parameters"))
        if status == "missing_required_parameters" and not user_missing:
            user_missing = _missing_values(data.get("required_parameters"))
        for key in user_missing:
            add(
                _missing_item(
                    key=key,
                    category="user_input",
                    reason=str(data.get("need_clarification") or raw_result.get("message") or "用户必须明确该业务参数。"),
                    origin_status=status or "missing_required_parameters",
                    retryable=retryable,
                    searched_sources=searched,
                )
            )

        system_missing = _missing_values(data.get("missing_system_data"))
        if status == "system_data_missing" and not system_missing:
            system_missing = _missing_values(data.get("required_system_data")) or [str(task_id or "system_data")]
        for key in system_missing:
            add(
                _missing_item(
                    key=key,
                    category="system_data",
                    reason=str(raw_result.get("message") or "系统当前没有可用的业务数据。"),
                    origin_status=status or "system_data_missing",
                    retryable=retryable,
                    searched_sources=searched,
                )
            )

        row_errors = [str(item) for item in raw_result.get("errors") or []]
        message = str(raw_result.get("message") or "")
        combined = " ".join([*row_errors, message]).lower()
        failure_markers = (
            "timeout", "timed out", "connection", "provider", "service unavailable",
            "tool_failure", "tool failed", "execution_failed", "database error",
            "data source", "rate limit", "circuit_open",
        )
        if not user_missing and not system_missing and any(marker in combined for marker in failure_markers):
            add(
                _missing_item(
                    key=f"runtime_{task_id}",
                    category="tool_failure",
                    description="当前专业能力或数据源",
                    reason="专业 Agent 的内部能力调用失败，不能通过要求用户补参来解决。",
                    origin_status=status or "tool_failure",
                    retryable=retryable,
                    searched_sources=["specialist_business_capabilities"],
                )
            )

        fallback_errors = [*row_errors]
        if "missing" in message.lower():
            fallback_errors.append(message)
        for error in fallback_errors:
            lowered = error.lower()
            fallback_keys: list[str] = []
            if "missing_stock_code" in lowered or "missing_required:stock_code" in lowered:
                fallback_keys.append("stock_target")
            fallback_keys.extend(match.strip(".:_") for match in _MISSING_PATTERN.findall(error))
            for key in fallback_keys:
                if not key or key in {"information", "context"}:
                    continue
                category = "system_data" if is_system_queryable_context_key(key) else "user_input"
                add(
                    _missing_item(
                        key=key,
                        category=category,
                        reason="专业 Agent 已检查任务输入、会话记忆、上游结果和自身能力，但仍无法获得该信息。",
                        origin_status=status or "missing_context",
                        retryable=retryable,
                        searched_sources=searched,
                    )
                )

    top_combined = " ".join(top_errors).lower()
    if top_errors and any(marker in top_combined for marker in ("execution_failed", "timeout", "connection", "circuit_open")):
        add(
            _missing_item(
                key="specialist_runtime",
                category="tool_failure",
                description="专业 Agent 运行时",
                reason="专业 Agent 运行失败；这不是用户参数缺失。",
                origin_status=str(orchestration.get("execution_status") or "tool_failure"),
                retryable=True,
                searched_sources=["specialist_runtime"],
            )
        )

    return collected


def _evidence_refs(orchestration: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for result in (orchestration.get("task_results") or {}).values():
        if not isinstance(result, dict):
            continue
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        for key in ("records", "events", "chunks", "items", "sources", "mcp_sources"):
            rows = data.get(key)
            if not isinstance(rows, list):
                continue
            for row in rows[:20]:
                if not isinstance(row, dict):
                    continue
                ref_id = str(
                    row.get("chunk_id")
                    or row.get("news_id")
                    or row.get("source_id")
                    or row.get("artifact_id")
                    or row.get("stock_code")
                    or row.get("code")
                    or ""
                )
                if not ref_id or ref_id in seen:
                    continue
                seen.add(ref_id)
                refs.append(
                    {
                        "source_type": key,
                        "source_id": ref_id,
                        "title": str(row.get("title") or row.get("stock_name") or row.get("name") or ref_id)[:180],
                    }
                )
    return refs[:50]


def _artifact_refs(orchestration: dict[str, Any]) -> list[dict[str, Any]]:
    """Preserve persisted Artifact IDs across the specialist boundary.

    Tool artifacts may appear at the task-result top level, in metadata, or in
    the business data envelope.  Runtime cache identifiers are intentionally
    not treated as persisted artifacts.
    """

    refs: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(value: Any, *, default_type: str = "tool_result") -> None:
        if isinstance(value, str):
            ref = {"artifact_id": value, "artifact_type": default_type}
        elif isinstance(value, dict):
            artifact_id = str(value.get("artifact_id") or "").strip()
            if not artifact_id:
                return
            ref = {
                str(key): _safe_scalar(item, 200)
                for key, item in value.items()
                if str(key).lower() not in _RAW_KEYS
                and key in {
                    "artifact_id", "artifact_type", "schema_version",
                    "stock_code", "stock_name", "created_at", "expires_at",
                    "content_summary", "summary",
                }
            }
            ref.setdefault("artifact_id", artifact_id)
            ref.setdefault("artifact_type", default_type)
        else:
            return
        artifact_id = str(ref.get("artifact_id") or "")
        if not artifact_id or artifact_id.startswith("runtime_cache_") or artifact_id in seen:
            return
        seen.add(artifact_id)
        refs.append(ref)

    for result in (orchestration.get("task_results") or {}).values():
        if not isinstance(result, dict):
            continue
        add(result)
        metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        add(metadata.get("artifact_ref"))
        for ref in result.get("artifact_refs") or []:
            add(ref)
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        add(data)
        for key in ("snapshot_id", "plan_id", "proposal_id"):
            if data.get(key):
                add(
                    {
                        "artifact_type": key,
                        "artifact_id": str(data[key])[:160],
                    },
                    default_type=key,
                )
        for ref in data.get("artifact_refs") or []:
            add(ref)
    return refs[:50]


def _findings(orchestration: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for task_id, result in (orchestration.get("task_results") or {}).items():
        if not isinstance(result, dict):
            continue
        findings.append(
            {
                "task_ref": str(task_id),
                "status": "completed" if result.get("success") else "failed",
                "message": str(result.get("message") or "")[:800],
                "data_summary": _safe_outline(result.get("data") if isinstance(result.get("data"), dict) else {}),
            }
        )
    return findings[:30]


def _stock_updates(task: AgentTask, orchestration: dict[str, Any]) -> list[MemoryUpdate]:
    text_parts = [task.objective, str(orchestration.get("answer") or "")]
    codes = list(dict.fromkeys(_STOCK_PATTERN.findall(" ".join(text_parts))))
    updates: list[MemoryUpdate] = []
    if len(codes) >= 2:
        updates.append(
            MemoryUpdate(
                key="comparison_targets",
                value=codes,
                value_type="stock_list",
                source_type="entity_resolution",
                source_ref=task.task_id,
                confirmed=False,
                confidence=0.9,
                summary="已识别的股票比较对象：" + "、".join(codes),
            )
        )
    elif len(codes) == 1:
        updates.append(
            MemoryUpdate(
                key="stock_target",
                value=codes[0],
                value_type="stock_code",
                source_type="entity_resolution",
                source_ref=task.task_id,
                confirmed=False,
                confidence=0.9,
                summary=f"当前股票对象：{codes[0]}",
            )
        )
    return updates


def _requirement_value_in_task(task: AgentTask, requirement: ContextRequirement, auto_context: dict[str, Any]) -> Any:
    key = requirement.key
    metadata = task.metadata
    if key in metadata and metadata[key] not in (None, "", [], {}):
        return metadata[key]
    if key == "specialist_results" and auto_context.get("dependency_results"):
        return auto_context["dependency_results"]
    if key in {"stock_target", "comparison_targets"}:
        combined = " ".join([task.objective, str(auto_context.get("current_user_request") or "")])
        codes = list(dict.fromkeys(_STOCK_PATTERN.findall(combined)))
        if key == "stock_target" and codes:
            return codes[0]
        if key == "comparison_targets" and len(codes) >= 2:
            return codes[:2]
    return None


class SpecialistRuntime:
    def __init__(
        self,
        *,
        requirement_engine: RequirementEngine,
        llm_service: LLMService,
        business_runtime: ScopedBusinessToolRuntime | None = None,
    ) -> None:
        self.requirement_engine = requirement_engine
        self.llm_service = llm_service
        self.business_runtime = business_runtime or ScopedBusinessToolRuntime(
            llm_service=llm_service,
        )

    def run(
        self,
        task: AgentTask,
        *,
        current_user_request: str,
        context_service: ContextService,
        dependency_results: dict[str, dict[str, Any]],
        user_id: str,
        output_dir: str | Path,
        db_path: str | Path | None,
        default_top_k: int,
        language: str,
        execution_context: dict[str, Any] | None = None,
    ) -> AgentResult:
        started = time.perf_counter()
        task.status = TaskStatus.RUNNING
        auto_context = context_service.build_auto_context(
            task,
            current_user_request=current_user_request,
            dependency_results=dependency_results,
        )
        requirements, requirement_meta = self.requirement_engine.infer(task, auto_context=auto_context)
        unresolved: list[ContextRequirement] = []
        resolved: dict[str, Any] = {}
        searched_sources: dict[str, list[str]] = {}

        for requirement in requirements:
            sources: list[str] = []
            value = _requirement_value_in_task(task, requirement, auto_context)
            sources.append("task_input")
            if value in (None, "", [], {}):
                direct = context_service.memory_get(
                    session_id=task.session_id,
                    key=requirement.key,
                    run_id=task.run_id,
                    task_id=task.task_id,
                    agent_id=task.assigned_agent,
                )
                sources.append("session_memory_get")
                if direct.get("found"):
                    value = direct.get("value")
            if value in (None, "", [], {}):
                for query in requirement.search_queries or [requirement.description, requirement.key]:
                    search = context_service.memory_search(
                        session_id=task.session_id,
                        query=query,
                        limit=6,
                        run_id=task.run_id,
                        task_id=task.task_id,
                        agent_id=task.assigned_agent,
                    )
                    sources.append("session_memory_search")
                    matches = search.get("matches") or []
                    if matches:
                        value = matches[0].get("value")
                        break
            if value in (None, "", [], {}):
                for dep_id in task.dependency_task_ids:
                    dep = dependency_results.get(dep_id)
                    sources.append("dependency_results")
                    if not isinstance(dep, dict):
                        continue
                    if requirement.key in dep and dep[requirement.key] not in (None, "", [], {}):
                        value = dep[requirement.key]
                        break
                    for finding in dep.get("findings") or []:
                        if isinstance(finding, dict) and requirement.key in finding:
                            value = finding[requirement.key]
                            break
            searched_sources[requirement.key] = list(dict.fromkeys(sources))
            if value in (None, "", [], {}):
                unresolved.append(requirement)
            else:
                resolved[requirement.key] = value

        if task.assigned_agent == STRATEGY_GUARD:
            return self._run_strategy_guard(
                task,
                current_user_request=current_user_request,
                auto_context=auto_context,
                dependency_results=dependency_results,
                user_id=user_id,
                output_dir=output_dir,
                db_path=db_path,
                default_top_k=default_top_k,
                language=language,
                execution_context=execution_context,
                unresolved=unresolved,
                searched_sources=searched_sources,
                requirement_meta=requirement_meta,
                started=started,
            )

        if task.assigned_agent == REPORT_WRITER:
            return self._run_report_writer(
                task,
                auto_context=auto_context,
                dependency_results=dependency_results,
                unresolved=unresolved,
                searched_sources=searched_sources,
                requirement_meta=requirement_meta,
                started=started,
                language=language,
            )

        # Even when a prerequisite is unresolved, execute the specialist's own
        # read-only capabilities. This satisfies the agreed rule: NEED_CONTEXT is
        # returned only after every available route has been tried.
        try:
            orchestration = self.business_runtime.execute(
                task,
                context_service=context_service,
                user_id=user_id,
                output_dir=output_dir,
                db_path=db_path,
                default_top_k=default_top_k,
                language=language,
                execution_context={
                    **dict(execution_context or {}),
                    "auto_context": auto_context,
                    "resolved_context": resolved,
                },
            )
        except Exception as exc:
            orchestration = {
                "success": False,
                "answer": "",
                "task_results": {},
                "tool_calls": [],
                "warnings": [],
                "errors": [f"specialist_execution_failed:{type(exc).__name__}"],
                "execution_status": "failed",
                "internal_task_count": 0,
            }

        missing = _missing_from_orchestration(orchestration)
        material_data = _result_has_material_data(orchestration)
        has_runtime_failure = any(item.category == "tool_failure" for item in missing)
        if not material_data and not has_runtime_failure:
            existing_keys = {item.key for item in missing}
            for requirement in unresolved:
                if requirement.required and requirement.key not in existing_keys:
                    missing.append(
                        _missing_item(
                            key=requirement.key,
                            category=(
                                "system_data"
                                if is_system_queryable_context_key(requirement.key)
                                else "user_input"
                            ),
                            description=requirement.description,
                            expected_format=requirement.expected_format,
                            reason="专业 Agent 已检查任务输入、会话记忆、上游结果和自身可用能力，但仍无法获得该信息。",
                            searched_sources=list(dict.fromkeys([
                                *searched_sources.get(requirement.key, []),
                                "specialist_business_capabilities",
                            ])),
                            origin_status="missing_context",
                        )
                    )

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        access_count = context_service.memory.access_count(task.session_id, task.task_id)
        warnings = [str(item) for item in orchestration.get("warnings") or []]
        if requirement_meta.get("warning"):
            warnings.append(str(requirement_meta["warning"]))

        if missing:
            task.status = TaskStatus.WAITING_CONTEXT
            return AgentResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.NEED_CONTEXT,
                summary="当前专业任务缺少必要上下文，已停止推断并请求主 Agent 处理。",
                findings=_findings(orchestration),
                confidence=0.0,
                evidence_refs=_evidence_refs(orchestration),
                warnings=warnings,
                missing_items=missing,
                artifact_refs=_artifact_refs(orchestration),
                metadata={
                    "task_type": task.task_type,
                    "attempt": task.attempt,
                    "duration_ms": duration_ms,
                    "internal_call_count": len(orchestration.get("tool_calls") or []),
                    "context_access_count": access_count,
                },
            )

        success = bool(orchestration.get("success"))
        partial = success and bool(orchestration.get("warnings")) and str(orchestration.get("execution_status") or "") in {"partial", "partially_completed"}
        status = ResultStatus.PARTIAL if partial else (ResultStatus.COMPLETED if success else ResultStatus.FAILED)
        task.status = TaskStatus.PARTIAL if partial else (TaskStatus.COMPLETED if success else TaskStatus.FAILED)
        summary = str(orchestration.get("answer") or "").strip()
        if not summary:
            summary = "专业分析已完成。" if success else "专业分析未能完成。"
        return AgentResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=status,
            summary=summary[:4000],
            findings=_findings(orchestration),
            recommendations=[],
            confidence=0.82 if success else 0.2,
            evidence_refs=_evidence_refs(orchestration),
            warnings=warnings + [str(item) for item in orchestration.get("errors") or [] if success],
            memory_updates=_stock_updates(task, orchestration),
            artifact_refs=_artifact_refs(orchestration),
            metadata={
                "task_type": task.task_type,
                "attempt": task.attempt,
                "duration_ms": duration_ms,
                "internal_call_count": len(orchestration.get("tool_calls") or []),
                "context_access_count": access_count,
                **({"partial_reason": str(orchestration.get("execution_status"))} if partial else {}),
            },
        )

    def _run_strategy_guard(
        self,
        task: AgentTask,
        *,
        current_user_request: str,
        auto_context: dict[str, Any],
        dependency_results: dict[str, dict[str, Any]],
        user_id: str,
        output_dir: str | Path,
        db_path: str | Path | None,
        default_top_k: int,
        language: str,
        execution_context: dict[str, Any] | None,
        unresolved: list[ContextRequirement],
        searched_sources: dict[str, list[str]],
        requirement_meta: dict[str, Any],
        started: float,
    ) -> AgentResult:
        """Generate exactly one Proposal through a private proposal capability.

        The old router is never called. Commit tools are excluded by operation
        type and approval remains the responsibility of WriteGateway.
        """
        from agent.tool_engine import (
            AGENT_MAIN,
            OP_PROPOSAL,
            execute_tool_legacy_dict,
            get_tool_registry_v2,
        )

        registry = get_tool_registry_v2()
        proposal_catalog: list[dict[str, Any]] = []
        for definition in registry.list(agent_type=AGENT_MAIN, operation_type=OP_PROPOSAL):
            operation = str(getattr(definition, "operation_type", "") or "").lower()
            if operation != str(OP_PROPOSAL).lower():
                continue
            if AGENT_MAIN not in list(getattr(definition, "allowed_agent_types", []) or []):
                continue
            proposal_catalog.append(
                {
                    "name": str(definition.name),
                    "description": str(definition.description),
                    "input_schema": dict(definition.input_schema or {}),
                    "produced_outputs": list(definition.produced_outputs or []),
                    "requires_approval": bool(definition.requires_approval),
                }
            )
        if not proposal_catalog:
            return AgentResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.FAILED,
                summary="策略保护 Agent 没有可用的 Proposal 能力；未进行任何写入。",
                warnings=["proposal_capability_catalog_empty"],
                metadata={
                    "task_type": task.task_type,
                    "attempt": task.attempt,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "internal_call_count": 0,
                    "context_access_count": 0,
                },
            )

        allowed_names = {item["name"] for item in proposal_catalog}

        def validate(payload: dict[str, Any]) -> None:
            action = str(payload.get("action") or "").strip().lower()
            if action not in {"execute_proposal", "need_context", "blocked"}:
                raise RuntimeError(f"invalid_strategy_guard_action:{action}")
            if action == "execute_proposal":
                name = str(payload.get("capability") or "").strip()
                if name not in allowed_names:
                    raise RuntimeError(f"proposal_capability_not_allowed:{name}")
                if not isinstance(payload.get("parameters") or {}, dict):
                    raise RuntimeError("proposal_parameters_not_object")
            if action == "need_context":
                missing = payload.get("missing_items")
                if not isinstance(missing, list) or not missing:
                    raise RuntimeError("strategy_guard_missing_items_required")

        system = (
            "你是 Strategy Guard 的私有 Proposal 规划器。你可以看到私有 Proposal 能力，主 Agent 看不到。"
            "你只能选择一个 operation_type=proposal 的能力生成待审批预案，绝对不能选择 Commit 或表示已执行。"
            "若缺少安全生成预案所需的关键事实，返回 need_context；若请求不应形成预案，返回 blocked。"
            "严格输出 JSON：{\"action\":\"execute_proposal|need_context|blocked\","
            "\"capability\":\"\",\"parameters\":{},\"reason\":\"\","
            "\"missing_items\":[{\"key\":\"\",\"description\":\"\","
            "\"expected_format\":\"\"}]}。"
        )
        try:
            decision = self.llm_service.generate_json(
                stage="strategy_guard_proposal_planner",
                messages=[
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "agent_task": task.safe_for_coordinator(),
                                "current_user_request": current_user_request,
                                "session_memory_summary": auto_context.get("session_memory_summary"),
                                "dependency_results": dependency_results,
                                "unresolved_requirements": [
                                    {
                                        "key": item.key,
                                        "description": item.description,
                                        "expected_format": item.expected_format,
                                    }
                                    for item in unresolved
                                ],
                                "available_proposal_capabilities": proposal_catalog,
                                "reply_language": language,
                            },
                            ensure_ascii=False,
                            default=str,
                        ),
                    },
                ],
                max_output_tokens=2000,
                validator=validate,
                operation=task.task_type,
            )
        except Exception as exc:
            return AgentResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.FAILED,
                summary="策略保护 Agent 无法可靠生成安全预案，未进行任何写入。",
                warnings=[f"strategy_internal_planner_failed:{type(exc).__name__}:{exc}"],
                metadata={
                    "task_type": task.task_type,
                    "attempt": task.attempt,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "internal_call_count": 0,
                    "context_access_count": 0,
                },
            )

        action = str(decision.get("action") or "").lower()
        if action == "need_context":
            missing_items: list[MissingContextItem] = []
            for item in decision.get("missing_items") or []:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key") or "proposal_context")
                missing_items.append(
                    _missing_item(
                        key=key,
                        category=("system_data" if is_system_queryable_context_key(key) else "user_input"),
                        description=str(item.get("description") or "生成预案所需的关键上下文"),
                        expected_format=str(item.get("expected_format") or "具体对象、数值或目标"),
                        reason=str(decision.get("reason") or "无法在不猜测的情况下生成 Proposal。"),
                        searched_sources=list(dict.fromkeys([
                            *searched_sources.get(key, []),
                            "task_input", "session_memory", "dependency_results",
                            "strategy_guard_private_planner",
                        ])),
                        origin_status="missing_required_parameters",
                    )
                )
            return AgentResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.NEED_CONTEXT,
                summary="生成预案前还需要补充信息。",
                missing_items=missing_items,
                metadata={
                    "task_type": task.task_type,
                    "attempt": task.attempt,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "internal_call_count": 0,
                    "context_access_count": 0,
                },
            )
        if action == "blocked":
            return AgentResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.BLOCKED,
                summary=str(decision.get("reason") or "当前请求不能安全形成 Proposal；未进行任何写入。"),
                metadata={
                    "task_type": task.task_type,
                    "attempt": task.attempt,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "internal_call_count": 0,
                    "context_access_count": 0,
                },
            )

        capability = str(decision.get("capability") or "")
        params = dict(decision.get("parameters") or {})
        params.setdefault("user_id", user_id)
        try:
            raw = execute_tool_legacy_dict(
                capability,
                params,
                context={
                    **dict(execution_context or {}),
                    "output_dir": output_dir,
                    "db_path": db_path,
                    "default_top_k": default_top_k,
                    "user_id": user_id,
                    "session_id": task.session_id,
                    "conversation_id": task.session_id,
                    "run_id": task.run_id,
                    "task_id": task.task_id,
                    "agent_role": task.assigned_agent,
                    "dependency_results": dependency_results,
                    "llm_runtime_settings": self.llm_service.settings,
                    "llm_profile_id": self.llm_service.profile_id,
                    "llm_config_hash": self.llm_service.config_hash,
                },
                agent_type=AGENT_MAIN,
                approval_granted=False,
            )
        except Exception as exc:
            return AgentResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.FAILED,
                summary="Proposal 能力执行失败，未进行任何写入。",
                warnings=[f"proposal_execution_failed:{type(exc).__name__}:{exc}"],
                metadata={
                    "task_type": task.task_type,
                    "attempt": task.attempt,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "internal_call_count": 1,
                    "context_access_count": 0,
                },
            )

        raw = dict(raw or {})
        missing = _missing_from_orchestration(
            {"errors": list(raw.get("errors") or []), "task_results": {"proposal": raw}}
        )
        if missing and not raw.get("success"):
            return AgentResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.NEED_CONTEXT,
                summary="预案生成需要补充上下文。",
                missing_items=missing,
                warnings=list(raw.get("warnings") or []),
                metadata={
                    "task_type": task.task_type,
                    "attempt": task.attempt,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "internal_call_count": 1,
                    "context_access_count": 0,
                },
            )
        if not raw.get("success"):
            return AgentResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.FAILED,
                summary="未能生成有效预案，未执行任何写入。",
                warnings=[*list(raw.get("warnings") or []), *list(raw.get("errors") or [])],
                metadata={
                    "task_type": task.task_type,
                    "attempt": task.attempt,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "internal_call_count": 1,
                    "context_access_count": 0,
                },
            )

        data = dict(raw.get("data") or {})
        plan_id = str(data.get("plan_id") or raw.get("plan_id") or "")
        proposal_id = str(data.get("proposal_id") or raw.get("proposal_id") or "")
        message = str(raw.get("message") or data.get("summary") or "预案已生成").strip()
        summary = f"{message} 本次仅生成 Proposal，尚未执行 Commit。"
        artifacts: list[dict[str, Any]] = []
        if plan_id:
            artifacts.append({"artifact_type": "plan_id", "artifact_id": plan_id})
        if proposal_id:
            artifacts.append({"artifact_type": "proposal_id", "artifact_id": proposal_id})
        return AgentResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.PROPOSAL_READY,
            summary=summary,
            findings=[{"status": "proposal_ready", "data_summary": _safe_outline(data)}],
            recommendations=["请核对预案后明确确认或拒绝；确认后仍需重新校验资金、价格、持仓和权限。"],
            confidence=0.88,
            warnings=list(raw.get("warnings") or []),
            memory_updates=[
                MemoryUpdate(
                    key="latest_proposal",
                    value={
                        "plan_id": plan_id,
                        "proposal_id": proposal_id,
                        "summary": summary,
                        "requires_approval": True,
                    },
                    value_type="proposal",
                    source_type="agent_result",
                    source_ref=task.task_id,
                    confirmed=False,
                    confidence=0.88,
                    summary=summary[:600],
                )
            ],
            artifact_refs=artifacts,
            metadata={
                "task_type": task.task_type,
                "attempt": task.attempt,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "internal_call_count": 1,
                "context_access_count": 0,
                "plan_id": plan_id,
                "proposal_id": proposal_id,
                "requires_approval": True,
                "proposal_capability": capability,
                "llm_profile_id": self.llm_service.profile_id,
                "llm_config_hash": self.llm_service.config_hash,
            },
        )

    def _run_report_writer(
        self,
        task: AgentTask,
        *,
        auto_context: dict[str, Any],
        dependency_results: dict[str, dict[str, Any]],
        unresolved: list[ContextRequirement],
        searched_sources: dict[str, list[str]],
        requirement_meta: dict[str, Any],
        started: float,
        language: str,
    ) -> AgentResult:
        selected = {
            dep_id: dependency_results[dep_id]
            for dep_id in task.dependency_task_ids
            if dep_id in dependency_results
        }
        if not selected:
            missing = [
                _missing_item(
                    key=req.key,
                    category="upstream_result",
                    description=req.description,
                    expected_format=req.expected_format,
                    reason="没有可供汇总的上游标准 AgentResult。",
                    searched_sources=searched_sources.get(req.key, ["dependency_results"]),
                    origin_status="upstream_result_missing",
                )
                for req in (unresolved or [ContextRequirement("specialist_results", "需要汇总的专业 Agent 结果")])
            ]
            return AgentResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.NEED_CONTEXT,
                summary="报告 Agent 尚未收到可汇总的专业结果。",
                missing_items=missing,
                metadata={
                    "task_type": task.task_type,
                    "attempt": task.attempt,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "internal_call_count": 0,
                    "context_access_count": 0,
                },
            )
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
            for key, value in selected.items()
        }
        answer = self._generate_report(task, safe_results=safe_results, language=language)
        return AgentResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.COMPLETED,
            summary=answer,
            findings=[
                {"source_task_id": key, "agent_id": value.get("agent_id"), "status": value.get("status")}
                for key, value in safe_results.items()
            ],
            confidence=0.85,
            evidence_refs=[ref for value in safe_results.values() for ref in value.get("evidence_refs") or []][:50],
            warnings=[str(requirement_meta.get("warning"))] if requirement_meta.get("warning") else [],
            metadata={
                "task_type": task.task_type,
                "attempt": task.attempt,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "internal_call_count": 0,
                "context_access_count": 0,
            },
        )

    def _generate_report(self, task: AgentTask, *, safe_results: dict[str, dict[str, Any]], language: str) -> str:
        system = (
            "你是报告编写 Agent。只能使用给定的标准 AgentResult，不能请求或推断 Tool、原始持仓、"
            "原始证据或内部参数。清楚区分已完成、部分完成和信息不足；不得把 Proposal 写成已执行。"
        )
        return self.llm_service.generate_text(
            stage="report_writer_agent",
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"objective": task.objective, "results": safe_results, "reply_language": language},
                        ensure_ascii=False,
                    ),
                },
            ],
            temperature=0.0,
            max_output_tokens=2200,
            operation="standard_agent_result_summary",
        )

