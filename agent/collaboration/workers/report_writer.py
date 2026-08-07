"""W06 presentation-only natural-language report writer.

DeepAgents-inspired boundary: upstream specialist Workers return structured
results; the presentation Worker receives only materialized terminal slots and
turns them into user-facing text.  It does not recreate entity schemas or
specialist analysis structures.
"""

from __future__ import annotations

from typing import Any

from core.llm import LLMService
from core.llm.prompt_compaction import compact_json_dumps

from ..completion import build_completion_report
from ..models import GraphAgentTask, GraphWorkerResult, MissingContextItem, ResultStatus
from .common import contract_output_slots, execution_safe_value
from .slot_inputs import slot_envelopes


_TERMINAL_REPORT_SLOTS = {
    "entity_analysis",
    "entity_analysis_uncertainty",
    "portfolio_analysis",
    "portfolio_risk_analysis",
    "portfolio_risk_constraints",
    "reviewed_proposal",
    "system_diagnosis",
    "graph_relation_facts",
    "financial_relation_paths",
    "account_financial_state",
    "current_portfolio_state",
    "portfolio_positions",
}

_RUNTIME_ONLY_SLOTS = {
    "current_user_request",
    "user_identity",
    "permission_context",
    "reply_language",
    "as_of_time",
    "runtime_context",
    "business_parameters",
    "authoritative_entity_refs",
    "context_entity_refs",
    "source_entity_refs",
    "target_entity_refs",
    "session_summary",
}

_MAX_REPORT_CHARS = 12000


def _terminal_inputs(
    task: GraphAgentTask,
    resolved_inputs: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    envelopes = slot_envelopes(task, resolved_inputs, projection="execution")
    upstream = [row for row in envelopes if row.get("source_task_ids")]
    terminal = [
        row for row in upstream
        if str(row.get("slot_id") or "") in _TERMINAL_REPORT_SLOTS
    ]
    selected = terminal or [
        row for row in upstream
        if str(row.get("slot_id") or "") not in _RUNTIME_ONLY_SLOTS
    ]
    producer_ids: list[str] = []
    rows: list[dict[str, Any]] = []
    for item in selected:
        source_ids = [str(value) for value in item.get("source_task_ids") or [] if str(value)]
        for source_id in source_ids:
            if source_id not in producer_ids:
                producer_ids.append(source_id)
        rows.append({
            "slot_id": str(item.get("slot_id") or ""),
            "source_task_ids": source_ids,
            "payload": execution_safe_value(item.get("payload")),
        })
    return rows, producer_ids


def _system_prompt(language: str) -> str:
    if language == "en":
        return (
            "You are W06, a presentation-only response writer. Convert the supplied terminal structured slots into a clear user-facing answer. "
            "The supplied slots are your entire factual world. Do not retrieve data, perform a second specialist analysis, infer missing capabilities, or add facts, numbers, risks, recommendations, entities, or causal claims that are not present in those slots. "
            "Do not mention Workers, task ids, slot ids, tools, GraphRefs, schemas, databases, or runtime internals. Return only the final natural-language answer, not JSON."
        )
    return (
        "你是W06，只负责把收到的终端结构化Slot转换为清晰的用户自然语言回答。"
        "这些Slot就是你完整的事实世界；不得重新检索数据、进行第二次专业分析、推断缺失能力，"
        "也不得增加输入中不存在的事实、数值、风险、建议、实体或因果结论。"
        "不要提及Worker、task_id、slot_id、Tool、GraphRef、Schema、数据库或运行时内部实现。"
        "只输出最终自然语言正文，不输出JSON。"
    )


def run_report_writer(
    llm_service: LLMService,
    task: GraphAgentTask,
    language: str,
    *,
    resolved_inputs: dict[str, Any] | None = None,
) -> GraphWorkerResult:
    # Worker-to-Worker execution context is authoritative via SlotStore materialization.
    terminal_inputs, source_task_ids = _terminal_inputs(task, resolved_inputs)
    if not terminal_inputs:
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.NEED_CONTEXT,
            output_type="FinalReport",
            data=None,
            error=None,
            focus_refs=task.focus_refs,
            summary="报告生成没有收到合同绑定的终端结构化输入。",
            missing_items=[
                MissingContextItem(
                    key="terminal_information_slots",
                    description="需要Runtime物化并绑定上游终端信息Slot。",
                    searched_sources=["RunSlotStore", "resolved_input_bindings"],
                )
            ],
        )

    objective = str(task.args.get("report_goal") or task.objective or "").strip()
    answer = llm_service.generate_text(
        stage="graph_report_writer",
        messages=[
            {"role": "system", "content": _system_prompt(language)},
            {
                "role": "user",
                "content": compact_json_dumps({
                    "user_goal": objective,
                    "terminal_structured_inputs": terminal_inputs,
                    "reply_language": "en" if language == "en" else "zh",
                }),
            },
        ],
        max_output_tokens=2200,
        temperature=0.0,
        operation="write_user_facing_report",
        disable_thinking=True,
    ).strip()
    if not answer:
        raise RuntimeError("report_writer_empty_text")
    if len(answer) > _MAX_REPORT_CHARS:
        answer = answer[:_MAX_REPORT_CHARS].rstrip()

    runtime_summary = {
        "status": "completed",
        "source_task_ids": source_task_ids,
        "source_slot_ids": [row["slot_id"] for row in terminal_inputs],
    }
    declared_outputs = contract_output_slots(task)
    slots: dict[str, Any] = {}
    for slot_id in declared_outputs:
        if slot_id == "user_facing_report":
            slots[slot_id] = answer
        elif slot_id == "goal_completion_summary":
            slots[slot_id] = runtime_summary
        else:
            # result.composition may be extended with another presentation slot;
            # keep its value presentation-only rather than inventing domain data.
            slots[slot_id] = answer

    completion = build_completion_report(
        task,
        execution_status="succeeded",
        contract_status="valid",
        business_status="sufficient",
        completion_status="completed",
        expected_task_completed=True,
        produced_information_slots=list(slots),
        criterion_results=[],
        limitations=[],
        failure_kind="none",
        report_source="runtime",
    )
    data = {
        "content": answer,
        "slots": slots,
        "produced_information_slots": list(slots),
        "source_task_ids": source_task_ids,
    }
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=ResultStatus.COMPLETED,
        output_type="FinalReport",
        payload_schema="final_report_text.v1",
        payload=data,
        data=data,
        error=None,
        focus_refs=task.focus_refs,
        summary=("已生成用户可读报告。" if language != "en" else "User-facing report generated."),
        confidence=1.0,
        completion=completion,
        metadata={
            "presentation_only": True,
            "natural_language_output": True,
            "source_task_ids": source_task_ids,
            "produced_information_slots": list(slots),
        },
    )


__all__ = ["run_report_writer"]
