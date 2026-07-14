# 金融分析 Agent 使用说明

## 1. 功能说明

金融分析 Agent 复用当前项目已有模块，不重新训练模型。它会根据用户问题识别意图，然后调用预测排名、Model Zoo、回测、新闻映射、RAG、市场环境和 LLM 解释等已有能力。

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议。

## 2. Skill 标准能力层

`skills/` 是 Agent 和 Pipeline 的标准任务方法层。Skill 不直接查数据库、不调用 API、不跑模型，只定义任务目的、输入、流程、输出 schema、约束和示例。

当前 Skill 覆盖：

- 新闻事件抽取
- 新闻-股票映射
- 新闻影响评分
- K 线预测解释
- 信号融合
- 用户画像适配
- 模拟盘调仓
- 推荐解释
- 合规风险控制

所有 Agent 输出和后处理逻辑都应围绕四个问题组织：用户是否适合、模型预测是否可靠、新闻事件是否带来风险、Agent 修改是否有效。

## 3. 数据库底座

`database/` 是 Agent 后处理和审计的 SQLite 数据底座，默认路径 `data/agent_quant.db`。当前底座保存用户适当性、模型预测、新闻事件、新闻-股票映射、Agent 决策日志、RAG 检索日志和回测评估。

Agent 不重新预测涨跌；它基于 `model_prediction`、新闻证据、用户约束和规则做保留、降权、剔除、加入观察或风险提示，并将后处理写入 `agent_decision_log`。日志中必须保留 `evidence_chunk_ids` 和 `evidence_snapshot`，用于后续判断 Agent 修改是否有效。

初始化：

```bash
python -c "from database import initialize_database; initialize_database()"
```

## 4. RAG 检索基础层

`rag/` 只负责检索证据，不直接给投资建议，也不直接决定买入、卖出、降权或剔除。Agent 和 Scoring 后续可以使用 RAG 返回的证据，但必须把最终后处理写入 `agent_decision_log`。

RAG 流程：

```text
news_chunk
→ metadata filter
→ BM25 / Dense
→ Hybrid merge
→ Rerank
→ rag_retrieval_log
```

metadata filter 必须使用 `publish_time <= decision_time` 和交易日范围，避免盘后新闻用于当天决策。BM25、Dense、Hybrid 和 Rerank 分数只表示相关性，不表示利好利空。

## 5. Signal Fusion 基础层

`scoring/` 是模型预测、新闻/RAG 证据、用户画像、组合风险和 Agent 规则之间的受约束融合层。它不是 Agent，不重新预测涨跌，不调用 LLM 自动买卖，不输出真实交易指令。

允许的 `final_action`：
```text
keep
down_weight
exclude
watchlist
risk_alert
```

`buy`、`sell`、`reduce` 属于后续 paper trading 动作，不由 Signal Fusion 直接生成。每个 `FusionOutput` 都应保留触发规则、证据 ID、原因、风险提示和合规声明，并可通过 `decision_logger.py` 写入 `agent_decision_log`，用于后续评估 Agent 修改是否有效。

## 6. Pipeline 固定流程层

`pipelines/` 是固定每日工作流层，不是 Agent。它不做复杂问答、不重新训练或预测模型、不连接真实交易，只按顺序编排已有模块：

```text
Prediction -> RAG -> Scoring -> Paper Trading -> Report
```

命令行示例：
```bash
python -m pipelines.pipeline_runner --user-id default --trade-date latest --top-k 50 --dry-run
```

职责边界：
- RAG 只提供证据；
- Scoring 只输出 `keep/down_weight/exclude/watchlist/risk_alert`；
- Portfolio 只执行 paper trading；
- Report 输出每日 Markdown 报告；
- `dry_run` 跳过落盘写入和模拟盘执行；
- `paper_trading_enabled` 只代表是否执行模拟盘，不代表真实交易。

入口 `daily_incremental_update.py` 和 `agent/report_agent.py` 继续保留。

## 7. 后台每日调度

`scheduler/` 是 Stage 5H 的独立后台 worker 层。它把每日自动更新从 Streamlit APP 中拆出来，APP 只负责保存配置、触发一次手动后台运行、展示 `latest_job_status.json` 和日志。

命令行入口：

```bash
python -m scheduler.scheduler_cli health
python -m scheduler.scheduler_cli run --all-users --dry-run --source manual
python -m scheduler.scheduler_cli status
```

Windows 任务计划：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_windows_daily_task.ps1 -Time 17:30
powershell -ExecutionPolicy Bypass -File scripts\uninstall_windows_daily_task.ps1
```

调度边界：
- `public_tasks` 每个交易日只执行一次，负责公共 ranking/news 状态。
- `user:{user_id}` 独立执行 recommendations、paper trading、evaluation 和 report。
- `runtime/locks/daily_update.lock` 防止重复 worker。
- `runtime/jobs/latest_job_status.json` 给 APP 展示状态。
- 某个用户失败不会阻断其他用户。
- 不做真实交易、不连接券商、不承诺收益。

## 8. Portfolio / Paper Trading 基础层

`portfolio/` 为后续 Agent 和 Signal Fusion 提供用户适当性与模拟盘状态，但当前只做 paper trading，不做真实交易。

核心能力：
- 用户画像读取和默认稳健型 fallback；
- 单股仓位、行业集中度、最大回撤和高风险股票约束；
- 模拟账户、模拟持仓、模拟订单和组合风险报告；
- 简单模拟调仓计划；
- 数据库优先写入，数据库不可用时 fallback 到 `outputs/portfolio/`。

Fallback 输出：
```text
outputs/portfolio/paper_account.json
outputs/portfolio/paper_positions.csv
outputs/portfolio/paper_orders.csv
outputs/portfolio/portfolio_risk_report.json
```

模拟盘结果仅用于机器学习研究、策略验证和项目展示，不构成投资建议，不用于实盘交易。RAG 只提供证据，不能直接触发交易动作。

### 历史回放与资金流水

AI 模拟盘默认从 `2026-04-01` 开始逐日回放：

```bash
python -m pipelines.paper_backfill_pipeline --user-id cht --start-date 2026-04-01 --end-date latest --initial-cash 100000
```

回放只允许使用当日可获得的历史 ranking、新闻和账户状态。缺少某日 ranking 时标记 `missing_prediction`，跳过新增买入，不能用 `ranking_latest.csv` 伪造历史。新闻证据必须满足 `publish_time <= decision_time`；缺新闻时新闻调整为 0，不默认观察、降权或负面。

资金变化必须记录为 `paper_cash_flow`：

```bash
python -m portfolio.cash_flow_cli add --user-id cht --type deposit --amount 50000 --effective-date 2026-05-04 --reason "追加模拟资金"
python -m portfolio.cash_flow_cli list --user-id cht
python -m portfolio.cash_flow_cli cancel --cash-flow-id <ID> --user-id cht
```

不能直接修改账户余额，因为这会篡改历史收益。新增历史生效流水后，需要从生效日重新回放；后台每日任务会在 paper trading 前应用当日生效流水。账户摘要使用净投入资金、绝对盈亏和时间加权收益率，避免把入金/出金当成投资收益。

## 9. APP 中使用

启动：

```bash
streamlit run app.py
```

进入“AI 分析”页签，可以生成个股解释，也可以输入自然语言问题或点击快捷问题。

## 10. 命令行使用

```bash
python -m agent.agent_core
```

单次提问：

```bash
python -m agent.agent_core --query "默认回测方案表现怎么样"
```

## 11. 生成 Agent 报告

```bash
python -m agent.report_agent
```

报告输出到：

```text
outputs/reports/
```

## 11. 运行 Agent 评估

```bash
python scripts/test/run_agent_eval.py
```

报告输出到：

```text
outputs/test_reports/agent_eval_report.md
```

## 12. 常见问题

### 没有预测排名怎么办？

先运行 `daily_incremental_update.py`。

### LLM Key 没配置怎么办？

系统使用模板兜底解释，不会因为缺少 Key 导致 APP 崩溃。

### 没有 RAG 索引怎么办？

先运行 `rag_indexer.py` 构建索引。

### 新闻映射没有结果怎么办？

说明本地映射库没有明确关联，系统不会编造股票列表。
## 13. Stage 5 Agent Tool Layer

Stage 5 adds a local, deterministic Agent tool layer. It reads existing artifacts and database records; it does not replace the fixed Pipeline and does not create real trading instructions.

Phase 0/1 of the financial Agent improvement route did not add new Agent tools. It added News RAG/Dense diagnostics and the command wrapper `scripts/resync_news_rag.py`; the existing tool registry and confirmation boundary remain the source of truth.

Phase 2 also does not add Agent tools. It adds the observation-only `系统监控` page, `evaluation/system_monitor.py`, and `scripts/run_system_monitor_snapshot.py`; these read Agent runtime tables such as `agent_runs`, `agent_steps`, `agent_tool_calls`, and `agent_sources`, but they do not execute tools, create proposals, confirm actions, or write paper-trading business tables.

Phase 3 adds `agent/context/`, a lightweight ContextBuilder used by `agent/executor.py`. It builds bounded `pre_execution` and `post_observation` context from read-only user profile, paper portfolio, conversation history, memory, tool results, and evidence ids. Compression is deterministic and preserves stock codes, dates, numbers, percentages, and source ids. It does not create new Agent tools and does not change confirmation, revalidation, paper-trading, or RAG retrieval boundaries.

Phase 4 adds layered memory through `agent/memory.py`. It does not add an Agent tool. ContextBuilder now reads Working/Episodic/Semantic memory through `LayeredMemoryService`; semantic memory writes must be explicit, source-traceable user facts. Deleted, expired, superseded, one-time-operation, and Agent-inference records are excluded from long-term context.

Phase 5 extends the existing Agent Harness rather than adding Agent tools. `evaluation/agent_harness/` now checks answer phrases, required numbers, disclaimer presence, evidence ids, wrong-stock evidence, future evidence, read-only business writes, and a weighted composite score where source quality plus safety outweigh tool selection.

Phase 6 adds runtime reliability utilities rather than Agent tools. `agent/runtime_reliability.py` provides timeout, cancellation, read-only retry, circuit breaker, latency tracking, and large-output summarization; `evaluation/runtime_fault_injection.py` and `scripts/run_runtime_fault_injection.py` provide local fault-injection checks.

Phase 7 adds decision attribution through `portfolio/decision_attribution.py` and the AI paper-trading page. It is not a new Agent tool yet. It reads persisted final recommendations, paper decisions, and execution diagnostics to explain base allocation, original rank/score, news/user/reliability adjustments, stored formula checks, lot constraints, recursive allocation, final paper target, and evidence ids. It must not recompute or rewrite business results.

Available tools:

```text
agent.pipeline_tool
agent.recommendation_tool
agent.portfolio_tool
agent.rag_tool
agent.report_tool
agent.decision_log_tool
```

Available lightweight agents:

```text
PortfolioQAAgent
EventImpactAgent
PortfolioReviewAgent
ModelMonitorAgent
```

Example usage:

```python
from agent.agent_registry import answer_with_registry

result = answer_with_registry(
    "Why was 000001 down_weighted?",
    user_id="default",
    trade_date="2026-06-11",
    stock_code="000001",
    output_dir="outputs",
    db_path="data/agent_quant.db",
)
print(result["answer"])
```

Important boundary:

```text
Agent answers can explain model signal, news evidence, user constraints, holding risk, rules, reports, and pipeline status.
Agent answers cannot be interpreted as deterministic buy/sell advice.
final_action is a scoring label; paper trading actions are simulated only.
When no evidence exists, the Agent must say that no evidence was found.
```
## 14. Stage 5B APP Navigation

Run the APP:

```bash
streamlit run app.py
```

The sidebar main navigation now includes:

```text
首页 Dashboard
今日最终推荐
运行 Pipeline
模拟盘
持仓风险
每日报告
AI Agent
模型监控
设置
模型搜索
经典旧版预测页
```

Use `运行 Pipeline` to run the fixed daily workflow in dry-run or paper-trading mode. Use `今日最终推荐` to inspect `final_action`, score adjustments, reasons, risk warnings, and evidence ids. Use `模拟盘` and `持仓风险` to inspect paper trading state only. Use `AI Agent` for Stage 5 registry-based QA/review/monitoring plus the old Prompt/LLM flow.

Rules:

```text
final_action is not a real trading instruction.
paper trading is simulated only.
Agent answers must cite available evidence or clearly say no evidence was found.
All pages and Agent answers keep the not-investment-advice disclaimer.
```

## Stage 5D Classic APP Usage

The APP has returned to the classic `app.py` interface. Independent Stage 5B frontend pages were removed.

Agent-facing rules:

```text
ranking_latest.csv = original K-line model prediction.
final_recommendations_latest.csv = AI/news/RAG/user/portfolio-risk post-processing.
final_action is not a real trading instruction.
Paper trading is simulated only.
Do not fabricate news evidence.
If no evidence exists, say: 当前没有找到可支持该结论的证据。
```

The classic APP includes user profile and paper trading settings. `user_id` separates profile, decision log, and paper portfolio outputs. Agent answers should include evidence source, summary, risk and compliance notes when available.

## Stage 5E APP And Paper Trading Usage

The Streamlit APP now has two same-level top pages in the main area:

```text
首页 / 预测排名
AI 模拟盘
```

Use `首页 / 预测排名` to inspect the original K-line rank and the AI/news/RAG/user/risk adjustment details. This page is where explanation fields belong:

```text
original score/rank
news adjustment
user suitability adjustment
risk penalty
rule penalty
final_score
final_action
target_weight
reason
triggered_rules
evidence_news_ids
evidence_chunk_ids
risk_warning
```

Use `AI 模拟盘` to inspect only paper trading state:

```text
account summary
today paper actions
current positions
historical orders
daily position snapshots
portfolio risk
```

Allowed paper actions:

```text
paper_buy
paper_sell
paper_reduce
paper_hold
paper_watchlist
paper_risk_alert
```

The paper page must not repeat homepage prediction explanations such as why the original K-line rank was high or how RAG/news changed the score. Each paper action must keep a source decision id and a paper-trading reason. If the user has not filled a profile and starting capital, the paper page must prompt `请先填写用户画像和模拟盘资金量。` and must not auto-buy.

Paper trading is simulated only. There is no broker API, no real trading, no promised return, and no LLM bypass around Scoring / Portfolio.

## Stage 5F AI Adjustment Reliability

AI/news/user/risk adjustment now primarily changes position size instead of directly excluding most stocks.

Rules:

```text
ordinary negative news or moderate risk -> down_weight
low confidence or partial mismatch -> watchlist
clear risk escalation -> risk_alert
hard risk -> exclude
```

Hard risk examples:

```text
ST / delisting risk
serious violations or accounting fraud
extremely poor liquidity
suspension / not tradable
major negative news with very high mapping confidence
user explicitly avoids an industry and the stock is extremely risky
```

The system records and later evaluates whether AI adjustment improved the original K-line decision:

```text
adjustment_hit
avoided_loss
missed_gain
adjustment_alpha
ai_adjustment_score
```

`ai_reliability_weight` is maintained separately for each `user_id`. It starts at `0.00` during cold start and remains `cold_start` until the user has at least 20 evaluated AI-adjustment samples. After that, good historical performance increases it and weak performance decreases it. The weight only changes non-hard-risk adjustment strength. It never creates real trading instructions.

Stage 5G paper-trading notes:

```text
final_recommendations_latest.csv must keep current_price.
Missing or invalid price must not fall back to price=1.
A-share paper orders use 100-share lots by default.
history/orders/orders_YYYYMMDD.csv contains only real nonzero paper_buy/paper_sell/paper_reduce orders.
paper_watchlist, paper_hold, and paper_risk_alert are stored separately as observations.
```

## Stage 5J AI Agent Control Center

The classic APP now exposes a top-level `AI Agent` page next to `首页 / 预测排名` and `AI 模拟盘`.

Supported examples:

```text
分析 600519
把 600519 加入模拟盘 5%
后台任务状态
追加 50000 资金 2026-06-12
```

Read-only tools can analyze ranking, final recommendations, news mappings, RAG chunks, user suitability, portfolio state, portfolio risk, scheduler status, and reports. Preview tools create a pending plan only. Write tools require the matching `confirmation_token`; a used plan is idempotently rejected on the second execution.

Audit locations:

```text
outputs/agent_audit/{user_id}/agent_action_log.jsonl
outputs/agent_audit/{user_id}/agent_tool_call_log.jsonl
outputs/agent_audit/{user_id}/agent_confirmation_log.jsonl
```

SQLite tables are created by migration `009_agent_action_logs.sql` when the database is initialized. This Agent only operates paper-trading and internal app workflows. It is not investment advice, does not promise returns, does not place real trades, and does not connect to brokers.

## Stage 5M: Residual Cash Reallocation

Agent and Pipeline write paths must continue to call Scoring / Portfolio. They must not bypass the residual-cash allocator or create direct buy/sell instructions.

Paper-trading allocation now follows this execution rule:

```text
Top10 eligible recommendations
-> reserve minimum cash
-> compute one-lot total cost with fee and slippage
-> release budgets that cannot buy one A-share lot
-> redistribute residual cash only within legal Top10 candidates
-> write paper orders, decisions, and allocation diagnostics
```

The APP exposes allocator output in the AI 模拟盘 `资金分配详情` expander. Key audit fields are `released_budget`, `redistributed_cash`, `actual_invested_cash`, `unavoidable_residual_cash`, `capital_utilization_rate`, and per-stock `allocation_details`.

Validation command:

```bash
py -3.12 -m pytest tests/unit -q
```

## Stage 5L: AI 模拟盘 Top10、手续费和净值

Agent 和 Pipeline 不能绕过 Scoring / Portfolio 直接生成真实交易动作。AI 模拟盘仍然只用于 paper trading 和项目展示，不连接券商、不承诺收益。

Stage 5L 执行口径：

```text
ranking / model_prediction
-> final_recommendations
-> Top10 入选、Top15 持仓缓冲
-> paper_buy / paper_sell
-> 手续费扣减
-> 每日盯市
-> paper_nav_history / paper_decision_log / paper_order
```

历史回放命令：

```bash
py -3.12 -m pipelines.paper_backfill_pipeline --user-id cht --start-date 2026-04-01 --end-date latest --strategy top10 --force
```

## Stage 5O Account Reconciliation and Hierarchical Top10

Use the audit command before and after historical rebuilds:

```powershell
py -3.12 -m pipelines.historical_account_audit --user-id cht --start-date 2026-04-01 --end-date latest
py -3.12 -m pipelines.paper_backfill_pipeline --user-id cht --start-date 2026-04-01 --end-date latest --strategy hierarchical_top10 --force
py -3.12 -m pipelines.historical_account_audit --user-id cht --start-date 2026-04-01 --end-date latest
```

Agent / Pipeline constraints:

```text
Do not create real trades.
Do not connect to a broker.
Do not promise returns.
Do not allow LLM output to bypass Scoring / Portfolio.
Use account reconciliation when judging whether an AI paper change was valid.
```

Stage 5O allocation semantics:

```text
Top1-5 base score: 12
Top6-10 base score: 5
Normalize adjusted Top10 scores to 80%
Top11-15 are an existing-position buffer only
Nonzero historical orders: paper_buy / paper_sell / paper_reduce
```

The AI 模拟盘 page shows `账户资产走势` as the main chart. It plots RMB amount series instead of treating a 1.0 NAV ratio as the main account curve.

## Stage 5P: 持仓跨日继承与账户对账硬校验

Agent 和 Pipeline 仍然只能操作模拟盘，不允许绕过 Scoring / Portfolio 生成真实交易。本阶段补强历史回放的持仓状态机：

```text
opening_positions_t = closing_positions_{t-1}
缺 ranking / hold day 保留上一日持仓并按历史收盘价盯市
每日 positions_YYYYMMDD.csv 保存全部有效持仓
持仓数量只允许通过 paper_buy / paper_sell 改变
持仓无故归零必须判定为对账失败
账户保存前必须满足 total_assets = cash + position_market_value
```

历史持仓查询优先读取精确日期快照；旧数据缺快照时 fallback 到最近早于目标日期的快照。Agent 页面展示历史持仓时应使用这些快照，不要用当前持仓冒充历史状态。

验证入口：

```powershell
py -3.12 -m pipelines.paper_backfill_pipeline --user-id cht --start-date 2026-04-01 --end-date latest --strategy hierarchical_top10 --force
py -3.12 -m pipelines.historical_account_audit --user-id cht --start-date 2026-04-01 --end-date latest
py -3.12 -m pytest tests/unit -q
```

当前本地结果：`cht` 历史重放 49 completed / 0 failed，账户审计 49 passed / 0 failed，全量单测 359 passed。

## Stage 5Q: stored-only 历史回放与集中度控制

历史模拟盘现在只消费已保存结果，不再补算上游生产结果：

```text
读取已保存原始 K 线 ranking
读取已保存 AI 新闻/RAG 修正 final_recommendations
读取历史价格、用户画像、手续费、资金流水、上一日账户和持仓
执行组合约束、一手取整、模拟订单、账户和持仓快照
```

禁止在历史回放中调用：

```text
模型推理
新闻接口
RAG 检索
LLM
Signal Fusion
```

若原始 ranking 缺失、AI 修正缺失或二者不一致，Pipeline 必须进入 hold-only，只继承持仓并按历史价格盯市。

全量审计：

```powershell
py -3.12 -m pipelines.full_replay_audit --user-id cht --start-date 2026-04-01 --end-date latest
```

stored-only 重建：

```powershell
py -3.12 -m pipelines.paper_backfill_pipeline --user-id cht --start-date 2026-04-01 --end-date latest --strategy hierarchical_top10 --force --use-stored-ranking-only --use-stored-ai-adjustment-only --disable-model-inference --disable-news-fetch --disable-rag --disable-llm --disable-signal-fusion
```

组合构建规则：

```text
Top1-5 基础权重 12%，Top6-10 基础权重 5%。
单只最终仓位上限 30% + 一手取整容差。
Top10 不可执行时只能使用已有 AI 修正的 11-30 名替补。
无法满足 80% 目标时保留现金，不突破单股上限。
普通情况 minimum_holding_days=5，硬风险 / exclude / 跌出 Top15 允许例外退出。
```

当前本地验收：49 个交易日均有原始 ranking 和 AI 修正；stored-only 重建 49 completed / 0 failed；重审 over_30 / over_50 / near_80 / account failed 均为 0；全量单测 383 passed。

## Stage 5N: 综合净值、现金上限和历史信号修复

Agent 和 Pipeline 仍然只能操作模拟盘，不允许绕过 Scoring / Portfolio 直接生成真实交易。

本阶段新增约束：

```text
AI 模拟盘页面展示“综合净值”，不向用户暴露 paper_nav / paper_nav_history 等内部命名。
账户摘要、风险等级、动作状态使用 app/display_labels.py 的中文映射。
模拟盘目标现金比例为 5%，最高现金比例为 30%。
现金比例超过 30% 时，必须展示 cash_cap_exception_reason。
历史回放优先使用 outputs/backtest_daily_predictions.csv 等真实预测文件。
严禁使用 ranking_latest.csv 补 2026 年 4 月至 5 月历史信号。
历史持仓日按 get_historical_close(...) 返回的历史收盘价盯市。
```

历史修复入口：

```bash
py -3.12 -m pipelines.historical_signal_importer audit --start-date 2026-04-01 --end-date 2026-06-12
py -3.12 -m pipelines.historical_signal_importer import --start-date 2026-04-01 --end-date 2026-06-12
py -3.12 -m pipelines.paper_backfill_pipeline --user-id cht --start-date 2026-04-01 --end-date latest --strategy top10 --force
```

缺失历史 ranking 的日期必须记录为 `missing_prediction`，只做账户和持仓延续，不允许使用 `ranking_latest.csv` 代替历史数据。

## Stage 5S: 每日结果源审计与逐日决策账本

Agent、Pipeline 和 AI 模拟盘必须把历史模拟盘视为结果消费端。历史回放只读取已保存结果，不允许调用模型、新闻/RAG、LLM 或 Signal Fusion 生产历史结果。

严格审计入口：

```powershell
py -3.12 -m pipelines.daily_result_source_audit --user-id cht --start-date 2026-04-01 --end-date latest
py -3.12 -m pipelines.paper_backfill_pipeline --user-id cht --start-date 2026-04-01 --end-date latest --strategy hierarchical_top10 --force --use-stored-ranking-only --use-stored-ai-adjustment-only --audit-log required --continue-on-error --disable-model-inference --disable-news-fetch --disable-rag --disable-llm --disable-signal-fusion
```

审计状态：

```text
ready：结果完整，允许调仓。
failed_continue：结果缺失、不足 Top30、日期/股票代码/原始分数不一致；不调仓，继承持仓，继续下一日。
price_incomplete_continue：结果完整但价格不完整；禁止缺价股票下单。
```

每日决策账本：

```text
runtime/replay_audit/{user_id}/{run_id}/manifest.json
runtime/replay_audit/{user_id}/{run_id}/run_summary.json
runtime/replay_audit/{user_id}/{run_id}/daily/YYYYMMDD.json
runtime/replay_audit/{user_id}/{run_id}/human_readable/YYYYMMDD.md
runtime/replay_audit/{user_id}/{run_id}/failures/YYYYMMDD.json
```

AI 模拟盘页面新增“每日决策审计”，可查看某个 run/date 的数据来源、校验结果、候选过滤、权重分配、一手处理、买入原因、卖出原因、账户对账、原始 JSON 和 Markdown。

最新本地严格审计：`cht` 的 49 个交易日均有原始 ranking，但已保存 AI 修正仅 15 条，不满足 Top30 完整覆盖；最新 run `backfill_20260614_171336_81e7d82a` 生成 49 份 JSON 和 49 份 Markdown，49 天均为 `failed_continue`，0 买入、0 卖出，账户审计 49 passed / 0 failed，全量单测 `400 passed`。
# Stage 35 Agent Usage Note

当前 Agent / Pipeline / Scoring 不再输出动作分类。Agent 回答和工具结果应解释数值仓位调整，而不是给出 keep、down_weight、exclude、watchlist 或 risk_alert 之类标签。

```text
effective_news_adjustment = ai_reliability_weight * news_adjustment
combined_adjustment = effective_news_adjustment + user_adjustment
position_adjustment_ratio = clip(1 + combined_adjustment, 0.0, 2.0)
```

Agent 仍然不能绕过 Scoring / Portfolio，不能连接券商，不能真实交易，不能承诺收益。模拟盘执行只读取固定原始 Top10 内的数值仓位修正，并把一手、价格、现金、费用、80% 总仓位和 30% 单股上限作为执行层约束。
