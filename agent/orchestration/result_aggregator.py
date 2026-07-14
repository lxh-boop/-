from __future__ import annotations

from typing import Any


ZH = "zh"
EN = "en"


def _normalise_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    if "." in text:
        left, right = text.split(".", 1)
        if left.isdigit():
            text = left
        elif right.isdigit():
            text = right
    digits = "".join(char for char in text if char.isdigit())
    return digits[-6:].zfill(6) if digits else ""


def _first_present(
    data: dict[str, Any],
    keys: list[str],
    default: Any = None,
) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _number(value: Any, digits: int = 3) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def _percent(value: Any, *, hide_zero: bool = False) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"

    if hide_zero and abs(number) < 1e-12:
        return "-"

    return f"{number * 100:.2f}%"


def _task_by_intent(
    task_results: dict[str, dict[str, Any]],
    intent: str,
) -> dict[str, Any] | None:
    for result in task_results.values():
        if result.get("intent") == intent:
            return result
    return None


def _first_mcp_evidence_task(
    task_results: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    for result in task_results.values():
        if str(result.get("intent") or "").startswith("mcp.") and result.get("success"):
            return result
    return None


def _portfolio_map(
    portfolio_task: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if not portfolio_task:
        return {}

    data = dict(portfolio_task.get("data") or {})
    positions = data.get("positions") or []
    result: dict[str, dict[str, Any]] = {}

    if not isinstance(positions, list):
        return result

    for raw in positions:
        if not isinstance(raw, dict):
            continue
        code = _normalise_code(
            _first_present(
                raw,
                ["stock_code", "code", "ts_code"],
                "",
            )
        )
        if code:
            result[code] = dict(raw)

    return result


def _analysis_map(
    analysis_task: dict[str, Any] | None,
) -> tuple[dict[str, dict[str, Any]], int]:
    result: dict[str, dict[str, Any]] = {}
    failed = 0

    if not analysis_task:
        return result, failed

    items = analysis_task.get("items") or []
    if not isinstance(items, list):
        data = analysis_task.get("data")
        if isinstance(data, dict):
            code = _normalise_code(data.get("stock_code"))
            if code:
                result[code] = data
        return result, failed

    for item in items:
        if not isinstance(item, dict):
            continue
        if not item.get("success"):
            failed += 1
            continue
        data = dict(item.get("data") or {})
        code = _normalise_code(
            data.get("stock_code")
            or (item.get("arguments") or {}).get("stock_code")
        )
        if code:
            result[code] = data

    return result, failed


def _review_direction(
    ratio: float,
    language: str,
) -> str:
    if ratio <= 0:
        return (
            "Do not add / exit review"
            if language == EN
            else "不新增/退出复核"
        )
    if ratio < 0.95:
        return (
            "Reduce-weight review"
            if language == EN
            else "降低仓位复核"
        )
    if ratio > 1.05:
        return (
            "Increase-weight review"
            if language == EN
            else "提高仓位复核"
        )
    return (
        "Maintain-weight review"
        if language == EN
        else "维持仓位复核"
    )


def _aggregate_ranking_portfolio_analysis(
    task_results: dict[str, dict[str, Any]],
    *,
    language: str,
) -> str | None:
    ranking_task = _task_by_intent(
        task_results,
        "ranking",
    )
    analysis_task = _task_by_intent(
        task_results,
        "stock_analysis",
    )

    if not ranking_task or not analysis_task:
        return None

    ranking_data = dict(ranking_task.get("data") or {})
    records = ranking_data.get("records") or []
    if not isinstance(records, list) or not records:
        return None

    portfolio_task = _task_by_intent(
        task_results,
        "portfolio_state",
    )
    positions = _portfolio_map(portfolio_task)
    analyses, failed_count = _analysis_map(analysis_task)

    if language == EN:
        lines = [
            "The prediction ranking, current paper-trading positions, "
            "and stock-level analysis have been combined.",
            "",
            f"- Ranked stocks analyzed: {len(records)}",
            f"- Current positions appearing in the ranking: "
            f"{sum(1 for row in records if _normalise_code(_first_present(row, ['stock_code', 'code', 'ts_code'], '')) in positions)}",
            f"- Failed stock analyses: {failed_count}",
            "",
            "| Rank | Code | Name | Currently Held | Current Weight | "
            "Combined Adjustment | Position Ratio | Review Direction |",
            "|---:|---|---|---|---:|---:|---:|---|",
        ]
    else:
        lines = [
            "已结合预测排名、当前模拟盘持仓和逐只股票分析结果。",
            "",
            f"- 已分析排名股票：{len(records)} 只",
            f"- 当前持仓中进入该排名："
            f"{sum(1 for row in records if _normalise_code(_first_present(row, ['stock_code', 'code', 'ts_code'], '')) in positions)} 只",
            f"- 个股分析失败：{failed_count} 只",
            "",
            "| 排名 | 股票代码 | 股票名称 | 当前持有 | 当前仓位 | "
            "综合调整分 | 仓位调整倍率 | 仓位复核方向 |",
            "|---:|---|---|---|---:|---:|---:|---|",
        ]

    reduce_codes: list[str] = []

    for index, raw_row in enumerate(records, start=1):
        if not isinstance(raw_row, dict):
            continue

        code = _normalise_code(
            _first_present(
                raw_row,
                ["stock_code", "code", "ts_code"],
                "",
            )
        )
        name = str(
            _first_present(
                raw_row,
                ["stock_name", "name"],
                "-",
            )
        )
        rank = _first_present(
            raw_row,
            ["rank", "ranking"],
            index,
        )

        analysis = analyses.get(code, {})
        position = positions.get(code, {})

        current_weight = _first_present(
            analysis,
            ["current_weight"],
            _first_present(
                position,
                ["position_ratio", "weight"],
                0.0,
            ),
        )
        combined_adjustment = _first_present(
            analysis,
            ["combined_adjustment"],
            0.0,
        )
        ratio = _float(
            _first_present(
                analysis,
                ["position_adjustment_ratio"],
                1.0,
            ),
            1.0,
        )
        held = code in positions or _float(current_weight) > 0
        direction = _review_direction(ratio, language)

        if held and ratio < 0.95:
            reduce_codes.append(code)

        held_text = (
            "Yes" if held else "No"
        ) if language == EN else (
            "是" if held else "否"
        )

        lines.append(
            f"| {rank} | {code or '-'} | {name} | {held_text} | "
            f"{_percent(current_weight)} | "
            f"{_number(combined_adjustment)} | "
            f"{_number(ratio)} | {direction} |"
        )

    lines.append("")

    if language == EN:
        if reduce_codes:
            lines.append(
                "Positions requiring reduce-weight review: "
                + ", ".join(reduce_codes)
                + "."
            )
        else:
            lines.append(
                "No currently held ranked stock triggered the "
                "reduce-weight review threshold."
            )
        lines.append(
            "The review direction is derived from the existing "
            "position_adjustment_ratio and is not a live-trading instruction."
        )
    else:
        if reduce_codes:
            lines.append(
                "当前持仓中需要重点进行降低仓位复核的股票："
                + "、".join(reduce_codes)
                + "。"
            )
        else:
            lines.append(
                "当前持有且进入该排名的股票中，没有触发降低仓位复核阈值的标的。"
            )
        lines.append(
            "上述方向仅根据现有 position_adjustment_ratio 进行模拟盘复核，"
            "不是实盘交易指令。"
        )

    return "\n".join(lines)


def _aggregate_portfolio_stability_recommendation(
    task_results: dict[str, dict[str, Any]],
    *,
    language: str,
) -> str | None:
    portfolio_task = _task_by_intent(task_results, "portfolio_state")
    risk_task = _task_by_intent(task_results, "portfolio_risk")
    ranking_task = _task_by_intent(task_results, "ranking") or _first_mcp_evidence_task(task_results)
    if not portfolio_task or not risk_task or not ranking_task:
        return None
    if not portfolio_task.get("success") or not risk_task.get("success"):
        return None

    portfolio_data = dict(portfolio_task.get("data") or {})
    positions = portfolio_data.get("positions") or []
    if not isinstance(positions, list):
        positions = []
    risk_data = dict(risk_task.get("data") or {})
    report = risk_data.get("risk_report") if isinstance(risk_data.get("risk_report"), dict) else {}
    ranking_data = dict(ranking_task.get("data") or {})
    records = ranking_data.get("records") or ranking_data.get("items") or []
    if not isinstance(records, list):
        records = []
    evidence_source = "mcp" if str(ranking_task.get("intent") or "").startswith("mcp.") else "local_ranking"

    candidate_lines: list[str] = []
    held_codes = {
        _normalise_code(_first_present(row, ["stock_code", "code", "ts_code"], ""))
        for row in positions
        if isinstance(row, dict)
    }
    for raw in records[:5]:
        if not isinstance(raw, dict):
            continue
        code = _normalise_code(_first_present(raw, ["stock_code", "code", "ts_code"], ""))
        name = _first_present(raw, ["stock_name", "name"], "-")
        rank = _first_present(raw, ["rank", "ranking"], "-")
        held = code in held_codes
        if language == EN:
            candidate_lines.append(
                f"- Rank {rank}: {code or '-'} {name} "
                f"({'already held' if held else 'candidate'})"
            )
        else:
            candidate_lines.append(
                f"- 排名 {rank}：{code or '-'} {name}"
                f"（{'已持有' if held else '候选'}）"
            )

    risk_level = _risk_scalar(
        report,
        ["risk_level", "overall_risk_level", "portfolio_risk_level", "level"],
    )
    max_position = _risk_scalar(
        report,
        ["max_single_position", "largest_position_weight", "max_position_weight", "top1_weight"],
    )
    cash_ratio = _risk_scalar(report, ["cash_ratio", "cash_weight"])
    concentration = _risk_scalar(
        report,
        ["concentration_hhi", "hhi", "concentration", "top3_concentration", "top3_weight"],
    )
    warnings = _risk_list(report, ["risk_warnings", "warnings", "violations", "breaches", "alerts"])

    if language == EN:
        lines = [
            "More robust paper-portfolio recommendation:",
            "",
            "Risk analysis:",
            f"- Current position count: {len(positions)}",
        ]
        if risk_level is not None:
            lines.append(f"- Risk level: {risk_level}")
        if max_position is not None:
            lines.append(f"- Largest single-position weight: {_percent(max_position)}")
        if cash_ratio is not None:
            lines.append(f"- Cash ratio: {_percent(cash_ratio)}")
        if concentration is not None:
            lines.append(f"- Concentration indicator: {_number(concentration)}")
        if warnings:
            lines.extend(f"- Warning: {item}" for item in warnings[:3])

        lines.extend(
            [
                "",
                "Recommendation plan:",
                "- Prefer a diversified candidate set instead of adding to the largest current holding.",
                "- Use ranking candidates as read-only evidence, then keep final changes as a confirmation-required preview.",
                "- Do not execute any rebalance automatically from this answer.",
            ]
        )
        if candidate_lines:
            lines.extend(["", f"Candidate evidence ({evidence_source}):", *candidate_lines])
        lines.extend(
            [
                "",
                "Why this is more robust:",
                "- It combines current holdings, portfolio risk, and model-ranked candidates.",
                "- It reduces concentration pressure before considering additional exposure.",
                "- It keeps execution behind the existing confirmation and revalidation boundary.",
            ]
        )
    else:
        lines = [
            "更稳健的模拟盘持仓建议：",
            "",
            "风险分析：",
            f"- 当前持仓数量：{len(positions)}",
        ]
        if risk_level is not None:
            lines.append(f"- 风险等级：{risk_level}")
        if max_position is not None:
            lines.append(f"- 最大单股仓位：{_percent(max_position)}")
        if cash_ratio is not None:
            lines.append(f"- 现金比例：{_percent(cash_ratio)}")
        if concentration is not None:
            lines.append(f"- 集中度指标：{_number(concentration)}")
        if warnings:
            lines.extend(f"- 风险提示：{item}" for item in warnings[:3])

        lines.extend(
            [
                "",
                "推荐方案：",
                "- 优先选择分散化候选，不直接继续增加当前最大仓位股票。",
                "- 以模型排名候选作为只读证据，再结合持仓风险做模拟盘预览。",
                "- 本回答只生成建议，不自动执行调仓；真实写入仍需确认、复校验和 Commit。",
            ]
        )
        if candidate_lines:
            lines.extend(["", "候选证据：", *candidate_lines])
        lines.extend(
            [
                "",
                "为什么更稳健：",
                "- 同时使用当前持仓、组合风险和模型排名候选，避免只看持仓列表。",
                "- 先识别集中度、现金比例和单股暴露，再考虑候选替换或分散。",
                "- 调仓动作仍被审批和重新校验链路保护，不会绕过模拟盘安全边界。",
            ]
        )

    return "\n".join(lines)




def _risk_scalar(
    report: dict[str, Any],
    keys: list[str],
) -> Any:
    for key in keys:
        value = report.get(key)
        if value not in (None, ""):
            return value
    return None


def _risk_list(
    report: dict[str, Any],
    keys: list[str],
) -> list[str]:
    for key in keys:
        value = report.get(key)
        if isinstance(value, list):
            return [
                str(item)
                for item in value
                if str(item).strip()
            ]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
    return []


def _aggregate_portfolio_risk(
    task_results: dict[str, dict[str, Any]],
    *,
    language: str,
) -> str | None:
    risk_task = _task_by_intent(
        task_results,
        "portfolio_risk",
    )
    if not risk_task or not risk_task.get("success"):
        return None

    data = dict(risk_task.get("data") or {})
    report = data.get("risk_report")
    if not isinstance(report, dict):
        report = {}

    source = str(data.get("source") or "")
    risk_level = _risk_scalar(
        report,
        [
            "risk_level",
            "overall_risk_level",
            "portfolio_risk_level",
            "level",
        ],
    )
    risk_score = _risk_scalar(
        report,
        [
            "risk_score",
            "overall_risk_score",
            "portfolio_risk_score",
        ],
    )
    position_count = _risk_scalar(
        report,
        [
            "position_count",
            "num_positions",
            "holding_count",
        ],
    )
    invested_ratio = _risk_scalar(
        report,
        [
            "invested_ratio",
            "position_ratio",
            "gross_exposure",
            "total_exposure",
        ],
    )
    cash_ratio = _risk_scalar(
        report,
        [
            "cash_ratio",
            "cash_weight",
        ],
    )
    max_position = _risk_scalar(
        report,
        [
            "max_single_position",
            "largest_position_weight",
            "max_position_weight",
            "top1_weight",
        ],
    )
    concentration = _risk_scalar(
        report,
        [
            "concentration_hhi",
            "hhi",
            "concentration",
            "top3_concentration",
            "top3_weight",
        ],
    )
    max_drawdown = _risk_scalar(
        report,
        [
            "max_drawdown",
            "drawdown",
            "portfolio_drawdown",
        ],
    )
    volatility = _risk_scalar(
        report,
        [
            "annualized_volatility",
            "portfolio_volatility",
            "volatility",
            "daily_volatility",
        ],
    )
    warnings = _risk_list(
        report,
        [
            "risk_warnings",
            "warnings",
            "violations",
            "breaches",
            "alerts",
        ],
    )

    if language == EN:
        lines = ["Paper-trading portfolio risk analysis:", ""]
        source_text = (
            "latest saved snapshot"
            if source == "latest_snapshot"
            else "calculated from the current account and positions"
        )
        lines.append(f"- Data source: {source_text}")
        if risk_level is not None:
            lines.append(f"- Risk level: {risk_level}")
        if risk_score is not None:
            lines.append(
                f"- Risk score: {_number(risk_score)}"
            )
        if position_count is not None:
            lines.append(
                f"- Number of positions: {position_count}"
            )
        if invested_ratio is not None:
            lines.append(
                f"- Invested ratio: {_percent(invested_ratio)}"
            )
        if cash_ratio is not None:
            lines.append(
                f"- Cash ratio: {_percent(cash_ratio)}"
            )
        if max_position is not None:
            lines.append(
                f"- Largest single-position weight: "
                f"{_percent(max_position)}"
            )
        if concentration is not None:
            lines.append(
                f"- Concentration indicator: "
                f"{_number(concentration)}"
            )
        if max_drawdown is not None:
            lines.append(
                f"- Maximum drawdown: "
                f"{_percent(max_drawdown)}"
            )
        if volatility is not None:
            lines.append(
                f"- Volatility: {_percent(volatility)}"
            )
        if warnings:
            lines.extend(["", "Risk warnings:"])
            lines.extend(
                f"- {item}" for item in warnings[:10]
            )
    else:
        lines = ["当前模拟盘组合风险分析：", ""]
        source_text = (
            "最新已保存风险快照"
            if source == "latest_snapshot"
            else "根据当前账户、持仓和用户约束实时计算"
        )
        lines.append(f"- 数据来源：{source_text}")
        if risk_level is not None:
            lines.append(f"- 风险等级：{risk_level}")
        if risk_score is not None:
            lines.append(
                f"- 风险分数：{_number(risk_score)}"
            )
        if position_count is not None:
            lines.append(
                f"- 持仓数量：{position_count}"
            )
        if invested_ratio is not None:
            lines.append(
                f"- 已投资比例：{_percent(invested_ratio)}"
            )
        if cash_ratio is not None:
            lines.append(
                f"- 现金比例：{_percent(cash_ratio)}"
            )
        if max_position is not None:
            lines.append(
                f"- 最大单股仓位：{_percent(max_position)}"
            )
        if concentration is not None:
            lines.append(
                f"- 集中度指标：{_number(concentration)}"
            )
        if max_drawdown is not None:
            lines.append(
                f"- 最大回撤：{_percent(max_drawdown)}"
            )
        if volatility is not None:
            lines.append(
                f"- 波动率：{_percent(volatility)}"
            )
        if warnings:
            lines.extend(["", "风险提示："])
            lines.extend(
                f"- {item}" for item in warnings[:10]
            )

    recognised = any(
        value is not None
        for value in [
            risk_level,
            risk_score,
            position_count,
            invested_ratio,
            cash_ratio,
            max_position,
            concentration,
            max_drawdown,
            volatility,
        ]
    )

    if not recognised and report:
        scalar_items = [
            (key, value)
            for key, value in report.items()
            if isinstance(
                value,
                (str, int, float, bool),
            )
            and value not in ("", None)
        ][:12]

        if scalar_items:
            lines.extend([
                "",
                (
                    "Other risk fields:"
                    if language == EN
                    else "其他风险字段："
                ),
            ])
            for key, value in scalar_items:
                lines.append(f"- {key}: {value}")

    if not report:
        lines.extend([
            "",
            (
                "No valid risk-report fields were returned."
                if language == EN
                else "当前工具未返回有效的风险报告字段。"
            ),
        ])

    return "\n".join(lines)


def _generic_summary(
    task_results: dict[str, dict[str, Any]],
    *,
    language: str,
) -> str:
    success_count = sum(
        1
        for item in task_results.values()
        if item.get("success")
    )
    failed_count = len(task_results) - success_count

    if language == EN:
        lines = [
            "The multi-step request has been processed.",
            "",
            f"- Successful tasks: {success_count}",
            f"- Failed tasks: {failed_count}",
            "",
        ]
    else:
        lines = [
            "复合任务已完成处理。",
            "",
            f"- 成功任务：{success_count} 个",
            f"- 失败任务：{failed_count} 个",
            "",
        ]

    for task_id, result in task_results.items():
        status = (
            "success" if result.get("success") else "failed"
        )
        lines.append(
            f"- {task_id}: {result.get('intent', 'unknown')} "
            f"({status})"
        )

    return "\n".join(lines)



def _task_by_any_intent(task_results: dict[str, dict[str, Any]], intents: set[str]) -> dict[str, Any] | None:
    for result in task_results.values():
        if str(result.get("intent") or "") in intents:
            return result
    return None


def _aggregate_target_portfolio(task_results: dict[str, dict[str, Any]], *, language: str) -> str | None:
    task = _task_by_any_intent(task_results, {"portfolio.construct_target_portfolio", "construct_target_portfolio"})
    if not task or not task.get("success"):
        return None
    data = dict(task.get("data") or {})
    target = data.get("target_portfolio") if isinstance(data.get("target_portfolio"), dict) else data
    positions = target.get("target_positions") or []
    if not isinstance(positions, list) or not positions:
        return None
    cash = _first_present(target, ["target_cash_weight", "cash_weight"], 0.0)
    if language == EN:
        lines = ["Structured target paper portfolio:", "", f"- Target cash weight: {_percent(cash)}", "", "| Stock | Name | Target weight | Industry |", "|---|---|---:|---|"]
    else:
        lines = ["结构化目标模拟组合：", "", f"- 目标现金比例：{_percent(cash)}", "", "| 股票代码 | 股票名称 | 目标仓位 | 行业 |", "|---|---|---:|---|"]
    for raw in positions:
        if not isinstance(raw, dict):
            continue
        lines.append(
            f"| {_first_present(raw, ['stock_code', 'code'], '-')} | "
            f"{_first_present(raw, ['stock_name', 'name'], '-')} | "
            f"{_percent(_first_present(raw, ['target_weight', 'weight'], 0.0))} | "
            f"{_first_present(raw, ['industry'], '-')} |"
        )
    ref = data.get("target_portfolio_ref") if isinstance(data.get("target_portfolio_ref"), dict) else {}
    artifact_id = str(ref.get("artifact_id") or data.get("artifact_id") or "")
    if artifact_id:
        lines.extend(["", ("- Target portfolio reference: " if language == EN else "- 目标组合引用：") + artifact_id])
    lines.extend(["", "This is a read-only target portfolio. No order was created." if language == EN else "该结果为只读目标组合，没有生成订单，也没有修改模拟盘。"])
    return "\n".join(lines)


def _aggregate_portfolio_comparison(task_results: dict[str, dict[str, Any]], *, language: str) -> str | None:
    task = _task_by_any_intent(task_results, {"portfolio.compare_portfolios", "compare_portfolios"})
    if not task or not task.get("success"):
        return None
    data = dict(task.get("data") or {})
    comparison = data.get("portfolio_comparison") if isinstance(data.get("portfolio_comparison"), dict) else {}
    rows = comparison.get("rows") or data.get("current_vs_target") or []
    if not isinstance(rows, list):
        return None
    if language == EN:
        lines = ["Current versus target paper portfolio:", "", "| Stock | Name | Change | Current | Target | Delta |", "|---|---|---|---:|---:|---:|"]
    else:
        lines = ["当前模拟组合与目标组合对比：", "", "| 股票代码 | 股票名称 | 变化 | 当前仓位 | 目标仓位 | 仓位差 |", "|---|---|---|---:|---:|---:|"]
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        lines.append(
            f"| {_first_present(raw, ['stock_code', 'code'], '-')} | "
            f"{_first_present(raw, ['stock_name', 'name'], '-')} | "
            f"{_first_present(raw, ['change_type'], '-')} | "
            f"{_percent(_first_present(raw, ['current_weight'], 0.0))} | "
            f"{_percent(_first_present(raw, ['target_weight'], 0.0))} | "
            f"{_percent(_first_present(raw, ['weight_delta'], 0.0))} |"
        )
    cash = comparison.get("cash_difference") if isinstance(comparison.get("cash_difference"), dict) else {}
    if cash:
        lines.extend(["", ("Cash-weight delta: " if language == EN else "现金比例变化：") + _percent(cash.get("cash_weight_delta"))])
    lines.extend(["", "No rebalance was executed." if language == EN else "本次只完成结构化比较，没有执行调仓。"])
    return "\n".join(lines)

def aggregate_multi_task_answer(
    task_results: dict[str, dict[str, Any]],
    *,
    language: str = ZH,
) -> str:
    normalised_language = (
        EN if str(language).lower() == EN else ZH
    )

    comparison = _aggregate_portfolio_comparison(task_results, language=normalised_language)
    if comparison:
        return comparison

    target_portfolio = _aggregate_target_portfolio(task_results, language=normalised_language)
    if target_portfolio:
        return target_portfolio

    specialised = _aggregate_ranking_portfolio_analysis(
        task_results,
        language=normalised_language,
    )
    if specialised:
        return specialised

    stability_recommendation = _aggregate_portfolio_stability_recommendation(
        task_results,
        language=normalised_language,
    )
    if stability_recommendation:
        return stability_recommendation

    risk_summary = _aggregate_portfolio_risk(
        task_results,
        language=normalised_language,
    )
    if risk_summary:
        return risk_summary

    return _generic_summary(
        task_results,
        language=normalised_language,
    )
