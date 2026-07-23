# Agent API 工程化入口

该目录为现有单 Main Coordinator Agent 增加独立服务层，不替换 Streamlit，也不改变业务 Tool、RAG、模拟盘和 Proposal 安全边界。

## 启动

```powershell
python -m pip install -r requirements-agent-api.txt
copy .env.agent-api.example .env
python run_agent_api.py
```

环境变量由操作系统或启动脚本注入；当前代码不会主动读取 `.env` 文件。默认地址：`http://127.0.0.1:8010`。

## 接口

- `GET /health/live`：进程存活检查。
- `GET /health/ready`：输出目录、入口模式和限流配置检查。
- `GET /metrics`：Prometheus 文本指标。
- `POST /v1/agent/chat`：普通 JSON 请求。
- `POST /v1/agent/chat/stream`：SSE 阶段进度流。当前是任务阶段流，不是模型 Token 流。
- `WS /v1/agent/ws`：多轮 WebSocket 请求。

请求示例：

```json
{
  "query": "分析股票 600519",
  "user_id": "demo_user",
  "session_id": "demo_session",
  "reply_language": "zh",
  "top_k": 20
}
```

生产环境建议设置：

```text
AGENT_API_KEY=<随机高强度密钥>
AGENT_REDIS_URL=redis://redis:6379/0
AGENT_API_MAX_CONCURRENCY=4
AGENT_API_TIMEOUT_SECONDS=180
```

启用 `AGENT_API_KEY` 后，`/v1/*` HTTP 与 WebSocket 请求必须携带 `X-API-Key`。这只是服务级共享密钥，不等于完整用户认证；公网部署仍应放在 API Gateway、反向代理或 OAuth/JWT 身份层之后。

## Docker

```powershell
docker build -f Dockerfile.agent-api -t stock-agent-api .
docker run --rm -p 8010:8010 --env-file .env.agent-api stock-agent-api
```

`Dockerfile.agent-api` 会优先安装项目现有的 `requirements.txt`，再安装 API 增量依赖。当前上传包不包含主项目依赖文件，因此只能验证 Dockerfile 语法和服务层代码，无法在本环境构建完整业务镜像。

## RAG 检索评估

准备 JSON：

```json
[
  {
    "case_id": "case_1",
    "query": "贵州茅台近期公告",
    "relevant_ids": ["chunk_1", "chunk_2"],
    "retrieved_ids": ["chunk_2", "chunk_7"],
    "latency_ms": 45.2
  }
]
```

执行：

```powershell
python -m agent.evaluation cases.json
```

输出 Hit Rate、MRR、Recall、Precision 和平均延迟，便于比较 chunk、embedding、混合召回和 reranker 配置。
