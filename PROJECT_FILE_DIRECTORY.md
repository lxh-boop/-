# 项目文件目录与作用说明

本文档按当前项目主要目录整理文件作用。`data/`、`models/`、`outputs/`、`logs/` 等目录主要保存本地运行产物，GitHub 中只保留占位文件。

## 根目录

| 文件 / 目录 | 作用 |
|---|---|
| `.gitattributes` | 统一 Git 中文件换行和二进制文件识别规则。 |
| `.gitignore` | 排除本地数据、模型权重、日志、密钥配置和缓存文件，避免误上传。 |
| `AGENTS.md` | Codex 接手项目时的阶段说明、开发约束和任务背景。 |
| `README.md` | 项目说明文档，包含安装、训练、每日更新、回测和启动 APP 命令。 |
| `PROJECT_STRUCTURE.md` | 项目结构总览和主要入口说明。 |
| `PROJECT_FILE_DIRECTORY.md` | 当前文件目录与作用说明。 |
| `requirements.txt` | Python 依赖列表。 |
| `config.py` | 全局配置，包括路径、股票池、模型、LLM、回测和风险阈值等参数。 |
| `app.py` | Streamlit 主应用入口，负责页面展示、侧边栏设置、任务触发和结果展示。 |
| `train_model.py` | 初始训练入口，读取本地 Qlib / CSV 数据并训练 Alpha158 MLP 模型。 |
| `daily_incremental_update.py` | 每日增量更新入口，拉取最新行情、更新缓存、预测排名并可微调模型。 |
| `daily_update.py` | 每日更新相关的兼容或辅助脚本。 |
| `rolling_update.py` | 滚动更新旧入口或兼容脚本。 |
| `auto_model_search.py` | 模型搜索兼容入口，调用新的目标搜索流程。 |
| `predict_latest.py` | 使用已有模型生成最新预测排名的脚本。 |
| `alpha158.py` | 构造 Alpha158 风格量化因子、未来收益标签和展示字段。 |
| `data_local.py` | 读取本地 Qlib / CSV 历史行情数据。 |
| `data_tushare.py` | 使用 Tushare 拉取股票池、日线行情、指数和最近交易日数据。 |
| `universe.py` | 统一管理 CSI300 股票池读取、缓存和股票名称补全。 |
| `torch_models.py` | PyTorch MLP 模型结构定义。 |
| `torch_trainer.py` | PyTorch 模型训练、验证、预测和指标计算逻辑。 |
| `model_store.py` | 本地模型版本保存、读取和 latest 指针管理。 |
| `model_factory.py` | 根据模型后端名称创建或加载模型实例。 |
| `model_zoo_backend.py` | Model Zoo 后端统一封装，连接外部时间序列模型。 |
| `model_backends/` | 传统本地模型后端封装目录。 |
| `model_zoo/` | 外部时间序列基础模型下载、检查、窗口构造和适配目录。 |
| `external_models/` | 用户已有外部模型适配目录，如 DFT_UNET。 |
| `model_discovery/` | 全网模型候选搜索、记录、下载和训练状态管理目录。 |
| `news_mapping/` | 新闻 / 公告与股票、事件、概念映射目录。 |
| `core/` | 新架构核心模块目录，逐步承接配置、搜索等通用能力。 |
| `app/` | 新架构 APP 页面、服务和组件目录。 |
| `scripts/` | 命令行脚本目录，包含回测、模型搜索和测试脚本。 |
| `tests/` | 自动化测试目录。 |
| `data/` | 本地行情、特征、股票池和新闻缓存目录，GitHub 只保留 `.gitkeep`。 |
| `models/` | 本地训练模型、外部权重和模型库目录，GitHub 只保留 `.gitkeep`。 |
| `outputs/` | 排名、回测、模型搜索、测试报告等输出目录，GitHub 只保留 `.gitkeep`。 |
| `logs/` | 训练、更新、搜索和 APP 运行日志目录，GitHub 只保留 `.gitkeep`。 |
| `external_repos/` | 下载的外部模型代码仓库目录，GitHub 只保留 `.gitkeep`。 |
| `backtest.py` | 基础回测入口，负责按模型输出做 TopK 回测和指标生成。 |
| `backtest_engine.py` | 回测核心计算逻辑，包括收益、净值、成本和基准口径。 |
| `backtest_rebalance.py` | TopK 调仓逻辑，保留仍在池内股票，只交易新进和跌出股票。 |
| `backtest_metrics.py` | 回测指标计算，如年化收益、夏普、最大回撤、胜率等。 |
| `backtest_external_models.py` | 外部模型预测结果的回测入口。 |
| `evaluate_external_models.py` | 批量评估外部模型预测效果。 |
| `compare_model_performance.py` | 比较不同模型的回测和预测表现。 |
| `diagnose_model_performance.py` | 诊断模型表现、分布、相关性和潜在异常。 |
| `calibration.py` | 概率校准模块，支持 Platt scaling、isotonic 和 fallback。 |
| `risk_scoring.py` | 风险评分模块，基于波动、回撤、流动性、冲击和新闻风险计算风险等级。 |
| `confidence_scoring.py` | 可信度评分模块，综合概率强度、排名位置、校准质量和风险惩罚。 |
| `ranking_schema.py` | 统一 ranking 字段规范、字段补齐和校验函数。 |
| `market_context.py` | 计算市场指数、成交、波动等市场环境特征。 |
| `event_rules.py` | 新闻事件类型、正负面、中立和风险事件规则。 |
| `news_data.py` | 新闻 / 公告数据读取、缓存和预处理。 |
| `news_features.py` | 新闻事件衍生特征计算。 |
| `rag_store.py` | RAG 文档存储和索引数据结构。 |
| `rag_indexer.py` | 构建 RAG 检索索引。 |
| `rag_retriever.py` | 根据查询检索相关证据文档。 |
| `rag_utils.py` | RAG 通用工具函数。 |
| `llm_client.py` | OpenAI-compatible 大模型客户端，支持连接测试和 chat completions。 |
| `llm_prompts.py` | 生成股票解释 Prompt，包含免责声明和禁止买卖建议约束。 |
| `llm_explainer.py` | 调用 LLM 生成个股解释，并处理失败兜底和缓存。 |
| `local_config.py` | 本地配置读写，如 Token、AI 配置和 APP 设置。 |
| `scheduler_manager.py` | 每日自动更新任务的配置和状态管理。 |
| `inspect_external_model.py` | 检查外部 `.pth` checkpoint 类型、keys、state_dict 和配置字段。 |

## `app/`

| 文件 / 目录 | 作用 |
|---|---|
| `app/__init__.py` | APP 包初始化文件。 |
| `app/pages/` | Streamlit 子页面目录。 |
| `app/pages/__init__.py` | 页面包初始化文件。 |
| `app/pages/model_search.py` | 模型搜索与回测结果页面，展示候选模型、回测表和默认策略选择。 |
| `app/services/` | APP 页面使用的服务函数目录。 |
| `app/services/__init__.py` | 服务包初始化文件。 |
| `app/services/file_loader.py` | 安全读取 CSV / JSON，处理缺文件、空文件、缺字段和异常格式。 |
| `app/services/backtest_display.py` | 回测结果展示辅助函数。 |
| `app/services/model_search_results.py` | 模型搜索结果读取、筛选和默认策略保存逻辑。 |
| `app/components/` | APP 可复用组件目录。 |
| `app/components/__init__.py` | 组件包初始化文件。 |

## `core/`

| 文件 / 目录 | 作用 |
|---|---|
| `core/__init__.py` | core 包初始化文件。 |
| `core/config/__init__.py` | 配置包初始化文件。 |
| `core/config/paths.py` | 统一管理项目根目录、输出目录和常用路径。 |
| `core/search/__init__.py` | 搜索包初始化文件。 |
| `core/search/discovery.py` | 模型发现流程的核心入口。 |
| `core/search/target_search.py` | 目标模式搜索核心逻辑，汇总候选、预测和回测结果。 |

## `model_backends/`

| 文件 | 作用 |
|---|---|
| `model_backends/__init__.py` | 模型后端包初始化文件。 |
| `model_backends/base.py` | 统一模型后端基础接口。 |
| `model_backends/lightgbm_backend.py` | LightGBM 模型训练、预测和保存封装。 |
| `model_backends/registry.py` | 本地模型后端注册和加载入口。 |

## `external_models/`

| 文件 | 作用 |
|---|---|
| `external_models/__init__.py` | 外部模型包初始化文件。 |
| `external_models/dft_unet_adapter.py` | DFT_UNET 外部模型适配器，负责检查模型、构造输入并输出统一预测字段。 |
| `external_models/model_registry.py` | 外部模型注册表，支持选择 Alpha158 MLP 或 External DFT_UNET。 |

## `model_zoo/`

| 文件 / 目录 | 作用 |
|---|---|
| `model_zoo/__init__.py` | Model Zoo 包初始化文件。 |
| `model_zoo/downloader.py` | 下载外部模型权重和元数据。 |
| `model_zoo/inspect_model.py` | 检查模型库文件、依赖和权重状态。 |
| `model_zoo/metadata.py` | 管理模型元数据，如来源、状态、路径和许可证。 |
| `model_zoo/ohlcv_windows.py` | 将 OHLCV 日线数据转换为时间序列模型窗口输入。 |
| `model_zoo/registry.py` | Model Zoo 模型注册、状态查询和加载入口。 |
| `model_zoo/adapters/` | 不同外部时间序列模型的适配器目录。 |
| `model_zoo/adapters/base.py` | Model Zoo 适配器基础接口。 |
| `model_zoo/adapters/chronos_adapter.py` | Chronos / Chronos-Bolt 模型适配器。 |
| `model_zoo/adapters/moment_adapter.py` | MOMENT 模型适配器。 |
| `model_zoo/adapters/moirai_adapter.py` | Moirai / Uni2TS 模型适配器。 |
| `model_zoo/adapters/timesfm_adapter.py` | TimesFM 模型适配器。 |
| `model_zoo/adapters/generic_pytorch_adapter.py` | 通用 PyTorch checkpoint 适配器。 |
| `model_zoo/configs/chronos.yaml` | Chronos 模型下载与加载配置。 |
| `model_zoo/configs/moment.yaml` | MOMENT 模型下载与加载配置。 |
| `model_zoo/configs/moirai.yaml` | Moirai 模型下载与加载配置。 |
| `model_zoo/configs/timesfm.yaml` | TimesFM 模型下载与加载配置。 |

## `model_discovery/`

| 文件 | 作用 |
|---|---|
| `model_discovery/__init__.py` | 模型发现包初始化文件。 |
| `model_discovery/model_candidate_schema.py` | 候选模型字段 schema 和分类标准。 |
| `model_discovery/candidate_store.py` | 候选模型 CSV / JSON 保存和读取。 |
| `model_discovery/web_searcher.py` | 通用网页搜索候选模型。 |
| `model_discovery/github_searcher.py` | GitHub 仓库搜索和候选提取。 |
| `model_discovery/huggingface_searcher.py` | Hugging Face 模型搜索和权重信息提取。 |
| `model_discovery/paper_searcher.py` | arXiv / 论文候选搜索。 |
| `model_discovery/repo_downloader.py` | 下载候选 GitHub 仓库到 external_repos。 |
| `model_discovery/checkpoint_downloader.py` | 下载候选模型公开权重。 |
| `model_discovery/train_if_needed.py` | 对无公开权重但代码完整的候选模型记录训练状态。 |
| `model_discovery/model_adapter_generator.py` | 为候选模型生成适配器骨架或记录适配计划。 |
| `model_discovery/discovery_pipeline.py` | 串联搜索、分类、记录和报告输出的发现流程。 |

## `news_mapping/`

| 文件 | 作用 |
|---|---|
| `news_mapping/__init__.py` | 新闻映射包初始化文件。 |
| `news_mapping/schema.py` | 新闻事件、股票映射和概念映射的数据结构定义。 |
| `news_mapping/stock_alias_builder.py` | 构建股票名称、简称、别名和代码的匹配表。 |
| `news_mapping/entity_extractor.py` | 从新闻文本中提取公司、股票和事件实体。 |
| `news_mapping/concept_mapper.py` | 将新闻事件映射到概念、行业或主题。 |
| `news_mapping/llm_mapper.py` | 使用 LLM 辅助新闻事件映射。 |
| `news_mapping/mapping_store.py` | 新闻映射结果的本地数据库读写。 |
| `news_mapping/news_ingestor.py` | 新闻 / 公告数据导入和缓存。 |
| `news_mapping/mapping_pipeline.py` | 新闻映射全流程入口。 |

## `scripts/`

| 文件 | 作用 |
|---|---|
| `scripts/evaluate/run_model_backtest.py` | 统一模型回测命令行入口，生成 daily_returns 和 master table。 |
| `scripts/model_search/discover_models.py` | 模型发现命令行 wrapper。 |
| `scripts/model_search/target_search.py` | 目标模式搜索命令行 wrapper。 |
| `scripts/test/run_all_tests.ps1` | 批量运行 unit、integration、e2e 测试的 PowerShell 脚本。 |

## `tests/`

| 文件 / 目录 | 作用 |
|---|---|
| `tests/conftest.py` | pytest 公共 fixture 和测试路径配置。 |
| `tests/fixtures/` | 测试用样例 ranking、回测表、收益 CSV、搜索结果和指标 JSON。 |
| `tests/unit/test_ranking_schema.py` | 测试 ranking 字段完整性、类型和 TopK 截取。 |
| `tests/unit/test_backtest_metrics.py` | 测试回测指标计算。 |
| `tests/unit/test_backtest_returns.py` | 测试 T+1 / holding_days 收益口径，避免把多日收益当日复利。 |
| `tests/unit/test_rebalance_logic.py` | 测试 TopK 保留、跌出卖出、新进买入的调仓逻辑。 |
| `tests/unit/test_data_cutoff.py` | 测试收盘前后最新可用数据截止日逻辑。 |
| `tests/unit/test_file_loaders.py` | 测试安全读取 CSV / JSON 的异常处理。 |
| `tests/unit/test_risk_confidence.py` | 测试风险等级和可信度评分字段范围。 |
| `tests/unit/test_llm_client_mock.py` | 使用 mock 测试 LLM 客户端空 Key、连接失败和解释调用。 |
| `tests/unit/test_model_search_results.py` | 测试模型搜索结果读取、筛选和默认策略保存。 |
| `tests/unit/test_model_zoo_preflight.py` | 测试模型库依赖和权重状态预检查。 |
| `tests/unit/test_backtest_display.py` | 测试 APP 回测展示辅助逻辑。 |
| `tests/unit/test_target_search.py` | 测试目标模式搜索结果汇总。 |
| `tests/integration/test_app_loads.py` | 测试 Streamlit APP 基础加载。 |
| `tests/integration/test_app_pages.py` | 测试 APP 页面切换和基础元素。 |
| `tests/integration/test_model_search_page.py` | 测试模型搜索页面展示。 |
| `tests/integration/test_backtest_page.py` | 测试回测页面展示。 |
| `tests/integration/test_ai_explainer_page.py` | 测试 AI 解释页面基础流程。 |
| `tests/e2e/test_streamlit_smoke.py` | Streamlit E2E smoke 测试。 |
| `tests/e2e/test_app_playwright.py` | Playwright 浏览器端基础交互测试。 |

## 本地运行产物目录

| 目录 | 作用 |
|---|---|
| `data/` | 保存本地行情缓存、Alpha158 特征、CSI300 股票池、新闻缓存等。 |
| `models/` | 保存训练好的 MLP、LightGBM、DFT_UNET、Chronos、MOMENT 等模型和权重。 |
| `outputs/` | 保存 ranking_latest.csv、回测结果、模型搜索结果、AI 解释、测试报告等。 |
| `logs/` | 保存训练、每日更新、模型搜索、APP 和测试日志。 |
| `external_repos/` | 保存自动下载的外部模型代码仓库。 |

以上运行产物目录默认不提交到 GitHub，需要在本地运行训练、每日更新、模型搜索或回测命令重新生成。
