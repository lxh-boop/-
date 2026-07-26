# Multi-Agent Intelligent Orchestration & RAG Workbench

一个面向复杂业务任务的、可控、可观测、可部署的多 Agent 智能编排系统。

项目以金融分析场景作为业务验证载体，但核心能力集中在 **Agent 架构设计、任务编排、上下文治理、统一实体、混合检索、安全写操作和工程化部署**。系统不依赖通用 Agent 框架完成核心运行时，而是自主实现主 Agent、Worker Agent、Task DAG、Tool Registry、Context/Memory、Runtime Trace 与写操作审批链路。

> 当前版本更新时间：2026-07-26  
> 项目根目录：`D:\stock_daily_app`  
> 项目仅用于研究、分析和模拟盘，不连接真实交易。

---

## 1. 项目定位

项目主要解决传统单 Agent 系统中的以下问题：

- 复杂任务依赖隐含在 Prompt 中，执行过程不可控；
- 一个 Agent 同时负责规划、检索、分析和写操作，职责耦合；
- 多个 Agent 重复携带完整上下文，Token 开销较大；
- 股票名称、代码和交易所可能在跨 Agent 传递中发生对象偏移；
- RAG 只依赖单路召回，复杂查询下召回稳定性不足；
- 长任务缺少状态管理、失败隔离和恢复机制；
- 模型生成的写操作缺少人工确认、状态复校和幂等控制；
- 本地环境、服务器环境和依赖版本不一致，部署迁移困难。

系统采用以下整体方案：

```text
前端页面
   ↓ HTTP / SSE
FastAPI 接口层
   ↓
Application Service
   ↓
Task Runtime / Task DAG
   ↓
Main Agent
   ↓ 能力发现与任务委派
Worker Agents
   ↓
Tool Registry / RAG / Portfolio / Pipeline
   ↓
SQLite / Neo4j / 模型与业务数据
```

---

## 2. 核心特点

### 2.1 自主实现的多 Agent 分层架构

系统将 Agent 能力划分为四层：

- **Main Agent**：理解用户目标、拆解任务、生成 Task DAG、选择 Worker、处理反馈并汇总结果；
- **Worker Agent**：负责特定领域任务，只接收完成任务所需的最小上下文；
- **Tool Layer**：统一封装行情、新闻、RAG、持仓、风险和业务操作；
- **Runtime Layer**：负责任务状态、依赖调度、并发控制、上下文共享、失败隔离和链路追踪。

Main Agent 只读取 Worker 的能力卡，不直接看到 Worker 私有 Tool Schema、Provider 标识、Cypher 或内部 Prompt，从而降低主流程与底层业务实现的耦合。

---

### 2.2 显式 Task DAG 任务编排

复杂请求会被拆解为结构化子任务，并形成有向无环图：

```text
用户请求
   ↓
意图识别与目标解析
   ↓
生成任务 DAG
   ↓
计算当前可执行节点
   ↓
并发执行无依赖只读任务
   ↓
汇总中间结果
   ↓
Critic / Validate
   ↓
有限 Replan 或生成最终回答
```

运行时支持：

- 子任务依赖管理；
- 跨任务参数引用；
- 中间结果复用；
- 无依赖节点并发执行；
- 单任务失败隔离；
- 超时、重试和取消；
- 结构化缺参反馈；
- 有限次数重新规划；
- 最终结果统一汇总。

DAG 只表达任务依赖，具体执行由运行时完成。

---

### 2.3 Asyncio 并发与写任务串行控制

项目对相互独立的 I/O 密集型只读任务进行并发调度，例如：

- LLM API 调用；
- 行情与新闻接口请求；
- RAG 检索；
- 数据库查询；
- 多个独立 Worker 任务。

当前执行策略：

```text
Task DAG 依赖调度
        +
asyncio 异步并发
        +
Semaphore 最大并发控制
        +
ThreadPoolExecutor 兼容同步阻塞工具
```

设计原则：

- 当前可执行且无相互依赖的只读节点可以并发；
- 最大并发数受运行时限制，避免 API 限流和资源耗尽；
- 同步阻塞型工具通过线程池移出事件循环；
- 持仓、策略、审批和提交等写任务保持串行；
- CPU 密集型计算不会因为 `asyncio` 自动获得多核并行能力。

---

### 2.4 按需上下文与会话级 Working Memory

系统不把全部历史消息发送给每个 Worker，而是建立会话级共享工作空间。

Worker 默认只接收：

- 当前任务目标；
- 已解析的权威实体引用；
- 必需的上游任务结果；
- 与当前任务相关的用户约束；
- 允许访问的上下文引用。

当信息不足时，Worker 通过统一接口申请补充上下文，而不是自行猜测或直接向用户无序追问。

Working Memory 保存本轮运行所需的临时信息，例如：

- 用户原始请求；
- Task DAG；
- GraphRef；
- Worker 中间结果；
- 工具调用结果；
- 上下文申请记录；
- 异常、重试和 Replan 信息；
- 最终回答与证据引用。

会话结束后，可清理临时信息，仅保留必要的运行审计记录。

---

### 2.5 Pydantic 协议与统一实体

Pydantic 用于定义和校验：

- FastAPI 请求与响应 DTO；
- Agent 任务合同；
- Worker 结果合同；
- Tool 输入输出；
- 任务状态和错误结构；
- GraphRef 等公共协议。

Pydantic 负责保证数据“结构正确”，统一实体系统负责保证数据“指向正确的业务对象”。

```text
Pydantic
   └─ 字段、类型、格式、枚举、序列化

GraphRef + 权威图谱
   └─ 实体识别、消歧、标准 ID、身份绑定、证据关系
```

系统公共金融对象只传递 `GraphRef`。股票代码、名称、交易所和 Provider 私有标识由 Worker 在边界内解析，Main Agent 不自行拼接证券代码。

典型目标：

```text
600519
600519.SH
贵州茅台
茅台
```

在上下文明确时应解析到同一个权威对象；存在歧义时返回结构化 `need_context`，而不是由 LLM 自行猜测。

---

### 2.6 Neo4j 与 SQLite 职责分离

项目采用不同存储承担不同职责：

#### Neo4j

负责跨任务的金融语义关系与实体权威，包括：

- 证券、公司、行业和事件；
- 标识映射；
- GraphAssertion；
- GraphEvidence；
- 对象间关系与可追踪路径；
- 新闻、公告和研报中的证据支持事实。

未经 Evidence 支持的 Claim 不允许直接覆盖权威对象属性。

#### SQLite

负责应用运行和业务事务数据，包括：

- 用户与会话；
- Agent Run、Task 和 Tool Call；
- 消息与审计记录；
- 模拟盘账户、持仓、订单和审批；
- Pipeline 运行结果；
- 页面和系统配置。

Neo4j 不负责任务编排、审批事务和运行审计；SQLite 也不承担金融语义图谱的权威关系表达。

---

### 2.7 混合 RAG 检索链路

系统将 RAG 封装为只读工具，供 Planner、Worker 和 Reporter 按需调用。

检索流程：

```text
查询标准化
   ↓
元数据过滤
   ↓
BM25 稀疏召回
   +
Dense 向量召回
   ↓
RRF 融合
   ↓
Cross-Encoder 重排序
   ↓
证据片段与来源返回
```

主要能力：

- BM25 与 Dense 双路召回；
- Reciprocal Rank Fusion；
- Cross-Encoder 重排序；
- 新闻、公告、研报和业务资料检索；
- 元数据过滤；
- 索引持久化；
- 增量更新与原子切换；
- 检索结果、分数和来源追踪。

RAG 负责提供证据，不直接覆盖真实业务状态。

---

### 2.8 安全写操作闭环

分析类 Agent 默认只读。涉及持仓、策略和模拟盘状态修改时，统一经过：

```text
Proposal
   ↓
Approval
   ↓
Revalidate
   ↓
Commit
```

具体流程：

1. Agent 生成结构化操作提案；
2. 系统校验用户身份、参数、权限和业务约束；
3. 用户确认或拒绝本次操作；
4. 提交前重新读取最新状态；
5. 检查资金、持仓和上下文是否已发生变化；
6. 使用幂等键执行提交；
7. 保存完整审计链路。

该机制避免模型基于过期信息、错误参数或重复请求直接修改业务状态。

---

### 2.9 全链路可观测性

每次运行使用统一标识串联：

- `run_id`
- `task_id`
- `tool_call_id`
- `session_id`
- `user_id`
- `trace_id`

系统记录：

- 用户请求；
- 任务拆解结果；
- DAG 节点与依赖；
- Worker 选择原因；
- 上下文来源；
- GraphRef 解析结果；
- 工具输入输出；
- RAG 召回和重排序结果；
- 中间产物；
- 异常、超时和重试；
- Critic 与 Replan；
- 最终结果来源；
- 写操作审批和提交记录。

目标是让 Agent 的重要结论能够定位到数据来源、工具调用和执行步骤。

---

## 3. FastAPI 服务层

FastAPI 将 Agent 能力封装为标准服务接口，使页面不再直接调用内部 Python 函数。

接口层主要承担：

- 请求和响应协议；
- Pydantic 参数校验；
- 会话与用户身份；
- 任务提交；
- 长任务状态查询；
- SSE 进度推送；
- 取消、超时和恢复；
- 错误格式统一；
- Application Service 调用；
- OpenAPI 文档。

典型接口类别：

```text
/api/v1/web/*          页面基础接口
/api/v1/tasks/*        长任务提交、查询、取消和 SSE
/api/v1/agent/*        Agent 会话与运行
/api/v1/rag/*          检索与证据查询
/api/v1/portfolio/*    模拟盘与持仓
/api/v1/system/*       健康检查与系统状态
```

前后端通过 HTTP 调用 API，普通业务数据主要使用 JSON，长任务进度使用 SSE。

---

## 4. Docker 与部署

Docker 用于统一应用的运行环境，而不是替代客户端/服务器架构。

```text
用户浏览器
   ↓ HTTP / HTTPS
服务器
   ↓
Docker Compose
   ├─ frontend
   ├─ api
   └─ 持久化目录与外部数据服务
```

Docker 主要解决：

- Python 和依赖版本一致；
- 本地与服务器启动方式一致；
- 前端和 FastAPI 服务隔离；
- 环境变量集中配置；
- 容器网络和端口管理；
- SQLite、索引、模型和日志持久化；
- 快速迁移和重复部署。

用户通过浏览器访问服务器，不需要在客户端安装 Docker。

---

## 5. 当前前端状态

当前稳定调用链路：

```text
Streamlit
   ↓ HTTP / SSE
FastAPI
   ↓
Application Service / Task Runtime
```

React 前端正在按阶段迁移：

```text
React Preview
   ↓ REST / SSE
FastAPI
```

迁移原则：

- React 只调用 FastAPI；
- React 不直接访问 SQLite、Neo4j、文件系统、模型或 Agent Runtime；
- 迁移期保留 Streamlit 作为功能对照基线；
- React 不复制第二套业务规则；
- 接口合同冻结后再迁移页面；
- 最终只保留一条正式前端调用路径。

默认开发端口以当前 `docker-compose.yml` 为准，迁移期常用配置为：

| 服务 | 默认端口 | 状态 |
|---|---:|---|
| FastAPI | `8010` | 后端服务 |
| Streamlit | `8501` | 当前基线页面 |
| React Preview | `3000` | 前端迁移预览 |

---

## 6. 主要业务能力

当前工作台覆盖：

- AI Agent 对话与复杂任务编排；
- 股票排名与个股分析；
- 模型指标与模型结果展示；
- 新闻、公告和研报检索；
- RAG 证据查询；
- 用户画像和风险约束；
- 持仓分析与组合风险；
- AI 模拟盘；
- 安全调仓提案与审批；
- 日更 Pipeline；
- 预测、新闻调整和用户适配；
- 回测与结果分析；
- 系统状态和运行链路查看。

这些业务模块用于验证 Agent 编排、上下文治理、统一实体、RAG 和安全写操作能力，不构成投资建议。

---

## 7. 技术栈

### Agent 与后端

- Python 3.12
- FastAPI
- Uvicorn
- Pydantic
- Asyncio
- ThreadPoolExecutor
- LLM API
- Function Calling

### 检索与数据

- BM25
- Dense Retrieval
- Sentence-Transformers
- RRF
- Cross-Encoder Reranker
- SQLite
- Neo4j

### 前端

- Streamlit
- React
- TypeScript
- Vite
- Ant Design
- TanStack Query
- Zustand
- Axios
- ECharts
- SSE

### 工程化

- Docker
- Docker Compose
- OpenAPI
- Pytest
- Runtime Trace
- Structured Logging

---

## 8. 代码结构

以下为逻辑结构，实际目录以当前仓库为准：

```text
stock_daily_app/
├─ agent/
│  ├─ main_agent/                 # 主 Agent、能力发现和任务委派
│  ├─ workers/                    # Worker Agents
│  ├─ tools/                      # Worker 私有工具与适配器
│  ├─ registry/                   # Agent 与 Tool 注册
│  ├─ memory/                     # Working Memory
│  ├─ communication/              # 消息与 Handoff
│  └─ financial_graph_agent/      # GraphRef 与金融图谱协议
├─ application/
│  ├─ agent_service.py
│  ├─ portfolio_service.py
│  ├─ dashboard_service.py
│  └─ contracts.py
├─ server/
│  ├─ api/
│  │  ├─ main.py
│  │  ├─ routers/
│  │  ├─ schemas/
│  │  └─ presenters/
│  └─ task_runtime/
│     ├─ scheduler/
│     ├─ state/
│     ├─ concurrency/
│     └─ tracing/
├─ rag/
│  ├─ bm25/
│  ├─ dense/
│  ├─ fusion/
│  ├─ reranker/
│  └─ index_store/
├─ database/
│  ├─ repositories/
│  ├─ migrations/
│  └─ sqlite/
├─ graph/
│  ├─ neo4j/
│  ├─ contracts/
│  └─ importers/
├─ portfolio/
│  ├─ paper_trading/
│  ├─ risk/
│  └─ approval/
├─ pipelines/
│  ├─ daily_update/
│  ├─ prediction/
│  └─ paper_trading/
├─ frontend/                       # React Preview
├─ app/                            # Streamlit 基线页面
├─ models/
├─ data/
├─ outputs/
├─ scripts/
├─ tests/
├─ docker-compose.yml
├─ Dockerfile.compose
├─ requirements.txt
└─ README.md
```

---

## 9. 快速启动

### 9.1 环境要求

推荐使用：

- Windows 10/11 或 Linux；
- Docker Desktop / Docker Engine；
- Docker Compose；
- 可用的 LLM API Key；
- 已初始化的业务数据、模型和索引。

项目默认不把真实密钥写入代码仓库。

---

### 9.2 配置环境变量

根据项目中的示例文件创建 `.env`：

```bash
cp .env.example .env
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

根据实际配置填写：

```env
LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=

NEO4J_URI=
NEO4J_USERNAME=
NEO4J_PASSWORD=

DATABASE_URL=
```

请勿提交：

- API Key；
- Token；
- Neo4j 密码；
- 数据库绝对路径；
- 用户隐私数据。

---

### 9.3 Docker Compose 启动

构建并后台启动：

```bash
docker compose up -d --build
```

查看服务：

```bash
docker compose ps
```

查看 API 日志：

```bash
docker compose logs -f api
```

停止服务：

```bash
docker compose down
```

停止并删除 Compose 数据卷前请确认数据已经备份：

```bash
docker compose down -v
```

---

### 9.4 访问服务

以当前 Compose 配置为准：

```text
Streamlit:     http://localhost:8501
React Preview: http://localhost:3000
FastAPI:       http://localhost:8010
API Docs:      http://localhost:8010/docs
```

若 OpenAPI 文档在生产配置中被关闭，则 `/docs` 不可访问。

---

## 10. 常用排查命令

```bash
docker compose ps
docker compose config
docker compose logs -f
docker compose logs -f api
docker compose exec api sh
docker compose restart api
```

检查 API 健康状态：

```bash
curl http://localhost:8010/api/v1/web/health
```

常见问题：

### 页面能打开但 API 请求失败

检查：

- API 容器是否 healthy；
- 前端 API 地址是否指向正确服务；
- CORS 是否允许当前前端地址；
- 宿主机端口是否已映射；
- 容器之间是否通过服务名通信。

### 容器内访问 `127.0.0.1` 失败

容器中的 `127.0.0.1` 只表示当前容器。不同 Compose 服务之间应通过服务名访问，例如：

```text
http://api:8010
```

实际容器内部端口以 Compose 配置为准。

### 容器重建后数据丢失

检查 SQLite、索引、模型、输出和日志目录是否正确挂载到 Volume 或宿主机目录。

### Agent 长任务超时

检查：

- Task Runtime 状态；
- SSE 是否断开；
- LLM API 超时与重试；
- 并发限制；
- 阻塞工具是否错误运行在事件循环；
- Worker 是否返回结构化错误。

---

## 11. 数据与安全边界

项目坚持以下约束：

- 不连接真实证券交易接口；
- 分析类能力默认只读；
- 写操作必须经过人工确认；
- `user_id` 是运行时可信用户身份；
- 模型生成的账户标识不能覆盖真实身份；
- Main Agent 不直接访问 Worker 私有 Provider；
- React 不接触服务端密钥；
- 未绑定 Evidence 的 Claim 不写入权威事实；
- Neo4j 故障时明确失败，不回退到非权威实体解析；
- 不允许新闻或工具结果覆盖用户当前锁定的 GraphRef；
- 所有关键写操作保留审计记录。

---

## 12. 与通用 Agent 框架的区别

项目并非否定 LangChain、LangGraph 等框架，而是针对可控性和可解释性要求较高的业务场景，自主实现核心运行时。

主要差异：

- Task DAG 和任务状态显式可见；
- Main Agent 与 Worker 职责边界明确；
- Worker 私有工具不会全部暴露给主 Agent；
- 上下文按需获取，而不是默认注入完整历史；
- 缺参、失败和重规划使用统一结构；
- 金融实体通过 GraphRef 与权威图谱绑定；
- RAG 结果只作为证据，不覆盖业务状态；
- 读任务并发、写任务串行；
- 写操作执行前重新校验真实状态；
- 每个重要结论可追踪到任务、工具和证据来源；
- 底层模型、Retriever 和工具可以独立替换。

---

## 13. 当前开发状态

### 已接入

- FastAPI 服务接口层；
- Pydantic 请求、响应和 Agent 合同；
- Docker / Docker Compose 运行方式；
- Main Agent 与 Worker Agent 协作；
- Task DAG 与任务状态管理；
- Asyncio 只读并发；
- 同步阻塞工具线程池适配；
- Working Memory 与按需上下文；
- GraphRef 公共实体协议；
- Neo4j 金融语义关系层；
- SQLite 运行与业务数据层；
- 混合 RAG 检索与重排序；
- 模拟盘审批写入闭环；
- Runtime Trace 和审计记录；
- Streamlit 基线页面。

### 迁移与完善中

- React 只读页面逐步替换；
- Agent 长任务在 React 端的恢复与取消体验；
- 模拟盘和写操作页面迁移；
- 最终下线 Streamlit 正式入口；
- 更完整的集成测试、压测和部署文档；
- 多用户环境下的认证、隔离和权限细化。

README 只描述已确认的能力。具体完成状态以当前分支、测试报告和运行结果为准。

---

## 14. 面试介绍参考

> 这是一个自主设计的多 Agent 智能任务编排与 RAG 系统。我将复杂请求拆成显式 Task DAG，由 Main Agent 基于 Worker 能力卡进行任务委派；无依赖的只读节点通过 Asyncio 并发执行，同步阻塞工具由线程池兼容，写任务保持串行。系统使用 Pydantic 定义接口和 Agent 协议，并通过 GraphRef 与 Neo4j 保证跨 Agent 传递的业务实体身份一致。检索侧采用 BM25、Dense、RRF 和 Cross-Encoder 组成混合 RAG；写操作采用 Proposal、Approval、Revalidate、Commit 闭环。后端通过 FastAPI 暴露任务、会话和状态接口，并使用 Docker Compose 统一前端、API、存储和运行环境。

--。

---

## 16. License

项目许可证以仓库中的 `LICENSE` 文件为准。若仓库暂未提供许可证，则默认保留全部权利，不代表允许公开复制、修改或商用。
