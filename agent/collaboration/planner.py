from __future__ import annotations

import json
import re
from typing import Any

from core.llm import LLMService

from .agent_directory import (
    AgentDirectory,
    GRAPH_IMPACT_ANALYST,
    PORTFOLIO_ANALYST,
    REPORT_WRITER,
    STRATEGY_GUARD,
)
from .models import GraphAgentTask, TaskStatus


class CoordinatorPlanningError(RuntimeError):
    pass


def _contains_private_implementation(value: str) -> bool:
    text = str(value or "").lower()
    blocked = (
        "tool", "schema", "cypher", "sql", "api endpoint", "database table",
        "tool_registry", "stock_code", "stock_codes", "ts_code", "security_scope",
        "route_agent_query", "intent router",
    )
    return any(item in text for item in blocked) or bool(re.search(r"\b[a-z]+\.[a-z_]+\b", text))


class CoordinatorPlanner:
    """Plan Worker-level tasks from capability cards only.

    The planner does not know private tools, provider identifiers, Neo4j schema,
    or legacy intent names. GraphRefs are attached by the coordinator after the
    business-level plan is validated.
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
            raise CoordinatorPlanningError(f"unsupported_agent_request_mode:{mode}")

        cards = self.directory.safe_catalog()

        def validate(payload: dict[str, Any]) -> None:
            rows = payload.get("tasks")
            if not isinstance(rows, list) or not rows:
                raise CoordinatorPlanningError("coordinator_plan_missing_tasks")
            if len(rows) > 8:
                raise CoordinatorPlanningError("coordinator_plan_too_many_tasks")
            known_ids: set[str] = set()
            selected_agents: set[str] = set()
            for row in rows:
                if not isinstance(row, dict):
                    raise CoordinatorPlanningError("coordinator_plan_task_not_object")
                task_id = str(row.get("task_id") or "").strip()
                if not task_id or task_id in known_ids:
                    raise CoordinatorPlanningError("coordinator_plan_invalid_task_id")
                known_ids.add(task_id)
                agent_id = str(row.get("assigned_agent") or "").strip().upper()
                card = self.directory.get(agent_id)
                selected_agents.add(agent_id)
                task_type = str(row.get("task_type") or "").strip()
                if task_type not in card.accepted_task_types:
                    raise CoordinatorPlanningError(
                        f"unsupported_task_type_for_agent:{agent_id}:{task_type}"
                    )
                objective = str(row.get("objective") or "").strip()
                if not objective or _contains_private_implementation(objective):
                    raise CoordinatorPlanningError(f"invalid_agent_objective:{task_id}")
                dependencies = row.get("dependency_task_ids") or []
                if not isinstance(dependencies, list):
                    raise CoordinatorPlanningError(f"invalid_dependencies:{task_id}")
            for row in rows:
                task_id = str(row.get("task_id") or "")
                for dependency in row.get("dependency_task_ids") or []:
                    if str(dependency) not in known_ids or str(dependency) == task_id:
                        raise CoordinatorPlanningError(f"invalid_dependency_ref:{task_id}:{dependency}")
            if mode == "proposal" and STRATEGY_GUARD not in selected_agents:
                raise CoordinatorPlanningError("proposal_plan_missing_strategy_guard")
            if REPORT_WRITER not in selected_agents:
                raise CoordinatorPlanningError("plan_missing_report_writer")

        system = (
            "你是系统现有主协调 Agent 的任务规划器。主 Agent 已经具备 Worker 能力发现、委派、反馈和重新规划，"
            "本步骤只生成 Worker 级业务任务。你只能看到能力卡，不能看到或猜测任何私有 Tool、函数、API、"
            "Neo4j 标签、Cypher、数据库表、参数 Schema、provider code、旧 stock_code 字段或旧 intent。"
            "把用户目标拆成 1 到 8 个 Worker 任务。task_type 必须来自对应能力卡 accepted_task_types。"
            "报告任务依赖需要汇总的专业任务。分析某篇新闻对持仓影响时，应并行读取新闻证据和持仓快照，"
            "随后安排 GRAPH_IMPACT_ANALYST，最后安排 REPORT_WRITER。"
            "只有用户明确涉及个人持仓、账户、现金、仓位、模拟盘或组合适配时，才安排 PORTFOLIO_ANALYST。"
            "RISK_ANALYST 处理个人组合风险时必须依赖组合结果。"
            "proposal 模式必须安排 STRATEGY_GUARD，但它只能生成待审批方案，不能 Commit。"
            "严格输出 JSON：{\"tasks\":[{\"task_id\":\"task_1\",\"assigned_agent\":\"...\","
            "\"objective\":\"...\",\"task_type\":\"...\",\"constraints\":[],"
            "\"dependency_task_ids\":[],\"required_outputs\":[],\"priority\":1}]}。"
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
                            "agent_capability_catalog": cards,
                            "reply_language": language,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            max_output_tokens=3000,
            validator=validate,
            operation=f"graph_agent_task_plan:{mode}",
        )

        tasks: list[GraphAgentTask] = []
        for row in payload["tasks"]:
            dependencies = [str(item) for item in row.get("dependency_task_ids") or []]
            try:
                priority = max(0, min(10, int(row.get("priority", 1))))
            except (TypeError, ValueError):
                priority = 1
            tasks.append(
                GraphAgentTask(
                    task_id=str(row["task_id"]),
                    run_id=run_id,
                    session_id=session_id,
                    assigned_agent=str(row["assigned_agent"]).upper(),
                    objective=str(row["objective"]),
                    task_type=str(row["task_type"]),
                    user_id=user_id,
                    focus_refs=list(focus_refs),
                    context_refs=list(context_refs),
                    dependency_task_ids=dependencies,
                    required_outputs=[str(item) for item in row.get("required_outputs") or []],
                    constraints=[str(item) for item in row.get("constraints") or []],
                    as_of_time=as_of_time,
                    priority=priority,
                    status=TaskStatus.READY if not dependencies else TaskStatus.CREATED,
                    metadata={"request_mode": mode},
                )
            )
        self._validate_dependencies(tasks)
        self._validate_impact_dependency(tasks)
        return tasks, {
            "planner": "coordinator_llm",
            "request_mode": mode,
            "fallback_used": False,
            "legacy_task_plan_consumed": False,
            "tool_visibility": "none",
            "graph_contract_version": "graph_agent_task.v1",
        }

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
                raise CoordinatorPlanningError("agent_task_dependency_cycle_or_unknown_dependency")

    @staticmethod
    def _validate_impact_dependency(tasks: list[GraphAgentTask]) -> None:
        by_id = {task.task_id: task for task in tasks}
        for task in tasks:
            if task.assigned_agent != GRAPH_IMPACT_ANALYST:
                continue
            upstream_agents = {
                by_id[dep].assigned_agent
                for dep in task.dependency_task_ids
                if dep in by_id
            }
            if PORTFOLIO_ANALYST not in upstream_agents:
                raise CoordinatorPlanningError("graph_impact_missing_portfolio_dependency")
