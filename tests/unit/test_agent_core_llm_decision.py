from __future__ import annotations

import agent.agent_core as core


def test_agent_uses_llm_for_explanation_when_prompt_and_api_are_available(monkeypatch):
    monkeypatch.setattr(core, "route_intent", lambda query: "explain_stock")
    monkeypatch.setattr(
        core.tool_adapter,
        "tool_explain_stock",
        lambda stock_query, model_name=None: {
            "success": True,
            "message": "ok",
            "explanation": "local explanation",
        },
    )
    monkeypatch.setattr(
        core,
        "_answer_with_llm",
        lambda **kwargs: "LLM 解释结果。本内容仅用于机器学习、金融数据分析和项目展示，不构成投资建议。",
    )

    response = core.run_agent(
        "为什么排名第一",
        prompt_text="prompt",
        llm_api_key="mock-key",
        llm_base_url="https://mock.example",
        llm_model="mock-model",
    )

    assert response.answer.startswith("LLM 解释结果")
    assert [call.tool_name for call in response.tool_calls] == [
        "tool_explain_stock",
        "llm_explain_prompt",
    ]


def test_agent_keeps_backtest_query_as_direct_tool_answer(monkeypatch):
    monkeypatch.setattr(core, "route_intent", lambda query: "query_backtest")
    monkeypatch.setattr(
        core.tool_adapter,
        "tool_query_backtest",
        lambda model_name=None: {
            "success": True,
            "message": "ok",
            "records": [
                {
                    "model_name": "mock",
                    "topk": 10,
                    "holding_days": 1,
                    "annual_return": 0.1,
                    "benchmark_return": 0.02,
                    "max_drawdown": -0.03,
                    "sharpe": 1.2,
                }
            ],
        },
    )
    monkeypatch.setattr(
        core,
        "_answer_with_llm",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not call llm")),
    )

    response = core.run_agent(
        "默认回测方案表现怎么样",
        prompt_text="prompt",
        llm_api_key="mock-key",
    )

    assert "已读取已有回测结果" in response.answer
    assert [call.tool_name for call in response.tool_calls] == ["tool_query_backtest"]
