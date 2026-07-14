from __future__ import annotations


SUPPORTED_INTENTS = {
    "query_latest_ranking",
    "explain_stock",
    "query_model_zoo",
    "query_backtest",
    "compare_models",
    "generate_daily_report",
    "query_news_mapping",
    "query_rag",
    "query_market_context",
    "unknown",
}


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword.lower() in text.lower() for keyword in keywords)


def route_intent(query: str) -> str:
    text = str(query or "").strip()
    lower = text.lower()

    if not text:
        return "unknown"

    if _contains_any(text, ["预测准", "准吗", "准不准", "准确", "靠谱", "可靠"]):
        return "query_backtest"

    if _contains_any(text, ["为什么", "原因", "解释"]):
        if _contains_any(text, ["准", "准确", "靠谱", "可靠", "预测"]):
            return "query_backtest"
        return "explain_stock"

    if _contains_any(text, ["报告", "总结", "日报", "每日分析", "agent报告"]):
        return "generate_daily_report"

    if _contains_any(
        text,
        ["新闻", "公告", "事件", "影响哪些股票", "利好", "利空", "概念", "行业映射", "涨价"],
    ):
        return "query_news_mapping"

    if _contains_any(text, ["研报", "年报", "论文", "知识库", "rag", "文档"]):
        return "query_rag"

    if _contains_any(text, ["市场环境", "市场", "指数", "波动", "成交"]):
        return "query_market_context"

    if _contains_any(text, ["哪个模型", "模型表现", "模型最好", "比较模型", "排行榜"]):
        return "compare_models"

    if _contains_any(text, ["回测", "收益", "年化", "ir", "夏普", "最大回撤", "换手率", "基准"]):
        return "query_backtest"

    if _contains_any(text, ["模型库", "当前模型", "有哪些模型", "model zoo", "模型状态"]):
        return "query_model_zoo"

    if _contains_any(text, ["推荐", "排名", "topk", "今天选股", "最新预测", "预测结果", "预测排名"]):
        return "query_latest_ranking"

    if "top" in lower and any(ch.isdigit() for ch in lower):
        return "query_latest_ranking"

    return "unknown"
