from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.llm import LLMService

from .models import AgentTask


class RequirementInferenceError(RuntimeError):
    pass


@dataclass
class ContextRequirement:
    key: str
    description: str
    expected_format: str = ""
    required: bool = True
    search_queries: list[str] | None = None

    def __post_init__(self) -> None:
        self.key = str(self.key or "").strip()
        self.description = str(self.description or self.key or "required context").strip()
        self.expected_format = str(self.expected_format or "").strip()
        self.required = bool(self.required)
        self.search_queries = [
            str(item) for item in list(self.search_queries or []) if str(item).strip()
        ][:8]


class RequirementEngine:
    """Infer missing context with the same run-bound LLMService.

    Failure is explicit. There is no keyword or semantic fallback that invents
    requirements after the main Agent plan has been accepted.
    """

    def __init__(self, *, llm_service: LLMService) -> None:
        self.llm_service = llm_service

    def infer(
        self,
        task: AgentTask,
        *,
        auto_context: dict[str, Any],
    ) -> tuple[list[ContextRequirement], dict[str, Any]]:
        def validate(payload: dict[str, Any]) -> None:
            rows = payload.get("requirements")
            if not isinstance(rows, list):
                raise RequirementInferenceError("requirements_not_list")
            if len(rows) > 12:
                raise RequirementInferenceError("too_many_requirements")
            for row in rows:
                if not isinstance(row, dict):
                    raise RequirementInferenceError("requirement_not_object")
                key = str(row.get("key") or "").strip()
                if not key:
                    raise RequirementInferenceError("requirement_key_missing")
                lowered = key.lower()
                if any(fragment in lowered for fragment in ("tool", "schema", "api", "sql")):
                    raise RequirementInferenceError(f"forbidden_requirement_key:{key}")

        system = (
            "你是专业 Agent 的上下文需求分析器。根据已分配的 AgentTask 判断完成任务必须知道哪些事实。"
            "不要列出专业 Agent 可以自行查询得到的普通数据，除非必须先有目标标识才能查询。"
            "不要假设关键事实，不要向用户提问，不要输出 Tool、函数、API、Schema 或数据库信息。"
            "若当前上下文已经足够，requirements 返回空数组。"
            "严格输出 JSON：{\"requirements\":[{\"key\":\"...\","
            "\"description\":\"...\",\"expected_format\":\"...\","
            "\"required\":true,\"search_queries\":[\"...\"]}]}。"
        )
        payload = self.llm_service.generate_json(
            stage="specialist_requirement",
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": __import__("json").dumps(
                        {
                            "specialist": task.assigned_agent,
                            "task_type": task.task_type,
                            "objective": task.objective,
                            "constraints": task.constraints,
                            "current_user_request": auto_context.get("current_user_request"),
                            "session_memory_summary": auto_context.get("session_memory_summary"),
                            "dependency_result_summaries": auto_context.get("dependency_results"),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            max_output_tokens=1200,
            validator=validate,
            operation=task.task_type,
        )
        result: list[ContextRequirement] = []
        for row in payload.get("requirements") or []:
            result.append(
                ContextRequirement(
                    key=str(row.get("key") or ""),
                    description=str(row.get("description") or row.get("key") or ""),
                    expected_format=str(row.get("expected_format") or ""),
                    required=bool(row.get("required", True)),
                    search_queries=list(row.get("search_queries") or []),
                )
            )
        return result, {
            "source": "specialist_llm",
            "fallback_used": False,
            "llm_profile_id": self.llm_service.profile_id,
            "llm_config_hash": self.llm_service.config_hash,
        }
