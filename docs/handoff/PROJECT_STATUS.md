# Project Status

更新时间：2026-06-23

## 当前可用状态

- Streamlit APP 当前部署端口：`8501`
- 首页预测排名可读：`outputs/ranking_latest.csv`
- 当前 ranking 行数：约 292 只股票
- 当前主要模型：`chronos_bolt_small`
- AI 模拟盘页面已恢复用户画像与初始资产入口。
- AI 模拟盘策略设置入口已移除，策略固定为 `hierarchical_top10`。
- 历史回放按钮可触发从 `2026-04-01` 起的重放。
- 模拟盘历史订单、持仓、净值和账户快照已保留。
- 第一阶段清理已完成，仅保留最佳外部模型相关内容和必要历史记录。
- 第 38 阶段 Agent 运行时升级已完成：工具元数据、只读并发、多步骤执行、受限 Python 分析、ActionProposal、一次性确认、运行历史、来源追踪、记忆和反馈表已接入。

## 最近验证

- 第 38 阶段专项回归：运行时契约、只读并发、历史持久化、Python 沙箱、ActionProposal、AI Agent 页面摘要 helper 均通过。
- 单元测试基线：后续请以当前分支重新执行 `python -m pytest tests/unit -q` 更新完整数字。
- APP 浏览器检查：主页、AI 模拟盘、历史回放入口、AI Agent 页面可访问。
- 当前截图见 `PAGE_SCREENSHOTS.md`。

## 当前默认模型和数据

当前最佳模型：

```text
models/external_zoo/chronos/chronos_bolt_small/
```

当前首页排名：

```text
outputs/ranking_latest.csv
```

当前用户模拟盘历史示例：

```text
outputs/portfolio/<user_id>/
```

回放起始日：

```text
2026-04-01
```

实现位置：

- `model_zoo_backend.py`
- `model_zoo/registry.py`
- `app.py`
- `app/pages/ai_paper_trading.py`
- `pipelines/paper_backfill_pipeline.py`

## 已完成的重要修复

- 修复 AI 模拟盘页面 `current_user_id` 未定义导致不可用的问题。
- 恢复“用户画像与初始资产”设置入口。
- 找到并固定每日模拟盘策略，不再由前端配置。
- 修复“重新执行历史回放”无反应，改为强制从选择日期重建。
- 保留历史模拟盘、回测和预测相关历史记录。
- 清理无用模型与缓存后，项目大小降至约 607 MB。

相关实现：

- `app/pages/ai_paper_trading.py`
- `pipelines/paper_trading_pipeline.py`
- `pipelines/paper_backfill_pipeline.py`
- `portfolio/rebalance_rules.py`
- `portfolio/hierarchical_top10_allocator.py`

## 当前未完成或需谨慎处理

### 每日增量更新后端口径

接手建议：

- APP 后端选择应走 `zoo:chronos_bolt_small`。
- `daily_incremental_update.py` 当前只保留外部模型每日更新路径。
- 不要重新接入旧本地 MLP 训练和模型存取链路。

涉及文件：

- `app.py`
- `daily_incremental_update.py`
- `model_zoo_backend.py`

### 旧字段兼容

历史文件可能仍有 `final_action`、`final_score`、`watchlist` 等旧字段，但当前主链路不应依赖这些字段。

涉及文件：

- `scoring/schemas.py`
- `database/migrations/013_remove_action_and_penalty_fields.sql`
- `portfolio/storage.py`
- `scoring/risk_penalty.py`
- `scoring/rule_engine.py`

### 交易撮合简化

当前 paper trading 没有完整模拟涨跌停、停牌、分红、退市和真实 T+1 卖出限制。

涉及文件：

- `portfolio/paper_trading_engine.py`
- `portfolio/rebalance_rules.py`
- `pipelines/historical_account_replayer.py`

### 文案编码历史

部分旧源码注释和中文文案存在编码历史问题。业务判断请优先看本文档、字段、函数名和测试，不要只看旧注释。

## 可删与不可删提醒

不可删：

- `outputs/ranking_latest.csv`
- `outputs/rankings/history/`
- `outputs/portfolio/<user_id>/history/`
- `outputs/users/<user_id>/recommendations/`
- `models/external_zoo/chronos/chronos_bolt_small/`
- `models/external_zoo/metadata.json`
- `data/latest_raw_stock_data.csv`
- `data/latest_feature_stock_data_alpha158.csv`
- `data/csi300_stock_pool.csv`

可按阶段清理：

- 临时日志。
- `__pycache__`、`.pytest_cache`。
- 非最佳外部模型权重。
- 明确无用的历史备份目录。

## 接手优先级

1. 先读 `CURRENT_REQUIREMENTS.md`。
2. 再读 `OPEN_DECISIONS.md`，先确认未闭合业务口径是否已经拍板。
3. 再读 `CORE_BUSINESS_RULES.md`、`PAPER_TRADING_RULES.md`。
4. 查字段看 `DATA_DICTIONARY.md` 和 `../sample_data/`。
5. 查数据源冲突看 `DATA_SOURCE_OF_TRUTH.md`。
6. 改模型看 `MODEL_SPECIFICATION.md`。
7. 改新闻/AI 调整看 `NEWS_AI_ADJUSTMENT_FLOW.md`。
