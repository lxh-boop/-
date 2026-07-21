from __future__ import annotations

from agent.intent_classifier import classify_intent
from agent.parameter_extractor import extract_parameters
from agent.router import route_agent_query


def test_agent_intent_routing_and_parameters() -> None:
    assert classify_intent("分析 600519") == "stock_analysis"
    assert classify_intent("把 600519 加入模拟盘 5%") == "one_time_position_operation"
    assert classify_intent("后台任务状态") == "scheduler_status"
    routed = route_agent_query("把 600519 加入模拟盘 5%")
    assert routed.intent == "one_time_position_operation"
    assert routed.parameters["operation_type"] == "one_time_position_operation"
    params = extract_parameters("确认执行 agent_plan_abc token:tok_123")
    assert params["plan_id"] == "agent_plan_abc"
    assert params["confirmation_token"] == "tok_123"


def test_agent_routes_existing_position_adjustment() -> None:
    query = "603986 " + "\u5146\u6613\u521b\u65b0\u4ed3\u4f4d\u592a\u9ad8\u4e86\uff0c\u51cf\u534a"
    assert classify_intent(query) == "one_time_position_operation"
    params = extract_parameters(query)
    assert params["stock_code"] == "603986"
    assert params["position_adjustment_ratio"] == 0.5
    assert params["amount"] is None
    routed = route_agent_query(query, enable_llm=False)
    assert routed.intent == "one_time_position_operation"
    assert routed.decomposition["tasks"][0]["operation_type"] == "one_time_position_operation"


def test_agent_extracts_explicit_sell_quantity() -> None:
    query = "603986 " + "\u5356\u51fa100\u80a1"
    params = extract_parameters(query)
    assert classify_intent(query) == "one_time_position_operation"
    assert params["stock_code"] == "603986"
    assert params["requested_quantity"] == 100.0
    routed = route_agent_query(query, enable_llm=False)
    assert routed.intent == "one_time_position_operation"
    assert routed.parameters["requested_quantity"] == 100.0


def test_strategy_change_intent_routing() -> None:
    query = "以后只持有模型排名前 5 的股票"
    assert classify_intent(query) == "strategy_change"
    routed = route_agent_query(query, enable_llm=False)
    assert routed.intent == "strategy_change"
    task = routed.decomposition["tasks"][0]
    assert task["operation_type"] == "strategy_change"
    assert task["persistent"] is True
    assert task["apply_now"] is False


def test_today_ranking_is_not_position_operation() -> None:
    assert classify_intent("今天模型推荐哪些股票") == "ranking"


def test_explicit_stock_news_evidence_uses_read_only_rag_hard_route() -> None:
    routed = route_agent_query("查询 002468 的新闻和公告证据", enable_llm=False)

    assert routed.intent == "stock_rag"
    assert routed.parameters["stock_code"] == "002468"
    assert routed.decomposition["route_layer"] == "hard_rule"
    assert routed.decomposition["tasks"][0]["operation_type"] == ""
    assert routed.decomposition["user_goal"]["requires_write"] is False
