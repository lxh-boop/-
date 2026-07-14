from __future__ import annotations

from datetime import UTC, datetime

from agent.executor import run_agent_request
from agent.session.confirmation_manager import reject_confirmation_plan
from agent.session.pending_action_store import update_pending_plan
from agent.tools.paper_trade_execute_tool import execute_confirmed_paper_trade_plan
from database.repositories.agent_repository import AgentRepository
from portfolio.paper_position import create_position
from portfolio.storage import PortfolioStorage
from agent_control_center_utils import write_agent_fixture


def _portfolio_fixture(tmp_path):
    output_dir, db_path = write_agent_fixture(tmp_path, with_position=True, cash=100000.0)
    storage = PortfolioStorage(db_path, output_dir=output_dir / "portfolio" / "u1")
    storage.save_positions(
        [
            create_position(
                "u1",
                "000001",
                stock_name="Ping An Bank",
                quantity=1000,
                cost_price=12.0,
                current_price=12.0,
                total_assets=100000.0,
                industry="Bank",
            ),
            create_position(
                "u1",
                "600519",
                stock_name="Kweichow Moutai",
                quantity=1000,
                cost_price=10.0,
                current_price=10.0,
                total_assets=100000.0,
                industry="Consumer",
            ),
        ]
    )
    return output_dir, db_path, storage


def _preview(tmp_path):
    output_dir, db_path, storage = _portfolio_fixture(tmp_path)
    result = run_agent_request(
        "把我现在的持仓调整得更稳健",
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        llm_api_key="",
    )
    assert result["success"] is True
    data = result["result"]["data"]
    return output_dir, db_path, storage, result, data


def test_stability_request_creates_full_portfolio_proposal_without_commit(tmp_path) -> None:
    _, db_path, _, result, data = _preview(tmp_path)

    assert result["intent"] == "one_time_position_operation"
    assert result["runtime"]["status"] == "waiting_for_approval"
    assert data["portfolio_level"] is True
    assert data["source_type"] == "deterministic_stable_portfolio_rebalance"
    assert {row["stock_code"] for row in data["current_positions"]} == {"000001", "600519"}
    assert {row["stock_code"] for row in data["target_positions"]} == {"000001", "600519"}
    assert len(data["proposed_changes"]) == 2
    assert data["risk_after"]["max_single_position"] <= 0.08 + 1e-9
    assert abs(data["validation_results"]["weights_plus_cash"] - 1.0) <= 1e-9
    assert data["ranking_context"]["candidate_count"] >= 2
    assert data["profile_context"]["constraints"]["max_single_position"] == 0.08
    repo = AgentRepository(db_path)
    assert len(repo.store.list("action_proposals", {"plan_id": data["plan_id"]})) == 1
    assert repo.store.list("action_commits", {"plan_id": data["plan_id"]}) == []


def test_stability_confirmation_commits_once_and_returns_trace_ids(tmp_path) -> None:
    output_dir, db_path, storage, preview, data = _preview(tmp_path)
    query = f"confirm execute {data['plan_id']} token: {data['confirmation_token']}"

    confirmed = run_agent_request(
        query,
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        llm_api_key="",
    )
    duplicate = run_agent_request(
        query,
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        llm_api_key="",
    )

    assert confirmed["success"] is True, {
        "intent": confirmed.get("intent"),
        "message": (confirmed.get("result") or {}).get("message"),
        "errors": (confirmed.get("result") or {}).get("errors"),
        "data": {
            key: value
            for key, value in ((confirmed.get("result") or {}).get("data") or {}).items()
            if "token" not in str(key).lower()
        },
    }
    assert confirmed["run_id"] == preview["run_id"]
    committed = confirmed["result"]["data"]
    assert committed["approval_id"]
    assert committed["commit_id"] == f"commit_{data['plan_id']}"
    assert len(committed["order_ids"]) == 2
    assert duplicate["success"] is False
    positions = {row.stock_code: row.quantity for row in storage.load_positions("u1")}
    assert positions == {"000001": 600.0, "600519": 800.0}
    repo = AgentRepository(db_path)
    assert len(repo.store.list("action_commits", {"plan_id": data["plan_id"]})) == 1


def test_stability_reject_expire_token_and_state_conflict_never_commit(tmp_path) -> None:
    output_dir, db_path, storage, _, data = _preview(tmp_path)
    before = {row.stock_code: row.quantity for row in storage.load_positions("u1")}
    rejected, status, _ = reject_confirmation_plan(
        "u1",
        data["plan_id"],
        output_dir=output_dir,
        db_path=db_path,
    )
    assert rejected is True and status == "rejected"
    assert AgentRepository(db_path).store.list("action_commits", {"plan_id": data["plan_id"]}) == []
    assert {row.stock_code: row.quantity for row in storage.load_positions("u1")} == before

    _, _, _, _, expired = _preview(tmp_path / "expired")
    expired_output = tmp_path / "expired" / "outputs"
    expired_db = tmp_path / "expired" / "agent.db"
    update_pending_plan(
        "u1",
        expired["plan_id"],
        {"expires_at": "2000-01-01 00:00:00"},
        expired_output,
    )
    expired_result = execute_confirmed_paper_trade_plan(
        "u1",
        expired["plan_id"],
        expired["confirmation_token"],
        output_dir=expired_output,
        db_path=expired_db,
    )
    assert "confirmation_token_expired" in expired_result.errors
    assert AgentRepository(expired_db).store.list("action_commits", {"plan_id": expired["plan_id"]}) == []

    _, _, _, _, invalid = _preview(tmp_path / "invalid")
    invalid_output = tmp_path / "invalid" / "outputs"
    invalid_db = tmp_path / "invalid" / "agent.db"
    invalid_result = execute_confirmed_paper_trade_plan(
        "u1",
        invalid["plan_id"],
        "wrong-token",
        output_dir=invalid_output,
        db_path=invalid_db,
    )
    assert "invalid_confirmation_token" in invalid_result.errors
    assert AgentRepository(invalid_db).store.list("action_commits", {"plan_id": invalid["plan_id"]}) == []

    conflict_output, conflict_db, conflict_storage, _, conflict = _preview(tmp_path / "conflict")
    changed = conflict_storage.load_positions("u1")
    conflict_storage.save_positions(
        [
            create_position(
                row.user_id,
                row.stock_code,
                stock_name=row.stock_name,
                quantity=row.quantity - 100 if index == 0 else row.quantity,
                cost_price=row.cost_price,
                current_price=row.current_price,
                total_assets=100000.0,
                industry=row.industry,
            )
            for index, row in enumerate(changed)
        ]
    )
    conflict_result = execute_confirmed_paper_trade_plan(
        "u1",
        conflict["plan_id"],
        conflict["confirmation_token"],
        output_dir=conflict_output,
        db_path=conflict_db,
    )
    assert "business_state_changed" in conflict_result.errors
    assert AgentRepository(conflict_db).store.list("action_commits", {"plan_id": conflict["plan_id"]}) == []


def test_stability_transaction_failure_rolls_back_all_positions(monkeypatch, tmp_path) -> None:
    output_dir, db_path, storage, _, data = _preview(tmp_path)
    before = {row.stock_code: row.quantity for row in storage.load_positions("u1")}

    def fail_snapshot(*args, **kwargs):
        raise RuntimeError("injected_snapshot_failure")

    monkeypatch.setattr(PortfolioStorage, "write_daily_snapshot", fail_snapshot)
    result = execute_confirmed_paper_trade_plan(
        "u1",
        data["plan_id"],
        data["confirmation_token"],
        output_dir=output_dir,
        db_path=db_path,
    )

    assert result.success is False
    assert result.data["rollback"] is True
    assert {row.stock_code: row.quantity for row in storage.load_positions("u1")} == before
    assert AgentRepository(db_path).store.list("action_commits", {"plan_id": data["plan_id"]}) == []


def test_stability_intent_boundaries_keep_advice_and_strategy_separate(tmp_path) -> None:
    output_dir, db_path, _, _, _ = _preview(tmp_path)
    repo = AgentRepository(db_path)
    count_before = len(repo.store.list("action_proposals"))

    advice = run_agent_request(
        "分析当前持仓风险并给出只读稳健调仓建议",
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        llm_api_key="",
    )
    assert advice["intent"] != "one_time_position_operation"
    assert len(repo.store.list("action_proposals")) == count_before

    strategy = run_agent_request(
        "以后都使用更稳健的策略",
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        llm_api_key="",
    )
    assert strategy["intent"] == "strategy_change"
    assert strategy["result"]["data"].get("operation_type") != "one_time_position_operation"


def test_chat_reject_plan_id_routes_to_rejection_without_token(tmp_path) -> None:
    output_dir, db_path, _, _, data = _preview(tmp_path)
    result = run_agent_request(
        f"拒绝 {data['plan_id']}",
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        llm_api_key="",
    )
    assert result["success"] is True, {
        "intent": result.get("intent"),
        "message": (result.get("result") or {}).get("message"),
        "errors": (result.get("result") or {}).get("errors"),
    }
    assert result["intent"] == "reject_execute"
    assert result["result"]["data"]["confirmation_status"] == "rejected"
    assert AgentRepository(db_path).store.list("action_commits", {"plan_id": data["plan_id"]}) == []
