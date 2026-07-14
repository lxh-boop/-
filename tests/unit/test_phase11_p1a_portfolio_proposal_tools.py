from __future__ import annotations

from dataclasses import replace

from agent.capability_index import CapabilityIndexRepository
from agent.agent_specs import RISK_OPERATION
from agent.session.pending_action_store import get_pending_plan
from agent.tool_engine import AGENT_MAIN, AGENT_READ, OP_PROPOSAL, OP_READ, OP_WRITE, execute_tool, get_tool_registry_v2
from agent.tools.position_recommendation_tool import recommend_position_weight
from agent.tools.rebalance_plan_tool import preview_add_stock_to_paper
from agent.write_gateway import execute_confirmed_plan_v2
from agent_control_center_utils import write_agent_fixture
from portfolio.storage import PortfolioStorage


def test_phase11_p1a_tools_are_registered_with_legacy_aliases() -> None:
    registry = get_tool_registry_v2()
    expected = {
        "portfolio.recommend_position": (OP_READ, False),
        "portfolio.recommend_replacement": (OP_READ, False),
        "portfolio.preview_manual_change": (OP_PROPOSAL, False),
        "portfolio.preview_rebalance": (OP_PROPOSAL, False),
        "portfolio.preview_adjust_position": (OP_PROPOSAL, False),
        "portfolio.preview_paper_trade": (OP_PROPOSAL, False),
        "portfolio.commit_paper_trade": (OP_WRITE, True),
    }
    aliases = {
        "position_recommendation": "portfolio.recommend_position",
        "replacement_recommendation": "portfolio.recommend_replacement",
        "manual_position_operation_tool": "portfolio.preview_manual_change",
        "rebalance_plan": "portfolio.preview_rebalance",
        "adjust_position": "portfolio.preview_adjust_position",
        "paper_trade_preview": "portfolio.preview_paper_trade",
        "paper_trade_execute": "portfolio.commit_paper_trade",
        "paper_trading_execution_tool": "portfolio.commit_paper_trade",
    }

    for name, (operation_type, requires_approval) in expected.items():
        definition = registry.get(name)
        assert definition is not None
        assert definition.operation_type == operation_type
        assert definition.requires_approval is requires_approval

    for legacy, canonical in aliases.items():
        definition = registry.get(legacy)
        assert definition is not None
        assert definition.name == canonical


def test_position_recommendation_alias_matches_legacy_core_fields(tmp_path) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path, price=10.0)
    legacy = recommend_position_weight("u1", "600519", output_dir=output_dir, db_path=db_path)
    migrated = execute_tool(
        "position_recommendation",
        {"user_id": "u1", "stock_code": "600519"},
        context={"user_id": "u1", "output_dir": output_dir, "db_path": db_path},
        agent_type=AGENT_READ,
    )

    assert migrated.success is True
    assert migrated.metadata["canonical_tool_name"] == "portfolio.recommend_position"
    assert migrated.artifact_id
    assert migrated.data["recommended_weight"] == legacy.data["recommended_weight"]
    assert migrated.data["estimated_quantity"] == legacy.data["estimated_quantity"]
    assert migrated.data["not_executed"] is True


def test_rebalance_preview_alias_keeps_preview_only_behavior(tmp_path) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path, price=10.0)
    legacy = preview_add_stock_to_paper("u1", "600519", output_dir=output_dir, db_path=db_path)
    migrated = execute_tool(
        "rebalance_plan",
        {"user_id": "u1", "stock_code": "600519"},
        context={"user_id": "u1", "output_dir": output_dir, "db_path": db_path, "session_id": "s1"},
        agent_type=AGENT_MAIN,
    )

    assert legacy.success is True
    assert migrated.success is True
    assert migrated.metadata["canonical_tool_name"] == "portfolio.preview_rebalance"
    assert migrated.data["estimated_quantity"] == legacy.data["estimated_quantity"]
    assert migrated.data["not_committed"] is True
    assert migrated.data["confirmation_plan"]["plan_id"]
    assert get_pending_plan("u1", migrated.data["plan_id"], output_dir)


def test_commit_requires_approval_and_gateway_selects_portfolio_commit(tmp_path) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path, price=10.0)
    preview = execute_tool(
        "portfolio.preview_paper_trade",
        {"user_id": "u1", "stock_code": "600519"},
        context={"user_id": "u1", "output_dir": output_dir, "db_path": db_path, "session_id": "s1"},
        agent_type=AGENT_MAIN,
    )
    assert preview.success is True

    blocked = execute_tool(
        "portfolio.commit_paper_trade",
        {"user_id": "u1", "plan_id": preview.data["plan_id"], "confirmation_token": preview.data["confirmation_token"]},
        context={"user_id": "u1", "output_dir": output_dir, "db_path": db_path},
        agent_type=AGENT_MAIN,
    )
    assert blocked.success is False
    assert blocked.error_type == "approval_required"

    committed = execute_confirmed_plan_v2(
        preview.data["plan_id"],
        preview.data["confirmation_token"],
        "u1",
        output_dir=output_dir,
        db_path=db_path,
    )
    duplicate = execute_confirmed_plan_v2(
        preview.data["plan_id"],
        preview.data["confirmation_token"],
        "u1",
        output_dir=output_dir,
        db_path=db_path,
    )

    assert committed.success is True
    assert committed.metadata["write_gateway"]["selected_tool"] == "portfolio.commit_paper_trade"
    assert committed.metadata["canonical_tool_name"] == "portfolio.commit_paper_trade"
    assert committed.artifact_id
    assert duplicate.success is False
    assert "already_executed" in duplicate.errors


def test_gateway_commit_revalidates_business_state(tmp_path) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path, price=10.0)
    preview = execute_tool(
        "portfolio.preview_paper_trade",
        {"user_id": "u1", "stock_code": "600519"},
        context={"user_id": "u1", "output_dir": output_dir, "db_path": db_path, "session_id": "s1"},
        agent_type=AGENT_MAIN,
    )
    assert preview.success is True

    storage = PortfolioStorage(db_path, output_dir=output_dir / "portfolio" / "u1")
    account = storage.load_account("paper_u1")
    assert account is not None
    storage.save_account(replace(account, cash=account.cash + 1.0, total_assets=account.total_assets + 1.0))

    rejected = execute_confirmed_plan_v2(
        preview.data["plan_id"],
        preview.data["confirmation_token"],
        "u1",
        output_dir=output_dir,
        db_path=db_path,
    )

    assert rejected.success is False
    assert "business_state_changed" in rejected.errors
    assert rejected.metadata["write_gateway"]["selected_tool"] == "portfolio.commit_paper_trade"


def test_capability_index_exposes_p1a_tools_as_v2_records() -> None:
    repo = CapabilityIndexRepository()
    risk_candidates = repo.query(
        agent_identity=RISK_OPERATION,
        goal_action="preview_write_operation",
        missing_outputs=["operation_preview"],
        permission_scope="preview",
        limit=10,
    )
    names = {name for item in risk_candidates for name in item["registered_tool_names"]}

    assert "portfolio.preview_manual_change" in names
    assert "manual_position_operation_tool" in names
    assert "portfolio.preview_rebalance" in names
    assert "adjust_position" in names
