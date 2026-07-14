# A 股每日股票评分系统

本项目支持两种并存运行方式：

```powershell
# 开发模式
python -m streamlit run app.py

# 源码桌面模式
python desktop_launcher.py

# Windows 发布构建
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

Windows 发布模式入口为 `desktop_launcher.py` 打包后的 `StockDailyApp.exe`。安装版会后台启动本地 Streamlit，只监听 `127.0.0.1` 的动态端口，并用桌面窗口打开页面。

开发模式继续使用项目根目录中的 `data/`、`models/`、`outputs/`、`runtime/`、`logs/` 和 `local_app_config.json`。安装版用户数据写入：

```text
%LOCALAPPDATA%\StockDailyApp\
```

其中 SQLite 数据库位于 `%LOCALAPPDATA%\StockDailyApp\database\agent_quant.db`，本地 Token/AI 配置位于 `%LOCALAPPDATA%\StockDailyApp\config\local_app_config.json`。安装和升级不会覆盖用户数据库、配置、模拟盘数据、输出和日志。

详细发布说明见 `docs/WINDOWS_DISTRIBUTION.md`。

## 金融 Agent 分阶段改进

阶段 0/1/2/3 已建立基线、新闻 RAG/Dense 检索改造入口、统一系统监控和 Agent 轻量 ContextBuilder：

- `docs/IMPROVEMENT_BASELINE.md`
- `docs/handoff/00_BASELINE_FREEZE.md`
- `docs/handoff/01_NEWS_RAG_DENSE_RETRIEVAL.md`
- `docs/handoff/02_SYSTEM_MONITORING.md`
- `docs/handoff/03_CONTEXT_BUILDER.md`
- `docs/handoff/04_LAYERED_MEMORY.md`
- `docs/handoff/05_AGENT_HARNESS_QUALITY.md`
- `docs/handoff/06_RUNTIME_RELIABILITY_FAULT_INJECTION.md`
- `docs/handoff/07_DECISION_ATTRIBUTION.md`

新闻 RAG 重同步、清理旧 chunk、重建 BM25/Dense 索引和执行诊断：

```powershell
py scripts\resync_news_rag.py --from-cache --db-path data\agent_quant.db --output-dir outputs --query "000001 news risk" --stock-code 000001 --decision-time "2026-06-24 14:30:00"
```

严格 Dense 验收：

```powershell
py -m evaluation.news_rag_diagnostics --db-path data\agent_quant.db --output-dir outputs --query "000001 news risk" --stock-code 000001 --decision-time "2026-06-24 14:30:00" --require-dense
```

本阶段不修改交易策略、模拟盘规则、原始模型排名或四个旧 Agent 文件。

阶段 2 系统监控快照命令：

```powershell
py scripts\run_system_monitor_snapshot.py --db-path data\agent_quant.db --output-dir outputs --user-id cht --trade-date 2026-07-01
```

APP 顶层页面新增 `系统监控`。该页面只读采集数据、模型、RAG、Agent 和组合五层指标；保存快照时只写 `system_monitor_snapshots` 和 `system_monitor_alerts`，不会修改模拟盘订单、持仓、策略或 Prompt。

阶段 3 新增 `agent/context/` 轻量 ContextBuilder。它在 Agent 执行前后收集只读上下文、按预算压缩并保留股票代码、日期、数值和证据 ID；不修改交易策略、模拟盘规则、RAG 主链路或四个旧 Agent 文件。
阶段 4 新增分层 Memory 服务，复用现有 `conversation_summaries`、`memory_items` 和 `memory_links`。它支持 Working/Episodic/Semantic 三层检索、用户隔离、来源追踪、过期、删除和用户纠正覆盖；不会把一次性调仓或 Agent 推断自动写成长期偏好。
阶段 5 扩展 `evaluation/agent_harness/`，新增证据质量、回答质量、只读业务安全和综合评分指标。Harness 可发现错误股票证据、未来证据、回答缺关键数字或免责声明、只读场景产生业务写入等问题。
阶段 6 新增运行时可靠性工具和故障注入套件，覆盖超时、取消、只读重试、SQLite lock 重试、熔断、P95 延迟和大输出截断；不改变交易策略或模拟盘执行规则。
阶段 7 新增 `portfolio/decision_attribution.py` 单股决策归因服务，并在 AI 模拟盘页面提供“单股决策归因”入口。它只读取已保存的最终推荐、模拟盘决策和执行诊断，展示基础仓位、原始排名、新闻/用户调整、公式核对、一手约束、递归分配、最终仓位和证据来源；不重新计算或改写实际业务结果。

## Ragas 离线评测

项目新增独立离线评测模块 `evaluation/ragas_eval/`，用于评估股票新闻 RAG 检索和 Agent 回答。Ragas 是可选依赖，未安装时不影响 App、日更、Agent 或模拟盘；可用 `--no-llm` 只运行确定性指标。当前验证组合见 `requirements-ragas.txt`。

```powershell
python -m evaluation.ragas_eval.cli `
  --dataset data/evaluation/rag_eval_template.jsonl `
  --config configs/ragas_eval/retrieval_only.yaml `
  --experiment-name smoke_test `
  --mode retrieval `
  --no-llm
```

详细说明见 `docs/RAGAS_EVALUATION_GUIDE.md`。

# 用户交易权限补丁

将压缩包内容复制到项目根目录：

```text
D:\stock_daily_app
```

保持目录结构并覆盖同名文件。

## 新增文件

- `portfolio/trading_permissions.py`
- `docs/TRADING_PERMISSION_RULES.md`
- `docs/TRADING_PERMISSION_DATA_DICTIONARY.md`

## 覆盖文件

- `portfolio/user_profile.py`
- `app/classic_services.py`
- `app/pages/ai_paper_trading.py`
- `portfolio/rebalance_rules.py`
- `portfolio/paper_trading_engine.py`
- `pipelines/paper_trading_pipeline.py`
- `agent/tools/user_profile_tool.py`

## 权限保存方式

本次不修改数据库表结构。`save_classic_user_context` 原本就会保存完整用户画像 JSON，因此交易权限保存在：

```text
outputs/users/<user_id>/user_profile.json
```

加载用户画像时，会将数据库中的原有字段与 JSON 中的交易权限合并。

## 默认权限

- 沪深主板：开通
- 创业板：未开通
- 科创板：未开通
- 北交所：未开通
- 风险警示股票：未开通
- 港股通：未开通

## 执行规则

- 无权限的新股票不能买入。
- 无权限的已有持仓不能加仓。
- 已有持仓仍可持有、减仓或卖出。
- 权限阻断释放的目标权重由现有 Top10 分配逻辑重新分配。
- 执行引擎会再次校验，防止计划层遗漏。
- 历史回放通过同一 `paper_trading_pipeline` 自动应用权限。

## 验证范围

仅完成 Python 语法检查；未运行项目测试，未覆盖真实本地数据库和历史回放。
