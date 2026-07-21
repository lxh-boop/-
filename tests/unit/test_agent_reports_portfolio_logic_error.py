from agent.logic_integrity import feature_unavailable_payload, validate_agent_logic_integrity


def test_agent_reports_portfolio_logic_error() -> None:
    integrity = validate_agent_logic_integrity(portfolio_state={"consistency_status": "rejected"})
    payload = feature_unavailable_payload(integrity)

    assert payload["status"] == "feature_unavailable"
    assert payload["error_code"] == "portfolio_snapshot_inconsistent"

