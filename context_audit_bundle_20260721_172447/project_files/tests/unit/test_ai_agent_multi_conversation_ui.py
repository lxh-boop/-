from __future__ import annotations

import inspect

from app.pages import ai_agent
from app.pages.ai_agent import (
    _phase51_active_conversation_options,
    _phase51_conversation_label,
)


def test_conversation_options_keep_active_id_when_not_in_page() -> None:
    options = _phase51_active_conversation_options(
        [{"conversation_id": "conv_a"}, {"conversation_id": "conv_b"}],
        "conv_current",
    )

    assert options[0] == "conv_current"
    assert options[1:] == ["conv_a", "conv_b"]


def test_conversation_label_hides_full_conversation_id() -> None:
    label = _phase51_conversation_label(
        {
            "conversation_id": "conv_secret_full_identifier",
            "title": "Portfolio risk chat",
            "updated_at": "2026-07-07 12:00:00",
        },
        "conv_secret_full_identifier",
        language="zh",
    )

    assert "Portfolio risk chat" in label
    assert "entifier" in label
    assert "conv_secret_full_identifier" not in label


def test_ai_agent_page_exposes_multi_conversation_controls() -> None:
    source = inspect.getsource(ai_agent.render_ai_agent_page)
    manager_source = inspect.getsource(ai_agent._phase51_render_conversation_manager)

    assert "_phase51_render_conversation_manager" in source
    assert "New conversation / \u65b0\u5efa\u5bf9\u8bdd" in manager_source
    assert "Switch conversation / \u5207\u6362\u5bf9\u8bdd" in manager_source
    assert "Delete current / \u5220\u9664\u5f53\u524d\u4f1a\u8bdd" in manager_source
    assert "st.selectbox" in manager_source
