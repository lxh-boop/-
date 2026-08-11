from __future__ import annotations

import json

import pytest

from agent.collaboration.planner import CoordinatorPlanner
from agent.collaboration.worker_contracts import WorkerContractViolation
from agent.collaboration.worker_directory import CapabilityWorkerDirectory


def _intent() -> dict:
    return {
        "schema_version": "canonical_intent_contract.v1",
        "intent_summary": "分析当前组合风险并形成用户可读结果。",
        "needs": [
            {"need_id": "N01", "kind": "business", "description": "分析组合风险", "required": True},
            {"need_id": "N_FINAL", "kind": "presentation", "description": "生成用户回答", "required": True},
        ],
        "constraints": [],
        "scope_note": "当前组合",
        "effect_limit": "read",
        "requires_user_facing_response": True,
    }


def _calls(risk_slot: str) -> list[dict]:
    return [
        {
            "call_id": "WC01",
            "worker_id": "W04",
            "objective": "分析组合集中度与风险暴露",
            "covers_need_ids": ["N01"],
            "desired_output_slots": ["portfolio_risk_result", risk_slot],
        },
        {
            "call_id": "WC02",
            "worker_id": "W06",
            "objective": "生成用户可读结果",
            "covers_need_ids": ["N_FINAL"],
            "desired_output_slots": ["user_facing_report"],
        },
    ]


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


def test_worker_synthesized_slot_namespace_stays_open_but_pattern_bounded() -> None:
    planner = CoordinatorPlanner(CapabilityWorkerDirectory(), llm_service=_CaptureLLM({}))
    descriptions = planner.worker_catalog.descriptions(request_mode="analysis")
    w04 = next(row for row in descriptions if row["worker_id"] == "W04")

    # 开放 Slot 设计保留：未预注册的新风险 Key 只要落在 risk.* 命名空间就合法。
    assert "risk.concentration" not in w04["output_slot_examples"]
    assert planner._worker_supports_output(w04, "risk.concentration") is True
    assert planner._worker_supports_output(w04, "risk.liquidity") is True

    # 语义合理但命名不满足 produced_output_patterns 的自由 Key 仍必须拒绝。
    assert planner._worker_supports_output(w04, "concentration_risk_fragment") is False


def test_worker_selection_prompt_treats_patterns_as_hard_namespace_contract() -> None:
    llm = _CaptureLLM({
        "worker_calls": _calls("risk.concentration"),
        "selection_reason": "W04负责风险，W06负责最终表达。",
    })
    planner = CoordinatorPlanner(CapabilityWorkerDirectory(), llm_service=llm)
    descriptions = planner.worker_catalog.descriptions(request_mode="analysis")

    result = planner._select_worker_calls(
        intent_contract=_intent(),
        worker_descriptions=descriptions,
        request_mode="analysis",
        run_id="r",
        initial_slots=set(),
    )

    system_prompt = llm.messages[0]["content"]
    assert "produced_output_patterns是硬命名合同" in system_prompt
    assert "risk.*只能生成risk.xxx" in system_prompt
    assert "concentration_risk_fragment" in system_prompt
    assert "不得把它作为返回包装层" in system_prompt
    assert "worker_call_output_outside_worker" in llm.repair_guidance
    assert result["worker_calls"][0]["desired_output_slots"][-1] == "risk.concentration"


def test_shape_example_echo_is_structurally_lifted_without_spending_repair_on_wrapper() -> None:
    payload = {
        "required_output_shape": {
            "worker_calls": _calls("risk.exposure"),
            "selection_reason": "W04负责风险，W06负责最终表达。",
        }
    }
    llm = _CaptureLLM(payload)
    planner = CoordinatorPlanner(CapabilityWorkerDirectory(), llm_service=llm)
    descriptions = planner.worker_catalog.descriptions(request_mode="analysis")

    result = planner._select_worker_calls(
        intent_contract=_intent(),
        worker_descriptions=descriptions,
        request_mode="analysis",
        run_id="r",
        initial_slots=set(),
    )

    # 只做结构抬升，不改变任何 Worker/Slot 语义。
    assert payload["worker_calls"] == payload["required_output_shape"]["worker_calls"]
    assert result["selection_reason"] == "W04负责风险，W06负责最终表达。"
    assert result["worker_calls"][0]["desired_output_slots"][-1] == "risk.exposure"


def test_invalid_dynamic_slot_surfaces_exact_worker_patterns_for_targeted_repair() -> None:
    class _InvalidLLM:
        def __init__(self) -> None:
            self.error = None

        def generate_json(self, **kwargs):
            payload = {
                # 模拟真实日志：模型把格式示例回显成包装层，同时还生成了非法 Slot 名。
                "required_output_shape": {
                    "worker_calls": _calls("concentration_risk_fragment"),
                    "selection_reason": "W04负责风险，W06负责最终表达。",
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
    descriptions = planner.worker_catalog.descriptions(request_mode="analysis")

    with pytest.raises(WorkerContractViolation) as caught:
        planner._select_worker_calls(
            intent_contract=_intent(),
            worker_descriptions=descriptions,
            request_mode="analysis",
            run_id="r",
            initial_slots=set(),
        )

    # 结构包装层先被程序确定性抬升，因此首个真正错误直接是 Slot Pattern，而不是 worker_calls_required。
    assert caught.value.code == "worker_call_output_outside_worker"
    detail = json.loads(caught.value.detail)
    assert detail["worker_id"] == "W04"
    assert detail["invalid_slots"] == ["concentration_risk_fragment"]
    assert "risk.*" in detail["produced_output_patterns"]
    assert "analysis.risk*" in detail["produced_output_patterns"]
    assert "portfolio_risk_result" in detail["output_slot_examples"]
    assert detail["output_publication_mode"] == "worker_synthesized"
    assert "literally matches" in detail["repair_rule"]


def test_private_tool_passthrough_contract_remains_closed_to_discoverable_tool_outputs() -> None:
    class _ToolDirectory:
        def semantic_output_slots(self, worker_role, *, tool_names=None):
            del tool_names
            if worker_role == "PORTFOLIO_ANALYST":
                return ["portfolio_positions", "user_constraints"]
            return []

    planner = CoordinatorPlanner(
        CapabilityWorkerDirectory(),
        llm_service=_CaptureLLM({}),
        worker_tool_directory=_ToolDirectory(),
    )
    descriptions = planner.worker_catalog.descriptions(request_mode="analysis")
    w02 = next(row for row in descriptions if row["worker_id"] == "W02")

    assert w02["output_publication_mode"] == "private_tool_passthrough"
    assert planner._worker_supports_output(w02, "portfolio_positions") is True
    # 即使命名可能匹配Worker聚合Pattern，passthrough仍不能凭空合成Tool没有声明的输出。
    assert planner._worker_supports_output(w02, "portfolio.synthetic_new_fact") is False
