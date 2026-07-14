from __future__ import annotations

import json
from typing import Any


# These names are the executable/compatible capability names already understood by
# the current executor.  They are descriptions for the LLM, not permission grants.
INTENT_CATALOG: dict[str, dict[str, Any]] = {
    "ranking": {
        "description": "读取最新股票预测排名、TopK 或今日选股结果。",
        "operation_type": "read",
        "parameters": ["top_k", "model_name"],
        "produced_outputs": ["ranking", "candidate_stocks"],
    },
    "portfolio_state": {
        "description": "读取当前模拟盘账户、现金、持仓和订单状态。只表示当前状态，不等于风险分析、比较或建议。",
        "operation_type": "read",
        "parameters": ["user_id"],
        "produced_outputs": ["current_portfolio", "cash", "positions", "orders"],
    },
    "portfolio_risk": {
        "description": "读取或计算当前模拟组合风险。只分析风险，不主动生成调仓建议。",
        "operation_type": "read",
        "parameters": ["user_id"],
        "produced_outputs": ["portfolio_risk", "position_concentration", "industry_concentration", "cash_ratio"],
    },
    "user_profile": {
        "description": "读取当前用户风险画像、投资目标和约束。",
        "operation_type": "read",
        "parameters": ["user_id"],
        "produced_outputs": ["risk_profile", "user_constraints"],
    },
    "stock_lookup": {
        "description": "把股票名称或不完整代码解析为明确股票代码。",
        "operation_type": "read",
        "parameters": ["stock_query", "stock_code", "user_id"],
        "produced_outputs": ["stock_identity"],
    },
    "stock_analysis": {
        "description": "分析一只明确股票的排名、AI 调整、新闻证据和用户适配。",
        "operation_type": "read",
        "parameters": ["stock_code", "top_k", "include_rag"],
        "produced_outputs": ["stock_analysis"],
    },
    "stock_news": {
        "description": "查询一只明确股票的映射新闻。",
        "operation_type": "read",
        "parameters": ["stock_code", "as_of_date", "limit"],
        "produced_outputs": ["news_evidence"],
    },
    "stock_rag": {
        "description": "查询一只明确股票的 RAG 证据。",
        "operation_type": "read",
        "parameters": ["stock_code", "top_k", "query"],
        "produced_outputs": ["rag_evidence", "source_refs"],
    },
    "position_recommendation": {
        "description": "为一只明确股票生成模拟仓位建议。只生成建议，不执行。",
        "operation_type": "read",
        "parameters": ["stock_code", "requested_weight", "top_k"],
        "produced_outputs": ["position_recommendation"],
    },
    "replacement_recommendation": {
        "description": "为候选股票寻找模拟盘中的可替换持仓。只生成建议，不执行。",
        "operation_type": "read",
        "parameters": ["stock_code", "requested_weight"],
        "produced_outputs": ["replacement_recommendation"],
    },
    "one_time_position_operation": {
        "description": "针对今天/本次的模拟盘持仓修改生成待确认预览，不直接执行。",
        "operation_type": "preview",
        "parameters": [
            "stock_code", "requested_weight", "position_adjustment_ratio",
            "requested_quantity", "cash_weight", "target_position_count", "query",
        ],
        "produced_outputs": ["proposal", "approval_request"],
    },
    "strategy_change": {
        "description": "对以后/长期/每次适用的持仓策略生成变更提案，不直接生效。",
        "operation_type": "preview",
        "parameters": ["requirement", "top_k", "target_position_count"],
        "produced_outputs": ["strategy_proposal", "approval_request"],
    },
    "capital_management": {
        "description": "创建模拟资金入金或出金的待确认预览。",
        "operation_type": "preview",
        "parameters": ["flow_type", "amount", "effective_date"],
        "produced_outputs": ["capital_proposal", "approval_request"],
    },
    "backfill": {
        "description": "创建历史模拟回放的待确认预览。",
        "operation_type": "preview",
        "parameters": ["start_date", "end_date"],
        "produced_outputs": ["backfill_proposal", "approval_request"],
    },
    "confirm_execute": {
        "description": "使用计划 ID 和确认令牌执行已确认且重新校验通过的模拟盘计划。",
        "operation_type": "write",
        "parameters": ["plan_id", "confirmation_token"],
        "produced_outputs": ["revalidation_result", "commit_result", "audit_record"],
    },
    "scheduler_status": {
        "description": "查询每日自动更新和调度状态。",
        "operation_type": "read",
        "parameters": [],
        "produced_outputs": ["scheduler_status"],
    },
    "report": {
        "description": "查询已经生成的项目报告。",
        "operation_type": "read",
        "parameters": [],
        "produced_outputs": ["reports"],
    },
    "model_zoo": {
        "description": "查询模型库、当前模型和本地模型状态。",
        "operation_type": "read",
        "parameters": [],
        "produced_outputs": ["model_status"],
    },
    "backtest": {
        "description": "查询已有回测指标，不自动重新回测。",
        "operation_type": "read",
        "parameters": ["model_name", "top_k", "holding_days"],
        "produced_outputs": ["backtest_metrics"],
    },
    "compare_models": {
        "description": "比较已有模型的回测表现。不能用于比较两个持仓组合。",
        "operation_type": "read",
        "parameters": ["metric"],
        "produced_outputs": ["model_comparison"],
    },
    "news_mapping": {
        "description": "分析一个新闻或事件可能影响的股票。",
        "operation_type": "read",
        "parameters": ["event_query"],
        "produced_outputs": ["event_stock_mapping"],
    },
    "market_context": {
        "description": "查询本地市场环境、指数和市场特征。",
        "operation_type": "read",
        "parameters": [],
        "produced_outputs": ["market_context"],
    },
    "daily_report": {
        "description": "生成或查询 Agent 每日分析报告。",
        "operation_type": "read",
        "parameters": ["top_k"],
        "produced_outputs": ["daily_report"],
    },
    "python_sandbox_analysis": {
        "description": "在明确、已提供且无敏感字段的只读快照上执行受限 Python 分析。只有上下文确实提供输入快照时才可规划；不得凭空构造 snapshot 或代码结果。",
        "operation_type": "read",
        "parameters": ["code", "snapshot", "snapshot_id", "timeout_seconds", "max_output_chars"],
        "produced_outputs": ["deterministic_analysis"],
    },
    "portfolio.design_target_portfolio": {
        "description": "在读取真实的当前持仓、风险报告、用户画像和模型排名后，由 LLM 主动设计完整目标组合参数。用户不必先填写持仓数量、现金比例或候选策略；只有真实数据缺失或冲突时才澄清。",
        "operation_type": "read",
        "parameters": [
            "current_portfolio", "ranking", "risk_report", "user_profile",
            "query", "user_goal"
        ],
        "produced_outputs": [
            "target_design", "target_position_count", "target_cash_weight",
            "candidate_policy", "allocation_method", "design_rationale",
            "assumptions", "source_map", "not_executed"
        ],
    },
    "portfolio.construct_target_portfolio": {
        "description": "根据上一步 LLM 生成的 target_design、当前模拟盘、排名和用户风险上限，确定性生成完整结构化目标组合。它负责精确计算和硬约束，不重新决定业务目标，不创建订单。",
        "operation_type": "read",
        "parameters": [
            "user_id", "current_portfolio", "ranking", "risk_report", "user_profile",
            "target_design", "target_position_count", "target_cash_weight",
            "candidate_policy", "allocation_method", "max_single_weight",
            "max_industry_weight"
        ],
        "required_task_inputs": ["current_portfolio", "ranking", "target_design"],
        "candidate_policy_values": [
            "ranking_only", "retain_ranked_current_then_ranking", "current_only_reweight"
        ],
        "allocation_method_values": ["equal_weight_with_caps"],
        "produced_outputs": [
            "target_portfolio", "target_positions", "target_portfolio_ref",
            "current_risk_snapshot", "target_risk_snapshot", "not_executed"
        ],
    },
    "portfolio.load_target_portfolio": {
        "description": "按当前会话和明确引用读取之前保存的结构化目标组合。没有目标组合或存在多个歧义引用时必须澄清。",
        "operation_type": "read",
        "parameters": ["user_id", "conversation_id", "artifact_id"],
        "produced_outputs": ["target_portfolio", "target_portfolio_ref"],
    },
    "portfolio.compare_portfolios": {
        "description": "确定性比较当前组合和结构化目标组合，输出股票、仓位、现金和风险差异；不生成订单。",
        "operation_type": "read",
        "parameters": ["current_portfolio", "target_portfolio"],
        "produced_outputs": [
            "portfolio_comparison", "current_vs_target", "added_stocks", "removed_stocks",
            "increased_stocks", "decreased_stocks", "cash_difference", "risk_before_after"
        ],
    },
    "general_help": {
        "description": "说明 Agent 当前能够做什么。",
        "operation_type": "read",
        "parameters": [],
        "produced_outputs": ["help"],
    },
}


PLANNER_SYSTEM_PROMPT = r'''
你是金融项目 Agent 的 LLM-First 用户目标解析器和任务规划器。
你不执行工具，不生成投资结论，只输出一个结构化 JSON 对象。

职责分工：
- 原始用户消息和 Context Packet 是事实来源。
- rule_hints 只是非裁决性建议，不是最终意图；可以纠正或忽略。
- 你负责生成唯一 UserGoal 和唯一 TaskPlan。
- 权限、Approval、Revalidate、Commit、Schema、预算由后续硬安全层检查。

必须遵守：
1. 不得凭经验补全用户没有提供且上下文中也不存在的对象、股票代码、日期、金额、仓位、计划 ID、确认令牌或比较基准。
2. 有不确定性、指代不清、比较对象缺失、上下文冲突或必要参数缺失时，必须 need_clarification=true，并提出一个具体问题；不要先执行一个看起来接近的工具。
3. 必须判断动作属于 query、analyze、compare、explain、recommend、construct、preview、execute、modify_policy、clarify 中哪一种。
4. 必须区分对象和动作：“持仓”通常是对象，不能因为出现“持仓”就自动等于 portfolio_state。
5. 不得扩大用户目标：
   - 只要求风险分析，不得主动增加候选股票、持仓建议、调仓方案或 proposal；
   - 只要求当前状态，不得主动做风险分析；
   - 只要求建议，不得声称已经执行；
   - 只要求解释，不得生成新的写操作。
6. 用户说“和现在的持仓做对比”“跟刚才的方案比较”等续问时：
   - 必须从 Context Packet 中确认另一侧比较对象和可用引用；
   - 找不到明确比较对象或可读取引用时，必须澄清；
   - 不能退化为只调用 portfolio_state。
7. 只能使用 available_intents 中的 intent；不得创造能力名，也不得把 compare_models 用于组合比较。
8. 如果现有工具目录无法可靠完成目标，返回 unsupported_reason 或请求澄清，不要拼凑不匹配的工具。
9. user_id、session_id、default_top_k 等系统参数可使用 $context 引用；不得要求用户重复提供。
10. 一个 task 只完成一个明确能力；依赖通过 depends_on 表达。
11. completion_contract.required_outputs 必须覆盖 UserGoal.expected_outputs。
12. 分析/建议通常 requires_write=false。生成待确认预案 requires_write=true，但只能规划 preview 类能力。真正执行只有用户明确确认且上下文中存在 plan_id 和 confirmation_token 时才可规划 confirm_execute。
13. 输出 confidence 必须真实反映不确定性。confidence < 0.60 时必须澄清，不能执行。
14. reason_summary 只能给简短、可展示的依据，不输出隐藏推理过程。
15. “推荐一个更稳健的持仓/组合”只有在能够产出完整结构化目标组合时才算完成：必须规划 portfolio.construct_target_portfolio；仅有 ranking、portfolio_state、portfolio_risk 或一段文字不算目标组合。
16. 对“推荐一个更稳健的持仓/组合”，不要因为用户没有亲自指定 target_position_count、target_cash_weight、candidate_policy、allocation_method 就先询问用户。你必须规划 portfolio.design_target_portfolio，让第二个 LLM 决策步骤在真实持仓、风险、用户画像、策略配置和排名数据可用后主动设计这些参数。
17. 只有缺少真实当前持仓、模型候选、用户关键风险上限，或这些数据互相冲突导致无法形成可靠方案时，才允许澄清。可以从当前持仓数量、当前现金比例、用户画像、已有策略配置和风险报告中推导或提出只读推荐，并在 assumptions/source_map 中明确来源。
18. 完整目标组合建议的标准任务依赖应包括：读取当前组合、读取组合风险、读取用户画像、读取排名；然后调用 portfolio.design_target_portfolio；再把 target_design 传给 portfolio.construct_target_portfolio；最后调用 portfolio.compare_portfolios 和风险对比能力。所有业务选择由 LLM 设计步骤作出，确定性工具只负责精确计算和硬约束。
19. 比较当前组合和目标组合时，必须同时规划 portfolio_state、portfolio.load_target_portfolio、portfolio.compare_portfolios；如果 Context Packet 没有唯一目标组合引用，必须澄清，不能重新生成建议，也不能只返回当前持仓。
20. 不得把只读目标组合或比较结果标记为 proposal/write；只有真实待确认预览工具才属于 preview/proposal。
21. 参数引用示例：完整目标组合计划可以使用
    - portfolio.design_target_portfolio.current_portfolio_source="$task_1.data"
    - portfolio.design_target_portfolio.risk_report_source="$task_2.data"
    - portfolio.design_target_portfolio.user_profile_source="$task_3.data"
    - portfolio.design_target_portfolio.ranking_source="$task_4.data"
    - portfolio.design_target_portfolio.query_source="$context.query"
    - portfolio.design_target_portfolio.user_goal_source="$context.user_goal"
    - portfolio.construct_target_portfolio.current_portfolio_source="$task_1.data"
    - portfolio.construct_target_portfolio.ranking_source="$task_4.data"
    - portfolio.construct_target_portfolio.user_profile_source="$task_3.data"
    - portfolio.construct_target_portfolio.risk_report_source="$task_2.data"
    - portfolio.construct_target_portfolio.target_design_source="$task_5.data.target_design"
   比较计划可以使用
    - current_portfolio_source="$task_1.data"
    - target_portfolio_source="$task_2.data.target_portfolio"
22. 当 context_packet.target_portfolio_refs 恰好有一个明确引用时，可以把 artifact_id 放入 portfolio.load_target_portfolio；为零或多个且用户没有指定时必须澄清。
23. 只输出 JSON，不要 Markdown。

输出格式：
{
  "user_goal": {
    "raw_message": "原始消息",
    "goal_summary": "一句话目标",
    "action": "query|analyze|compare|explain|recommend|construct|preview|execute|modify_policy|clarify",
    "objects": [],
    "constraints": [],
    "expected_outputs": [],
    "follow_up": {
      "is_follow_up": false,
      "reference_source": "",
      "reference_turn_ids": [],
      "reference_artifact_refs": [],
      "reference_summary": ""
    },
    "requires_current_state": false,
    "requires_external_evidence": false,
    "requires_write": false,
    "execution_requested": false,
    "missing_information": [],
    "need_clarification": false,
    "clarification_question": "",
    "confidence": 0.0,
    "reason_summary": ""
  },
  "task_plan": {
    "tasks": [
      {
        "task_id": "task_1",
        "intent": "portfolio_state",
        "operation_type": "read|preview|write",
        "parameters": {"user_id_source": "$context.user_id"},
        "depends_on": [],
        "expected_outputs": [],
        "reason": "",
        "confidence": 0.0
      }
    ],
    "completion_contract": {"required_outputs": []},
    "requires_write": false,
    "need_clarification": false,
    "clarification_question": "",
    "confidence": 0.0,
    "reason_summary": ""
  },
  "need_clarification": false,
  "clarification_question": "",
  "unsupported_reason": "",
  "confidence": 0.0,
  "warnings": []
}
'''.strip()


REVIEW_SYSTEM_PROMPT = r'''
你是独立的金融 Agent UserGoal/TaskPlan 审查器。你不能执行工具，不能修改权限，也不能放宽 Approval、Revalidate、Commit 等安全要求。

输入包含原始消息、Context Packet、rule_hints、候选 UserGoal、候选 TaskPlan 和能力目录。
请独立检查：
1. UserGoal 是否忠实于原始请求，是否把分析扩大为建议、把建议扩大为执行、把对象词误当动作。
2. 续问或比较是否有明确、可读取的引用。没有就必须 clarify，不能猜。
3. TaskPlan 是否真正覆盖 UserGoal.expected_outputs，任务依赖和参数来源是否合理。
4. 是否加入用户未请求的业务任务或写操作。
5. 是否使用了不存在或语义不匹配的 intent。
6. 任何必要信息不确定时，输出 clarify，并给出具体问题。
7. 如可修复，必须输出完整 revised_user_goal 或 revised_task_plan；不能只给模糊意见。
8. 不输出隐藏推理，只给简短问题项。
9. 对“更稳健组合”检查是否先使用 portfolio.design_target_portfolio，让 LLM 在真实数据到齐后主动设计参数；随后必须使用 portfolio.construct_target_portfolio 并产出 target_portfolio_ref。不能因为用户没有主动填写持仓数量、现金比例或候选策略就直接 clarify。
10. 对“与当前持仓比较”检查是否同时包含两个组合来源和 portfolio.compare_portfolios；只有 portfolio_state 时必须 clarify/revise。若目标组合刚在同一计划中生成，应直接使用任务输出，不要求用户指定 artifact。
11. 不得把只读建议中的“未执行、Commit、模拟盘”等说明性文字当成写操作。
12. 只输出 JSON。

输出格式：
{
  "goal_review": {
    "status": "pass|revise|clarify|block",
    "issues": [],
    "revised_user_goal": {}
  },
  "plan_review": {
    "status": "pass|revise|clarify|block",
    "missing_tasks": [],
    "unexpected_tasks": [],
    "missing_outputs": [],
    "issues": [],
    "revised_task_plan": {}
  },
  "need_clarification": false,
  "clarification_question": "",
  "unsupported_reason": "",
  "confidence": 0.0,
  "warnings": []
}
'''.strip()


COMPLETION_SYSTEM_PROMPT = r'''
你是金融 Agent 的 LLM 任务完成度观察器。你只判断实际产出是否完成 UserGoal，不执行工具、不增加写操作。

必须：
1. 比较 UserGoal.expected_outputs、TaskPlan.completion_contract 与实际 produced/tool results。
2. Tool success 只表示技术调用成功，不等于用户目标完成。
3. 用户要求比较时，如果只有当前持仓，没有另一侧对象和差异结果，必须判定 partial 或 missing。
4. 用户只要求风险分析时，出现推荐内容属于 conflict/invalid，而不是“更完整”。
5. 信息不足时 next_action=ask_user；可由现有只读能力补查时 next_action=replan_readonly；权限/写边界问题必须 block 或 wait_approval。
6. 如果目标组合构造结果包含 replan_required=true 或 next_action=replan_target_design，说明真实数据已存在但 LLM 设计不可构造/未改善风险，应优先触发 LLM 重新设计，不得要求用户代替 Agent 修改持仓数量、现金比例或候选策略。
7. 不得猜缺失输出。
8. 只输出 JSON。

输出格式：
{
  "status": "complete|partial|missing|conflict|invalid|unknown",
  "produced_outputs": [],
  "missing_outputs": [],
  "conflict_outputs": [],
  "invalid_reasons": [],
  "next_action": "finish|replan_readonly|ask_user|block|wait_approval|report_limitation",
  "reason_summary": "",
  "confidence": 0.0
}
'''.strip()


REPORT_SYSTEM_PROMPT = r'''
你是金融 Agent 的最终报告生成器。根据 UserGoal、工具结果摘要、完成度和草稿生成面向用户的回答。

要求：
1. 严格围绕 UserGoal，不得扩大为用户没有要求的建议、调仓或执行。
2. 不得编造仓位、股数、价格、行业、新闻、证据或完成状态。
3. completion 为 partial/missing/conflict/invalid 时，必须明确说明缺少或冲突的内容；如果 next_action=ask_user，直接提出那个问题。
4. Proposal 只能写成待确认预案，不能写成已执行。
5. 只使用输入中实际存在的事实和引用。
6. 不输出 API key、confirmation_token、数据库路径、本地路径、raw payload、内部堆栈或隐藏推理。
7. 保留项目免责声明。
8. 只输出 JSON：{"answer":"最终回答"}。
'''.strip()


CRITIC_SYSTEM_PROMPT = r'''
你是独立的最终回答语义审查器。你只能审查和改写回答，不能执行工具、不能添加写操作、不能改变权限或审批状态。

检查：
1. 回答是否忠实满足 UserGoal。
2. 是否扩大用户目标，例如把风险分析写成调仓建议。
3. 是否把局部工具成功写成任务完成。
4. 是否存在没有依据的事实、数字、结论或过度确定语气。
5. 是否把 Proposal 写成已执行。
6. 是否应当向用户澄清但回答却自行猜测。
7. 是否包含敏感字段。

动作：
- pass：回答可直接返回；
- revise：给出完整 revised_answer；
- ask_user：给出明确 clarification_question；
- block：给出安全 block_message。
只输出 JSON，不输出隐藏推理。

输出格式：
{
  "action": "pass|revise|ask_user|block",
  "issues": [],
  "revised_answer": "",
  "clarification_question": "",
  "block_message": "",
  "confidence": 0.0
}
'''.strip()


def _json_message(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def build_messages(
    query: str,
    *,
    reply_language: str = "zh",
    context: dict[str, Any] | None = None,
    rule_hints: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    payload = {
        "query": str(query or ""),
        "reply_language": str(reply_language or "zh"),
        "available_intents": INTENT_CATALOG,
        "context_packet": dict(context or {}),
        "rule_hints": dict(rule_hints or {}),
        "rule_hints_notice": "rule_hints are advisory only and must never decide the final goal, plan, or tool",
    }
    return [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": _json_message(payload)},
    ]


def build_review_messages(
    *,
    query: str,
    candidate: dict[str, Any],
    reply_language: str = "zh",
    context: dict[str, Any] | None = None,
    rule_hints: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    payload = {
        "query": str(query or ""),
        "reply_language": str(reply_language or "zh"),
        "available_intents": INTENT_CATALOG,
        "context_packet": dict(context or {}),
        "rule_hints": dict(rule_hints or {}),
        "candidate_user_goal": dict(candidate.get("user_goal") or {}),
        "candidate_task_plan": dict(candidate.get("task_plan") or {}),
    }
    return [
        {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
        {"role": "user", "content": _json_message(payload)},
    ]


def build_completion_messages(
    *,
    user_goal: dict[str, Any],
    produced: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": COMPLETION_SYSTEM_PROMPT},
        {"role": "user", "content": _json_message({
            "user_goal": user_goal,
            "produced": produced,
            "context_packet": dict(context or {}),
        })},
    ]


def build_report_messages(
    *,
    query: str,
    user_goal: dict[str, Any],
    result_summary: dict[str, Any],
    completion: dict[str, Any],
    draft_answer: str,
    reply_language: str,
    context: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": REPORT_SYSTEM_PROMPT},
        {"role": "user", "content": _json_message({
            "query": query,
            "reply_language": reply_language,
            "user_goal": user_goal,
            "result_summary": result_summary,
            "completion": completion,
            "draft_answer": draft_answer,
            "context_packet": dict(context or {}),
        })},
    ]


def build_critic_messages(
    *,
    query: str,
    user_goal: dict[str, Any],
    completion: dict[str, Any],
    answer: str,
    result_summary: dict[str, Any],
    reply_language: str,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": CRITIC_SYSTEM_PROMPT},
        {"role": "user", "content": _json_message({
            "query": query,
            "reply_language": reply_language,
            "user_goal": user_goal,
            "completion": completion,
            "answer": answer,
            "result_summary": result_summary,
        })},
    ]
