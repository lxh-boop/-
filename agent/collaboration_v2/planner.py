from __future__ import annotations

import re
from typing import Any

from core.llm import LLMService

from .agent_directory import AgentDirectory, REPORT_WRITER, STRATEGY_GUARD
from .contracts import (
    build_stable_analysis_tasks,
    enforce_analysis_agent_scope,
    enforce_risk_dependency,
)
from .models import AgentTask, TaskStatus


class CoordinatorPlanningError(RuntimeError):
    pass


def _contains_tool_like_content(value: str) -> bool:
    text = str(value or "").lower()
    blocked = (
        "tool", "schema", "sql", "api endpoint", "database table", "execute_tool",
        "tool_registry", "stock_analysis", "portfolio_state", "stock_rag",
        "stock_news", "route_agent_query", "intent",
    )
    return any(item in text for item in blocked) or bool(re.search(r"\b[a-z]+\.[a-z_]+\b", text))


class CoordinatorPlanner:
    """Build an Agent-level DAG from capability cards only."""

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
        memory_summary: str,
        language: str = "zh",
    ) -> tuple[list[AgentTask], dict[str, Any]]:
        mode = str(request_mode or "analysis").strip().lower()
        if mode not in {"analysis", "proposal"}:
            raise CoordinatorPlanningError(f"unsupported_agent_request_mode:{mode}")

        stable = (
            build_stable_analysis_tasks(
                query=query,
                session_id=session_id,
                run_id=run_id,
            )
            if mode == "analysis"
            else None
        )
        if stable is not None:
            tasks, metadata = stable
            tasks = enforce_risk_dependency(tasks)
            self._validate_dependencies(tasks)
            return tasks, metadata

        cards = self.directory.safe_catalog()

        def validate(payload: dict[str, Any]) -> None:
            rows = payload.get("tasks")
            if not isinstance(rows, list) or not rows:
                raise CoordinatorPlanningError("coordinator_plan_missing_tasks")
            if len(rows) > 6:
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
                if not objective or _contains_tool_like_content(objective):
                    raise CoordinatorPlanningError(f"invalid_agent_objective:{task_id}")
                dependencies = row.get("dependency_task_ids") or []
                if not isinstance(dependencies, list):
                    raise CoordinatorPlanningError(f"invalid_dependencies:{task_id}")
            for row in rows:
                task_id = str(row.get("task_id") or "")
                for dependency in row.get("dependency_task_ids") or []:
                    if str(dependency) not in known_ids or str(dependency) == task_id:
                        raise CoordinatorPlanningError(f"invalid_dependency_ref:{task_id}:{dependency}")
            if mode == "proposal":
                if STRATEGY_GUARD not in selected_agents:
                    raise CoordinatorPlanningError("proposal_plan_missing_strategy_guard")
                if REPORT_WRITER not in selected_agents:
                    raise CoordinatorPlanningError("proposal_plan_missing_report_writer")

        system = (
            "你是唯一主协调 Agent 的任务规划器。你只能选择专业 Agent、定义业务目标和依赖，"
            "不能看到、猜测或输出任何 Tool、函数、API、数据库表、参数 Schema、代码路径、旧 intent。"
            "请把用户目标拆成 1 到 6 个 Agent 级任务。task_type 必须严格来自相应能力卡的 accepted_task_types。"
            "无依赖任务可以并行；报告任务应依赖需要汇总的专业任务。"
            "当 request_mode=proposal 时，必须包含 STRATEGY_GUARD 的 build_proposal/review_proposal 任务，"
            "并包含 REPORT_WRITER；STRATEGY_GUARD 只能生成待审批 Proposal，不能 Commit。"
            "当 request_mode=analysis 时，不得安排 STRATEGY_GUARD 生成 Proposal，除非用户明确要求审查已有方案。"
            "只有用户明确涉及个人持仓、账户、现金、仓位、模拟盘或组合适配时，才能安排 PORTFOLIO_ANALYST。"
            "RISK_ANALYST 只处理个人组合风险，并且必须依赖 PORTFOLIO_ANALYST 的账户与组合结果。"
            "普通个股分析或个股风险问题只安排 EVIDENCE_RETRIEVER 和 REPORT_WRITER。"
            "严格输出 JSON：{\"tasks\":[{\"task_id\":\"task_1\","
            "\"assigned_agent\":\"...\",\"objective\":\"...\",\"task_type\":\"...\","
            "\"constraints\":[],\"dependency_task_ids\":[],"
            "\"expected_output_type\":\"...\",\"priority\":1}]}。"
        )
        payload = self.llm_service.generate_json(
            stage="coordinator_planner",
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": __import__("json").dumps(
                        {
                            "request_mode": mode,
                            "user_request": str(query or ""),
                            "session_context_summary": str(memory_summary or "")[:6000],
                            "agent_capability_catalog": cards,
                            "reply_language": language,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            max_output_tokens=2400,
            validator=validate,
            operation=f"agent_level_task_plan:{mode}",
        )

        tasks: list[AgentTask] = []
        for row in payload["tasks"]:
            agent_id = str(row["assigned_agent"]).upper()
            card = self.directory.get(agent_id)
            dependencies = [str(item) for item in row.get("dependency_task_ids") or []]
            priority_value = row.get("priority", 1)
            try:
                priority = int(priority_value)
            except (TypeError, ValueError):
                priority = 1
            tasks.append(
                AgentTask(
                    task_id=str(row["task_id"]),
                    run_id=run_id,
                    session_id=session_id,
                    assigned_agent=agent_id,
                    objective=str(row["objective"]),
                    task_type=str(row["task_type"]),
                    constraints=[str(item) for item in row.get("constraints") or []],
                    dependency_task_ids=dependencies,
                    expected_output_type=str(
                        row.get("expected_output_type")
                        or (card.output_types[0] if card.output_types else "agent_result")
                    ),
                    priority=max(1, priority),
                    status=TaskStatus.READY if not dependencies else TaskStatus.PENDING,
                    metadata={"request_mode": mode},
                )
            )
        tasks = (
            enforce_analysis_agent_scope(tasks, query)
            if mode == "analysis"
            else enforce_risk_dependency(tasks)
        )
        if not tasks:
            raise CoordinatorPlanningError("coordinator_plan_empty_after_scope_enforcement")
        self._validate_dependencies(tasks)
        return tasks, {
            "planner": "coordinator_llm",
            "request_mode": mode,
            "fallback_used": False,
            "legacy_task_plan_consumed": False,
            "keyword_business_fallback_used": False,
            "tool_visibility": "none",
        }

    @staticmethod
    def _validate_dependencies(tasks: list[AgentTask]) -> None:
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
                raise CoordinatorPlanningError("agent_task_dependency_cycle")
