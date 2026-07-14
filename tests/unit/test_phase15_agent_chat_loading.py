from __future__ import annotations

import inspect

from app.pages import ai_agent


def test_phase15_default_message_window_is_small() -> None:
    assert ai_agent.PHASE8_MESSAGE_PAGE_SIZE == 10
    assert ai_agent.PHASE15_VISIBLE_MESSAGE_WINDOW == 10
    assert ai_agent.PHASE15_LOAD_MORE_STEP == 10
    assert ai_agent.PHASE15_MAX_MESSAGE_WINDOW >= 50


def test_phase15_message_limit_helpers_are_bounded() -> None:
    messages = [{"role": "user", "content": str(index)} for index in range(10)]

    assert ai_agent._phase15_should_offer_load_earlier(messages, 10) is True
    assert ai_agent._phase15_should_offer_load_earlier(messages[:9], 10) is False
    assert len(ai_agent._phase15_trim_visible_messages(messages + messages, 10)) == 10
    assert ai_agent._phase15_trim_visible_messages(messages, 10)[0]["content"] == "0"
    assert ai_agent._phase15_next_message_limit(10) == 20
    assert ai_agent._phase15_next_message_limit(ai_agent.PHASE15_MAX_MESSAGE_WINDOW) == ai_agent.PHASE15_MAX_MESSAGE_WINDOW


def test_phase15_result_details_are_lazy_loaded() -> None:
    source = inspect.getsource(ai_agent._render_result_details)

    assert "Load context safe summary" in source
    assert "Load message trace safe summary" in source
    assert "Load ReAct trace safe summary" in source
    assert "Load sanitized tool/result details" in source


def test_phase15_run_id_from_result_supports_legacy_runtime_shape() -> None:
    assert ai_agent._phase15_run_id_from_result({"run_id": "run_top"}) == "run_top"
    assert ai_agent._phase15_run_id_from_result({"runtime": {"run_id": "run_nested"}}) == "run_nested"
    assert ai_agent._phase15_run_id_from_result({}) == ""
