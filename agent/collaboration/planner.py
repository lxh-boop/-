from __future__ import annotations

import json
import re
from typing import Any

from core.llm import LLMService

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
                    "constraints": array_schema({"type": "string"}),
                    "dependency_task_ids": array_schema(
                        string_schema(min_length=1),
                        max_items=8,
                    ),
                    "expected_output_type": string_schema(min_length=1),
                    "priority": {"type": "integer"},
                },
                required=[
                    "task_id",
                    "worker_id",
                    "objective",
                    "task_type",
                    "args",
                    "constraints",
                    "dependency_task_ids",
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
    """MainAgent Worker-DAG planner.

    MainAgent directly chooses registered ``worker_id`` values and fixes the
    complete Worker DAG. The validator may accept or reject that whole graph but
    never inserts, removes, splits, merges, replaces, or rewires Worker nodes.
    """

    def __init__(self, directory: AgentDirectory, *, llm_service: LLMService) -> None:
        self.directory = directory
        self.llm_service = llm_service

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

        authoritative_ref_ids = {
            str(ref.node_id) for ref in [*focus_refs, *context_refs]
        }

        def validate(payload: dict[str, Any]) -> None:
            try:
                self._validate_payload(
                    payload,
                    request_mode=mode,
                    authoritative_ref_ids=authoritative_ref_ids,
                    authoritative_user_id=str(user_id or "default"),
                    reply_language="en" if language == "en" else "zh",
                )
            except (WorkerContractViolation, KeyError) as exc:
                raise CoordinatorPlanningError(str(exc)) from exc

        system = (
            "你是系统唯一的 MainAgent Worker 编排器。你必须直接从给定的结构化 Worker 能力卡中选择 worker_id，"
            "并一次性生成完整 Worker DAG。执行器和 Validator 都不会替你增加、删除、拆分、合并、替换或重连节点。"
            "每个节点必须由一个 Worker 完整承担一个业务子目标；不要规划 Worker 内部的 Tool 调用。"
            "只选择完成用户明确目标所必要的最少 Worker；某个 Worker 可用不代表本次任务需要它；"
            "不得为了更全面、可能有帮助或顺便给建议而扩大用户目标。"
            "objective 只描述该 Worker 的完整业务子目标，不得包含 Tool、函数、API、数据库、Schema、字段名或实现细节。"
            "args 必须严格符合所选 Worker 的 input_schema；expected_output_type 必须来自该卡 output_types。"
            "dependency_task_ids 必须表达真实的数据依赖；依赖输入必须符合能力卡的上游输出合同。"
            "当 Worker 必要输入在当前请求、GraphRef、会话上下文或上游结果中都不可确定时，"
            "不要猜测；只规划能够合法表达缺失上下文的 Worker 任务，由 Worker 返回 need_context 给 MainAgent。"
            "analysis 模式只允许只读或派生事实写入能力，不得生成 Proposal；proposal 模式必须包含可生成 Proposal 的 Worker。"
            "最终必须包含一个产生 FinalReport 的报告 Worker，并让它依赖所有需要汇总的专业结果。"
            "严格只输出符合提供的 worker_dag_output_schema 的 JSON 对象，不要 Markdown，不要解释。"
        )
        payload = self.llm_service.generate_json(
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
                                "reply_language": "en" if language == "en" else "zh",
                                "as_of_time": str(as_of_time or ""),
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            max_output_tokens=4200,
            validator=validate,
            operation=f"graph_agent_task_plan:{mode}",
        )

        tasks: list[GraphAgentTask] = []
        for row in payload["tasks"]:
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
                    },
                )
            )
        self._validate_dependencies(tasks)
        return tasks, {
            "planner": "main_agent_worker_dag_llm",
            "request_mode": mode,
            "fallback_used": False,
            "legacy_task_plan_consumed": False,
            "tool_visibility": "none",
            "worker_selection_owner": "main_agent",
            "dag_mutation_after_planning": "forbidden",
            "graph_contract_version": "graph_agent_task.v1",
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
            known_ref_ids = set(authoritative_ref_ids or set())
            for arg_name, arg_value in args.items():
                if not arg_name.endswith("_ref_ids") or not isinstance(arg_value, list):
                    continue
                unknown_refs = [
                    str(item) for item in arg_value
                    if str(item) not in known_ref_ids
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

            dependencies = [
                str(item) for item in row.get("dependency_task_ids") or []
            ]
            validate_dependency_ids(
                dependencies,
                known_task_ids=known_ids,
                task_id=task_id,
            )
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

        for index, row in enumerate(rows):
            task_id = str(row["task_id"])
            card = cards_by_task[task_id]
            dependencies = [
                str(item) for item in row.get("dependency_task_ids") or []
            ]
            upstream_types = {
                output_type_by_task[dependency_id]
                for dependency_id in dependencies
            }
            for group in card.required_upstream_output_groups:
                if not upstream_types.intersection(set(group)):
                    raise WorkerContractViolation(
                        "worker_upstream_output_contract_unsatisfied",
                        f"$.tasks[{index}].dependency_task_ids",
                        f"worker={card.worker_id},required_one_of={group},available={sorted(upstream_types)}",
                    )

            args = dict(row.get("args") or {})
            for field_name, allowed_types in card.dependency_arg_fields.items():
                referenced_ids = args.get(field_name) or []
                if not isinstance(referenced_ids, list):
                    continue
                for referenced_id in referenced_ids:
                    referenced_id = str(referenced_id)
                    if referenced_id not in dependencies:
                        raise WorkerContractViolation(
                            "dependency_arg_not_declared_as_dependency",
                            f"$.tasks[{index}].args.{field_name}",
                            referenced_id,
                        )
                    actual_type = output_type_by_task.get(referenced_id, "")
                    if "*" not in allowed_types and actual_type not in allowed_types:
                        raise WorkerContractViolation(
                            "dependency_output_type_not_accepted",
                            f"$.tasks[{index}].args.{field_name}",
                            f"task={referenced_id},actual={actual_type},allowed={allowed_types}",
                        )

        self._validate_payload_dependencies(rows)
        self._validate_report_reachability(rows, report_task_ids)

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
                if all(dep in completed for dep in task.dependency_task_ids):
                    completed.add(task.task_id)
                    remaining.remove(task.task_id)
                    progressed = True
            if not progressed:
                raise CoordinatorPlanningError(
                    "agent_task_dependency_cycle_or_unknown_dependency"
                )
