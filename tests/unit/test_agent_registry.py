from __future__ import annotations

from agent.agent_registry import (
    answer_with_registry,
    get_agent_registry,
    route_agent,
)


def test_agent_registry_exposes_only_the_financial_graph_entry(
    monkeypatch,
    tmp_path,
) -> None:
    registry = get_agent_registry()
    assert set(registry) == {"financial_graph_agent"}
    assert route_agent("news impact on 000001") == "financial_graph_agent"

    monkeypatch.setattr(
        "agent.executor.run_agent_request",
        lambda query, **kwargs: {
            "query": query,
            "user_id": kwargs["user_id"],
        },
    )
    result = answer_with_registry(
        "why numeric adjustment 000001",
        user_id="user-1",
        output_dir=tmp_path,
        db_path=tmp_path / "db.sqlite",
    )
    assert result == {
        "query": "why numeric adjustment 000001",
        "user_id": "user-1",
    }
