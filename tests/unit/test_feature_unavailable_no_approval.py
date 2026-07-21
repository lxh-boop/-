from agent.executor import _feature_unavailable_result
from agent.logic_integrity import validate_agent_logic_integrity


def test_feature_unavailable_no_approval() -> None:
    result = _feature_unavailable_result(
        intent="one_time_position_operation",
        integrity=validate_agent_logic_integrity(write_requested=True, write_allowed=False),
        language="zh",
        previous={"requires_confirmation": True, "errors": []},
    )

    assert result["requires_confirmation"] is False
    assert result["data"]["safe_to_write"] is False

