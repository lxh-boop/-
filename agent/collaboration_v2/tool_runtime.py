from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Callable

from .agent_directory import (
    EVIDENCE_RETRIEVER,
    PORTFOLIO_ANALYST,
    RISK_ANALYST,
    STRATEGY_GUARD,
    SYSTEM_DIAGNOSTIC,
)
from .context_service import ContextService
from .models import AgentTask


# This mapping is private to SpecialistRuntime. It is never included in the
# coordinator capability catalog, task prompt or standardized agent result.
_ROLE_INTENTS: dict[str, set[str]] = {
    EVIDENCE_RETRIEVER: {
        "ranking",
        "stock_lookup",
        "classic_stock_score",
        "classic_ranking",
        "stock_analysis",
        "market.compare_stocks",
        "market.get_signal_summary",
        "stock_news",
        "stock_rag",
        "news_search",
        "rag_search",
        "evidence.search_news",
        "evidence.search_rag",
        "evidence.get_stock_evidence",
        "evidence.get_market_evidence",
        "evidence.mcp_readonly_evidence",
        "mcp_market_risk_summary",
        "mcp_tool",
        "mcp.readonly.invoke",
    },
    PORTFOLIO_ANALYST: {
        "portfolio_state",
        "portfolio.get_state",
        "portfolio.get_account_summary",
        "portfolio.get_positions",
        "portfolio.get_orders",
        "portfolio.design_target_portfolio",
        "portfolio.construct_target_portfolio",
        "portfolio.load_target_portfolio",
        "portfolio.compare_portfolios",
        "user_profile",
    },
    RISK_ANALYST: {
        "portfolio_risk",
        "portfolio.analyze_risk",
        "portfolio.compare_risk_before_after",
        "position_recommendation",
        "replacement_recommendation",
        "user_profile",
    },
    STRATEGY_GUARD: {
        # Proposal-capable tasks remain inside the existing approval workflow.
        # Collaboration v2 only uses these names when the outer executor has
        # already classified a request as a proposal; no commit tool is present.
        "preview_add_stock",
        "adjust_position",
        "one_time_position_operation",
        "strategy_change",
        "position_recommendation",
        "replacement_recommendation",
    },
    SYSTEM_DIAGNOSTIC: {
        "scheduler_status",
        "report",
        "report_latest",
        "python_sandbox_analysis",
    },
}

_DEFAULT_TASK_BLUEPRINTS: dict[tuple[str, str], list[dict[str, Any]]] = {
    (EVIDENCE_RETRIEVER, "retrieve_evidence"): [
        {"intent": "evidence.get_market_evidence", "parameters": {}},
    ],
    (EVIDENCE_RETRIEVER, "analyze_stock_evidence"): [
        {"intent": "stock_analysis", "parameters": {}},
        {"intent": "evidence.get_stock_evidence", "parameters": {}},
    ],
    (EVIDENCE_RETRIEVER, "compare_stock_evidence"): [
        {"intent": "market.compare_stocks", "parameters": {}},
        {"intent": "evidence.get_market_evidence", "parameters": {}},
    ],
    (EVIDENCE_RETRIEVER, "resolve_context"): [
        {"intent": "evidence.get_market_evidence", "parameters": {}},
    ],
    (PORTFOLIO_ANALYST, "analyze_portfolio"): [
        {"intent": "portfolio_state", "parameters": {}},
        {"intent": "user_profile", "parameters": {}},
    ],
    (PORTFOLIO_ANALYST, "analyze_portfolio_fit"): [
        {"intent": "portfolio_state", "parameters": {}},
        {"intent": "user_profile", "parameters": {}},
    ],
    (PORTFOLIO_ANALYST, "compare_portfolios"): [
        {"intent": "portfolio.compare_portfolios", "parameters": {}},
    ],
    (PORTFOLIO_ANALYST, "resolve_context"): [
        {"intent": "portfolio_state", "parameters": {}},
    ],
    (RISK_ANALYST, "analyze_risk"): [
        {"intent": "portfolio_risk", "parameters": {}},
        {"intent": "user_profile", "parameters": {}},
    ],
    (RISK_ANALYST, "compare_risk"): [
        {"intent": "portfolio.compare_risk_before_after", "parameters": {}},
    ],
    (RISK_ANALYST, "review_risk_constraints"): [
        {"intent": "portfolio_risk", "parameters": {}},
        {"intent": "user_profile", "parameters": {}},
    ],
    (RISK_ANALYST, "resolve_context"): [
        {"intent": "portfolio_risk", "parameters": {}},
    ],
    (SYSTEM_DIAGNOSTIC, "diagnose_system"): [
        {"intent": "scheduler_status", "parameters": {}},
        {"intent": "report", "parameters": {}},
    ],
    (SYSTEM_DIAGNOSTIC, "inspect_runtime"): [
        {"intent": "scheduler_status", "parameters": {}},
    ],
    (SYSTEM_DIAGNOSTIC, "resolve_context"): [
        {"intent": "scheduler_status", "parameters": {}},
    ],
}


ToolPlanExecutor = Callable[..., dict[str, Any]]


def _normalise_stock_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    match = re.search(r"(?<!\d)(\d{6})(?:\.(?:SH|SZ|BJ))?(?!\d)", text)
    return match.group(1) if match else ""


def _stock_values(value: Any) -> list[str]:
    values: list[Any]
    if isinstance(value, list):
        values = value
    elif isinstance(value, dict):
        values = list(value.values())
    elif isinstance(value, str):
        cleaned = re.sub(r"^(?:请|帮我|比较|对比|分析|看看|股票|是|为|：|:|\s)+", "", value.strip(), flags=re.IGNORECASE)
        pieces = [item.strip() for item in re.split(r"(?:和|与|以及|、|，|,|/|\s+and\s+|\s+vs\.?\s+)", cleaned, flags=re.IGNORECASE) if item.strip()]
        values = pieces if len(pieces) >= 2 else [value]
    else:
        values = [value]
    result: list[str] = []
    for item in values:
        if isinstance(item, dict):
            candidate = item.get("stock_code") or item.get("code") or item.get("symbol") or item.get("name")
        else:
            candidate = item
        code = _normalise_stock_code(candidate)
        text = code or str(candidate or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _memory_value(context_service: ContextService, task: AgentTask, keys: list[str]) -> Any:
    for key in keys:
        result = context_service.memory_get(
            session_id=task.session_id,
            key=key,
            run_id=task.run_id,
            task_id=task.task_id,
            agent_id=task.assigned_agent,
        )
        if result.get("found"):
            return result.get("value")
    return None


def _enrich_parameters(
    task: AgentTask,
    intent: str,
    parameters: dict[str, Any],
    context_service: ContextService,
    *,
    user_id: str,
    default_top_k: int,
) -> dict[str, Any]:
    args = dict(parameters or {})
    args.setdefault("user_id", user_id)
    if "top_k" not in args and intent in {
        "ranking",
        "stock_analysis",
        "stock_rag",
        "stock_news",
        "market.compare_stocks",
        "evidence.get_market_evidence",
        "evidence.get_stock_evidence",
    }:
        args["top_k"] = max(1, min(int(default_top_k or 10), 100))

    existing_stock = args.get("stock_codes") or args.get("stock_code") or args.get("stock_query")
    if existing_stock in (None, "", [], {}):
        memory_stocks = _memory_value(
            context_service,
            task,
            ["comparison_targets", "stock_codes", "stock_code", "active_stocks", "active_entities"],
        )
        stocks = _stock_values(memory_stocks)
        if stocks:
            if intent in {"market.compare_stocks", "evidence.get_market_evidence"}:
                args["stock_codes"] = stocks
            elif len(stocks) == 1:
                args["stock_code"] = stocks[0]
            else:
                args["stock_code"] = stocks

    if intent in {"stock_rag", "rag_search", "evidence.search_rag", "evidence.get_stock_evidence", "evidence.get_market_evidence"}:
        args.setdefault("query", task.objective)

    if intent == "portfolio.compare_portfolios":
        if args.get("current_portfolio") in (None, "", {}, []):
            current = _memory_value(context_service, task, ["current_portfolio", "portfolio_snapshot"])
            if current is not None:
                args["current_portfolio"] = current
        if args.get("target_portfolio") in (None, "", {}, []):
            target = _memory_value(context_service, task, ["target_portfolio", "proposed_portfolio"])
            if target is not None:
                args["target_portfolio"] = target

    if intent == "portfolio.compare_risk_before_after":
        if args.get("before") in (None, "", {}, []):
            before = _memory_value(context_service, task, ["current_portfolio", "portfolio_snapshot"])
            if before is not None:
                args["before"] = before
        if args.get("after") in (None, "", {}, []):
            after = _memory_value(context_service, task, ["target_portfolio", "proposed_portfolio"])
            if after is not None:
                args["after"] = after
    return args


def _default_blueprints(task: AgentTask) -> list[dict[str, Any]]:
    """Resolve private implementation capabilities from the new Agent task contract.

    This is not a semantic router: the Main Coordinator has already selected the
    specialist and task_type. The mapping only binds that explicit task contract
    to reusable internal business capabilities.
    """
    return [
        copy.deepcopy(item)
        for item in _DEFAULT_TASK_BLUEPRINTS.get((task.assigned_agent, task.task_type), [])
    ]


def _normalize_internal_tasks(task: AgentTask, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    internal_ids: set[str] = set()
    for index, item in enumerate(tasks, start=1):
        if not isinstance(item, dict):
            continue
        intent = str(item.get("intent") or "")
        if not intent:
            continue
        if intent not in _ROLE_INTENTS.get(task.assigned_agent, set()) and not (
            task.assigned_agent == EVIDENCE_RETRIEVER and (intent.startswith("mcp_") or intent.startswith("mcp."))
        ):
            continue
        task_id = str(item.get("task_id") or f"{task.task_id}_internal_{index}")
        if task_id in internal_ids:
            task_id = f"{task.task_id}_internal_{index}"
        internal_ids.add(task_id)
        result.append(
            {
                **item,
                "task_id": task_id,
                "intent": intent,
                "parameters": dict(item.get("parameters") or {}),
                "depends_on": list(item.get("depends_on") or []),
                "capability_status": str(item.get("capability_status") or "executable"),
            }
        )
    for item in result:
        item["depends_on"] = [dep for dep in item.get("depends_on") or [] if dep in internal_ids]
    return result


def _private_tool_catalog(role: str) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    allowed = sorted(_ROLE_INTENTS.get(role, set()))
    try:
        from agent.tool_engine import get_tool_registry_v2

        registry_v2 = get_tool_registry_v2()
    except Exception:
        registry_v2 = None
    try:
        from agent.tools.tool_registry import get_tool_registry

        registry_legacy = get_tool_registry()
    except Exception:
        registry_legacy = None
    for name in allowed:
        description = ""
        schema: dict[str, Any] = {}
        definition = registry_v2.get(name) if registry_v2 is not None else None
        if definition is not None:
            description = str(getattr(definition, "description", "") or "")[:500]
            raw_schema = getattr(definition, "input_schema", None)
            schema = dict(raw_schema) if isinstance(raw_schema, dict) else {}
        elif registry_legacy is not None:
            spec = registry_legacy.get(name)
            if spec is not None:
                description = str(getattr(spec, "description", "") or "")[:500]
                raw_schema = getattr(spec, "input_schema", None)
                schema = dict(raw_schema) if isinstance(raw_schema, dict) else {}
        catalog.append(
            {
                "name": name,
                "description": description,
                "input_schema": {
                    "required": list(schema.get("required") or [])[:20],
                    "properties": {
                        key: {
                            "type": str((value or {}).get("type") or ""),
                            "description": str((value or {}).get("description") or "")[:200],
                        }
                        for key, value in list((schema.get("properties") or {}).items())[:30]
                        if isinstance(value, dict)
                    },
                },
            }
        )
    return catalog


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        parsed = json.loads(raw)
        return dict(parsed) if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            parsed = json.loads(raw[start : end + 1])
            return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _lookup_code_from_payload(payload: dict[str, Any]) -> str:
    for result in (payload.get("task_results") or {}).values():
        if not isinstance(result, dict) or not result.get("success"):
            continue
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        candidates: list[Any] = [
            data.get("stock_code"),
            data.get("code"),
            (data.get("record") or {}).get("stock_code") if isinstance(data.get("record"), dict) else None,
            (data.get("match") or {}).get("stock_code") if isinstance(data.get("match"), dict) else None,
        ]
        for key in ("records", "matches", "items"):
            rows = data.get(key)
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                candidates.extend([rows[0].get("stock_code"), rows[0].get("code"), rows[0].get("symbol")])
        for candidate in candidates:
            code = _normalise_stock_code(candidate)
            if code:
                return code
    return ""


def _resolve_named_stocks(
    names: list[str],
    *,
    executor: ToolPlanExecutor,
    user_id: str,
    output_dir: str | Path,
    db_path: str | Path | None,
    default_top_k: int,
    session_id: str,
    language: str,
    context: dict[str, Any],
) -> tuple[dict[str, str], list[dict[str, Any]], list[str]]:
    mapping: dict[str, str] = {}
    tool_calls: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, name in enumerate(names, start=1):
        if _normalise_stock_code(name):
            mapping[name] = _normalise_stock_code(name)
            continue
        try:
            payload = executor(
                {
                    "tasks": [
                        {
                            "task_id": f"entity_lookup_{index}",
                            "intent": "stock_lookup",
                            "parameters": {"user_id": user_id, "stock_query": name},
                            "depends_on": [],
                            "capability_status": "executable",
                        }
                    ]
                },
                user_id=user_id,
                output_dir=output_dir,
                db_path=db_path,
                default_top_k=default_top_k,
                session_id=session_id,
                language=language,
                context={**context, "entity_resolution_only": True},
            )
            code = _lookup_code_from_payload(dict(payload or {}))
            tool_calls.extend(list((payload or {}).get("tool_calls") or []))
            if code:
                mapping[name] = code
            else:
                warnings.append(f"stock_name_resolution_empty:{name[:40]}")
        except Exception as exc:
            warnings.append(f"stock_name_resolution_failed:{type(exc).__name__}")
    return mapping, tool_calls, warnings


class ScopedBusinessToolRuntime:
    """Private business-capability runtime for one specialist.

    It shares the exact Executor-created LLMService. The coordinator never sees
    the private capability catalog, internal plan, tool arguments or raw output.
    """

    def __init__(
        self,
        executor: ToolPlanExecutor | None = None,
        *,
        llm_service,
    ) -> None:
        self._executor = executor
        self.llm_service = llm_service

    def _plan_internal_tasks(self, task: AgentTask, context: dict[str, Any]) -> list[dict[str, Any]]:
        catalog = _private_tool_catalog(task.assigned_agent)
        if not catalog:
            raise RuntimeError(f"specialist_private_capability_catalog_empty:{task.assigned_agent}")
        allowed = {str(item.get("name") or "") for item in catalog}

        def validate(payload: dict[str, Any]) -> None:
            rows = payload.get("tasks")
            if not isinstance(rows, list) or not rows:
                raise RuntimeError("specialist_internal_plan_missing_tasks")
            if len(rows) > 6:
                raise RuntimeError("specialist_internal_plan_too_many_tasks")
            ids: set[str] = set()
            for row in rows:
                if not isinstance(row, dict):
                    raise RuntimeError("specialist_internal_task_not_object")
                task_id = str(row.get("task_id") or "").strip()
                intent = str(row.get("intent") or "").strip()
                if not task_id or task_id in ids:
                    raise RuntimeError("specialist_internal_task_id_invalid")
                ids.add(task_id)
                if intent not in allowed:
                    raise RuntimeError(f"specialist_internal_capability_not_allowed:{intent}")
                if not isinstance(row.get("parameters") or {}, dict):
                    raise RuntimeError(f"specialist_internal_parameters_invalid:{task_id}")
                if not isinstance(row.get("depends_on") or [], list):
                    raise RuntimeError(f"specialist_internal_dependencies_invalid:{task_id}")
            for row in rows:
                task_id = str(row.get("task_id") or "")
                for dependency in row.get("depends_on") or []:
                    if str(dependency) not in ids or str(dependency) == task_id:
                        raise RuntimeError(f"specialist_internal_dependency_invalid:{task_id}:{dependency}")

        system = (
            "你是专业 Agent 的私有执行规划器。只有当前专业 Agent 能看到下面的业务能力；"
            "主 Agent 与其他专业 Agent永远看不到。根据 AgentTask 和已解析上下文选择最少的能力，"
            "输出 1 到 6 个内部任务。不得选择清单外能力，不得执行 Commit，不得向用户提问，"
            "不得编造缺失目标。严格输出 JSON：{\"tasks\":[{\"task_id\":\"internal_1\","
            "\"intent\":\"能力名称\",\"parameters\":{},\"depends_on\":[]}]}。"
        )
        payload = self.llm_service.generate_json(
            stage="specialist_internal_planner",
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "specialist": task.assigned_agent,
                            "objective": task.objective,
                            "task_type": task.task_type,
                            "constraints": task.constraints,
                            "current_user_request": (
                                (context.get("auto_context") or {}).get("current_user_request")
                                if isinstance(context.get("auto_context"), dict) else ""
                            ),
                            "session_memory_summary": context.get("session_memory_summary"),
                            "resolved_context": context.get("resolved_context") or {},
                            "dependency_results": (
                                (context.get("auto_context") or {}).get("dependency_results")
                                if isinstance(context.get("auto_context"), dict) else {}
                            ),
                            "available_business_capabilities": catalog,
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                },
            ],
            max_output_tokens=1800,
            validator=validate,
            operation=task.task_type,
        )
        return _normalize_internal_tasks(task, list(payload.get("tasks") or []))

    def execute(
        self,
        task: AgentTask,
        *,
        context_service: ContextService,
        user_id: str,
        output_dir: str | Path,
        db_path: str | Path | None,
        default_top_k: int,
        language: str,
        execution_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        executor = self._executor
        if executor is None:
            from agent.orchestration.multi_task_executor import execute_multi_intent_plan
            executor = execute_multi_intent_plan

        context = {
            **dict(execution_context or {}),
            "agent_role": task.assigned_agent,
            "user_id": user_id,
            "session_id": task.session_id,
            "conversation_id": task.session_id,
            "run_id": task.run_id,
            "task_id": task.task_id,
            "current_specialist_task": task.safe_for_coordinator(),
            "session_memory_summary": context_service.memory.build_summary(
                task.session_id,
                task_objective=task.objective,
                max_chars=5000,
            ),
            "llm_runtime": {
                "profile_id": self.llm_service.profile_id,
                "config_hash": self.llm_service.config_hash,
            },
        }
        internal_tasks = self._plan_internal_tasks(task, context)

        for item in internal_tasks:
            item["parameters"] = _enrich_parameters(
                task,
                str(item.get("intent") or ""),
                dict(item.get("parameters") or {}),
                context_service,
                user_id=user_id,
                default_top_k=default_top_k,
            )

        names: list[str] = []
        for item in internal_tasks:
            args = dict(item.get("parameters") or {})
            for value in _stock_values(args.get("stock_codes") or args.get("stock_code") or []):
                if value and not _normalise_stock_code(value) and value not in names:
                    names.append(value)
        lookup_calls: list[dict[str, Any]] = []
        lookup_warnings: list[str] = []
        if names and task.assigned_agent == EVIDENCE_RETRIEVER:
            mapping, lookup_calls, lookup_warnings = _resolve_named_stocks(
                names,
                executor=executor,
                user_id=user_id,
                output_dir=output_dir,
                db_path=db_path,
                default_top_k=default_top_k,
                session_id=task.session_id,
                language=language,
                context=context,
            )
            if mapping:
                for item in internal_tasks:
                    args = dict(item.get("parameters") or {})
                    for field in ("stock_codes", "stock_code"):
                        if field not in args:
                            continue
                        original = _stock_values(args[field])
                        resolved = [mapping.get(value, _normalise_stock_code(value) or value) for value in original]
                        args[field] = resolved if isinstance(args[field], list) or len(resolved) > 1 else resolved[0]
                    item["parameters"] = args
                resolved_codes = list(dict.fromkeys(mapping.values()))
                if len(resolved_codes) >= 2:
                    context_service.memory.put(
                        session_id=task.session_id,
                        key="comparison_targets",
                        value=resolved_codes,
                        value_type="stock_list",
                        summary="专业 Agent 已将股票名称标准化为代码：" + "、".join(resolved_codes),
                        source_type="tool_result",
                        source_ref=task.task_id,
                        confirmed=False,
                        confidence=0.9,
                    )
                elif len(resolved_codes) == 1:
                    context_service.memory.put(
                        session_id=task.session_id,
                        key="stock_target",
                        value=resolved_codes[0],
                        value_type="stock_code",
                        summary=f"专业 Agent 已将股票名称标准化为代码：{resolved_codes[0]}",
                        source_type="tool_result",
                        source_ref=task.task_id,
                        confirmed=False,
                        confidence=0.9,
                    )

        result = executor(
            {"tasks": internal_tasks},
            user_id=user_id,
            output_dir=output_dir,
            db_path=db_path,
            default_top_k=default_top_k,
            session_id=task.session_id,
            language=language,
            context=context,
        )
        payload = dict(result or {})
        payload["tool_calls"] = [*lookup_calls, *list(payload.get("tool_calls") or [])]
        payload["warnings"] = [*lookup_warnings, *list(payload.get("warnings") or [])]
        payload["internal_task_count"] = len(internal_tasks) + len(lookup_calls)
        payload["llm_profile_id"] = self.llm_service.profile_id
        payload["llm_config_hash"] = self.llm_service.config_hash
        return payload
