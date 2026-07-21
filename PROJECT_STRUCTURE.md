# Project Structure

更新时间：2026-07-17

本文用于让 AI、Codex 或新接手开发者快速理解当前 `stock_daily_app`。更细的文件级说明见 [PROJECT_FILE_DIRECTORY.md](PROJECT_FILE_DIRECTORY.md)。

## 项目定位

`stock_daily_app` 是一个面向 A 股的每日股票评分、外部模型预测、新闻/RAG、AI 调整、模拟盘和金融 Agent 工作台项目。

核心原则：

- 本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。
- 不接入真实券商或真实交易接口。
- Tushare Token、AI API Key 等密钥只能来自 APP 输入、本地配置或环境变量，不允许硬编码。
- 旧本地 MLP / `torch_mlp` 训练链路已经移除，不要恢复旧训练、旧预测或旧模型存储入口。
- 当前默认模型路线是外部模型：`Model Zoo: zoo:chronos_bolt_small` 和 `DFT_UNET: dft_unet_external`。
- 写模拟盘、策略或资金状态必须经过 WriteGateway / approval / revalidate / commit，不允许 LLM、MCP 或 Specialist Agent 直接写业务状态。

## 当前开发运行环境

当前源码开发和本地 Web 部署统一使用 D 盘运行环境：

```text
项目根目录：D:\stock_daily_app
项目虚拟环境：D:\stock_daily_app\.venv
虚拟环境基础解释器：D:\python_runtime\cpython-3.12.0-windows-x86_64-none\python.exe
本地 Web 地址：http://127.0.0.1:8501
健康检查：http://127.0.0.1:8501/_stcore/health
```

开发、测试、每日更新和 Streamlit 启动必须显式使用项目虚拟环境解释器：

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8501 --server.address 127.0.0.1 --server.headless true --browser.gatherUsageStats false
```

不要使用 `py -3`、裸 `python` 或 C 盘 Python 启动本项目。当前 8501 部署只监听 `127.0.0.1`，供本机访问；桌面发布模式仍由 `desktop_launcher.py` 选择动态本地端口。

## 当前高层目录

```text
stock_daily_app/
├── app.py                         # Streamlit 主入口
├── desktop_launcher.py            # Windows 桌面启动器，发布模式 EXE 入口
├── runtime_paths.py               # 运行路径兼容包装
├── app_version.py                 # 桌面版和安装包版本
├── stock_daily_app.spec           # PyInstaller onedir 构建配置
├── build_windows.ps1              # Windows 构建脚本
├── requirements.txt               # 主依赖
├── requirements-desktop.txt       # 桌面/打包依赖
├── requirements-ragas.txt         # Ragas 离线评测依赖
├── config.py                      # 全局路径、股票池、模型和运行参数
├── core/llm/                       # API / Ollama profile、运行快照和安全本地模型管理
├── daily_incremental_update.py    # 每日增量更新与 ranking_latest 生成入口
├── data_tushare.py                # Tushare 行情和交易日数据
├── data_local.py                  # 本地 Qlib / CSV 历史行情
├── universe.py                    # CSI300 股票池统一入口
├── alpha158.py                    # Alpha158 因子与标签
├── model_factory.py               # 模型后端工厂
├── model_zoo_backend.py           # Model Zoo 统一后端
├── app/                           # Streamlit 子页面、服务和 UI 组件
├── agent/                         # Agent Runtime、工具、上下文、消息、记忆、ReAct、Reflection、Handoff
├── pipelines/                     # 预测、信号融合、RAG、报告、模拟盘、回放流水线
├── portfolio/                     # 模拟账户、订单、持仓、调仓、风控和归因
├── scoring/                       # AI 调整、规则、融合、解释和决策日志
├── rag/                           # 新 RAG 检索、切分、索引、rerank 和日志
├── database/                      # SQLite schema、migration 和 repository
├── scheduler/                     # 每日任务、交易日历、重试、锁和任务状态
├── evaluation/                    # AI 调整评估、Agent harness、multi-agent、Ragas、系统监控
├── model_zoo/                     # Chronos/MOMENT/Moirai/TimesFM 等外部模型适配
├── model_backends/                # 传统本地模型后端兼容层，例如 LightGBM
├── external_models/               # DFT_UNET 等外部模型适配
├── model_discovery/               # 模型候选发现和下载辅助
├── news_mapping/                  # 新闻实体、股票别名和概念映射
├── strategies/                    # 策略注册、账户 Binding、运行时解析和基础接口
├── skills/                        # 项目内技能定义和 schema
├── scripts/                       # 构建、调度、评估、网页检查和维护脚本
├── models/ollama/                  # 项目固定 Ollama Modelfile（不含模型权重）
├── docs/                          # 接手文档、阶段文档、报告和截图
├── installer/                     # Inno Setup 安装脚本
├── resources/                     # 发布版只读资源
├── tests/                         # pytest 单元、集成和回归测试
├── data/                          # 本地行情、特征、股票池和开发数据库
├── models/                        # 模型文件和外部模型缓存
├── outputs/                       # ranking、报告、模拟盘和回放输出
├── runtime/                       # 运行状态、Agent artifacts、Streamlit 日志和 job 状态
└── logs/                          # 更新、调度和诊断日志
```

## 主要运行链路

### 1. 每日增量更新和预测排名

```text
Tushare 最近交易日日线
    -> data_tushare.fetch_stock_pool_recent_daily_fast(...)
    -> data/latest_raw_stock_data.csv
    -> alpha158.py
    -> Model Zoo / DFT_UNET 外部模型预测
    -> outputs/ranking_latest.csv
    -> outputs/rankings/history/ranking_YYYYMMDD.csv
```

常用命令：

```powershell
.\.venv\Scripts\python.exe daily_incremental_update.py --token <TUSHARE_TOKEN> --base-version latest
```

每日更新只支持外部模型后端，不再加载或训练旧本地 MLP。APP 打开时不自动全量下载、不自动训练。

### 2. Streamlit APP

```text
app.py
    -> 首页 / 预测排名
    -> AI 模拟盘
    -> AI Agent
    -> 系统监控
```

常用启动：

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8501 --server.address 127.0.0.1 --server.headless true --browser.gatherUsageStats false
```

APP 主要读取已有模型和输出文件。每日更新、历史回放、模拟盘更新都由按钮或调度触发。

### 2.1 LLM 手动部署模式

```text
侧边栏“AI 接口设置”
    -> 远程 API profile（API Key / Base URL / Model）
    -> 或本地 Ollama profile（固定 127.0.0.1:11434/v1 / stock-agent-qwen3-4b）
    -> 验证成功后“保存并应用”
    -> 下一次 run_agent_request 解析一个不可变 LLMRuntimeSettings 快照
    -> Planner / Completion / Report / Critic / Replan / LLM 工具共用该快照
```

模式不会自动切换或回退。审计只保留 `deployment_mode`、provider、model、endpoint scope、配置哈希、耗时与错误类别；不会保存密钥、完整提示词或完整回复。安装本地模型请执行 `scripts/setup_ollama_qwen3_4b.ps1`，说明见 `docs/setup/LOCAL_LLM_SETUP.md`。

当前页面边界：

- 首页展示预测排名、回测摘要和基础更新入口；首页 RAG 检索和 AI 解释前端入口已移除。
- AI 模拟盘展示用户画像、账户、持仓、订单、资金、回放和单股归因。
- AI Agent 提供多会话对话、工具调用、审批、运行轨迹、Context/Message/Memory/ReAct/Reflection/Handoff 安全摘要。
- 系统监控只读采集数据、模型、RAG、Agent 和组合指标，不自动修改业务状态。

### 3. AI 模拟盘

```text
outputs/ranking_latest.csv 或历史 ranking
    -> scoring/final_score.py
    -> pipelines/paper_trading_pipeline.py
    -> portfolio/rebalance_rules.py
    -> portfolio/paper_trading_engine.py
    -> outputs/portfolio/<user_id>/
```

无账户 Binding 时，模拟盘继续使用默认 `hierarchical_top10`，业务结果保持：

- Top10 新买入。
- Top15 持仓缓冲。
- Top10 目标仓位 80%。
- 目标现金 5%。
- 单股最高 30%。
- 遵守 A 股一手约束。
- 不接入真实交易，不连接券商。

存在有效账户 Binding 时，`StrategyRuntimeResolver` 按
`user_id + account_id + trade_date` 解析已注册且禁用的个性化版本，并把同一份
`ResolvedStrategyConfig` 传给每日模拟盘、历史回放、目标组合、调仓规则、订单、
快照和审计。Binding 只影响该用户、该账户及生效日之后的未来运行。

历史回放默认从 `config.DEFAULT_PAPER_TRADING_START_DATE` 开始。前端“重新执行历史回放”会备份旧结果并强制从所选日期重建。

### 4. 长期模拟盘策略调整

完整状态机：

```text
discussion
  -> proposal_draft (可多轮版本化修改)
  -> locked_for_implementation
  -> isolated_implementation
  -> validated / validation_failed
  -> apply_plan_pending_confirmation
  -> registered_disabled
  -> activation_plan_pending_confirmation
  -> account_binding_active / scheduled
  -> position_plan_pending_confirmation
  -> paper_position_committed
```

正式操作被拆成三个互不替代的确认边界：

```text
确认应用并注册
确认启用未来策略
确认执行模拟盘调仓
```

注册不会启用，启用不会立即修改当前持仓，当前持仓调整会再次校验账户、
Binding 和 config hash 后调用原 `paper_trading_pipeline`。Proposal、实现、
应用、Binding 和实际调仓均保留历史；无 Binding 用户继续走默认策略。

核心调用链：

```text
AI Agent 对话
  -> strategy.get_context / strategy.get_active_proposal
  -> strategy.save_proposal_draft
  -> strategy.prepare_implementation
  -> runtime/strategy_drafts/<user>/<proposal>/<version>/
  -> validation + security + isolated backtest
  -> strategy.create_apply_plan
  -> strategy.apply.commit
  -> disabled StrategyRegistry version
  -> strategy.create_activation_plan
  -> strategy.binding.commit
  -> StrategyBinding
  -> StrategyRuntimeResolver
  -> paper_trading_pipeline
  -> strategy.preview_current_position_change
  -> strategy.position.commit
```

`strategy.get_audit_trace` 可按稳定 ID 还原 Proposal 版本、锁定实现、
artifact、两次确认、注册结果、Binding、会话、运行及持仓前后变化；审计输出
会移除 confirmation token。

### 5. AI Agent

当前 Agent 主链路：

```text
app/pages/ai_agent.py
    -> agent/executor.py
    -> agent/goal_planning.py
    -> agent/intent_decomposition/
    -> agent/orchestration/
    -> agent/context/
    -> agent/communication/
    -> agent/memory/
    -> agent/tool_engine.py
    -> agent/tools/tool_registry.py
    -> agent/services/
    -> agent/react/
    -> agent/reflection/
    -> agent/handoff/
    -> agent/mcp/
    -> agent/specialists/
    -> database/repositories/agent_repository.py
```

Agent 当前具备：

- UserGoal / TaskPlan 规划和能力缺口判断。
- 意图拆解、依赖解析、只读并发执行和结果聚合。
- ContextManager：受限上下文收集、压缩、清洗、窗口和 artifact 引用。
- AgentMessage / CommunicationBus：消息协议、清洗、存储、路由和轨迹。
- MemoryManager：WorkingMemory、SQLite 记忆、检索、合并、剪枝和安全清洗。
- ReAct Observe / Replan：Observation、ObservePolicy、Trace 和有限 Replan。
- Reflection Critic：只读审查，不直接写业务状态。
- Multi-Agent Handoff：Coordinator 与 Market / Portfolio / Risk / Report specialist 的结构化交接。
- ToolExecutor v2：工具权限、只读/写、确认、超时、摘要、产物和运行可靠性统一入口。
- WriteGateway：写操作 approval / revalidate / idempotency / commit 边界。

组合状态、风险和仓位预览共用 `portfolio/portfolio_snapshot.py` 的只读归一化快照：`cash` 固定表示未投资现金，总资产固定按“未投资现金 + 有效持仓市值”计算，仓位权重随之重算。快照输出 `snapshot_id` 与逐项 `calculation_trace`，使状态、风控和预览可验证使用同一资产口径；跨用户、跨账户、显式快照时间不一致、负资产或非有限数会拒绝合并，原始 latest 文件不会被读取链路改写。

`agent/logic_integrity.py` 是不依赖 LLM 的流程安全门：它验证资产快照、任务/结果、完成状态、Replan 审计和写入边界。出现逻辑错误时，执行器返回用户可见的 `feature_unavailable`，禁止继续、推荐、Replan、审批和写入，不能被 LLM 覆盖。

Completion 与 Reflection Critic 返回 `REPLAN_READONLY` 时，`agent/replan_execution.py` 只消费经注册表验证的只读工具；每轮记录触发源、缺失项前后、计划/结果签名、任务与工具、产物变化、进展和停止原因。相同请求、相同计划、相同结果、无新有效证据、达到上限、目标完成、预算耗尽或逻辑错误都会立即停止。TopK 由 `agent/top_k.py` 统一解析，优先级为用户显式值、任务值、请求默认值、工具默认值、系统兜底；返回和正常排名源读取均不超过解析后的数量。

当前 Specialist 角色：

```text
Supervisor / Coordinator
Market Intelligence
Portfolio Analysis
Risk Operation
Report
```

重要边界：

- 纯组合风险分析只应运行 `portfolio_state` 和 `portfolio_risk`，不应自动生成推荐方案、候选证据、买卖或调仓预览。
- 明确要求“更稳健 / 推荐 / 建议 / 调仓”的问题可以进入只读推荐链路，但真实写入仍需审批。
- MCP 只允许只读金融证据，MCP 写工具继续禁止。
- UI 和 LLM 不应展示 `confirmation_token`、API Key、数据库路径、内部堆栈、raw payload 等敏感字段。

### 6. 新闻、RAG 和 Ragas

```text
news_data.py / news_mapping/
    -> news_db_sync.py
    -> rag/chunkers.py
    -> rag/bm25_retriever.py
    -> rag/dense_retriever.py
    -> rag/hybrid_retriever.py
    -> rag/reranker.py
    -> agent/services/evidence_service.py
    -> agent/tools/evidence_adapters.py
```

RAG 能力包含 BM25、Dense、Hybrid/RRF、metadata filter、rerank、检索日志和新闻内容级 chunk。Ragas 离线评测在 `evaluation/ragas_eval/`，用于 Context Precision、Context Recall、content faithfulness、Answer Relevancy 等指标。

### 7. 系统监控

```text
app/pages/system_monitor.py
    -> evaluation/system_monitor.py
    -> database/repositories/system_monitor_repository.py
    -> system_monitor_snapshots / system_monitor_alerts
```

系统监控只读采集并展示：

- 数据层指标。
- 模型层指标。
- RAG 层指标。
- Agent 层指标。
- 组合/模拟盘指标。

告警阈值来自 `configs/system_monitor_thresholds.json`。监控不会自动切换模型、修改策略、修改 Prompt、调整 RAG 参数或更新仓位。

### 8. 调度和自动任务

```text
scheduler_manager.py
scheduler/
scripts/run_scheduled_daily_update.ps1
scripts/install_windows_daily_task.ps1
runtime/jobs/
```

调度任务负责每日更新和用户级任务执行。状态保存在 `runtime/jobs/`，日志保存在 `logs/`。

## 数据库与运行数据

开发数据库：

```text
data/agent_quant.db
```

安装版数据库：

```text
%LOCALAPPDATA%\StockDailyApp\database\agent_quant.db
```

安装版首次启动通过 `database/migrations/*.sql` 初始化用户数据库，不复制开发机 live 数据库。

当前 migration 序列从 `001_initial_schema.sql` 到
`023_paper_decision_strategy_metadata.sql`，其中 `019`—`023` 新增：

- 股票、预测、新闻、组合和用户配置。
- 模拟盘账户、持仓、订单、资金流水、净值和交易成本。
- Agent action log、runtime history、steps、tool calls、sources、sandbox、approval、commit、memory、artifacts、messages。
- 策略注册。
- 版本化 Proposal 与隔离 Implementation。
- 用户/账户/生效日隔离的 Strategy Binding。
- 订单、账户快照、决策日志的策略版本和 resolved config 元数据。
- `paper_strategy_execution_history` 的持仓前后、订单、现金和策略运行审计。
- 新闻内容级字段。
- 系统监控快照和告警。

## 关键输出目录

```text
outputs/ranking_latest.csv
    APP 当前预测排名核心输入。

outputs/rankings/history/ranking_YYYYMMDD.csv
    历史回放使用的每日原始排名。

outputs/portfolio/<user_id>/
    模拟盘账户、持仓、订单、净值、资金流水和回放状态。

outputs/users/<user_id>/recommendations/
    用户级 AI 调整后的推荐结果。

runtime/artifacts/<user_id>/
    Agent 工具结果、Context、Message、Memory、ReAct、Reflection、Handoff 等产物引用。

runtime/replay_audit/<user_id>/<run_id>/
    历史回放逐日审计 JSON / Markdown。

runtime/strategy_drafts/<user_id>/<proposal_id>/<version>/
    隔离实现、config/code artifact、diff、安全检查、测试和回测报告。

models/external_zoo/
    Model Zoo 下载的外部模型文件。

models/dft_unet/
    DFT_UNET 相关模型文件和微调输出。
```

## Windows 桌面发布

项目支持三种运行方式：

```powershell
# 开发模式
.\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8501 --server.address 127.0.0.1 --server.headless true --browser.gatherUsageStats false

# 源码桌面模式
.\.venv\Scripts\python.exe desktop_launcher.py

# Windows onedir 构建
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

发布模式入口为 `StockDailyApp.exe`，由 `desktop_launcher.py` 打包生成。启动器选择动态本地端口，只监听 `127.0.0.1`，后台启动 Streamlit 子进程，并用 `pywebview` 打开桌面窗口。

安装和升级不得覆盖用户数据库、配置、输出、日志、模型和模拟盘数据。

开发模式用户数据：

```text
data/
models/
outputs/
runtime/
logs/
local_app_config.json
```

冻结/安装模式用户数据：

```text
%LOCALAPPDATA%\StockDailyApp\
├── database/
├── outputs/
├── logs/
├── cache/
├── runtime/
├── config/
└── models/
```

构建与验证：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-desktop.txt
.\.venv\Scripts\python.exe .\scripts\prepare_distribution_assets.py
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
.\.venv\Scripts\python.exe .\scripts\verify_distribution.py
```

`build_windows.ps1` 当前仍会自行检测 `py`/`python`，不属于已验证的 D 盘 8501 启动链路。如要求构建流程也完全禁止 C 盘 Python，必须先改造该脚本的解释器选择逻辑，再执行 Windows 构建。

## 常用验证命令

```powershell
.\.venv\Scripts\python.exe -m compileall -q agent app portfolio scoring rag pipelines database strategies scripts
.\.venv\Scripts\python.exe -m pytest tests\unit -q
.\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8501 --server.address 127.0.0.1 --server.headless true --browser.gatherUsageStats false
```

针对前端或 Agent 改动，除了 pytest，还应真实打开并检查：

```text
http://127.0.0.1:8501
首页 / 预测排名
AI Agent
AI 模拟盘
系统监控
```

## 接手优先级

1. 先读 `AGENTS.md`、`PROJECT_STRUCTURE.md`、`PROJECT_FILE_DIRECTORY.md`。
2. 处理 APP 页面时先看 `app.py`、`app/pages/ai_agent.py`、`app/pages/ai_paper_trading.py`、`app/pages/system_monitor.py`。
3. 处理每日更新时先看 `daily_incremental_update.py`、`data_tushare.py`、`alpha158.py`、`model_zoo_backend.py`、`pipelines/daily_update_pipeline.py`。
4. 处理模拟盘时先看 `portfolio/`、`pipelines/paper_trading_pipeline.py`、`pipelines/paper_backfill_pipeline.py`、`app/pages/ai_paper_trading.py`。
5. 处理 Agent 时先看 `agent/executor.py`、`agent/tool_engine.py`、`agent/tools/tool_registry.py`、`agent/services/`、`agent/write_gateway.py`。
6. 处理 Context/Message/Memory/ReAct/Reflection/Handoff 时分别看：
   - `agent/context/`
   - `agent/communication/`
   - `agent/memory/`
   - `agent/react/`
   - `agent/reflection/`
   - `agent/handoff/`
7. 处理 RAG/Ragas 时先看 `rag/`、`news_db_sync.py`、`agent/services/evidence_service.py`、`evaluation/ragas_eval/`。
8. 修改后至少运行相关单测；改核心逻辑时跑更宽的 `tests/unit` 回归。

## 阶段文档入口

当前较新的阶段文档集中在：

```text
docs/phase12_context_system_docs/
docs/phase13_communication_system_docs/
docs/phase14_memory_system_docs/
docs/phase15_react_observe_replan_docs/
docs/phase16_17_reflection_handoff_docs/
```

这些目录包含执行指南、阶段报告、网页检查报告和最终交付报告。`docs/handoff/` 仍保留更早的业务规则、数据字典、模型规格、新闻/RAG、模拟盘规则和开放决策说明。

## Disclaimer

## Stable portfolio workflow guardrails

```text
portfolio recommendation
  -> target holding count × candidate redundancy (default 2.0)
  -> exact ranking source read
  -> strict target-design constraints
  -> Completion / Critic
  -> shared readonly Replan controller
  -> FINAL_RESPONSE audit event
```

- LLM token and call quotas are disabled by default only. Tool-call limits, run-step limits, timeouts, retries, no-progress stopping, readonly-only Replan, write confirmation and approval checks are unchanged.
- A `logic_error` / `feature_unavailable` terminal state has priority over Completion, Critic and report generation. It returns the deterministic safe message, records suppressed Replan intent, and cannot create a plan, approval or write.
- Target designs must meet accounting, cash, candidate identity, duplicate, target-count, single-position and industry constraints. The validator never silently clips weights. Incomplete industry metadata with an industry cap is `industry_constraint_unverifiable`, so the design is not executable.
- Replan audit records the request source(s), missing outputs before/after, plan/result signatures, planned/executed tasks, changed outputs, progress, stop reason and timestamps. The execution counter advances only when a recovery plan really begins execution.
- `FINAL_RESPONSE` is an independent AgentMessage audit event with final status, message source/template, integrity/completion/critic/Replan facts, approval/write flags, a response hash and no secrets.
- The offline benchmark is in `benchmarks/agent/`; formal outputs are in `outputs/benchmarks/agent/`. It has 84 cases (A–F, 14 each), runs offline LLM-contract cases five times and deterministic cases three times, and gates on zero unauthorized writes, approval bypasses, Replan-limit violations and TopK overreads.
- The L1 real-LLM capability benchmark is separate in `benchmarks/agent_capability/`. It contains 180 cases (A–F, 30 each; 108 development / 36 validation / 36 hidden), runs each case through the ordinary `run_agent_request` chain at least five times, and keeps hidden Gold outside Agent prompts. Every iteration uses a new synthetic paper user, conversation, SQLite and output fixture under `outputs/benchmarks/agent_capability/`; it never uses a production database, broker or committed paper order. Its resume key is `case_id + iteration + model_config_hash`, and failures are retained with redacted normalized traces and evidence-only diagnostics.

### L1 real-LLM audit and scoring boundary (2026-07-20)

- `agent/llm_audit.py` persists a redacted `LLM_CALL` receipt for every benchmark-bound real LLM transport attempt. The receipt records formal entry, run/conversation/case identifiers, stage, provider/model, timing, success, status/request ID when exposed, schema outcome and error category; it never records secrets, prompts or full responses.
- `agent.executor.run_agent_request` is the only producer of `formal_entry_used=true` / `formal_entry_name=agent.executor.run_agent_request`. The benchmark runner reads this evidence and cannot manufacture it.
- `benchmarks/agent_capability/` scores only samples with formal entry evidence, a persisted real planner receipt, and a reviewer receipt when the normal flow requires it. Provider, trace and other infrastructure failures are retained but excluded from Agent metrics.
- `outputs/benchmarks/agent_capability/metrics_pipeline_repair.json` separates Agent metric records (value/numerator/denominator/status/reason) from infrastructure metrics. With zero valid samples all Agent capability and safety metrics are N/A, including `forbidden_capability_rate`.
- Run and test commands must use `D:\stock_daily_app\.venv\Scripts\python.exe`; the local Streamlit service listens only on `127.0.0.1:8501`.

This project is for machine learning, financial data analysis and demonstration only. It is not investment advice and is not for live trading.

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。回测和模拟盘结果仅代表历史或纸面环境下的项目演示，不代表未来收益。
