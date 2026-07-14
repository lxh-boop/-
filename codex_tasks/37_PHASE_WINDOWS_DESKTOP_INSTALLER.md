# 37 Phase Windows Desktop Installer

## 本次新增文件

```text
desktop_launcher.py
runtime_paths.py
app_version.py
requirements-desktop.txt
stock_daily_app.spec
build_windows.ps1
.streamlit/config.toml
installer/StockDailyApp.iss
scripts/prepare_distribution_assets.py
scripts/verify_distribution.py
docs/WINDOWS_DISTRIBUTION.md
resources/database/README.md
resources/defaults/README.md
resources/icons/README.md
```

## 本次修改文件

```text
core/config/paths.py
config.py
local_config.py
app.py
scheduler_manager.py
daily_incremental_update.py
.gitignore
README.md
PROJECT_STRUCTURE.md
PROJECT_FILE_DIRECTORY.md
AGENTS.md
```

## 路径策略

开发模式保持现有行为：

```text
D:\stock_daily_app\data
D:\stock_daily_app\models
D:\stock_daily_app\outputs
D:\stock_daily_app\runtime
D:\stock_daily_app\logs
D:\stock_daily_app\local_app_config.json
```

冻结模式使用：

```text
%LOCALAPPDATA%\StockDailyApp\database
%LOCALAPPDATA%\StockDailyApp\outputs
%LOCALAPPDATA%\StockDailyApp\logs
%LOCALAPPDATA%\StockDailyApp\cache
%LOCALAPPDATA%\StockDailyApp\runtime
%LOCALAPPDATA%\StockDailyApp\config
%LOCALAPPDATA%\StockDailyApp\models
```

统一路径入口位于 `core/config/paths.py`，`runtime_paths.py` 只做兼容导出。

## 数据库策略

当前实际开发数据库：

```text
D:\stock_daily_app\data\agent_quant.db
```

安装版用户数据库：

```text
%LOCALAPPDATA%\StockDailyApp\database\agent_quant.db
```

本阶段不复制开发数据库为模板。首次启动和升级继续复用现有 `database/migrations/*.sql`。

## 构建命令

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-desktop.txt
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

只运行 PyInstaller：

```powershell
python -m PyInstaller --noconfirm --clean .\stock_daily_app.spec
```

如需尝试完整内置外部模型推理依赖：

```powershell
$env:STOCK_DAILY_INCLUDE_OPTIONAL_ML = "1"
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

只运行分发检查：

```powershell
python .\scripts\verify_distribution.py
```

## 已完成验证

- 已确认项目有 `database/migrations/` 和 SQLite 初始化函数。
- 已确认 live 数据库位于 `data/agent_quant.db`。
- 已确认 `local_config.py` 原先读写根目录 `local_app_config.json`，现已接入冻结模式用户配置目录。
- 已确认 APP 手动更新和自动更新原先使用 `sys.executable daily_incremental_update.py`，现已增加冻结模式内部 `--daily-update-child`。

## 未完成事项

- 需要在已安装桌面构建依赖的 Windows 环境运行完整 `build_windows.ps1`。
- 需要在安装 Inno Setup 6 的环境编译 `installer/StockDailyApp.iss`。
- 需要手动关闭桌面窗口后确认 Streamlit 子进程清理。
- 需要在干净用户目录下安装并确认首次数据库初始化和升级不覆盖数据。

## 已知限制

- 当前没有自定义 `.ico` 图标；安装脚本会在图标存在时自动使用。
- 当前没有自动在线更新、代码签名、Microsoft Store 发布或 onefile 构建。
- 默认不打包外部模型推理的大型可选依赖、本地大型模型权重、live 数据库、个人 outputs、日志和密钥配置。
