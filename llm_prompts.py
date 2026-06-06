from __future__ import annotations

import json
from typing import Any


DISCLAIMER_TEXT = "本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。"

FORBIDDEN_TERMS = [
    "建议买入",
    "建议卖出",
    "目标价",
    "稳赚",
    "保证收益",
    "适合实盘",
]


def _json_block(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(data)


def build_stock_explanation_prompt(
    stock_row: dict,
    model_metrics: dict | None = None,
    risk_detail: dict | None = None,
    news_context: list[dict] | None = None,
) -> list[dict]:
    model_metrics = model_metrics or {}
    risk_detail = risk_detail or {}
    news_context = news_context or []

    system_prompt = f"""
你是一个谨慎的量化模型解释助手，只解释机器学习股票评分系统的输出。

硬性规则：
1. 不能给出买入、卖出、持有、加仓、减仓等交易建议。
2. 不能输出目标价，不能承诺收益，不能暗示稳赚。
3. 只能基于输入数据做机器学习结果解释。
4. 必须区分“模型输出”“量化指标”“新闻/公告事实”和“不确定性”。
5. 必须包含免责声明：{DISCLAIMER_TEXT}
6. 禁止使用这些表达：{", ".join(FORBIDDEN_TERMS)}

请使用客观、克制、项目展示式的中文表达。
""".strip()

    user_prompt = f"""
请基于下面的输入，为该股票生成 Markdown 结构化解释。

输出结构必须包括：
1. 模型评分概览
2. 主要量化因素
3. 上涨概率和可信度解释
4. 风险等级解释
5. 不确定性说明
6. 免责声明

再次强调：你不能给出买入、卖出、目标价或实盘交易建议。

【股票与模型输出】
{_json_block(stock_row)}

【模型指标】
{_json_block(model_metrics)}

【风险与置信度细节】
{_json_block(risk_detail)}

【新闻/RAG 上下文】
{_json_block(news_context)}
""".strip()

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def messages_to_text(messages: list[dict]) -> str:
    parts = []

    for message in messages:
        role = message.get("role", "unknown")
        content = message.get("content", "")
        parts.append(f"【{role}】\n{content}")

    return "\n\n".join(parts)


def validate_prompt_safety(messages_or_text) -> dict:
    if isinstance(messages_or_text, list):
        text = messages_to_text(messages_or_text)
    else:
        text = str(messages_or_text or "")

    return {
        "has_disclaimer": DISCLAIMER_TEXT in text,
        "blocks_trading_advice": "不能给出买入" in text and "不能给出买入、卖出" in text,
        "blocks_return_promises": "不能承诺收益" in text,
        "blocks_target_price": "目标价" in text and "不能输出目标价" in text,
        "requires_uncertainty": "不确定性" in text,
        "lists_forbidden_terms": all(term in text for term in FORBIDDEN_TERMS),
    }
