"""Bundle-level presentation-only report writer."""
from __future__ import annotations

import json
from typing import Any

from core.llm import LLMService

from ..completion import runtime_completion_report
from ..models import GraphAgentTask, GraphWorkerResult, ResultStatus
from .common import execution_safe_value, materialize_promised_data


def run_report_writer(
    llm_service: LLMService,
    task: GraphAgentTask,
    language: str,
    *,
    request_bundle_results: Any,
    presentation_policy: dict[str, Any] | None = None,
) -> GraphWorkerResult:
    """Render already-verified Request results without business-data retrieval."""
    results = execution_safe_value(request_bundle_results)
    policy = execution_safe_value(dict(presentation_policy or {}))
    if results in (None, {}, []):
        result = GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.NEED_CONTEXT,
            output_type="FinalReport",
            data=None,
            error={
                "error_id": "request_results_unavailable",
                "operation": task.objective,
                "reason": "Bundle-level report writer did not receive Request results.",
                "retryable": False,
            },
            focus_refs=task.focus_refs,
            summary="最终报告阶段没有收到Request结果集合。",
        )
        result.completion = runtime_completion_report(
            task, result_status=result.status, output_type=result.output_type, data=result.data, error=result.error
        )
        return result

    system = (
        "你是W06最终报告Worker。你只能把Runtime提供的Request结果集合整理成用户可读回答。"
        "不得重新查询、不得重新做专业分析、不得补充结果中不存在的事实。"
        "严格区分completed、waiting_context、waiting_approval、unsupported、tool_failed、business_empty等状态。"
        "presentation_policy是最终呈现要求。"
        if language != "en" else
        "You are W06, the final presentation Worker. Render only the supplied verified Request results. Do not retrieve or add business facts. Respect presentation_policy."
    )
    answer = llm_service.generate_text(
        stage="graph_report_writer",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps({
                "request_bundle_results": results,
                "presentation_policy": policy,
                "reply_language": language,
            }, ensure_ascii=False, default=str)},
        ],
        max_output_tokens=2200,
        operation="write_user_facing_report",
        disable_thinking=True,
    )
    answer = str(answer or "").strip()
    report_data = {
        "content": answer,
        "request_bundle_results": results,
        "presentation_policy": policy,
    }
    business_data = materialize_promised_data(
        task, answer, per_name={"report": answer, "result.user_facing": answer}
    )
    data = {**report_data, "business_data": business_data, "produced_data_names": list(business_data)}
    result = GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=ResultStatus.COMPLETED,
        output_type="FinalReport",
        data=data,
        error=None,
        focus_refs=task.focus_refs,
        summary=answer[:8000],
        confidence=1.0,
        metadata={"presentation_only": True, "database_write": False},
    )
    result.completion = runtime_completion_report(
        task, result_status=result.status, output_type=result.output_type, data=result.data, error=result.error
    )
    return result


__all__ = ["run_report_writer"]
