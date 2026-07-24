# Stock Daily App FastAPI 服务端

阶段 3 将整个 Streamlit 应用的业务调用统一迁移到 FastAPI。Streamlit 只负责页面交互和展示，Agent、RAG、模拟盘、回测、模型搜索、配置和系统监控均由服务端执行。

## 架构

```text
Streamlit / future React
        ↓ HTTP JSON
FastAPI server/api
        ↓
Application Service
        ↓
Agent / RAG / Portfolio / Pipeline / Repository
```

客户端不得直接导入 `application`、`agent`、`database`、`pipelines`、`portfolio` 或 RAG 模块。

## 启动

安装增量依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-agent-api.txt
```

启动 FastAPI：

```powershell
$env:AGENT_API_HOST = "127.0.0.1"
$env:AGENT_API_PORT = "8010"
.\.venv\Scripts\python.exe -u run_agent_api.py
```

另一个终端启动 Streamlit：

```powershell
$env:STOCK_AGENT_API_URL = "http://127.0.0.1:8010"
.\.venv\Scripts\python.exe -u -m streamlit run .\app.py
```

正式交付提供 `D:\google\D_google_run_stock_daily_app.bat`，无需手动打开两个终端。

## 核心接口

- `GET /api/v1/health`
- `GET /openapi.json`
- `GET /api/v1/dashboard/bootstrap`
- `POST /api/v1/dashboard/operations/{operation}`
- `POST /api/v1/agent/operations/{operation}`
- `POST /api/v1/paper-trading/operations/{operation}`
- `POST /api/v1/paper-profile/operations/{operation}`
- `POST /api/v1/model-search/operations/{operation}`
- `POST /api/v1/system-monitor/operations/{operation}`

每个 operation 都由服务端白名单控制，不能通过接口执行任意 Python 函数。

## 数据合同

请求和响应只使用 JSON。DataFrame、Series、Path、日期、元组和业务结果对象通过显式类型标记传输，不使用 pickle。

LLM API Key 不会从服务端返回到 Streamlit。服务端生成短期 `settings_token`，连接验证和 Agent 执行时再由服务端恢复对应配置。

## React 兼容

FastAPI 不返回 Streamlit 对象或页面 HTML。后续 React 只需替换客户端，不需要重构 Agent、RAG、数据库和 Application Service。

## 当前阶段边界

阶段 3 仍采用同步 HTTP 请求。长任务持久化、SSE 流式状态、取消和服务重启恢复在阶段 4 完成。
