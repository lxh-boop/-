from __future__ import annotations

import argparse
from dataclasses import asdict
from typing import Any, Callable

from agent.intent_router import route_intent
from agent.logging_utils import log_agent_call
from agent.schemas import AgentResponse, RISK_WARNING, ToolCallRecord
import agent.tool_adapter as tool_adapter


ToolFunc = Callable[..., dict]


def _ensure_warning(answer: str) -> str:
    text = str(answer or "").strip()
    if RISK_WARNING not in text:
        text = text.rstrip() + f"\n\n{RISK_WARNING}"
    return text


def _preview(result: dict) -> str:
    if "records" in result:
        return f"返回 {len(result.get('records') or [])} 条记录"
    if "stocks" in result:
        return f"返回 {len(result.get('stocks') or [])} 条股票映射"
    if "evidence" in result:
        return f"返回 {len(result.get('evidence') or [])} 条证据"
    if "explanation" in result:
        return str(result.get("explanation") or "")[:120]
    if "report_path" in result:
        return str(result.get("report_path"))
    return str(result.get("message", ""))[:120]


def _format_percent(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return "N/A"
    return f"{number:.2%}"


def _format_value(value: Any) -> str:
    if value is None:
        return "N/A"
    text = str(value)
    return "N/A" if text.lower() in {"none", "nan", ""} else text


def _answer_latest_ranking(result: dict) -> str:
    if not result.get("success"):
        return _ensure_warning(str(result.get("message", "未查询到相关数据。")))

    rows = result.get("records", [])
    lines = [
        f"已查询到最新模型预测排名，共 {result.get('total_rows', 0)} 条，当前展示 TopK={result.get('topk')}。",
    ]
    if result.get("trade_date"):
        lines.append(f"数据截止日：{result.get('trade_date')}")
    if result.get("predict_for_date"):
        lines.append(f"预测交易日：{result.get('predict_for_date')}")
    if rows:
        lines.append("")
        lines.append("| 排名 | 股票代码 | 股票名称 | 模型分数 | 可信度 | 风险等级 |")
        lines.append("|---|---|---|---:|---|---|")
        for item in rows:
            score = item.get("score")
            try:
                score_text = f"{float(score):.3f}"
            except Exception:
                score_text = "N/A"
            lines.append(
                "| {rank} | {code} | {name} | {score} | {confidence} | {risk} |".format(
                    rank=item.get("rank", ""),
                    code=item.get("stock_code", ""),
                    name=item.get("stock_name", ""),
                    score=score_text,
                    confidence=item.get("confidence", ""),
                    risk=item.get("risk_level", ""),
                )
            )
    return _ensure_warning("\n".join(lines))


def _answer_stock_explanation(result: dict) -> str:
    if not result.get("success"):
        return _ensure_warning(str(result.get("message", "未查询到相关数据。")))
    return _ensure_warning(str(result.get("explanation", "")))


def _answer_model_zoo(result: dict) -> str:
    if not result.get("success"):
        return _ensure_warning(str(result.get("message", "未查询到模型库数据。")))

    rows = result.get("model_zoo", [])
    latest = result.get("latest_model", {})
    lines = [
        f"当前默认本地模型：{result.get('default_model', '')}",
        f"本地 latest 是否存在：{'是' if latest.get('latest_exists') else '否'}",
        f"Model Zoo 登记模型数：{len(rows)}",
    ]
    if rows:
        lines.extend(["", "| 模型 | 家族 | 状态 | 本地路径 |", "|---|---|---|---|"])
        for item in rows[:10]:
            lines.append(
                f"| {item.get('name', '')} | {item.get('family', '')} | "
                f"{item.get('status', '')} | {item.get('local_path', '')} |"
            )
    errors = result.get("errors") or []
    if errors:
        lines.append("")
        lines.append("部分信息读取提示：" + "；".join(errors))
    return _ensure_warning("\n".join(lines))


def _answer_backtest(result: dict) -> str:
    if not result.get("success"):
        return _ensure_warning(str(result.get("message", "未查询到回测结果。")))

    rows = result.get("records", [])
    lines = [
        "不能直接判断某一次预测一定准不准，只能根据历史回测、风险和稳定性评估它在项目数据上的可靠性。",
        "已读取已有回测结果，不会自动重新回测。",
    ]
    if rows:
        best = rows[0]
        lines.extend(
            [
                f"展示方案：{best.get('model_name', '未知模型')}，TopK={best.get('topk', 'N/A')}，持有期={best.get('holding_days', 'N/A')}",
                f"年化收益：{_format_percent(best.get('annual_return'))}",
                f"基准收益：{_format_percent(best.get('benchmark_return'))}",
                f"最大回撤：{_format_percent(best.get('max_drawdown'))}",
                f"夏普：{_format_value(best.get('sharpe'))}",
                "",
                "判断依据：如果历史回测收益、夏普或信息比率较好，同时最大回撤可控，说明这个模型在历史样本上有一定排序能力；但这不代表下一交易日一定正确，也不代表未来收益。",
            ]
        )
    return _ensure_warning("\n".join(lines))


def _answer_compare_models(result: dict) -> str:
    if not result.get("success"):
        return _ensure_warning(str(result.get("message", "未查询到模型比较结果。")))
    best = result.get("display_candidate", {})
    lines = [
        "已根据现有回测表做模型表现比较，排序仅用于项目展示。",
        f"当前综合表现靠前的展示方案：{best.get('model_name', '未知模型')}",
        f"TopK={best.get('topk', 'N/A')}，持有期={best.get('holding_days', 'N/A')}",
        f"年化收益：{_format_percent(best.get('annual_return'))}",
        f"最大回撤：{_format_percent(best.get('max_drawdown'))}",
    ]
    return _ensure_warning("\n".join(lines))


def _answer_news_mapping(result: dict) -> str:
    if not result.get("success"):
        return _ensure_warning(str(result.get("message", "未查询到相关新闻映射。")))
    stocks = result.get("stocks", [])
    lines = [
        f"事件识别：{result.get('event', '')}",
        f"本地映射结果数量：{len(stocks)}",
    ]
    if stocks:
        lines.extend(["", "| 股票代码 | 股票名称 | 匹配原因 | 置信度 |", "|---|---|---|---:|"])
        for item in stocks[:10]:
            lines.append(
                f"| {item.get('stock_code', '')} | {item.get('stock_name', '')} | "
                f"{item.get('match_reason', '')} | {item.get('confidence', '')} |"
            )
    return _ensure_warning("\n".join(lines))


def _answer_rag(result: dict) -> str:
    if not result.get("success"):
        return _ensure_warning(str(result.get("message", "未查询到 RAG 证据。")))
    evidence = result.get("evidence", [])
    lines = [str(result.get("answer") or "已检索到相关证据，下面展示证据摘要。")]
    if evidence:
        lines.extend(["", "| 来源 | 匹配度 | 片段 |", "|---|---:|---|"])
        for item in evidence[:5]:
            text = str(item.get("text", "")).replace("\n", " ")[:80]
            lines.append(f"| {item.get('source', '')} | {item.get('score', '')} | {text} |")
    return _ensure_warning("\n".join(lines))


def _answer_market_context(result: dict) -> str:
    if not result.get("success"):
        return _ensure_warning(str(result.get("message", "未查询到市场环境数据。")))
    lines = [
        "已读取本地市场环境缓存。",
        f"指数数据日期：{result.get('index_date_min', '')} 至 {result.get('index_date_max', '')}",
        f"特征数据日期：{result.get('feature_date_min', '')} 至 {result.get('feature_date_max', '')}",
        f"市场环境特征数：{result.get('feature_columns', 'N/A')}",
    ]
    return _ensure_warning("\n".join(lines))


def _answer_report(result: dict) -> str:
    if not result.get("success"):
        return _ensure_warning(str(result.get("message", "报告生成失败。")))
    return _ensure_warning(f"Agent 每日报告已生成：{result.get('report_path')}")


def _answer_unknown() -> str:
    return _ensure_warning(
        "暂时没有识别出可调用的项目能力。可以尝试这样问：\n"
        "- 今天模型预测排名是什么？\n"
        "- 为什么排名第一？\n"
        "- 当前有哪些模型？\n"
        "- 默认回测方案表现怎么样？\n"
        "- 最近某类事件会影响哪些股票？\n"
        "- 根据 RAG 知识库回答问题。\n"
        "- 当前市场环境怎么样？"
    )


def _dispatch(intent: str, query: str, model_name: str | None, topk: int) -> tuple[str, ToolFunc | None, dict]:
    if intent == "query_latest_ranking":
        return "tool_query_latest_ranking", tool_adapter.tool_query_latest_ranking, {
            "topk": topk,
            "model_name": model_name,
        }
    if intent == "explain_stock":
        return "tool_explain_stock", tool_adapter.tool_explain_stock, {
            "stock_query": query,
            "model_name": model_name,
        }
    if intent == "query_model_zoo":
        return "tool_query_model_zoo", tool_adapter.tool_query_model_zoo, {}
    if intent == "query_backtest":
        return "tool_query_backtest", tool_adapter.tool_query_backtest, {
            "model_name": model_name,
        }
    if intent == "compare_models":
        return "tool_compare_models", tool_adapter.tool_compare_models, {}
    if intent == "query_news_mapping":
        return "tool_query_news_mapping", tool_adapter.tool_query_news_mapping, {"query": query}
    if intent == "query_rag":
        return "tool_query_rag", tool_adapter.tool_query_rag, {"question": query, "topk": topk}
    if intent == "query_market_context":
        return "tool_query_market_context", tool_adapter.tool_query_market_context, {}
    if intent == "generate_daily_report":
        from agent.report_agent import generate_daily_agent_report

        return "tool_generate_daily_report", generate_daily_agent_report, {"topk": topk}
    return "", None, {}


def _format_answer(intent: str, result: dict) -> str:
    answer_map = {
        "query_latest_ranking": _answer_latest_ranking,
        "explain_stock": _answer_stock_explanation,
        "query_model_zoo": _answer_model_zoo,
        "query_backtest": _answer_backtest,
        "compare_models": _answer_compare_models,
        "query_news_mapping": _answer_news_mapping,
        "query_rag": _answer_rag,
        "query_market_context": _answer_market_context,
        "generate_daily_report": _answer_report,
    }
    formatter = answer_map.get(intent)
    if formatter is None:
        return _answer_unknown()
    return formatter(result)


def _agent_should_use_llm(intent: str, prompt_text: str, api_key: str | None) -> bool:
    if not str(prompt_text or "").strip() or not str(api_key or "").strip():
        return False
    return intent in {
        "explain_stock",
        "query_rag",
        "query_news_mapping",
        "query_market_context",
    }


def _answer_with_llm(
    prompt_text: str,
    api_key: str,
    base_url: str,
    llm_model: str,
    cache_row: dict | None = None,
) -> str:
    from llm_explainer import explain_prompt_with_llm

    row = cache_row or {"date": "agent", "code": "agent", "name": "Agent 分析"}
    return explain_prompt_with_llm(
        stock_row=row,
        prompt_text=prompt_text,
        api_key=api_key,
        base_url=base_url,
        model=llm_model,
    )


def run_agent(
    query: str,
    model_name: str | None = None,
    topk: int = 10,
    prompt_text: str | None = None,
    llm_api_key: str | None = None,
    llm_base_url: str = "",
    llm_model: str = "",
    llm_cache_row: dict | None = None,
) -> AgentResponse:
    intent = route_intent(query)
    if intent == "unknown":
        return AgentResponse(answer=_answer_unknown(), intent=intent)

    tool_name, tool_func, tool_args = _dispatch(intent, query, model_name, topk)
    if tool_func is None:
        return AgentResponse(answer=_answer_unknown(), intent="unknown")

    try:
        result = tool_func(**tool_args)
    except Exception as exc:
        result = {
            "success": False,
            "message": f"工具调用失败：{type(exc).__name__}: {exc}",
        }

    tool_preview = _preview(result)
    tool_record = ToolCallRecord(
        intent=intent,
        tool_name=tool_name,
        tool_args=tool_args,
        success=bool(result.get("success")),
        message=str(result.get("message", "")),
        result_preview=tool_preview,
    )
    log_agent_call(
        query=query,
        intent=intent,
        tool_name=tool_name,
        tool_args=tool_args,
        success=tool_record.success,
        message=tool_record.message,
        result_preview=tool_preview,
    )

    tool_calls = [tool_record]
    if result.get("success") and _agent_should_use_llm(intent, str(prompt_text or ""), llm_api_key):
        answer = _answer_with_llm(
            prompt_text=str(prompt_text or ""),
            api_key=str(llm_api_key or ""),
            base_url=str(llm_base_url or ""),
            llm_model=str(llm_model or ""),
            cache_row=llm_cache_row,
        )
        llm_success = not answer.startswith("AI 解释生成失败")
        llm_record = ToolCallRecord(
            intent=intent,
            tool_name="llm_explain_prompt",
            tool_args={
                "model": llm_model,
                "base_url": llm_base_url,
                "prompt_chars": len(str(prompt_text or "")),
            },
            success=llm_success,
            message="Agent 判断该问题需要 AI 解释。" if llm_success else answer,
            result_preview=str(answer or "")[:120],
        )
        log_agent_call(
            query=query,
            intent=intent,
            tool_name=llm_record.tool_name,
            tool_args=llm_record.tool_args,
            success=llm_record.success,
            message=llm_record.message,
            result_preview=llm_record.result_preview,
        )
        tool_calls.append(llm_record)
        if not llm_success:
            answer = _format_answer(intent, result)
    else:
        answer = _format_answer(intent, result)

    return AgentResponse(
        answer=answer,
        intent=intent,
        tool_calls=tool_calls,
        data=result,
    )


def _run_once(query: str, topk: int) -> None:
    response = run_agent(query=query, topk=topk)
    print(response.answer)
    if response.tool_calls:
        print("\n工具调用：")
        for call in response.tool_calls:
            print(json_like(asdict(call)))


def json_like(data: dict) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="金融分析 Agent 命令行入口")
    parser.add_argument("--query", type=str, default="")
    parser.add_argument("--topk", type=int, default=10)
    args = parser.parse_args()

    if args.query:
        _run_once(args.query, args.topk)
        return

    print("金融分析 Agent 已启动，输入 exit 退出。")
    while True:
        query = input("用户：").strip()
        if query.lower() in {"exit", "quit", "q"}:
            break
        if not query:
            continue
        _run_once(query, args.topk)


if __name__ == "__main__":
    main()
