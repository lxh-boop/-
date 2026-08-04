from __future__ import annotations

import copy
import inspect
import json

from agent.collaboration.agent_directory import AgentDirectory
from agent.collaboration.coordinator import AgentCollaborationCoordinator
from agent.collaboration.entry_decision import MainEntryDecisionPlanner
from agent.collaboration.planner import PLAN_SCHEMA, CoordinatorPlanner
from agent.collaboration.workers import entity_analysis, report_writer
from agent.tool_dag.planner import WorkerToolDagPlanner
from core.llm.prompt_compaction import catalog_for_prompt, compact_json_dumps, schema_for_prompt


class _MentionLLM:
    def __init__(self, mentions: list[dict] | None = None) -> None:
        self.mentions = list(mentions or [])
        self.request: dict = {}

    def generate_json(self, **kwargs):
        self.request = json.loads(kwargs["messages"][1]["content"])
        payload = {"mentions": list(self.mentions)}
        kwargs["validator"](payload)
        return payload


class _IdentityHints:
    def extract_candidate_mentions(self, query: str):
        if "贵州茅台" in query:
            return ["贵州茅台"]
        return ["我的持仓"]



def test_schema_prompt_view_does_not_mutate_runtime_schema() -> None:
    original = copy.deepcopy(PLAN_SCHEMA)
    prompt_view = schema_for_prompt(PLAN_SCHEMA)

    assert PLAN_SCHEMA == original
    assert prompt_view is not PLAN_SCHEMA
    assert prompt_view["properties"]["goal_contract"]["properties"]["access_mode"]["type"] == "string"
    assert prompt_view["properties"]["goal_contract"]["properties"]["access_mode"]["enum"] == ["read", "write"]
    assert "description" not in prompt_view["properties"]["goal_contract"]["properties"]["access_mode"]
    assert "readOnly" not in prompt_view["properties"]["goal_contract"]["properties"]["access_mode"]
    assert PLAN_SCHEMA["properties"]["goal_contract"]["properties"]["access_mode"]["readOnly"] is True



def test_catalog_prompt_view_preserves_contract_semantics() -> None:
    directory = AgentDirectory()
    full = directory.planning_catalog()
    compact = catalog_for_prompt(full)

    assert len(compact) == len(full)
    for before_worker, after_worker in zip(full, compact):
        assert before_worker["worker_id"] == after_worker["worker_id"]
        assert before_worker["agent_id"] == after_worker["agent_id"]
        assert before_worker["access_mode"] == after_worker["access_mode"]
        assert len(before_worker["task_contracts"]) == len(after_worker["task_contracts"])
        for before_task, after_task in zip(before_worker["task_contracts"], after_worker["task_contracts"]):
            for key in (
                "task_type",
                "output_type",
                "completion_criteria",
                "consumes_information_slots",
                "produces_information_slots",
                "required_context_slots",
                "coverage_semantics",
                "freshness_semantics",
                "authority_level",
                "allowed_request_modes",
                "access_mode",
            ):
                assert before_task[key] == after_task[key]



def test_prompt_compaction_changes_no_worker_completion_contract() -> None:
    directory = AgentDirectory()
    card = directory.get("W01")
    contract = card.task_contract("collect_external_evidence")
    before = copy.deepcopy(contract.safe_for_coordinator())

    _ = catalog_for_prompt(directory.planning_catalog())
    _ = schema_for_prompt(PLAN_SCHEMA)

    after = contract.safe_for_coordinator()
    assert after == before
    assert after["completion_criteria"] == before["completion_criteria"]
    assert after["output_type"] == "EvidenceCollectionResult"



def test_portfolio_scope_mentions_remain_llm_owned() -> None:
    llm = _MentionLLM([])
    coordinator = AgentCollaborationCoordinator.__new__(AgentCollaborationCoordinator)
    coordinator.llm_service = llm
    coordinator.identity = _IdentityHints()

    mentions = coordinator._extract_mentions(
        "你认为我的持仓应该怎么调整？",
        "zh",
        {"entity_scope": "portfolio", "inherit_previous_focus": False},
    )

    assert mentions == []
    assert llm.request["context_binding"]["entity_scope"] == "portfolio"
    assert llm.request["lexical_candidates"] == ["我的持仓"]



def test_explicit_security_mention_can_still_be_returned_by_llm() -> None:
    llm = _MentionLLM([{"text": "贵州茅台", "role": "focus"}])
    coordinator = AgentCollaborationCoordinator.__new__(AgentCollaborationCoordinator)
    coordinator.llm_service = llm
    coordinator.identity = _IdentityHints()

    mentions = coordinator._extract_mentions(
        "分析贵州茅台",
        "zh",
        {"entity_scope": "explicit_entities", "inherit_previous_focus": False},
    )

    assert mentions == [{"text": "贵州茅台", "role": "focus"}]
    assert llm.request["lexical_candidates"] == ["贵州茅台"]



def test_report_prompt_view_preserves_all_positions_and_account_metrics() -> None:
    positions = []
    catalog = []
    for index in range(10):
        code = f"{index + 1:06d}"
        catalog.append({
            "entity_ref": {"node_id": f"cn:security:sse:{code}", "metadata": "x" * 1000},
            "public_code": code,
            "display_label": f"Security {index}",
            "exchange": "SSE",
            "identity_source": "graph_identity",
            "identity_locked": True,
        })
        positions.append({
            "entity_ref": {"node_id": f"cn:security:sse:{code}", "metadata": "y" * 1000},
            "public_code": code,
            "display_label": f"Security {index}",
            "exchange": "SSE",
            "quantity": 100 + index,
            "cost_price": 10.0 + index,
            "current_price": 11.0 + index,
            "market_value": 1100.0 + index,
            "position_ratio": 0.05,
            "unrealized_pnl": 100.0,
            "updated_at": "2026-08-03",
        })
    portfolio_payload = {
        "entity_catalog": catalog,
        "display_positions": positions,
        "account_snapshot": {"cash": 1000.0, "total_assets": 12000.0, "trace": {"raw": "z" * 4000}},
        "portfolio_totals": {"cash": 1000.0, "total_assets": 12000.0, "position_market_value": 11000.0},
        "portfolio_summary": {
            "as_of_date": "2026-08-03",
            "snapshot_id": "snapshot-1",
            "cash_state": {"cash_ratio": 0.0833},
            "active_positions": positions,
            "calculation_trace": "a" * 6000,
        },
        "unresolved_positions": [],
        "as_of_time": "2026-08-03",
        "graph_snapshot_materialized": False,
    }
    account_payload = {
        "user_id": "cht",
        "account": {
            "cash": 70286.95,
            "total_assets": 300524.95,
            "position_market_value": 230238.0,
            "daily_return": -0.0025,
            "cumulative_return": 1.0035,
            "time_weighted_return": 1.1223,
            "daily_fee": 309.05,
            "cumulative_fee": 6004.05,
        },
        "account_summary": {"cash": 70286.95, "total_assets": 300524.95},
        "summary": {"cash": 70286.95, "total_assets": 300524.95},
        "calculation_trace": {"rows": ["b" * 1000] * 10},
        "sources": [{"path": "outputs/private/path"}],
        "as_of_date": "2026-08-03",
        "snapshot_id": "snapshot-1",
        "consistency_status": "consistent",
    }

    portfolio_view = report_writer._compact_report_payload("PortfolioAnalysisResult", portfolio_payload)
    account_view = report_writer._compact_report_payload("AccountStateResult", account_payload)

    assert len(portfolio_view["display_positions"]) == 10
    assert portfolio_view["display_positions"][0]["quantity"] == 100
    assert portfolio_view["portfolio_totals"]["position_market_value"] == 11000.0
    assert account_view["account_metrics"]["daily_return"] == -0.0025
    assert account_view["account_metrics"]["cumulative_fee"] == 6004.05
    assert "calculation_trace" not in account_view
    assert "sources" not in account_view

    full_chars = len(json.dumps([portfolio_payload, account_payload], ensure_ascii=False, default=str))
    view_chars = len(compact_json_dumps([portfolio_view, account_view]))
    assert view_chars < full_chars * 0.45



def test_all_llm_decision_stages_are_still_present() -> None:
    sources = {
        "entry": inspect.getsource(MainEntryDecisionPlanner.decide),
        "entity_extraction": inspect.getsource(AgentCollaborationCoordinator._extract_mentions),
        "worker_planning": inspect.getsource(CoordinatorPlanner.plan),
        "forward_replan": inspect.getsource(CoordinatorPlanner.replan_forward),
        "tool_planning": inspect.getsource(WorkerToolDagPlanner.plan),
        "tool_replan": inspect.getsource(WorkerToolDagPlanner.replan),
        "entity_analysis": inspect.getsource(entity_analysis.run_entity_analysis),
        "report_writer": inspect.getsource(report_writer.run_report_writer),
    }
    for stage, source in sources.items():
        assert "generate_json" in source, stage



def test_private_tool_catalog_keeps_registered_tools_and_contract_keys() -> None:
    full = [
        {
            "tool_id": "evidence.search_news",
            "description": "Search news",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "results": {"type": "array", "items": {"type": "object"}}
                },
                "required": ["results"],
                "additionalProperties": True,
            },
            "produced_outputs": ["results"],
            "side_effects": [],
        }
    ]
    prompt_view = catalog_for_prompt(full)

    assert [item["tool_id"] for item in prompt_view] == [item["tool_id"] for item in full]
    assert prompt_view[0]["side_effects"] == full[0]["side_effects"]
    assert prompt_view[0]["input_schema"]["required"] == full[0]["input_schema"]["required"]
    assert prompt_view[0]["output_schema"]["required"] == full[0]["output_schema"]["required"]
    assert "description" not in prompt_view[0]["input_schema"]["properties"]["query"]


def test_llm_audit_persists_token_metrics(tmp_path) -> None:
    from agent.llm_audit import activate_llm_audit_context, load_llm_events, record_llm_call

    activate_llm_audit_context(
        run_id="run-token-audit",
        conversation_id="conversation-token-audit",
        output_dir=tmp_path,
        formal_entry_used=True,
        formal_entry_name="test",
    )
    event_id = record_llm_call(
        stage="planner",
        provider="openai_compatible",
        model="qwen3.5-plus",
        temperature=0.2,
        request_at="2026-08-04T00:00:00+00:00",
        response_at="2026-08-04T00:00:01+00:00",
        duration_ms=1000,
        success=True,
        prompt_chars=4200,
        max_output_tokens=1200,
        prompt_tokens=1050,
        completion_tokens=250,
        total_tokens=1300,
    )
    events = load_llm_events(tmp_path, "run-token-audit")

    assert event_id
    assert events[0]["prompt_chars"] == 4200
    assert events[0]["prompt_tokens"] == 1050
    assert events[0]["completion_tokens"] == 250
    assert events[0]["total_tokens"] == 1300
