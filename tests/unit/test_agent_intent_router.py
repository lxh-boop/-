from __future__ import annotations

from agent.intent_router import route_intent


def test_route_latest_ranking():
    assert route_intent("今天模型推荐哪些股票") == "query_latest_ranking"
    assert route_intent("最新预测排名 TopK 是什么") == "query_latest_ranking"


def test_route_explain_stock():
    assert route_intent("为什么推荐排名第一的股票") == "explain_stock"
    assert route_intent("解释一下 600519 的模型分数") == "explain_stock"


def test_route_prediction_quality_to_backtest():
    assert route_intent("你认为这个预测的准吗？为什么？") == "query_backtest"
    assert route_intent("这个预测靠谱吗") == "query_backtest"


def test_route_model_zoo():
    assert route_intent("当前有哪些模型") == "query_model_zoo"
    assert route_intent("当前 Model Zoo 状态是什么") == "query_model_zoo"


def test_route_backtest():
    assert route_intent("默认回测方案表现怎么样") == "query_backtest"
    assert route_intent("年化收益和最大回撤是多少") == "query_backtest"


def test_route_compare_models():
    assert route_intent("哪个模型表现最好") == "compare_models"
    assert route_intent("比较模型排行榜") == "compare_models"


def test_route_news_mapping():
    assert route_intent("最近稀土涨价会影响哪些股票") == "query_news_mapping"
    assert route_intent("新闻事件影响哪些股票") == "query_news_mapping"


def test_route_rag():
    assert route_intent("根据研报知识库回答问题") == "query_rag"
    assert route_intent("RAG 文档里有没有相关证据") == "query_rag"


def test_route_market_context():
    assert route_intent("当前市场环境怎么样") == "query_market_context"
    assert route_intent("指数波动和成交情况") == "query_market_context"


def test_route_unknown():
    assert route_intent("随便聊聊") == "unknown"
