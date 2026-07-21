from agent.logic_integrity import validate_agent_logic_integrity


def test_logic_integrity_detects_portfolio_conflict() -> None:
    result = validate_agent_logic_integrity(
        portfolio_state={"consistency_status": "rejected", "safe_to_continue": False},
        risk_report={"snapshot_id": "risk-a"},
    )

    assert result.status == "logic_error"
    assert "portfolio_snapshot_inconsistent" in result.errors
    assert result.safe_to_write is False

