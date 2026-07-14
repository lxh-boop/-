from __future__ import annotations


def _contains_any(text: str, tokens: list[str]) -> bool:
    return any(token in text for token in tokens)


def classify_intent(query: str) -> str:
    text = str(query or "").strip().lower()
    if not text:
        return "empty"

    if _contains_any(text, ["拒绝", "取消计划", "reject"]) and _contains_any(
        text,
        ["agent_plan_", "计划", "plan"],
    ):
        return "reject_execute"

    if _contains_any(text, ["确认", "执行", "confirm"]) and _contains_any(
        text,
        ["agent_plan_", "token", "令牌", "confirmation_token"],
    ):
        return "confirm_execute"

    if _contains_any(text, ["以后", "今后", "后续", "长期", "每次", "从现在开始", "从下次", "策略"]):
        return "strategy_change"

    if _contains_any(text, ["卖出", "买入", "减仓", "加仓", "减半", "清仓", "调到", "降到", "把我的持仓调整", "修改持仓"]):
        return "one_time_position_operation"

    if _contains_any(text, ["分析当前持仓风险", "持仓风险", "组合风险", "模拟盘风险", "portfolio risk"]):
        return "portfolio_risk"

    if _contains_any(text, ["查看当前持仓", "当前模拟盘持仓", "模拟盘状态", "账户摘要", "当前账户", "持仓有多少", "portfolio state", "positions", "account"]):
        return "portfolio_state"

    if _contains_any(text, ["排名", "排行", "前十", "top10", "top 10", "模型推荐", "推荐股票"]):
        return "ranking"

    if _contains_any(text, ["新闻", "公告", "news"]):
        return "stock_news"

    if _contains_any(text, ["rag", "证据", "检索"]):
        return "stock_rag"

    if _contains_any(text, ["portfolio risk", "risk report", "combination risk", "portfolio drawdown"]):
        return "portfolio_risk"

    if _contains_any(text, ["确认", "confirm", "执行"]) and _contains_any(
        text,
        ["agent_plan_", "token", "令牌"],
    ):
        return "confirm_execute"

    if _contains_any(
        text,
        [
            "以后",
            "今后",
            "后续",
            "长期",
            "每次",
            "从现在开始",
            "从下次",
            "新增策略",
            "持仓策略",
            "调仓策略",
            "策略",
        ],
    ):
        return "strategy_change"

    if _contains_any(text, ["追加", "入金", "出金", "提现", "资金", "capital", "deposit", "withdraw"]):
        return "capital_management"

    if _contains_any(text, ["回放", "补回", "backfill", "历史模拟"]):
        return "backfill"

    if _contains_any(text, ["后台", "调度", "scheduler", "任务状态", "更新状态", "自动更新状态"]):
        return "scheduler_status"

    if _contains_any(text, ["报告", "report"]):
        return "report"

    if _contains_any(text, ["替换", "换掉", "replacement", "replace"]):
        return "replacement_recommendation"

    has_one_time_marker = _contains_any(
        text,
        ["今天", "这次", "本次", "临时", "当前持仓", "本轮"],
    )
    has_position_operation = _contains_any(
        text,
        [
            "调",
            "卖",
            "买",
            "持有",
            "仓位",
            "现金",
            "不要",
            "减",
            "加",
            "position",
            "weight",
        ],
    )
    if has_one_time_marker and has_position_operation:
        return "one_time_position_operation"

    if _contains_any(
        text,
        [
            "减仓",
            "减半",
            "降低仓位",
            "降仓",
            "调低",
            "调到",
            "减到",
            "清仓",
            "卖出",
            "仓位太高",
            "reduce",
            "trim",
            "sell",
        ],
    ):
        return "one_time_position_operation"

    if _contains_any(text, ["加入", "放入", "加到", "买入", "调仓预览", "paper trade", "preview"]):
        return "one_time_position_operation"

    if _contains_any(
        text,
        ["账户", "持仓", "资产", "订单", "当前组合", "模拟账户", "模拟盘状态", "portfolio state", "positions", "account"],
    ):
        return "portfolio_state"

    if _contains_any(
        text,
        [
            "排名",
            "排行",
            "topk",
            "top k",
            "top10",
            "top 10",
            "前十",
            "前10",
            "前五",
            "最新预测",
            "预测结果",
            "今天选股",
            "模型推荐",
            "哪些股票",
            "推荐哪些股票",
            "推荐股票",
        ],
    ):
        return "ranking"

    if _contains_any(text, ["仓位", "买多少", "配多少", "position", "weight"]):
        return "position_recommendation"

    if _contains_any(text, ["新闻", "news"]):
        return "stock_news"

    if _contains_any(text, ["rag", "证据", "检索"]):
        return "stock_rag"

    if _contains_any(text, ["分析", "怎么样", "看看", "analyze", "analysis"]) or any(ch.isdigit() for ch in text):
        return "stock_analysis"

    return "general_help"
