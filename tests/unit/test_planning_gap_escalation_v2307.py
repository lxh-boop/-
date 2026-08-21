from __future__ import annotations

from types import SimpleNamespace

from agent.capabilities import CapabilityTask, TaskDependencyCompiler
from agent.collaboration.error_contracts import escalation_from_worker_result
from agent.collaboration.models import MissingContextItem
from agent.collaboration.worker_directory import CapabilityWorkerDirectory
from agent.context.context_sufficiency_gate import ContextAndEntitySufficiencyGate


def _contract(outputs, *, required_data=None, mutation=False):
    return {
        "description": "v2316 context contract",
        "required_data": [{"name": name, "required": True} for name in (required_data or [])],
        "required_parameters": [],
        "promised_data": [{"name": name} for name in outputs],
        "acceptance_rule_ids": ["schema_valid"],
        "forbidden_data_names": [],
        "criticality": "required",
        "mutation_allowed": mutation,
        "allowed_terminal_states": ["completed", "business_empty", "business_insufficient"],
    }


def _task(task_id, worker_id, boundary, outputs, *, required_data=None, mutation=False):
    return CapabilityTask.from_dict({
        "task_id": task_id, "worker_id": worker_id, "boundary_id": boundary,
        "objective": task_id,
        "contracts": [_contract(outputs, required_data=required_data, mutation=mutation)],
    }, task_id=task_id)


def test_w04_w05_public_descriptions_are_working_memory_consumers_not_worker_bound() -> None:
    directory = CapabilityWorkerDirectory()
    w04, w05 = directory.get("W04"), directory.get("W05")
    assert w04.working_memory_mode == "consumer"
    assert w05.working_memory_mode == "consumer"
    assert w04.can_mutate is False
    assert w05.can_mutate is False
    assert "W02" not in w04.full_description
    assert "W04" not in w05.full_description


def test_task_dependencies_only_order_execution_stages_not_transport_data() -> None:
    directory = CapabilityWorkerDirectory()
    tasks = [
        _task("T01", "W02", "system_internal_fact_provider", ["portfolio"]),
        _task("T02", "W04", "portfolio_risk_assessment", ["risk"], required_data=["portfolio"]),
        _task("T03", "W05", "state_change_proposal", ["proposal"], required_data=["risk"]),
    ]
    deps = TaskDependencyCompiler(directory).compile(tasks)
    assert deps["T01"] == []
    assert deps["T02"] == ["T01"]
    assert set(deps["T03"]) == {"T01", "T02"}
    # No point-to-point data binding exists on the capability tasks.
    assert not hasattr(tasks[1], "resolved_input_bindings")


def test_analysis_business_data_gap_is_not_a_runtime_parameter_gap() -> None:
    gate = ContextAndEntitySufficiencyGate()
    internal = gate.evaluate(missing_items=[MissingContextItem(
        key="盈利能力相关经营数据", description="当前工作记忆中的业务信息不足",
        reason="analysis_context_insufficient",
    )])
    assert internal.next_action == "wait_context"
    assert internal.missing_parameters == []
    assert internal.missing_context == ["盈利能力相关经营数据"]


def test_context_sufficiency_asks_user_only_for_explicit_parameter_gap() -> None:
    gate = ContextAndEntitySufficiencyGate()
    user_parameter = gate.evaluate(missing_items=[MissingContextItem(
        key="comparison_security_b", description="缺少第二只比较股票",
        reason="parameter missing: user must specify the second security",
    )])
    assert user_parameter.next_action == "ask_user"
    assert user_parameter.missing_parameters == ["comparison_security_b"]


def test_worker_escalation_keeps_user_parameter_and_internal_context_distinct() -> None:
    task = SimpleNamespace(objective="比较证券", boundary_id="entity.analysis")
    parameter_result = SimpleNamespace(
        status=SimpleNamespace(value="need_context"), error=None,
        missing_items=[MissingContextItem(key="comparison_security_b", description="缺少第二只证券",
                                          reason="parameter missing: user must specify")],
        summary="需要用户补充参数",
    )
    internal_result = SimpleNamespace(
        status=SimpleNamespace(value="need_context"), error=None,
        missing_items=[MissingContextItem(key="盈利能力相关经营数据", description="工作记忆信息不足",
                                          reason="analysis_context_insufficient")],
        summary="需要内部上下文",
    )
    assert escalation_from_worker_result(task, parameter_result).error_id == "user_input_required"
    assert escalation_from_worker_result(task, internal_result).error_id == "worker_context_unresolved"
