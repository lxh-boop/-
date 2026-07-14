# 每日更新并发 / 异步改造汇总

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。

## 已完成

1. `data_tushare.fetch_stock_pool_recent_daily_fast`
   - 改造点：按交易日并发下载 Tushare 日线数据。
   - 当前策略：每个交易日一个线程任务；任务内部仍按顺序调用 `daily`、`daily_basic`、可选 `adj_factor`。
   - 默认并发：`min(4, 最近交易日数量)`。
   - 配置方式：
     - 命令行：`python daily_incremental_update.py --token ... --fetch-workers 4`
     - 环境变量：`TUSHARE_DAILY_FETCH_WORKERS=4`
   - 顺序保证：并发完成后按原交易日顺序合并，最终仍按 `code,date` 排序。

2. `daily_incremental_update.py`
   - 新增 `--fetch-workers` 参数。
   - `model_zoo_daily_update` 和 `dft_unet_external_daily_update` 会把该参数传给行情下载函数。

3. `pipelines.rag_pipeline.run_rag_pipeline`
   - 改造点：对多只股票的 RAG 检索并发执行。
   - 当前策略：检索并发，`rag_retrieval_log` 写入仍在主线程串行执行。
   - 默认并发：`min(4, prediction 数量)`。
   - 配置方式：
     - 函数参数：`run_rag_pipeline(..., max_workers=4)`
     - 环境变量：`RAG_PIPELINE_WORKERS=4`
   - 顺序保证：检索结果按原 prediction 顺序汇总。

4. `news_data` 的 AkShare fallback 下载
   - 改造点：
     - `fetch_akshare_announcements` 的按日期 fallback 改为并发抓取。
     - `fetch_akshare_stock_news` 的按股票代码抓取改为并发执行。
   - 当前策略：外部请求并发，CSV 缓存合并和写入仍在主线程串行执行。
   - 默认并发：`AKSHARE_FETCH_WORKERS=4`。
   - 配置方式：
     - 配置项：`AKSHARE_FETCH_WORKERS`
     - 环境变量：`AKSHARE_FETCH_WORKERS=4` 或 `NEWS_FETCH_WORKERS=4`
   - 顺序保证：并发完成后按原日期/股票代码顺序合并。

5. SQLite 短连接关闭
   - 改造点：`database.connection.initialize_database` 和 `database.sqlite_store.SQLiteStore` 使用 `contextlib.closing(...)` 关闭连接。
   - 原因：`sqlite3.Connection` 的上下文管理器只提交/回滚，不自动关闭连接；Windows 下会导致临时库文件被占用，也会影响并发测试稳定性。

## 仍适合继续并发 / 异步的地方

1. Agent 只读工具
   - 相关文件：`agent/orchestration/multi_task_executor.py`
   - 当前方向：已有只读多任务并发框架。
   - 可继续优化：对 `stock_analysis` 的新闻、RAG、排名读取做更细粒度并发。
   - 注意：写操作、确认计划、模拟盘执行必须保持串行。

2. 模型库批量下载
   - 相关文件：`model_zoo/downloader.py`
   - 适合并发的部分：多个模型同时下载。
   - 注意：单个 HuggingFace snapshot 本身已有下载管理，不要在同一模型目录重复并发写。

3. 回测 / 多模型评估
   - 相关模块：`model_backends/`、`evaluation/`、`pipelines/`
   - 适合并发的部分：多模型预测、多 TopK 回测、多策略指标计算。
   - 注意：最终报告、CSV、数据库写入需要统一汇总后串行保存。

## 不建议直接并发的地方

1. `add_alpha158_features`
   - 原因：当前基于完整行情表计算滚动特征，股票内时序依赖强。
   - 后续方向：可以按股票分组并行计算，再统一 concat，但要严格测试滚动窗口一致性。

2. 模拟盘执行
   - 相关模块：`portfolio.paper_trading_engine`、`portfolio.storage`、`agent.tools.paper_trade_execute_tool`
   - 原因：账户现金、持仓、订单、净值之间有强一致性要求。
   - 建议：继续串行执行，并保留确认计划机制。

3. `ranking_latest.csv` 写入
   - 原因：这是 APP 展示核心文件。
   - 建议：计算可以并发，最终写入必须一次性原子替换或串行写。

4. SQLite 写入
   - 原因：本地 SQLite 更适合短事务串行写。
   - 建议：并发读取可以逐步优化，写入集中到主线程或单写队列。

## 测试结果

本次改造后已完成以下验证：

1. `python -m py_compile database\connection.py database\sqlite_store.py pipelines\rag_pipeline.py news_data.py`
   - 结果：通过。

2. RAG 并发行为脚本
   - 结果：通过。
   - 观测：`max_active=4`，证据数 `4`，检索日志数 `4`。

3. Tushare 日线并发行为脚本
   - 结果：通过。
   - 观测：`max_active=4`，返回行数 `4`，最终日期顺序保持为 `20260615` 到 `20260618`。

4. AkShare 个股新闻并发行为脚本
   - 结果：通过。
   - 观测：`max_active=4`，返回行数 `4`。

5. AkShare 公告日期 fallback 并发行为脚本
   - 结果：通过。
   - 观测：`max_active=4`，返回行数 `4`。

6. AkShare 中文列名归一化脚本
   - 结果：通过。
   - 观测：公告中文列名可归一化为标准事件列。

7. pytest 状态
   - 当前 Codex 内置 Python 没有安装项目测试依赖 `pytest` 和 `tushare`，因此本轮没有跑完整 pytest。
   - 已补充单元测试文件：
     - `tests/unit/test_tushare_parallel_fetch.py`
     - `tests/unit/test_rag_pipeline.py`
     - `tests/unit/test_news_data_akshare_fallback.py`

## 建议并发上限

- Tushare 日线：默认 4，建议范围 2-6。
- AkShare 新闻/公告：默认 4，遇到限流降到 2。
- RAG 检索：默认 4，建议范围 2-8。
- CPU 特征计算：按 CPU 核数控制，但要先验证数值一致性。
- 数据库写入：默认 1。

## 每次继续改造后的验证要求

1. 行数一致。
2. 股票数量一致。
3. 日期范围一致。
4. 核心输出文件存在且更新时间变化。
5. `outputs/ranking_latest.csv` 不为空。
6. 涉及的单元测试或本地行为脚本通过。
