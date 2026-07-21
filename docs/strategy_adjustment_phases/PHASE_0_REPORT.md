# Phase 0 验收报告：基线审计与回归基线

更新时间：2026-07-17

## 修改文件

- 无生产业务代码修改。
- 新增 Phase 0 测试和固定 golden 夹具。

## 新增文件

- `tests/fixtures/strategy_default_golden.json`
- `tests/unit/strategy_baseline_helpers.py`
- `tests/unit/test_strategy_baseline_snapshot.py`
- `tests/unit/test_default_strategy_rebalance_golden.py`
- `tests/unit/test_existing_strategy_confirmation_baseline.py`
- `tests/unit/test_portfolio_history_baseline.py`

## 业务链路审计

### 现有策略注册与启用链路

```text
用户输入
→ agent/intent_decomposition/rule_fallback.py（strategy_change）
→ agent/executor.py
→ agent/tools/strategy_builder_tool.py
→ create_confirmation_plan(register_strategy)
→ 用户确认
→ agent/write_gateway.py
→ agent/tools/strategy_management_tool.py
→ strategies/registry.py
→ outputs/strategies/strategy_registry.json
→ strategy_registry SQLite 镜像
→ 单独创建 enable_strategy 确认计划
```

确认事实：

- `strategy_builder_tool.py` 当前会从自由文本中自行提取 TopN 和现金比例，并立即创建正式注册确认计划。
- 注册确认后策略保持未启用，并创建第二个启用确认计划。
- `StrategyRegistry` 的运行时权威来源是 `outputs/strategies/strategy_registry.json`；SQLite `strategy_registry` 是尽力写入的镜像，写入失败会被吞掉。
- `enabled_for_paper_trading` 是全局布尔值，没有用户级或账户级隔离。
- 当前模拟盘 Pipeline 不读取 `StrategyRegistry`，因此 Registry 中启用的策略不会被实际模拟盘消费。

### 现有每日模拟盘链路

```text
run_paper_trading_from_latest
→ PipelineContext(strategy="hierarchical_top10", entry_top_k=10,
  hold_buffer_rank=15, max_positions=10, minimum_cash_ratio=0.05)
→ pipelines/paper_trading_pipeline.py
→ portfolio/rebalance_rules.py
→ portfolio/hierarchical_top10_allocator.py
→ portfolio/paper_trading_engine.py
→ PortfolioStorage / PortfolioRepository
```

默认参数基线：

| 参数 | 修改前行为 |
|---|---:|
| `entry_top_k` | 10 |
| `hold_buffer_rank` | 15 |
| `max_positions` | 10；分层 Top10 路径当前没有真实使用该参数 |
| `target_invested_weight` | 0.80；分层 Top10 路径当前实际使用固定 `TOP10_TARGET_RATIO=0.80` |
| `minimum_cash_ratio` | 0.05 |
| `min_rebalance_weight_delta` | 0.01 |
| 最短持有天数 | 5 |
| Top11-15 单股上限 | 0.03 |
| Top11-15 合计上限 | 0.15 |
| 单股最终上限 | 0.30 |
| A 股最小交易单位 | 100 股 |

### 当前状态与历史

- 当前账户：`paper_account_latest.json` / `paper_account.json`，并镜像到 `paper_account`。
- 当前持仓：`paper_positions_latest.csv` / `paper_positions.csv`；读取时本地 latest 文件优先，数据库表为 `portfolio_position`。
- 历史持仓：`outputs/portfolio/<user_id>/history/positions/positions_YYYYMMDD*.csv`。
- 历史账户：`outputs/portfolio/<user_id>/history/accounts/account_YYYYMMDD*.json`，另有 `paper_account_snapshot`。
- 历史订单：`paper_orders.csv`、`history/orders/orders_YYYYMMDD*.csv` 和 `paper_order`。
- 历史净值：`paper_nav_latest.csv`、`history/nav/nav_YYYYMMDD.csv` 和 `paper_nav_history`。
- `PortfolioStorage.write_daily_snapshot` 会校验账户、现金和持仓市值一致性，并按交易日保留历史文件。

## Golden 基线

固定输入：

- 15 只固定排名股票；
- 统一价格 10 元；
- 账户总资产 100,000 元、现金 90,000 元；
- 已持有 `000001` 1,000 股；
- 默认交易费用；
- 默认分层 Top10 参数。

固定结果：

- TargetPortfolio 数值和动作已保存；
- 生成 10 笔买单；
- 总手续费 21 元；
- 期末现金 19,979 元；
- 期末总资产 99,979 元；
- 10 只最终持仓数量已保存。

## 专项测试

```text
tests/unit/test_strategy_baseline_snapshot.py
tests/unit/test_default_strategy_rebalance_golden.py
tests/unit/test_existing_strategy_confirmation_baseline.py
tests/unit/test_portfolio_history_baseline.py
```

结果：`5 passed`。

## 回归测试

```powershell
.\.venv\Scripts\python.exe -m compileall -q agent app portfolio scoring rag pipelines database strategies
.\.venv\Scripts\python.exe -m pytest tests\unit -q --tb=short
```

结果：

- 编译：通过。
- 全量测试：`857 passed, 9 failed`。
- 修改前基线：`852 passed, 9 failed`。
- 新增失败：0。
- 9 个失败文件和测试名称与修改前完全相同，属于既有 Agent/MCP/多 Agent/Goal Planning 基线失败。

## 兼容性结论

- 未写入正式 Registry、正式账户、正式持仓、正式订单或正式净值。
- 所有写入测试均使用 pytest 临时目录。
- 默认策略 golden 已固定，可用于后续 Phase 6 数值兼容验收。
- 当前 Strategy Registry 与模拟盘运行链路不相连，后续必须通过用户/账户 Binding 和 Runtime Resolver 打通。

## 剩余风险

- Registry JSON 与 SQLite 是双写且数据库失败被忽略，尚不具备事务一致性。
- 全局 `enabled_for_paper_trading` 无法表达用户/账户级激活状态。
- 分层 Top10 路径仍固定使用 0.80，`max_positions` 和传入的 `target_invested_weight` 尚未完全生效。
- 当前策略 Builder 会解释自然语言并直接创建正式注册计划，不符合“先对话草稿、再隔离实施”的目标。
- 基线已有 9 项非本任务引入的失败，后续阶段不得增加失败数。

## 下一阶段入口

Phase 1 新增 Strategy Proposal、版本历史和对话上下文持久化；将 `strategy_change` 改为长期策略设计对话，不再由 Builder 直接创建正式注册计划。

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。
