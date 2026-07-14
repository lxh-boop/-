from __future__ import annotations

from agent.agent_registry import answer_with_registry, get_agent_registry, route_agent


def test_agent_registry_routes_queries(tmp_path) -> None:
    registry = get_agent_registry()
    assert set(registry) == {"portfolio_qa", "event_impact", "portfolio_review", "model_monitor"}
    assert route_agent("news impact on 000001") == "event_impact"
    assert route_agent("portfolio concentration review") == "portfolio_review"
    assert route_agent("pipeline failure status") == "model_monitor"
    assert route_agent("why numeric adjustment 000001") == "portfolio_qa"

    result = answer_with_registry("why numeric adjustment 000001", output_dir=tmp_path, db_path=tmp_path / "db.sqlite")
    assert result["agent"] == "portfolio_qa"
    assert "not real buy/sell instructions" in result["answer"]
