from __future__ import annotations

from llm_client import LLMClient
from llm_prompts import build_stock_explanation_prompt, validate_prompt_safety


def test_llm_missing_api_key_returns_clear_error(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    ok, message = LLMClient(api_key="", base_url="", model="mock").validate_connection()
    assert not ok
    assert "API Key" in message


def test_llm_chat_mock_success(mocker):
    mocker.patch.object(LLMClient, "chat", return_value="本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。")
    text = LLMClient(api_key="mock-key", model="mock").chat([])
    assert "不构成投资建议" in text


def test_prompt_contains_disclaimer_and_safety_rules(sample_ranking_df):
    messages = build_stock_explanation_prompt(sample_ranking_df.iloc[0].to_dict())
    safety = validate_prompt_safety(messages)
    assert all(safety.values())
