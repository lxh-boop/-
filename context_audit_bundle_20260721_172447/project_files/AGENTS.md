# A 股每日股票评分系统接手说明

## 项目定位

本项目是 `stock_daily_app`，用于机器学习、金融数据分析、量化因子建模、AI 调整、模拟盘和 Agent 工作台展示。

页面和文档必须保留免责声明：

```text
本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。
```

## 当前模型策略

旧本地 MLP 训练链路已经移除。不要再恢复或引用旧训练、旧预测、旧模型存取入口。

当前默认模型路径是外部模型路线：

```text
Model Zoo：zoo:chronos_bolt_small
DFT_UNET：dft_unet_external
```

每日更新入口：

```powershell
.\.venv\Scripts\python.exe daily_incremental_update.py --token <TUSHARE_TOKEN> --base-version latest
```

`daily_incremental_update.py` 只支持外部模型后端，不再加载或训练旧本地 MLP。

## 当前开发解释器与端口

```text
项目虚拟环境：D:\stock_daily_app\.venv
虚拟环境解释器：D:\stock_daily_app\.venv\Scripts\python.exe
基础解释器：D:\python_runtime\cpython-3.12.0-windows-x86_64-none\python.exe
本地 Web：http://127.0.0.1:8501
```

开发、测试、每日更新和本地 Streamlit 必须显式使用上述 D 盘虚拟环境。
不要使用 `py -3`、裸 `python` 或 C 盘 Python。

## 主要结构

```text
stock_daily_app/
├── app.py
├── desktop_launcher.py
├── runtime_paths.py
├── app_version.py
├── config.py
├── daily_incremental_update.py
├── data_local.py
├── data_tushare.py
├── universe.py
├── alpha158.py
├── model_zoo_backend.py
├── app/
├── agent/
├── portfolio/
├── pipelines/
├── database/
├── evaluation/
├── model_zoo/
├── scoring/
├── rag/
├── scheduler/
├── installer/
├── resources/
├── scripts/
├── docs/
├── data/
├── models/
├── outputs/
├── runtime/
└── logs/
```

## 股票池和数据

股票池统一通过：

```python
from universe import get_stock_pool
```

默认 Universe 是 CSI300。不要在业务代码中手写 300 只股票代码。

Tushare Token 只能来自：

- APP 输入框；
- 本地配置；
- 环境变量 `TUSHARE_TOKEN`。

不要硬编码 Token 或 API Key。

## APP 原则

`app.py` 只负责页面展示和任务触发。APP 打开时不自动训练、不自动全量下载。

最新排名展示以：

```text
outputs/ranking_latest.csv
```

为核心输入。

## 长期模拟盘策略调整

无 Strategy Binding 的用户继续使用默认 `hierarchical_top10`，golden 业务
结果不得变化。个性化请求必须遵循：

```text
多轮 Proposal
-> 锁定版本
-> runtime/strategy_drafts 隔离实现与验证
-> 确认应用并注册
-> registered_disabled
-> 确认启用未来策略
-> user/account/effective_date Binding
-> 确认执行模拟盘调仓
```

三次确认互相独立：注册不得自动启用，启用不得立即修改当前持仓，当前持仓
修改必须再次校验账户、Binding 和 config hash，并调用原模拟盘 Pipeline。

策略含义由 LLM 基于完整会话提出，工具只接受结构化 Proposal，不得自行猜测
或重写策略语义。LLM 缺 Key、余额不足、超时或格式失败时不得自动实施。

正式基线不得被用户个性化请求覆盖。隔离 code/config 只有在安全检查、测试、
回测和确认通过后才能作为新版本原子注册；失败必须回滚且保留历史。

运行时统一通过 `strategies/runtime_resolver.py` 解析策略。每日模拟盘、历史
回放、目标组合、调仓规则、订单、快照和审计必须消费同一份 resolved config。

UI 不得显示 confirmation token。审计链应能关联 `proposal_id`、
`implementation_id`、`plan_id`、`commit_id`、`binding_id`、`run_id` 和
`conversation_id`。

## Windows 桌面发布

项目支持两种并存运行方式：

```powershell
# 开发模式
.\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8501 --server.address 127.0.0.1

# 源码桌面模式
.\.venv\Scripts\python.exe desktop_launcher.py

# Windows onedir 构建
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

发布模式入口为 `StockDailyApp.exe`，由 `desktop_launcher.py` 打包生成。启动器会选择动态本地端口，只监听 `127.0.0.1`，后台启动 Streamlit 子进程，并用 `pywebview` 打开桌面窗口。

开发模式继续使用项目根目录：

```text
data/
models/
outputs/
runtime/
logs/
local_app_config.json
```

冻结模式用户数据写入：

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

安装和升级不得覆盖用户数据库、配置、模拟盘数据、输出和日志。

## 数据库策略

当前开发数据库：

```text
data/agent_quant.db
```

安装版数据库：

```text
%LOCALAPPDATA%\StockDailyApp\database\agent_quant.db
```

首次启动使用 `database/migrations/*.sql` 初始化用户数据库，不复制开发机 live 数据库。

## 构建和验证

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-desktop.txt
.\.venv\Scripts\python.exe .\scripts\prepare_distribution_assets.py
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
.\.venv\Scripts\python.exe .\scripts\verify_distribution.py
```

详细说明见：

```text
docs/WINDOWS_DISTRIBUTION.md
codex_tasks/37_PHASE_WINDOWS_DESKTOP_INSTALLER.md
```
