from __future__ import annotations

import json
import re
from typing import Any

from core.llm import LLMService

from agent.console_trace import flow_event

from .agent_directory import AgentDirectory
from .models import GraphAgentTask, TaskStatus
from .worker_contracts import (
    WorkerContractViolation,
    array_schema,
    object_schema,
    string_schema,
    validate_dependency_ids,
    validate_schema,
)


class CoordinatorPlanningError(RuntimeError):
    pass


def _contains_private_implementation(value: str) -> bool:
    text = str(value or "").lower()
    blocked = (
        "tool",
        "cypher",
        "sql",
        "api endpoint",
        "database table",
        "tool_registry",
        "stock_code",
        "stock_codes",
        "ts_code",
        "security_scope",
        "route_agent_query",
        "intent router",
    )
    return any(item in text for item in blocked) or bool(
        re.search(r"\b[a-z]+\.[a-z_]+\b", text)
    )


TASK_INPUT_REFERENCE_SCHEMA = object_schema(
    {
        "from_task_id": string_schema(min_length=1),
        "expected_output_type": string_schema(min_length=1),
    },
    required=["from_task_id", "expected_output_type"],
)

# Worker-specific role names are declared in each public Worker card. Every
# value under ``inputs`` must nevertheless be a semantic upstream reference or
# an array of references. Direct runtime values such as focus_ref_ids, user_id,
# language, and as_of_time are code-bound args and never belong in ``inputs``.
TASK_INPUT_VALUE_SCHEMA = {
    "anyOf": [
        TASK_INPUT_REFERENCE_SCHEMA,
        array_schema(TASK_INPUT_REFERENCE_SCHEMA, min_items=1, max_items=8),
    ]
}
TASK_INPUTS_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": TASK_INPUT_VALUE_SCHEMA,
}

PLAN_SCHEMA = object_schema(
    {
        "tasks": array_schema(
            object_schema(
                {
                    "task_id": string_schema(min_length=1),
                    "worker_id": string_schema(min_length=1),
                    "objective": string_schema(min_length=1),
                    "task_type": string_schema(min_length=1),
                    "args": object_schema({}, additional_properties=True),
                    "inputs": TASK_INPUTS_SCHEMA,
                    "constraints": array_schema({"type": "string"}),
                    "expected_output_type": string_schema(min_length=1),
                    "priority": {"type": "integer"},
                },
                required=[
                    "task_id",
                    "worker_id",
                    "objective",
                    "task_type",
                    "args",
                    "inputs",
                    "constraints",
                    "expected_output_type",
                    "priority",
                ],
            ),
            min_items=1,
            max_items=8,
        )
    },
    required=["tasks"],
)


class CoordinatorPlanner:
    """MainAgent Worker-DAG planner with deterministic dependency compilation.

    MainAgent directly chooses registered ``worker_id`` values, creates Worker
    nodes, and declares semantic upstream bindings through ``inputs``. Runtime
    code derives ``dependency_task_ids`` from those explicit ``from_task_id``
    references. The compiler never invents an edge and the validator never
    inserts, removes, splits, merges, replaces, or rewires Worker nodes.
    """

    def __init__(self, directory: AgentDirectory, *, llm_service: LLMService) -> None:
        self.directory = directory
        self.llm_service = llm_service

    @staticmethod
    def _authoritative_runtime_values(
        *,
        focus_refs: list,
        context_refs: list,
        user_id: str,
        reply_language: str,
        as_of_time: str,
        run_id: str,
    ) -> dict[str, Any]:
        focus_ref_ids = [
            str(getattr(ref, "node_id", "") or "").strip()
            for ref in focus_refs
        ]
        context_ref_ids = [
            str(getattr(ref, "node_id", "") or "").strip()
            for ref in context_refs
        ]
        focus_ref_ids = [item for item in focus_ref_ids if item]
        context_ref_ids = [item for item in context_ref_ids if item]
        return {
            "focus_ref_ids": list(dict.fromkeys(focus_ref_ids)),
            "context_ref_ids": list(dict.fromkeys(context_ref_ids)),
            "all_ref_ids": list(
                dict.fromkeys([*focus_ref_ids, *context_ref_ids])
            ),
            "user_id": str(user_id or "default"),
            "reply_language": str(reply_language or "zh"),
            "as_of_time": str(as_of_time or ""),
            "run_id": str(run_id or ""),
        }

    def _prepare_payload(
        self,
        payload: dict[str, Any],
        *,
        runtime_values: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Bind code-owned args and isolate upstream WorkerResult references.

        MainAgent still owns Worker selection and every semantic edge. Runtime
        only supplies authoritative values that already exist outside the LLM
        plan. A misplaced code-owned value under ``inputs`` is removed from the
        semantic input map and recorded in the audit; no Worker or edge is
        inserted, removed, or rewired.
        """

        rows = [dict(item) for item in payload.get("tasks") or []]
        prepared_rows: list[dict[str, Any]] = []
        audit_rows: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            worker_id = str(row.get("worker_id") or "").upper()
            try:
                card = self.directory.get(worker_id)
            except KeyError:
                prepared_rows.append(row)
                continue

            args = dict(row.get("args") or {})
            inputs = dict(row.get("inputs") or {})
            bound: dict[str, Any] = {}
            removed_from_inputs: list[str] = []
            for arg_name, source_name in card.authoritative_arg_bindings.items():
                value = runtime_values.get(str(source_name))
                args[str(arg_name)] = value
                bound[str(arg_name)] = value
                if arg_name in inputs:
                    inputs.pop(arg_name, None)
                    removed_from_inputs.append(str(arg_name))

            prepared = dict(row)
            prepared["worker_id"] = worker_id
            prepared["args"] = args
            prepared["inputs"] = inputs
            prepared_rows.append(prepared)
            if bound or removed_from_inputs:
                audit_rows.append(
                    {
                        "task_index": index,
                        "task_id": str(row.get("task_id") or ""),
                        "worker_id": worker_id,
                        "authoritative_args_bound": sorted(bound),
                        "misplaced_runtime_args_removed_from_inputs": sorted(
                            removed_from_inputs
                        ),
                    }
                )
        return {"tasks": prepared_rows}, {"tasks": audit_rows}

    @staticmethod
    def _canonical_inputs(value: Any) -> dict[str, list[dict[str, str]]]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, list[dict[str, str]]] = {}
        for raw_role, raw_value in value.items():
            role = str(raw_role or "").strip()
            if not role:
                continue
            raw_items = raw_value if isinstance(raw_value, list) else [raw_value]
            items: list[dict[str, str]] = []
            seen: set[tuple[str, str]] = set()
            for raw_item in raw_items:
                if not isinstance(raw_item, dict):
                    continue
                task_id = str(raw_item.get("from_task_id") or "").strip()
                output_type = str(
                    raw_item.get("expected_output_type") or ""
                ).strip()
                if not task_id:
                    continue
                key = (task_id, output_type)
                if key in seen:
                    continue
                seen.add(key)
                items.append(
                    {
                        "from_task_id": task_id,
                        "expected_output_type": output_type,
                    }
                )
            if items:
                result[role] = items
        return result

    def _compile_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Compile semantic inputs into executor dependencies without new edges."""

        rows = [dict(item) for item in payload.get("tasks") or []]
        output_type_by_task = {
            str(row.get("task_id") or ""): str(
                row.get("expected_output_type") or ""
            )
            for row in rows
        }
        compiled_rows: list[dict[str, Any]] = []
        for row in rows:
            task_id = str(row.get("task_id") or "")
            worker_id = str(row.get("worker_id") or "")
            canonical_inputs = self._canonical_inputs(row.get("inputs") or {})
            dependencies = self.directory.validate_task_inputs(
                worker_id,
                canonical_inputs,
                task_id=task_id,
                output_type_by_task=output_type_by_task,
                path=f"$.tasks[{task_id}].inputs",
            )
            compiled = dict(row)
            compiled["inputs"] = canonical_inputs
            compiled["dependency_task_ids"] = dependencies
            compiled_rows.append(compiled)
        return {
            "tasks": compiled_rows,
            "dependency_derivation": "compiled_from_semantic_inputs",
        }

    def plan(
        self,
        *,
        query: str,
        request_mode: str,
        session_id: str,
        run_id: str,
        user_id: str,
        focus_refs: list,
        context_refs: list,
        memory_summary: str,
        language: str = "zh",
        as_of_time: str = "",
    ) -> tuple[list[GraphAgentTask], dict[str, Any]]:
        mode = str(request_mode or "analysis").strip().lower()
        if mode not in {"analysis", "proposal"}:
            raise CoordinatorPlanningError(
                f"unsupported_agent_request_mode:{mode}"
            )

        cards = self.directory.safe_catalog()
        reply_language = "en" if language == "en" else "zh"
        runtime_values = self._authoritative_runtime_values(
            focus_refs=focus_refs,
            context_refs=context_refs,
            user_id=str(user_id or "default"),
            reply_language=reply_language,
            as_of_time=str(as_of_time or ""),
            run_id=run_id,
        )
        authoritative_ref_ids = {
            str(ref.node_id) for ref in [*focus_refs, *context_refs]
        }

        def validate(payload: dict[str, Any]) -> None:
            try:
                prepared_payload, _ = self._prepare_payload(
                    payload,
                    runtime_values=runtime_values,
                )
                self._validate_payload(
                    prepared_payload,
                    request_mode=mode,
                    authoritative_ref_ids=authoritative_ref_ids,
                    authoritative_user_id=str(user_id or "default"),
                    reply_language=reply_language,
                )
            except (WorkerContractViolation, KeyError) as exc:
                raise CoordinatorPlanningError(str(exc)) from exc

        system = (
            "你是系统唯一的 MainAgent Worker 编排器。你必须直接从给定的结构化 Worker 能力卡中选择 worker_id，"
            "并一次性生成完整 Worker DAG。执行器和 Validator 都不会替你增加、删除、拆分、合并、替换或重连节点。"
            "每个节点必须由一个 Worker 完整承担一个业务子目标；不要规划 Worker 内部的 Tool 调用。"
            "只选择完成用户明确目标所必要的最少 Worker；某个 Worker 可用不代表本次任务需要它；"
            "不得为了更全面、可能有帮助或顺便给建议而扩大用户目标。"
            "当用户只要求分析一个已解析金融实体，且没有明确提出组合、持仓、适配性、集中度、权限风险或策略目标时，"
            "只选择实体研究 Worker 和最终报告 Worker；不得选择组合、影响或组合风险 Worker。"
            "W03 只能引用 W01 产生的 EntityResearchResult 与 W02 产生的 PortfolioAnalysisResult；"
            "W04 必须引用 W02 产生的 PortfolioAnalysisResult；报告 Worker 不能作为任何专业分析 Worker 的上游状态来源。"
            "objective 只描述该 Worker 的完整业务子目标，不得包含 Tool、函数、API、数据库、Schema、字段名或实现细节。"
            "能力卡 runtime_bound_args 中列出的参数由程序从权威运行上下文写入；不要生成这些参数，也不要把它们放入 inputs。"
            "args 只填写所选 Worker input_schema 中剩余的普通业务参数，args 中禁止填写任何 task_id。"
            "上游结果必须写入 inputs；inputs 的角色名必须来自该 Worker 的 upstream_input_bindings。"
            "每个输入引用必须包含 from_task_id 和 expected_output_type；单个引用可写对象，多个引用写数组。"
            "inputs 只能包含上述上游 WorkerResult 引用对象，禁止写入字符串、GraphRef ID、user_id、语言或时间等直接值。"
            "不要输出 dependency_task_ids；程序会严格根据 inputs 中已经声明的 from_task_id 确定性生成执行依赖。"
            "程序不会推测或新增任何未在 inputs 中声明的依赖边。"
            "expected_output_type 必须来自所选 Worker 的 output_types。"
            "当 Worker 必要输入在当前请求、GraphRef、会话上下文或上游结果中都不可确定时，"
            "不要猜测；只规划能够合法表达缺失上下文的 Worker 任务，由 Worker 返回 need_context 给 MainAgent。"
            "analysis 模式只允许只读或派生事实写入能力，不得生成 Proposal；proposal 模式必须包含可生成 Proposal 的 Worker。"
            "最终必须包含一个产生 FinalReport 的报告 Worker，并通过 inputs 引用所有需要汇总的专业结果。"
            "严格只输出符合提供的 worker_dag_output_schema 的 JSON 对象，不要 Markdown，不要解释。"
        )
        event_names = {
            "request_started": "LOCAL_LLM_REQUEST_STARTED",
            "response_received": "LOCAL_LLM_RESPONSE_RECEIVED",
            "candidate_generated": "WORKER_PLAN_CANDIDATE_GENERATED",
            "validation_succeeded": "WORKER_PLAN_VALIDATION_SUCCEEDED",
            "validation_failed": "WORKER_PLAN_VALIDATION_FAILED",
            "repair_started": "WORKER_PLAN_REPAIR_STARTED",
            "repair_response_received": "WORKER_PLAN_REPAIR_RESPONSE_RECEIVED",
            "repair_candidate_generated": "WORKER_PLAN_REPAIR_CANDIDATE_GENERATED",
            "repair_validation_succeeded": "WORKER_PLAN_REPAIR_SUCCEEDED",
            "repair_failed": "WORKER_PLAN_REPAIR_FAILED",
        }

        def emit_planning_event(event: str, event_payload: dict[str, Any]) -> None:
            flow_event(
                event_names.get(event, f"WORKER_PLANNING_{event.upper()}"),
                event_payload,
                run_id=run_id,
                level=(
                    "ERROR"
                    if event in {"validation_failed", "repair_failed"}
                    else "INFO"
                ),
            )

        semantic_payload = self.llm_service.generate_json(
            stage="graph_coordinator_planner",
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "request_mode": mode,
                            "user_request": str(query or ""),
                            "session_context_summary": str(memory_summary or "")[:6000],
                            "resolved_focus_refs": [ref.to_dict() for ref in focus_refs],
                            "available_context_refs": [ref.to_dict() for ref in context_refs],
                            "worker_capability_catalog": cards,
                            "worker_dag_output_schema": PLAN_SCHEMA,
                            "authoritative_runtime_values": {
                                "user_id": str(user_id or "default"),
                                "reply_language": reply_language,
                                "as_of_time": str(as_of_time or ""),
                                "runtime_binding_policy": (
                                    "fields listed in worker.runtime_bound_args are supplied by code"
                                ),
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            max_output_tokens=4200,
            validator=validate,
            operation=f"graph_agent_task_plan:{mode}",
            event_callback=emit_planning_event,
        )
        prepared_payload, binding_audit = self._prepare_payload(
            semantic_payload,
            runtime_values=runtime_values,
        )
        flow_event(
            "WORKER_PLAN_AUTHORITATIVE_ARGS_BOUND",
            {
                "binding_policy": "worker_card.authoritative_arg_bindings",
                "tasks": binding_audit.get("tasks") or [],
                "worker_nodes_changed": False,
                "semantic_edges_changed": False,
            },
            run_id=run_id,
        )
        compiled_payload = self._compile_payload(prepared_payload)
        flow_event(
            "WORKER_PLAN_DEPENDENCIES_DERIVED",
            {
                "task_count": len(compiled_payload.get("tasks") or []),
                "derivation": "inputs.from_task_id -> dependency_task_ids",
                "semantic_plan": semantic_payload,
                "compiled_plan": compiled_payload,
                "new_edges_invented": False,
            },
            run_id=run_id,
        )
        flow_event(
            "WORKER_PLAN_ACCEPTED",
            {
                "request_mode": mode,
                "task_count": len(compiled_payload.get("tasks") or []),
                "tasks": compiled_payload.get("tasks") or [],
                "dag_mutation_after_planning": "forbidden",
                "dependency_derivation": "compiled_from_semantic_inputs",
            },
            run_id=run_id,
        )

        tasks: list[GraphAgentTask] = []
        for row in compiled_payload["tasks"]:
            card = self.directory.get(str(row["worker_id"]))
            dependencies = [
                str(item) for item in row.get("dependency_task_ids") or []
            ]
            try:
                priority = max(0, min(10, int(row.get("priority", 1))))
            except (TypeError, ValueError):
                priority = 1
            tasks.append(
                GraphAgentTask(
                    task_id=str(row["task_id"]),
                    run_id=run_id,
                    session_id=session_id,
                    worker_id=card.worker_id,
                    assigned_agent=card.agent_id,
                    objective=str(row["objective"]),
                    task_type=str(row["task_type"]),
                    args=dict(row.get("args") or {}),
                    inputs=dict(row.get("inputs") or {}),
                    expected_output_type=str(row["expected_output_type"]),
                    user_id=user_id,
                    focus_refs=list(focus_refs),
                    context_refs=list(context_refs),
                    dependency_task_ids=dependencies,
                    required_outputs=[str(row["expected_output_type"])],
                    constraints=[
                        str(item) for item in row.get("constraints") or []
                    ],
                    as_of_time=as_of_time,
                    priority=priority,
                    status=(
                        TaskStatus.READY
                        if not dependencies
                        else TaskStatus.CREATED
                    ),
                    metadata={
                        "request_mode": mode,
                        "structured_worker_contract": True,
                        "dependency_derivation": "compiled_from_semantic_inputs",
                    },
                )
            )
        self._validate_dependencies(tasks)
        for task in tasks:
            self.directory.validate_task_contract(task)
        flow_event(
            "WORKER_DAG_VALIDATED",
            {
                "task_count": len(tasks),
                "tasks": [task.safe_for_coordinator() for task in tasks],
                "validator_action": "accept_only_no_mutation",
                "dependency_derivation": "compiled_from_semantic_inputs",
            },
            run_id=run_id,
        )
        return tasks, {
            "planner": "main_agent_worker_dag_llm",
            "request_mode": mode,
            "fallback_used": False,
            "legacy_task_plan_consumed": False,
            "tool_visibility": "none",
            "worker_selection_owner": "main_agent",
            "dag_mutation_after_planning": "forbidden",
            "dependency_derivation": "compiled_from_semantic_inputs",
            "graph_contract_version": "graph_agent_task.v2",
            "structured_worker_contract": True,
        }

    def _validate_payload(
        self,
        payload: dict[str, Any],
        *,
        request_mode: str,
        authoritative_ref_ids: set[str] | None = None,
        authoritative_user_id: str = "",
        reply_language: str = "zh",
    ) -> None:
        validate_schema(payload, PLAN_SCHEMA)
        rows = payload["tasks"]
        known_ids = {str(row["task_id"]) for row in rows}
        if len(known_ids) != len(rows):
            raise WorkerContractViolation(
                "duplicate_task_id",
                "$.tasks",
            )

        cards_by_task: dict[str, Any] = {}
        output_type_by_task: dict[str, str] = {}
        proposal_capability_selected = False
        report_task_ids: list[str] = []

        # Validate each Worker node and its ordinary business args first. Task
        # references are deliberately not allowed in args.
        for index, row in enumerate(rows):
            task_id = str(row["task_id"])
            worker_id = str(row["worker_id"]).upper()
            card = self.directory.get(worker_id)
            cards_by_task[task_id] = card

            objective = str(row["objective"]).strip()
            if _contains_private_implementation(objective):
                raise WorkerContractViolation(
                    "private_implementation_in_worker_objective",
                    f"$.tasks[{index}].objective",
                )
            task_type = str(row["task_type"])
            if task_type not in card.accepted_task_types:
                raise WorkerContractViolation(
                    "unsupported_task_type_for_worker",
                    f"$.tasks[{index}].task_type",
                    f"{card.worker_id}:{task_type}",
                )
            self.directory.validate_task_args(card.worker_id, row["args"])
            args = dict(row.get("args") or {})
            for arg_name, arg_value in args.items():
                if "task_id" in str(arg_name).lower():
                    raise WorkerContractViolation(
                        "task_reference_not_allowed_in_args",
                        f"$.tasks[{index}].args.{arg_name}",
                    )
                if not arg_name.endswith("_ref_ids") or not isinstance(arg_value, list):
                    continue
                unknown_refs = [
                    str(item) for item in arg_value
                    if str(item) not in set(authoritative_ref_ids or set())
                ]
                if unknown_refs:
                    raise WorkerContractViolation(
                        "worker_arg_ref_not_in_authoritative_context",
                        f"$.tasks[{index}].args.{arg_name}",
                        ",".join(unknown_refs[:20]),
                    )
            if "user_id" in args and str(args.get("user_id")) != authoritative_user_id:
                raise WorkerContractViolation(
                    "worker_arg_user_id_mismatch",
                    f"$.tasks[{index}].args.user_id",
                )
            if "reply_language" in args and str(args.get("reply_language")) != reply_language:
                raise WorkerContractViolation(
                    "worker_arg_reply_language_mismatch",
                    f"$.tasks[{index}].args.reply_language",
                )

            output_type = str(row["expected_output_type"])
            if output_type not in card.output_types:
                raise WorkerContractViolation(
                    "unexpected_task_output_type",
                    f"$.tasks[{index}].expected_output_type",
                    f"{card.worker_id}:{output_type}",
                )
            output_type_by_task[task_id] = output_type

            if card.can_generate_proposal:
                proposal_capability_selected = True
                if request_mode != "proposal":
                    raise WorkerContractViolation(
                        "proposal_worker_not_allowed_in_read_only_mode",
                        f"$.tasks[{index}].worker_id",
                        card.worker_id,
                    )
            if "FinalReport" in card.output_types:
                report_task_ids.append(task_id)

        if not report_task_ids:
            raise WorkerContractViolation(
                "plan_missing_final_report_worker",
                "$.tasks",
            )
        if request_mode == "proposal" and not proposal_capability_selected:
            raise WorkerContractViolation(
                "proposal_plan_missing_proposal_capability",
                "$.tasks",
            )

        compiled_rows: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            task_id = str(row["task_id"])
            card = cards_by_task[task_id]
            inputs = self._canonical_inputs(row.get("inputs") or {})
            dependencies = self.directory.validate_task_inputs(
                card.worker_id,
                inputs,
                task_id=task_id,
                output_type_by_task=output_type_by_task,
                path=f"$.tasks[{index}].inputs",
            )
            validate_dependency_ids(
                dependencies,
                known_task_ids=known_ids,
                task_id=task_id,
            )
            upstream_types = {
                output_type_by_task[dependency_id]
                for dependency_id in dependencies
            }
            for group in card.required_upstream_output_groups:
                if not upstream_types.intersection(set(group)):
                    raise WorkerContractViolation(
                        "worker_upstream_output_contract_unsatisfied",
                        f"$.tasks[{index}].inputs",
                        f"worker={card.worker_id},required_one_of={group},available={sorted(upstream_types)}",
                    )
            compiled = dict(row)
            compiled["inputs"] = inputs
            compiled["dependency_task_ids"] = dependencies
            compiled_rows.append(compiled)

        self._validate_payload_dependencies(compiled_rows)
        self._validate_report_reachability(compiled_rows, report_task_ids)

    @staticmethod
    def _validate_payload_dependencies(rows: list[dict[str, Any]]) -> None:
        remaining = {str(row["task_id"]) for row in rows}
        completed: set[str] = set()
        while remaining:
            progressed = False
            for row in rows:
                task_id = str(row["task_id"])
                if task_id not in remaining:
                    continue
                dependencies = {
                    str(item)
                    for item in row.get("dependency_task_ids") or []
                }
                if dependencies.issubset(completed):
                    completed.add(task_id)
                    remaining.remove(task_id)
                    progressed = True
            if not progressed:
                raise WorkerContractViolation(
                    "worker_dag_cycle",
                    "$.tasks",
                    ",".join(sorted(remaining)),
                )

    @staticmethod
    def _validate_report_reachability(
        rows: list[dict[str, Any]],
        report_task_ids: list[str],
    ) -> None:
        reverse: dict[str, set[str]] = {
            str(row["task_id"]): set() for row in rows
        }
        for row in rows:
            task_id = str(row["task_id"])
            for dependency in row.get("dependency_task_ids") or []:
                reverse.setdefault(str(dependency), set()).add(task_id)

        reachable_to_report: set[str] = set(report_task_ids)
        changed = True
        while changed:
            changed = False
            for source, downstream in reverse.items():
                if source in reachable_to_report:
                    continue
                if downstream.intersection(reachable_to_report):
                    reachable_to_report.add(source)
                    changed = True

        all_ids = {str(row["task_id"]) for row in rows}
        orphaned = sorted(all_ids - reachable_to_report)
        if orphaned:
            raise WorkerContractViolation(
                "worker_task_not_connected_to_final_report",
                "$.tasks",
                ",".join(orphaned),
            )

    @staticmethod
    def _validate_dependencies(tasks: list[GraphAgentTask]) -> None:
        ids = {task.task_id for task in tasks}
        remaining = set(ids)
        completed: set[str] = set()
        while remaining:
            progressed = False
            for task in tasks:
                if task.task_id not in remaining:
                    continue
                if any(dep not in ids for dep in task.dependency_task_ids):
                    raise CoordinatorPlanningError(
                        "agent_task_unknown_dependency"
                    )
                if all(dep in completed for dep in task.dependency_task_ids):
                    completed.add(task.task_id)
                    remaining.remove(task.task_id)
                    progressed = True
            if not progressed:
                raise CoordinatorPlanningError(
                    "agent_task_dependency_cycle_or_unknown_dependency"
                )
