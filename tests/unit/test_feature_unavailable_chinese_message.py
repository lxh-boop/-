from agent.logic_integrity import FEATURE_UNAVAILABLE_MESSAGE_ZH, feature_unavailable_payload, validate_agent_logic_integrity


def test_feature_unavailable_chinese_message() -> None:
    payload = feature_unavailable_payload(validate_agent_logic_integrity(write_requested=True, write_allowed=False), language="zh")

    assert payload["message"] == FEATURE_UNAVAILABLE_MESSAGE_ZH

