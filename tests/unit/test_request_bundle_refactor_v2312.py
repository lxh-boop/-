from __future__ import annotations

import pytest

from agent.collaboration.context_binding import ContextBinding, EntityScope, ReferenceEntityType
from agent.collaboration.presentation_policy import PresentationPolicy, PresentationPolicyResolver, PresentationValidator
from agent.collaboration.request_bundle import (
    PresentationRequest,
    RequestBundle,
    RequestBundleError,
    RequestBundleValidator,
    RequestCategory,
    RequestDecomposer,
    RequestItem,
    RequestStatus,
    RequestType,
    deterministic_structure_parse,
)


class _QueueLLM:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def generate_json(self, **kwargs):
        self.calls.append({"stage": kwargs.get("stage"), "operation": kwargs.get("operation")})
        assert self.payloads, "unexpected LLM call"
        payload = self.payloads.pop(0)
        kwargs["validator"](payload)
        return payload


def _binding(scope="none", inherit=False, ref_type="none"):
    return {
        "entity_scope": scope,
        "inherit_previous_focus": inherit,
        "reference_entity_type": ref_type,
        "reason": "test",
    }


def _business(
    source_index: int,
    objective: str,
    *,
    target=None,
    constraints=None,
    depends_on=None,
    request_type="read",
    proposal_required=False,
    action_type="",
    status="pending",
    reason="",
    binding=None,
):
    return {
        "source_index": source_index,
        "category": "business",
        "objective": objective,
        "request_type": request_type,
        "proposal_required": proposal_required,
        "target": dict(target or {}),
        "constraints": list(constraints or []),
        "depends_on": list(depends_on or []),
        "scope": "current_turn",
        "status": status,
        "reason": reason,
        "action_type": action_type,
        "presentation": {},
        "context_binding": binding or _binding(),
    }


def test_deterministic_structure_parser_preserves_explicit_numbering() -> None:
    rows = deterministic_structure_parse("1. 分析贵州茅台\n2. 分析五粮液\n3. 比较两只")
    assert [row["source_index"] for row in rows] == [1, 2, 3]
    assert [row["text"] for row in rows] == ["分析贵州茅台", "分析五粮液", "比较两只"]
    assert all(row["boundary_source"] == "explicit_number" for row in rows)


def test_request_decomposer_supports_repeated_business_dependency_and_presentation() -> None:
    llm = _QueueLLM([{
        "requests": [
            _business(1, "分析目标股票", target={"security_name": "贵州茅台"}, binding=_binding("explicit_entities", False, "security")),
            _business(2, "分析目标股票", target={"security_name": "五粮液"}, binding=_binding("explicit_entities", False, "security")),
            _business(3, "比较两只目标股票", depends_on=[1, 2], binding=_binding("explicit_entities", False, "security")),
            {
                "source_index": 4,
                "category": "presentation",
                "objective": "用英文简洁回答",
                "request_type": "read",
                "proposal_required": False,
                "target": {},
                "constraints": [],
                "depends_on": [],
                "scope": "whole_bundle",
                "status": "pending",
                "reason": "",
                "action_type": "",
                "presentation": {
                    "language": "en",
                    "style": "concise",
                    "length": "short",
                    "format": "bullet_list",
                    "scope": "whole_bundle",
                    "persist": False,
                },
                "context_binding": _binding(),
            },
        ]
    }])
    bundle = RequestDecomposer(llm_service=llm).decompose(
        query="1. 分析贵州茅台\n2. 分析五粮液\n3. 比较两只\n4. 用英文简洁回答",
        memory_summary="",
        execution_context={},
        language="zh",
        run_id="run-v2312",
    )

    assert [item.request_id for item in bundle.requests] == ["R01", "R02", "R03", "R04"]
    assert [item.category for item in bundle.requests] == [
        RequestCategory.BUSINESS,
        RequestCategory.BUSINESS,
        RequestCategory.BUSINESS,
        RequestCategory.PRESENTATION,
    ]
    assert all(item.request_type == RequestType.READ for item in bundle.business_requests())
    assert bundle.requests[2].depends_on == ["R01", "R02"]
    assert bundle.requests[3].presentation is not None
    assert bundle.requests[3].presentation.language == "en"
    assert llm.calls == [{"stage": "request_bundle_decomposition", "operation": "request_bundle_decompose"}]


def test_explicit_numbered_request_keeps_normalized_objective_instead_of_raw_segment() -> None:
    llm = _QueueLLM([{
        "requests": [
            _business(
                1,
                "评估用户当前投资组合风险",
                target={"portfolio": "current"},
                binding=_binding("portfolio", False, "portfolio"),
            )
        ]
    }])
    bundle = RequestDecomposer(llm_service=llm).decompose(
        query="1. 我感觉我现在仓位有点危险，你帮我看看。",
        memory_summary="",
        execution_context={},
        language="zh",
        run_id="r",
    )
    assert bundle.requests[0].source_index == 1
    assert bundle.requests[0].objective == "评估用户当前投资组合风险"
    assert bundle.requests[0].objective != "我感觉我现在仓位有点危险，你帮我看看。"
    assert len(llm.calls) == 1


def test_objective_target_constraints_are_kept_separate() -> None:
    llm = _QueueLLM([{
        "requests": [
            _business(
                1,
                "分析目标股票风险",
                target={"security_name": "贵州茅台"},
                constraints=["时间范围=最近一个月"],
                binding=_binding("explicit_entities", False, "security"),
            )
        ]
    }])
    bundle = RequestDecomposer(llm_service=llm).decompose(
        query="分析贵州茅台最近一个月的风险，只看最近一个月。",
        memory_summary="",
        execution_context={},
        language="zh",
        run_id="r",
    )
    request = bundle.requests[0]
    assert request.objective == "分析目标股票风险"
    assert request.target == {"security_name": "贵州茅台"}
    assert request.constraints == ["时间范围=最近一个月"]
    assert "贵州茅台" not in request.objective
    assert "最近一个月" not in request.objective


def test_request_decomposer_rejects_need_worker_or_tool_planning_fields() -> None:
    row = _business(1, "分析目标股票", binding=_binding("explicit_entities", False, "security"))
    row["needs"] = [{"description": "不应在这里生成"}]
    llm = _QueueLLM([{"requests": [row]}])
    with pytest.raises(RequestBundleError, match="request_decomposer_planning_fields_forbidden"):
        RequestDecomposer(llm_service=llm).decompose(
            query="分析贵州茅台", memory_summary="", execution_context={}, language="zh", run_id="r"
        )


def test_partial_unsupported_is_request_status_not_bundle_category() -> None:
    llm = _QueueLLM([{
        "requests": [
            _business(1, "分析目标股票", target={"security_name": "贵州茅台"}, binding=_binding("explicit_entities", False, "security")),
            _business(2, "预订机票", status="unsupported", reason="no_matching_capability"),
        ]
    }])
    bundle = RequestDecomposer(llm_service=llm).decompose(
        query="分析贵州茅台，并帮我订机票",
        memory_summary="", execution_context={}, language="zh", run_id="r",
    )
    assert bundle.requests[0].status == RequestStatus.PENDING
    assert bundle.requests[1].status == RequestStatus.UNSUPPORTED
    assert bundle.requests[1].category == RequestCategory.BUSINESS
    assert bundle.requests[1].status_reason == "no_matching_capability"


def test_confirmation_protocol_relation_forces_deterministic_write_without_mainagent_semantics() -> None:
    llm = _QueueLLM([{
        "requests": [
            _business(1, "确认并执行已有待审批方案"),
        ]
    }])
    bundle = RequestDecomposer(llm_service=llm).decompose(
        query="确认执行刚才方案",
        memory_summary="",
        execution_context={"conversation_state": {"relation_type": "confirmation"}},
        language="zh", run_id="r",
    )
    request = bundle.requests[0]
    assert request.request_type == RequestType.WRITE
    assert request.action_type == "confirm_execute"
    assert request.proposal_required is False


def test_cancellation_and_analysis_can_coexist_as_separate_requests() -> None:
    llm = _QueueLLM([{
        "requests": [
            _business(1, "取消已有待审批方案"),
            _business(2, "分析目标股票", target={"security_name": "贵州茅台"}, binding=_binding("explicit_entities", False, "security")),
        ]
    }])
    bundle = RequestDecomposer(llm_service=llm).decompose(
        query="取消刚才方案，然后分析贵州茅台",
        memory_summary="",
        execution_context={"conversation_state": {"relation_type": "cancellation"}},
        language="zh", run_id="r",
    )
    assert bundle.requests[0].request_type == RequestType.WRITE
    assert bundle.requests[0].action_type == "cancel"
    assert bundle.requests[1].request_type == RequestType.READ
    assert bundle.requests[1].action_type == ""


def test_request_dependency_cycle_is_rejected() -> None:
    bundle = RequestBundle(
        raw_message="cycle",
        requests=[
            RequestItem("R01", 1, RequestCategory.BUSINESS, "A", depends_on=["R02"]),
            RequestItem("R02", 2, RequestCategory.BUSINESS, "B", depends_on=["R01"]),
        ],
    )
    with pytest.raises(RequestBundleError, match="request_dependency_cycle"):
        RequestBundleValidator().validate(bundle)


def test_presentation_policy_later_global_request_wins_and_session_is_baseline() -> None:
    bundle = RequestBundle(
        raw_message="",
        requests=[
            RequestItem(
                "R01", 1, RequestCategory.PRESENTATION, "中文",
                presentation=PresentationRequest(language="zh", scope="current_turn"),
            ),
            RequestItem(
                "R02", 2, RequestCategory.PRESENTATION, "改成英文",
                presentation=PresentationRequest(language="en", style="concise", scope="whole_bundle"),
            ),
        ],
    )
    policy = PresentationPolicyResolver().resolve(
        bundle=bundle,
        session_preference={"language": "zh", "format": "table"},
        system_language="zh",
    )
    assert policy.language == "en"
    assert policy.style == "concise"
    assert policy.format == "table"
    assert policy.source_request_ids == ["R01", "R02"]


def test_request_scoped_presentation_does_not_mutate_global_policy() -> None:
    bundle = RequestBundle(
        raw_message="",
        requests=[
            RequestItem("R01", 1, RequestCategory.BUSINESS, "分析目标股票"),
            RequestItem(
                "R02", 2, RequestCategory.PRESENTATION, "R01用英文",
                target={"request_id": "R01"},
                presentation=PresentationRequest(language="en", format="bullet_list", scope="request"),
            ),
        ],
    )
    policy = PresentationPolicyResolver().resolve(
        bundle=bundle, session_preference={"language": "zh"}, system_language="zh"
    )
    assert policy.language == "zh"
    assert policy.for_request("R01")["language"] == "en"
    assert policy.for_request("R01")["format"] == "bullet_list"
    assert policy.request_overrides["R01"]["language"] == "en"


def test_presentation_validator_checks_language_length_and_format() -> None:
    validator = PresentationValidator()
    policy = PresentationPolicy(language="en", length="80", format="bullet_list")
    ok = validator.validate("- Revenue improved\n- Risk remains elevated", policy)
    bad = validator.validate("这是一个很长的中文回答，不符合英文与分点要求。" * 10, policy)
    assert ok.valid is True
    assert bad.valid is False
    assert "language_not_english" in bad.violations
    assert "length_exceeded" in bad.violations
    assert "format_not_bullet_list" in bad.violations


def test_session_presentation_update_survives_later_current_turn_override() -> None:
    bundle = RequestBundle(
        raw_message="",
        requests=[
            RequestItem(
                "R01", 1, RequestCategory.PRESENTATION, "以后都用英文",
                presentation=PresentationRequest(language="en", scope="session", persist=True),
            ),
            RequestItem(
                "R02", 2, RequestCategory.PRESENTATION, "但这次用中文",
                presentation=PresentationRequest(language="zh", scope="current_turn", persist=False),
            ),
        ],
    )
    policy = PresentationPolicyResolver().resolve(
        bundle=bundle, session_preference={"language": "zh", "format": "table"}, system_language="zh"
    )
    assert policy.language == "zh"
    assert policy.session_update == {"language": "en"}
    assert policy.format == "table"


def test_request_scoped_presentation_target_indexes_are_normalized_without_dependency_edge() -> None:
    llm = _QueueLLM([{
        "requests": [
            _business(1, "分析目标股票", target={"security_name": "贵州茅台"}, binding=_binding("explicit_entities", False, "security")),
            {
                "source_index": 2,
                "category": "presentation",
                "objective": "第一项用英文",
                "request_type": "read",
                "proposal_required": False,
                "target": {"request_indexes": [1]},
                "constraints": [],
                "depends_on": [],
                "scope": "request",
                "status": "pending",
                "reason": "",
                "action_type": "",
                "presentation": {
                    "language": "en", "style": "", "length": "", "format": "",
                    "scope": "request", "persist": False,
                },
                "context_binding": _binding(),
            },
        ]
    }])
    bundle = RequestDecomposer(llm_service=llm).decompose(
        query="分析贵州茅台，第一项用英文", memory_summary="", execution_context={}, language="zh", run_id="r"
    )
    presentation = bundle.requests[1]
    assert presentation.target["request_ids"] == ["R01"]
    assert presentation.depends_on == []


def test_conversation_focus_binding_can_request_proposal_without_write_permission() -> None:
    item = RequestItem(
        "R01", 1, RequestCategory.BUSINESS, "生成把上一只股票加入持仓的待审批方案",
        request_type=RequestType.READ,
        proposal_required=True,
        context_binding=ContextBinding(
            entity_scope=EntityScope.CONVERSATION_FOCUS,
            inherit_previous_focus=True,
            reference_entity_type=ReferenceEntityType.SECURITY,
            reason="刚刚那只股票",
        ),
    )
    RequestBundleValidator().validate(RequestBundle(raw_message=item.objective, requests=[item]))
    assert item.request_type == RequestType.READ
    assert item.proposal_required is True
    assert item.context_binding.reference_entity_type == ReferenceEntityType.SECURITY
    assert item.context_binding.inherit_previous_focus is True
