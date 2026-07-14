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
python daily_incremental_update.py --token <TUSHARE_TOKEN> --base-version latest
```

`daily_incremental_update.py` 只支持外部模型后端，不再加载或训练旧本地 MLP。

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

## Windows 桌面发布

项目支持两种并存运行方式：

```powershell
# 开发模式
python -m streamlit run app.py

# 源码桌面模式
python desktop_launcher.py

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
python -m pip install -r requirements.txt
python -m pip install -r requirements-desktop.txt
python .\scripts\prepare_distribution_assets.py
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
python .\scripts\verify_distribution.py
```

详细说明见：

```text
docs/WINDOWS_DISTRIBUTION.md
codex_tasks/37_PHASE_WINDOWS_DESKTOP_INSTALLER.md
```
