# Windows 桌面发布说明

本文档说明 `stock_daily_app` 的双运行模式、打包方式、安装脚本和用户数据路径策略。

## 运行模式

开发模式继续使用源码目录中的数据、配置和输出：

```powershell
cd D:\stock_daily_app
python -m streamlit run app.py
```

源码桌面模式用于验证桌面启动器，不需要先打包：

```powershell
cd D:\stock_daily_app
python desktop_launcher.py
```

也可以只检查启动器会使用的路径和命令，不启动窗口：

```powershell
python desktop_launcher.py --dry-run
```

发布模式入口是：

```text
StockDailyApp.exe
```

EXE 会选择动态本地端口，仅监听 `127.0.0.1`，后台启动 Streamlit 子进程，然后用 `pywebview` 打开桌面窗口。窗口关闭后，启动器会终止后台 Streamlit 子进程。

## 路径策略

开发模式保持当前项目目录：

```text
D:\stock_daily_app
├── data/
├── models/
├── outputs/
├── runtime/
└── logs/
```

安装版写入用户目录：

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

安装版中的 SQLite 数据库路径为：

```text
%LOCALAPPDATA%\StockDailyApp\database\agent_quant.db
```

源码开发库仍为：

```text
D:\stock_daily_app\data\agent_quant.db
```

本地 Token、AI Key 和用户设置在安装版写入：

```text
%LOCALAPPDATA%\StockDailyApp\config\local_app_config.json
```

## 数据库初始化和升级

项目已有 `database/migrations/*.sql`。安装版首次启动时会在用户数据目录创建数据库，并通过现有 migration 初始化结构。

升级时如果用户数据库已存在，程序继续使用原数据库，不复制模板库，也不覆盖模拟盘账户、持仓、订单、资金流水、用户画像和本地配置。

当前没有把开发机的 live 数据库复制为模板库，也没有生成 `agent_quant_template.db`。

## 构建依赖

先安装业务依赖和桌面打包依赖：

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-desktop.txt
```

桌面新增依赖：

```text
pywebview    # 桌面窗口
pyinstaller  # onedir 构建
```

## 构建命令

完整构建：

```powershell
cd D:\stock_daily_app
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

默认构建会排除外部模型推理的大型可选依赖，以保证桌面壳、页面展示、配置和本地数据目录策略可以稳定打包。若要尝试把外部模型推理依赖一起打进安装包，先设置：

```powershell
$env:STOCK_DAILY_INCLUDE_OPTIONAL_ML = "1"
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

完整内置模型依赖会显著拉长 PyInstaller 分析时间，并生成更大的安装目录。

只运行 PyInstaller：

```powershell
python -m PyInstaller --noconfirm --clean .\stock_daily_app.spec
```

构建输出：

```text
dist\StockDailyApp\StockDailyApp.exe
```

分发检查：

```powershell
python .\scripts\verify_distribution.py
```

## Inno Setup

安装 Inno Setup 6 后，`build_windows.ps1` 会自动调用 `ISCC.exe`。

手动构建安装包：

```powershell
ISCC.exe /DMyAppVersion=0.1.0 .\installer\StockDailyApp.iss
```

安装包输出：

```text
installer_output\StockDailyApp_Setup_0.1.0.exe
```

安装脚本使用当前用户安装：

```text
{localappdata}\Programs\StockDailyApp
```

卸载默认只删除程序文件，不删除：

```text
%LOCALAPPDATA%\StockDailyApp\database
%LOCALAPPDATA%\StockDailyApp\config
%LOCALAPPDATA%\StockDailyApp\outputs
```

## 不打包的内容

默认不打包：

```text
外部模型推理的大型可选依赖
data/
models/
outputs/
logs/
runtime/
external_repos/
local_app_config.json
.env
*.db
*.sqlite
__pycache__/
.pytest_cache/
.git/
build/
dist/
```

必要的只读资源包括：

```text
app.py
.streamlit/config.toml
database/migrations/
database/seed/
resources/
model_zoo/configs/
```

## 发布流程

1. 更新 `app_version.py` 中的 `APP_VERSION`。
2. 确认开发模式仍能启动。
3. 运行 `python .\scripts\prepare_distribution_assets.py`。
4. 运行 `powershell -ExecutionPolicy Bypass -File .\build_windows.ps1`。
5. 运行或检查 `python .\scripts\verify_distribution.py`。
6. 在干净 Windows 用户环境安装 `installer_output\StockDailyApp_Setup_<version>.exe`。
7. 验证首次启动创建用户数据库，再次启动不覆盖用户数据。

## 常见问题

如果没有生成安装包，但 `dist\StockDailyApp\StockDailyApp.exe` 存在，通常是本机没有安装 Inno Setup。安装 Inno Setup 6 后重新运行 `build_windows.ps1` 即可。

如果桌面窗口打不开，先运行：

```powershell
python desktop_launcher.py --dry-run
```

再查看：

```text
logs\desktop_launcher.log
logs\streamlit_child.log
```

安装版日志位于：

```text
%LOCALAPPDATA%\StockDailyApp\logs
```

如果每日更新失败，查看：

```text
rolling_update_app.log
auto_retrain.log
```
