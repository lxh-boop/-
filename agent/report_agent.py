from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agent.schemas import RISK_WARNING
from agent.tool_adapter import (
    tool_compare_models,
    tool_query_backtest,
    tool_query_latest_ranking,
    tool_query_market_context,
    tool_query_model_zoo,
)
from core.config.paths import OUTPUTS_DIR


REPORT_DIR = OUTPUTS_DIR / "reports"


def _fmt(value, default: str = "N/A") -> str:
    if value is None or value == "":
        return default
    return str(value)


def _pct(value) -> str:
    try:
        return f"{float(value):.2%}"
    except Exception:
        return "N/A"


def generate_daily_agent_report(topk: int = 10) -> dict:
    ranking = tool_query_latest_ranking(topk=topk)
    model_zoo = tool_query_model_zoo()
    backtest = tool_query_backtest()
    market = tool_query_market_context()
    compare = tool_compare_models()

    now = datetime.now()
    report_path = REPORT_DIR / f"daily_agent_report_{now.strftime('%Y%m%d')}.md"
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    ranking_rows = ranking.get("records", []) if ranking.get("success") else []
    backtest_rows = backtest.get("records", []) if backtest.get("success") else []
    model_rows = model_zoo.get("model_zoo", []) if model_zoo.get("success") else []

    lines = [
        "# A股每日模型预测 Agent 报告",
        "",
        "## 1. 报告信息",
        f"- 生成时间：{now.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 数据截止日：{_fmt(ranking.get('trade_date'))}",
        f"- 预测交易日：{_fmt(ranking.get('predict_for_date'))}",
        f"- 使用模型：{_fmt(ranking.get('model_name') or model_zoo.get('default_model'))}",
        f"- TopK：{topk}",
        "",
        "## 2. 今日预测排名",
        "| 排名 | 股票代码 | 股票名称 | 模型分数 | 可信度 | 风险等级 |",
        "|---|---|---|---:|---|---|",
    ]
    if ranking_rows:
        for item in ranking_rows:
            score = item.get("score")
            try:
                score_text = f"{float(score):.3f}"
            except Exception:
                score_text = "N/A"
            lines.append(
                f"| {item.get('rank', '')} | {item.get('stock_code', '')} | "
                f"{item.get('stock_name', '')} | {score_text} | "
                f"{item.get('confidence', '')} | {item.get('risk_level', '')} |"
            )
    else:
        lines.append("| N/A | N/A | 未查询到预测排名，请先运行每日更新 | N/A | N/A | N/A |")

    lines.extend(
        [
            "",
            "## 3. 模型库状态",
            f"- 当前模型：{_fmt(model_zoo.get('default_model'))}",
            f"- Model Zoo 状态：登记 {len(model_rows)} 个模型",
            f"- latest 指针：{_fmt((model_zoo.get('latest_model') or {}).get('latest_dir'))}",
            "",
            "## 4. 回测表现",
        ]
    )
    if backtest_rows:
        item = backtest_rows[0]
        lines.extend(
            [
                f"- TopK：{_fmt(item.get('topk'))}",
                f"- 持有期：{_fmt(item.get('holding_days'))}",
                f"- 年化收益：{_pct(item.get('annual_return'))}",
                f"- 基准收益：{_pct(item.get('benchmark_return'))}",
                f"- IR：{_fmt(item.get('information_ratio'))}",
                f"- 最大回撤：{_pct(item.get('max_drawdown'))}",
                f"- 换手率：{_pct(item.get('turnover'))}",
            ]
        )
    else:
        lines.append("- 未查询到回测结果，请先运行回测脚本。")

    display_candidate = compare.get("display_candidate", {}) if compare.get("success") else {}
    if display_candidate:
        lines.extend(
            [
                "",
                "## 5. 模型比较摘要",
                f"- 项目展示候选：{_fmt(display_candidate.get('model_name'))}",
                f"- 年化收益：{_pct(display_candidate.get('annual_return'))}",
                f"- 最大回撤：{_pct(display_candidate.get('max_drawdown'))}",
            ]
        )

    lines.extend(["", "## 6. 市场环境"])
    if market.get("success"):
        lines.extend(
            [
                f"- 指数数据日期：{_fmt(market.get('index_date_min'))} 至 {_fmt(market.get('index_date_max'))}",
                f"- 市场环境特征数：{_fmt(market.get('feature_columns'))}",
                f"- 数据来源：{_fmt(market.get('data_source'))}",
            ]
        )
    else:
        lines.append(f"- {market.get('message', '未查询到市场环境数据。')}")

    lines.extend(
        [
            "",
            "## 7. 风险与限制",
            "- 数据截止日可能滞后。",
            "- 模型预测结果只表示相对排序。",
            "- 回测结果不代表未来表现。",
            "- 新闻映射和 RAG 结果取决于本地缓存和索引质量。",
            "",
            "## 8. 免责声明",
            RISK_WARNING,
            "",
        ]
    )

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return {
        "success": True,
        "message": "Agent 每日报告已生成。",
        "report_path": str(report_path),
    }


def main() -> None:
    result = generate_daily_agent_report()
    print(result.get("report_path"))


if __name__ == "__main__":
    main()
