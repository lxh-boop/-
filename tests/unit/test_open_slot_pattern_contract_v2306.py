from __future__ import annotations

import json

import pytest

from agent.collaboration.planner import CoordinatorPlanner
from agent.collaboration.worker_contracts import WorkerContractViolation
from agent.collaboration.worker_directory import CapabilityWorkerDirectory


def _request_need_contract() -> dict:
    return {
        "schema_version": "request_need_contract.v1",
        "request_id": "R01",
        "request_objective": "评估当前组合风险",
        "request_target": {"portfolio": "current"},
        "requirement_contract_version": "need-requirement.v2",
        "needs": [{
            "need_id": "N01",
            "request_id": "R01",
            "kind": "business",
            "description": "分析组合风险",
            "required": True,
            "requirements": [{
                "requirement_id": "N01-R01",
                "semantic_key": "portfolio_risk",
                "direction": "output",
                "kind": "data",
                "semantic_role": "组合风险、集中度与约束分析结果",
                "source_policy": "system",
                "satisfaction_rule": "exists",
                "required": True,
                "required_paths": [],
                "data_name": "risk",
            }],
        }],
        "constraints": [],
        "effect_limit": "read",
    }


def _calls(risk_data_name: str) -> list[dict]:
    return [{
        "call_id": "WC01",
        "worker_id": "W04",
        "objective": "分析组合集中度与风险暴露",
        "covers_need_ids": ["N01"],
        "desired_output_data_names": list(dict.fromkeys(["risk", risk_data_name])),
    }]


class _CaptureLLM:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.messages = None
        self.repair_guidance = ""

    def generate_json(self, **kwargs):
        self.messages = kwargs["messages"]
        self.repair_guidance = kwargs.get("repair_guidance", "")
        kwargs["validator"](self.payload)
        return self.payload


def test_worker_synthesized_data_namespace_uses_current_exact_patterns() -> None:
    planner = CoordinatorPlanner(CapabilityWorkerDirectory(), llm_service=_CaptureLLM({}))
    descriptions = planner.worker_catalog.descriptions(effect_limit="read")
    w04 = next(row for row in descriptions if row["worker_id"] == "W04")

    assert "risk" in w04["output_data_examples"]
    assert "risk_constraints" in w04["output_data_examples"]
    assert planner._worker_supports_output(w04, "risk") is True
    assert planner._worker_supports_output(w04, "risk_constraints") is True
    assert planner._worker_supports_output(w04, "risk.concentration") is False
    assert planner._worker_supports_output(w04, "concentration_risk_fragment") is False


def test_worker_selection_prompt_treats_patterns_as_hard_namespace_contract() -> None:
    llm = _CaptureLLM({
        "worker_calls": _calls("risk"),
        "selection_reason": "W04负责风险分析。",
    })
    planner = CoordinatorPlanner(CapabilityWorkerDirectory(), llm_service=llm)
    descriptions = planner.worker_catalog.descriptions(effect_limit="read")

    result = planner._select_worker_calls(
        request_need_contract=_request_need_contract(),
        worker_descriptions=descriptions,
        effect_limit="read",
        run_id="r",
        initial_context_names=set(),
    )

    system_prompt = llm.messages[0]["content"]
    assert "produced_data_patterns是硬命名合同" in system_prompt
    assert "concentration_risk_fragment" in system_prompt
    assert "不得把它作为返回包装层" in system_prompt
    assert "worker_call_output_outside_worker" in llm.repair_guidance
    assert result["worker_calls"][0]["desired_output_data_names"][-1] == "risk"


def test_shape_example_echo_is_structurally_lifted_without_spending_repair_on_wrapper() -> None:
    payload = {
        "required_output_shape": {
            "worker_calls": _calls("risk_constraints"),
            "selection_reason": "W04负责风险分析。",
        }
    }
    llm = _CaptureLLM(payload)
    planner = CoordinatorPlanner(CapabilityWorkerDirectory(), llm_service=llm)
    descriptions = planner.worker_catalog.descriptions(effect_limit="read")

    result = planner._select_worker_calls(
        request_need_contract=_request_need_contract(),
        worker_descriptions=descriptions,
        effect_limit="read",
        run_id="r",
        initial_context_names=set(),
    )

    assert payload["worker_calls"] == payload["required_output_shape"]["worker_calls"]
    assert result["selection_reason"] == "W04负责风险分析。"
    assert result["worker_calls"][0]["desired_output_data_names"][-1] == "risk_constraints"


def test_invalid_dynamic_data_name_surfaces_exact_worker_patterns_for_targeted_repair() -> None:
    class _InvalidLLM:
        def __init__(self) -> None:
            self.error = None

        def generate_json(self, **kwargs):
            payload = {
                "required_output_shape": {
                    "worker_calls": _calls("concentration_risk_fragment"),
                    "selection_reason": "W04负责风险分析。",
                }
            }
            try:
                kwargs["validator"](payload)
            except WorkerContractViolation as exc:
                self.error = exc
                raise
            raise AssertionError("invalid payload unexpectedly passed")

    llm = _InvalidLLM()
    planner = CoordinatorPlanner(CapabilityWorkerDirectory(), llm_service=llm)
    descriptions = planner.worker_catalog.descriptions(effect_limit="read")

    with pytest.raises(WorkerContractViolation) as caught:
        planner._select_worker_calls(
            request_need_contract=_request_need_contract(),
            worker_descriptions=descriptions,
            effect_limit="read",
            run_id="r",
            initial_context_names=set(),
        )

    assert caught.value.code == "worker_call_output_outside_worker"
    detail = json.loads(caught.value.detail)
    assert detail["worker_id"] == "W04"
    assert detail["invalid_data_names"] == ["concentration_risk_fragment"]
    assert "risk" in detail["produced_data_patterns"]
    assert "risk_constraints" in detail["produced_data_patterns"]
    assert "resolved_context" in detail["produced_data_patterns"]
    assert "risk" in detail["output_data_examples"]
    assert detail["output_publication_mode"] == "worker_synthesized"
    assert "literally matches" in detail["repair_rule"]


def test_private_tool_passthrough_contract_remains_closed_to_discoverable_tool_outputs() -> None:
    class _ToolDirectory:
        def semantic_output_slots(self, worker_role, *, tool_names=None):
            del tool_names
            if worker_role == "PORTFOLIO_ANALYST":
                return ["portfolio", "positions", "user_constraints"]
            return []

    planner = CoordinatorPlanner(
        CapabilityWorkerDirectory(),
        llm_service=_CaptureLLM({}),
        worker_tool_directory=_ToolDirectory(),
    )
    descriptions = planner.worker_catalog.descriptions(effect_limit="read")
    w02 = next(row for row in descriptions if row["worker_id"] == "W02")

    assert w02["output_publication_mode"] == "private_tool_passthrough"
    assert planner._worker_supports_output(w02, "positions") is True
    assert planner._worker_supports_output(w02, "portfolio.synthetic_new_fact") is False
