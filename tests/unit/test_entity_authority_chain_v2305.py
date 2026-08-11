from __future__ import annotations

from agent.collaboration.coordinator import (
    _has_forward_replan_context_blocker,
    _planning_memory_summary,
)
from agent.collaboration.worker_directory import CapabilityWorkerDirectory


def test_portfolio_request_without_focus_inheritance_hides_session_entity_from_business_planner() -> None:
    summary = _planning_memory_summary(
        session_summary="上一轮分析了贵州茅台，并形成了实体分析。",
        long_term_memory_summary="",
        inherit_previous_focus=False,
    )
    assert summary == ""


def test_conversation_focus_inheritance_keeps_session_summary_for_business_planner() -> None:
    summary = _planning_memory_summary(
        session_summary="上一轮分析了贵州茅台，并形成了实体分析。",
        long_term_memory_summary="",
        inherit_previous_focus=True,
    )
    assert "贵州茅台" in summary


def test_long_term_memory_remains_available_without_previous_focus_inheritance() -> None:
    summary = _planning_memory_summary(
        session_summary="上一轮分析了贵州茅台。",
        long_term_memory_summary="用户风险偏好为稳健型。",
        inherit_previous_focus=False,
    )
    assert "贵州茅台" not in summary
    assert "稳健型" in summary


def test_worker_context_unresolved_blocks_business_worker_forward_replan() -> None:
    observations = [
        {"task_id": "T01", "failure_kind": "none"},
        {"task_id": "T02", "failure_kind": "worker_context_unresolved"},
        {"task_id": "T03", "failure_kind": "upstream_worker_failed"},
    ]
    assert _has_forward_replan_context_blocker(observations) is True


def test_regular_worker_failure_still_allows_forward_replan() -> None:
    observations = [
        {"task_id": "T01", "failure_kind": "none"},
        {"task_id": "T02", "failure_kind": "tool_execution_failure"},
    ]
    assert _has_forward_replan_context_blocker(observations) is False


def test_w02_ranking_resolution_is_only_for_discovery_not_named_entity_substitution() -> None:
    prompt = CapabilityWorkerDirectory().get("W02").private_worker_prompt
    assert "排名、筛选或发现候选证券" in prompt
    assert "绝不能用排名第一或其他候选证券替代目标" in prompt
    assert "internal.entity.resolve_ranked_security" in prompt


def test_coordinator_does_not_pass_previous_session_entity_to_planner_when_entry_rejects_focus_inheritance(tmp_path) -> None:
    import types
    import pytest

    from agent.collaboration.coordinator import AgentCollaborationCoordinator
    from agent.collaboration.entry_decision import ContextBinding, EntityScope, EntryDecision, RequestMode
    from agent.context.context_hydrator import HydratedContext

    class FakeSessionState:
        def build_summary(self, session_id, limit=40):
            del session_id, limit
            return "上一轮分析了贵州茅台。"

        def put(self, **kwargs):
            del kwargs

    class FakeEntry:
        def decide(self, **kwargs):
            del kwargs
            return EntryDecision(
                mode=RequestMode.PROPOSAL,
                reason="完整组合调整",
                confidence=1.0,
                context_binding=ContextBinding(
                    entity_scope=EntityScope.PORTFOLIO,
                    inherit_previous_focus=False,
                    reason="完整组合任务不继承上一轮单一证券",
                ),
            )

    class FakeHydrator:
        def hydrate(self, **kwargs):
            del kwargs
            return HydratedContext(
                user_id="u",
                session_id="s",
                session_summary="上一轮分析了贵州茅台。",
                previous_focus_refs=[],
                pending_run_ids=[],
                pending_proposal_ids=[],
                permission_context={},
                available_parameters={},
                long_term_memory_summary="",
                long_term_memory_refs=[],
                source_audit=[{"slot_id": "session_summary", "source": "session_state"}],
            )

    class FakeCheckpoints:
        def save(self, checkpoint):
            del checkpoint

    class CapturePlanner:
        def __init__(self):
            self.memory_summary = None
            self.context_binding = None

        def plan(self, **kwargs):
            self.memory_summary = kwargs["memory_summary"]
            self.context_binding = kwargs.get("context_binding")
            raise RuntimeError("stop_after_memory_capture")

    coordinator = AgentCollaborationCoordinator.__new__(AgentCollaborationCoordinator)
    coordinator.output_dir = tmp_path
    coordinator.db_path = None
    coordinator.runtime_services = None
    coordinator.session_state = FakeSessionState()
    coordinator.entry = FakeEntry()
    coordinator.context_hydrator = FakeHydrator()
    coordinator.checkpoints = FakeCheckpoints()
    coordinator.planner = CapturePlanner()
    coordinator._resolve_request_refs = types.MethodType(
        lambda self, **kwargs: ([], [], {"mentions": [], "items": [], "context_binding": kwargs.get("context_binding") or {}}),
        coordinator,
    )

    with pytest.raises(RuntimeError, match="stop_after_memory_capture"):
        coordinator.execute(
            query="你觉得我的持仓应该怎么调整？",
            decomposition={},
            user_id="u",
            default_top_k=10,
            session_id="s",
            run_id="r",
            language="zh",
            execution_context={},
        )

    assert coordinator.planner.memory_summary == ""
    assert coordinator.planner.context_binding["entity_scope"] == "portfolio"
    assert coordinator.planner.context_binding["inherit_previous_focus"] is False


def test_canonical_intent_prompt_receives_authoritative_portfolio_scope_without_historical_entity() -> None:
    import json

    from agent.collaboration.planner import CoordinatorPlanner

    class CaptureLLM:
        def __init__(self):
            self.messages = None

        def generate_json(self, **kwargs):
            self.messages = kwargs["messages"]
            payload = {
                "intent_summary": "用户希望基于当前整个持仓获得组合调整建议。",
                "needs": [
                    {"description": "获取当前组合、持仓、账户和用户约束。", "required": True},
                    {"description": "分析当前组合的集中度、暴露和风险约束。", "required": True},
                    {"description": "基于组合事实和风险分析形成持仓调整建议。", "required": True},
                ],
                "constraints": [],
                "scope_note": "当前整个投资组合。",
                "effect_limit": "proposal",
            }
            kwargs["validator"](payload)
            return payload

    llm = CaptureLLM()
    planner = CoordinatorPlanner(CapabilityWorkerDirectory(), llm_service=llm)
    initial_slots = planner._initial_slots(focus_refs=[], context_refs=[], memory_summary="")
    result = planner._plan_intent_contract(
        query="你觉得我的持仓应该怎么调整？",
        request_mode="proposal",
        run_id="r",
        language="zh",
        initial_slots=initial_slots,
        memory_summary="",
        context_binding={
            "entity_scope": "portfolio",
            "inherit_previous_focus": False,
            "reason": "完整组合任务不继承上一轮单一证券",
        },
    )

    user_payload = json.loads(llm.messages[1]["content"])
    assert user_payload["context_binding"]["entity_scope"] == "portfolio"
    assert user_payload["context_binding"]["inherit_previous_focus"] is False
    assert user_payload["authoritative_entity_refs_available"] is False
    assert user_payload["session_summary"] == ""
    assert "贵州茅台" not in json.dumps(user_payload, ensure_ascii=False)
    assert "组合" in result["intent_summary"]
    assert "贵州茅台" not in json.dumps(result, ensure_ascii=False)
