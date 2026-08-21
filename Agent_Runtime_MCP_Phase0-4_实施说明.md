# Agent Runtime MCP Phase 0～4 实施说明

> 本文记录 `Agent_Runtime_MCP_全量接入技术方案.md` 在当前项目中的实际落地方式、关键设计决策、调用链变化、旧逻辑清理范围和验收结果。
>
> 本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。

## 1. 本次改造的目标

本次改造不是简单地“给现有函数套一层 MCP”，也不是用 MCP 重写整个 Agent Runtime。实际目标分为四部分：

1. 先完成 Phase 0，统一所有受控写操作的 Proposal → Approval → Execute 安全链路。
2. 将业务运行数据的权威来源迁移到数据库，彻底消除生产运行时对 CSV 的静默回退。
3. 使用官方 Python MCP SDK 和 stdio transport，把 Data、RAG、Model 三类内部能力暴露为 MCP Tool。
4. 保留现有 Agent Runtime 的编排、权限、重试、熔断、审计和长任务能力，只替换底层能力的调用协议。

Phase 1～4 已落地；Phase 5 只保留外部 MCP 的扩展配置框架，不连接真实外部 MCP Server，避免当前阶段引入不可控的网络依赖、鉴权依赖和第三方可用性风险。

## 2. 最终架构

```text
浏览器
  -> React / Nginx :3000
  -> FastAPI :8010
  -> Application Service
  -> Agent / Task Runtime
  -> ToolExecutor
       ├─ 权限校验
       ├─ 参数校验
       ├─ 超时与重试
       ├─ 熔断
       ├─ 审计
       └─ MCP Worker Adapter
            -> Runtime Registry（Admission / Contract / Permission / Visibility）
            -> MCP Client Manager
            -> 官方 MCP stdio Client
                 ├─ Data MCP Server
                 ├─ RAG MCP Server
                 └─ Model MCP Server
```

写操作使用另一条受控链路：

```text
生成写操作建议
  -> 创建 Proposal
  -> 用户明确确认
  -> 服务端复校所有者、版本、状态、有效期和幂等键
  -> ToolExecutor
  -> 唯一业务写实现
  -> 数据库事务提交
  -> 审计结果
```

这里最重要的边界是：

- MCP 替换的是能力发现和执行协议，不替换 Runtime。
- ToolExecutor 继续作为所有工具执行的外层控制面。
- Task Runtime 继续负责长时间运行的模型任务。
- MCP Server 不直接绕过权限、审计或写操作确认。
- React 仍然只调用 `/api/v1/**`，不会直接访问 MCP、数据库、文件、模型或密钥。

## 3. 新旧逻辑并存时的处理原则

本次改造采用“单一权威实现”原则：如果新旧两条链路实现的是同一个功能，旧执行链必须删除，不能以兼容为理由继续保留两套真实实现。

允许保留的是兼容入口或 Adapter，但它只能把旧的调用参数转换后委托给新的唯一实现，不能拥有自己的数据读取、状态流转或业务写逻辑。

```text
允许：旧 Tool ID -> Adapter -> 新的唯一 MCP/业务实现

禁止：旧 Tool ID -> 旧实现
                    新 Tool ID -> 新实现
```

这样处理的原因是：

- 避免两个实现的权限规则逐渐不一致。
- 避免生产问题发生后无法判断请求实际走了哪条链路。
- 避免 CSV 与数据库、旧 RAG 与新 RAG 返回不同结果。
- 避免修复只进入新链路，而旧链路继续暴露同样的问题。
- 保持已有 Planner、历史测试和 Worker Tool ID 的稳定性，同时确保底层执行只有一份。

本次已删除或终止使用的旧链路包括：

- 删除旧的 `agent/mcp/example_server.py` 示例 MCP Server。
- 删除根目录旧的 `rag_retriever.py` 检索实现。
- 删除生产 RAG 中独立的旧 TF-IDF 回退链路。
- 删除 `mcp_example_*` 示例配置和 local fixture 执行链。
- 删除旧的 `local_financial_evidence` 示例能力。
- 不再让生产业务读取在数据库失败或无数据时静默回退 CSV。

保留的旧 Tool ID 不是旧逻辑。它们通过 Worker Adapter 进入同一套 MCP 实现，用于避免一次性修改 Planner、冻结合同和历史工具引用。

## 4. Phase 0：统一 Proposal 安全写链路

### 4.1 要解决的问题

原有写操作分散在组合、模拟盘和 Agent 工具中。如果每个入口分别实现确认、幂等和状态校验，就容易形成多套相似但不一致的写链路。

Phase 0 先建立统一 Proposal 模型，所有正式 Agent 业务写操作都必须经过：

```text
Proposal -> Approval -> Execute
```

### 4.2 数据模型

迁移文件：

- `database/migrations/091_agent_canonical_proposals.sql`

新增的核心表：

- `proposals`：Proposal 主记录、所有者、状态、有效期和当前版本。
- `proposal_versions`：不可变的版本快照，记录每次建议内容和参数。
- `proposal_action_requests`：确认和执行请求，负责 request_id 与幂等控制。

数据库访问集中在：

- `database/repositories/proposal_repository.py`
- `agent/proposals/models.py`
- `agent/proposals/store.py`

### 4.3 状态和安全校验

执行前由服务端统一复校：

- 当前用户是否为 Proposal 所有者。
- Proposal 是否存在且没有过期。
- Proposal 当前状态是否允许确认或执行。
- 客户端确认的版本是否仍为当前版本。
- request_id 是否已经处理。
- idempotency key 是否已对应一个既有结果。
- 用户提交的确认文本是否符合服务端要求。

状态变更由数据库事务保证原子性，避免同一个 Proposal 被并发确认或重复执行。

浏览器不再生成或保存确认令牌。浏览器只提交 `proposal_id`、`request_id`、幂等键和用户明确输入的确认文本；最终权限与状态判断全部在服务端完成。

### 4.4 六个既有文件的处理

以下六个已有文件被保留并改造，没有删除用户原有工作：

- `agent/collaboration/workers/graph_business_mutation.py`
- `agent/collaboration/workers/portfolio_mutation.py`
- `agent/collaboration/write_runtime.py`
- `agent/proposals/__init__.py`
- `agent/proposals/models.py`
- `agent/proposals/store.py`

它们现在共同接入统一 Proposal Runtime。旧 `{plan_id}` 入口只作为参数兼容入口映射到同一个 Proposal 身份，不再维护独立的 plan 写执行链。

## 5. Phase 1：数据库成为业务运行数据的唯一权威来源

### 5.1 数据边界

本次没有把所有文件都强行搬进数据库，而是明确区分：

进入数据库的内容：

- 用户资料和交易权限。
- 组合、持仓和订单。
- 正式模型预测结果。
- 排名和推荐结果。
- 风险快照。
- Runtime 状态快照。
- 数据导入审计记录。

继续保留为离线文件的内容：

- 训练数据。
- 模型文件。
- 检索缓存和可重建索引。
- 回测结果。
- 离线分析产物。
- 明确标记为镜像或导出用途的 CSV。

### 5.2 数据库改造

迁移文件：

- `database/migrations/092_runtime_data_authority.sql`

主要 Repository：

- `database/repositories/prediction_repository.py`
- `database/repositories/portfolio_repository.py`
- `database/repositories/user_repository.py`
- `database/repositories/runtime_state_repository.py`
- Recommendation 相关 Repository

迁移和校验工具：

- `database/runtime_data_import.py`
- `scripts/migrations/import_runtime_data.py`

### 5.3 迁移方式

导入过程设计为可重复执行：

1. 扫描明确允许导入的数据集。
2. 解析和标准化数据。
3. 校验字段、用户、股票代码和业务约束。
4. 使用数据集指纹判断是否已经导入。
5. 在事务内写入业务表和导入审计表。
6. 重复执行时返回 `already_imported`，而不是再次插入。

实际迁移共校验 41 个数据集；重复执行时 41/41 均被识别为 `already_imported`。迁入的实际业务记录包括 292 条预测、50 条 alice 推荐记录及现有用户的持仓和订单。无效 watchlist 数据没有被带入正式库。

### 5.4 禁止静默 CSV 回退

生产读取器现在以数据库为唯一权威来源：

- 数据存在：返回数据库结果。
- 数据为空：明确返回空结果或“尚未生成”。
- 数据库异常：明确报错并进入日志、审计或任务失败状态。
- 不允许：数据库异常或空数据时自动改读 CSV。

CSV 只有在离线分析、一次性导入、回测或明确的镜像导出场景下才能使用。

`daily_incremental_update.py` 也已调整为先将 Kronos 排名结果写入数据库，再写 CSV 镜像。调度器校验最新排名时读取数据库日期，不再通过 CSV 判断正式任务是否成功。

## 6. Phase 2：官方 MCP stdio 基础设施

### 6.1 SDK 和 Transport

项目使用官方 Python MCP SDK，依赖约束为：

```text
mcp>=2,<3
```

依赖已进入：

- `requirements.txt`
- `requirements-compose-api.txt`
- `requirements-agent-api.txt`

正式 stdio transport 位于：

- `agent/mcp/transport.py`

其职责包括：

- 使用 `StdioServerParameters` 启动内部 MCP 子进程。
- 使用 `stdio_client` 建立双向通信。
- 创建并初始化 `ClientSession`。
- 执行 `list_tools` 和 `call_tool`。
- 将异步 MCP 调用安全桥接到现有同步 ToolExecutor 调用方式。
- 统一处理超时、子进程环境变量和错误转换。

MCP 子进程使用当前项目解释器 `D:\stock_daily_app\.venv\Scripts\python.exe`，不会调用裸 `python` 或其他环境。

为了防止内部 MCP 子进程在生产调用时临时访问模型网站，子进程以及 RAG retriever 都设置：

```text
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

### 6.2 配置和发现

核心文件：

- `agent/mcp/config.py`
- `agent/mcp/discovery.py`
- `agent/mcp/client_manager.py`
- `agent/mcp/registry_bridge.py`
- `agent/mcp/runtime_registry.py`
- `agent/mcp/security.py`

启动后，Discovery 只通过真实 stdio 会话读取 Server 的 `list_tools`，并保存：

1. Server 和 Tool 标识。
2. Tool 描述和 MCP annotation。
3. `inputSchema`。
4. `outputSchema`。
5. transport、超时和发现时间。
6. Discovery 缓存。

Discovery 不做 Admission，不注册 Runtime Tool，不分配 Agent Role，也不向 LLM 暴露 Tool。`list_tools` 只证明 Server 声称自己具有某项能力。

### 6.3 Runtime Registry 是最终权威

Runtime 采用四阶段准入：

```text
Discovered
  -> Admitted
  -> Registered
  -> Projected
```

- `Discovered`：MCP Server 的 `list_tools` 返回该 Tool。
- `Admitted`：Runtime 存在精确的 Tool Admission Policy，并通过启用状态、allowlist、只读和 annotation 校验。
- `Registered`：Runtime 将该底层能力注册为 `system_private` ToolDefinition。
- `Projected`：Runtime 将能力投影为明确的 Worker Tool ID，而不是把原始 `mcp.*` ID 投影给 LLM。

当前三个内部 Server 共发现 13 个 Tool。只有已经与正式 Worker Adapter 精确绑定的 6 个底层 MCP Tool 完成 Admission 和 Registration，并投影为 7 个 Worker Tool ID；其他 7 个 Tool 保持 `Discovered-only`，不能调用。

一次底层调用必须同时满足：

- 精确 MCP Tool ID 已完成四阶段准入。
- 调用者是 Admission Policy 中登记的 Worker Tool ID。
- 当前 `agent_type` 在 Runtime Registry 的允许范围内。
- 原始 Tool 的可见性为 `system_private`。
- 输入满足 `inputSchema`。
- 返回值满足 `outputSchema`。

不存在根据 `startswith("mcp.")` 自动判断角色、语义或放行权限的逻辑。

### 6.4 MCP Schema 与 Artifact Contract

MCP schema 和业务合同的职责明确分离：

```text
inputSchema：校验 MCP 调用参数结构
outputSchema：校验 MCP 返回值结构
ToolInputContract / ToolOutputContract：定义业务语义、版本和 DAG 兼容性
```

没有新增第二套 Artifact Contract 系统，而是扩展现有 `ToolInputContract/ToolOutputContract`：

- `contract`
- `version`
- `schema_id`
- `accepted_versions`
- `slot_id`
- `source_path`（仅 Runtime 可见）
- `provenance_required`

ToolExecutor 物化语义输出时，会同时生成 `slots` 和 `slot_contracts`。Tool DAG 在连接生产者与消费者时同时校验：

```text
schema_id
contract
version / accepted_versions
```

Artifact 落盘必须携带：

```json
{
  "contract": "portfolio.risk",
  "version": "1.0",
  "schema_id": "PortfolioRisk.v1",
  "provenance": {
    "producer_id": "risk.calculate",
    "provider_type": "mcp",
    "server_id": "data",
    "transport_tool_name": "get_portfolio_risk"
  }
}
```

一个 Tool 产生多个语义 Slot 时，Artifact 还会保存完整的 `contracts` 列表。原先根据 MCP Tool 名称猜测 `market_evidence/evidence/reasons/limitations` 的 Artifact 语义逻辑已删除。

Worker 之间继续通过既有 ContextBundle 传递业务数据，但 ContextBundle 记录已从 `name + value` 升级为：

```text
name + value + contract + version + schema_id + provenance
```

`context_bundle_business_data.v2` 会在实体数据和全局数据旁同时返回合同映射。W02 从 Tool DAG 发布数据时会把实际 `ToolOutputContract` 一起传入 ContextBundle；没有显式映射的 Worker 输出也必须通过同一个 `ToolOutputContract` 规范化后才能发布，不再产生无合同的 Worker 间数据。

## 7. Phase 3：Data、RAG、Model 三类 MCP Server

三类 Server 当前以三个独立 stdio 进程运行，这是进程级能力边界，不代表必须拆成三个网络微服务。后续如果复杂度不支持继续拆分，可以在不改变 MCP 工具合同的前提下合并部署。

### 7.1 Data MCP

实现文件：

- `agent/services/data_query_service.py`
- `agent/mcp/adapters/data_adapter.py`
- `agent/mcp/servers/data_server.py`

Server 声明的工具：

- `get_user_profile`
- `get_portfolio_state`
- `get_positions`
- `get_orders`
- `get_stock_info`
- `get_latest_ranking`
- `get_latest_recommendations`

Data MCP 只通过 Service 和 Repository 读取数据库，不直接把 CSV 文件暴露给 Agent，也不允许调用方指定任意文件路径。

### 7.2 RAG MCP

实现文件：

- `agent/mcp/adapters/rag_adapter.py`
- `agent/mcp/servers/rag_server.py`
- `agent/services/evidence_service.py`

Server 声明的工具：

- `search_documents`
- `search_news`
- `retrieve_evidence`

底层继续使用项目已有的混合检索能力：

```text
BM25 + Dense Retrieval + RRF Fusion + Reranker
```

没有引入 Chroma、Qdrant 或新的向量数据库。MCP 只负责暴露检索能力，不改变检索算法。

旧根目录 `rag_retriever.py` 和生产 TF-IDF 备用实现已删除。当前 canonical hybrid retriever 在本地 Dense 模型或 Reranker 不可用时，可以在同一个实现内部按能力降级；这属于一个实现的运行策略，不是保留第二套旧检索链。

### 7.3 Model MCP

实现文件：

- `agent/services/model_inference_service.py`
- `agent/mcp/adapters/model_adapter.py`
- `agent/mcp/servers/model_server.py`

Server 声明的工具：

- `predict_stock_score`
- `predict_rank`
- `predict_risk`

Model MCP 不在普通同步请求中启动耗时模型推理。它读取已经由 Task Runtime 完成并写入数据库的 Kronos 预测快照，返回结果时明确标记：

```text
inference_mode=completed_task_snapshot
```

因此职责分工为：

```text
Task Runtime：调度和执行耗时模型任务
Model MCP：读取已完成结果并向 Agent 提供标准化工具接口
```

这避免了同步 HTTP 请求、MCP call 和模型子任务形成多层不可控超时。

## 8. Phase 4：Worker Tool Adapter 与 Runtime 保留

实现文件：

- `agent/mcp/worker_adapter.py`
- `agent/worker_tools/evidence.py`
- `agent/worker_tools/internal_system.py`

已有 Worker Tool ID 被保留，包括：

- `evidence.search_news`
- `evidence.search_rag`
- `internal.prediction.get_stock`
- `internal.ranking.get_latest`
- `internal.portfolio.get_state`
- `internal.account.get_state`
- `internal.user_profile.get`

这些 ID 的 handler 已改为调用 MCP，不再调用一套并行的旧实现。完整链路为：

```text
Planner / Worker
  -> 原 Worker Tool ID
  -> ToolExecutor
  -> MCP Worker Adapter
  -> Runtime Registry Admission / Authorization
  -> MCP Client Manager
  -> 对应 Data / RAG / Model MCP Tool
```

因此以下能力全部继续保留：

- Planner 不需要一次性重写工具名称。
- 冻结合同和历史 Tool ID 保持稳定。
- ToolExecutor 的角色和权限校验继续生效。
- ToolExecutor 的超时、重试、熔断和审计继续生效。
- MCP Server 只处理自己的能力，不承担整个 Agent Runtime 的职责。
- 原始 `mcp.*` Tool 不进入 Main Agent 或 Worker LLM 的 Tool 列表。
- `mcp.readonly.invoke` 和 `evidence.mcp_readonly_evidence` 任意名称调用链已删除。

## 9. Phase 5：只保留外部 MCP 扩展框架

配置中保留 `mcp_external_servers` 扩展点，默认值为空且禁用。

未来接入外部 MCP 时必须显式配置：

- Server 标识和 transport。
- 命令或地址。
- 工具 allowlist。
- 信任级别。
- 允许的角色。
- 超时和错误策略。

没有 allowlist 的外部 MCP 配置不能启用；即使未来被 Discovery 发现，没有 Runtime Admission Policy 也只能停留在 `Discovered-only`。未支持的 transport 会 fail closed。目前没有连接真实外部 MCP，也没有为了展示能力而增加第三方运行依赖。

## 10. 关键失败语义

本次改造明确了几个不能静默处理的失败场景：

| 场景 | 当前处理 |
| --- | --- |
| 数据库无正式数据 | 返回空结果或“尚未生成”，不读 CSV |
| 数据库访问异常 | 明确失败并记录，不读 CSV |
| MCP Server 启动失败 | 工具调用失败，由 ToolExecutor 记录和处理 |
| MCP 工具只被 Discovery 发现 | 不注册、不投影、不可调用 |
| MCP 工具不在 Runtime allowlist | Admission 失败 |
| MCP 调用者 Worker ID 或 Agent Role 不匹配 | Runtime Registry 拒绝调用 |
| 输入不符合 MCP inputSchema | 调用前拒绝 |
| 返回值不符合 MCP outputSchema | 调用后 fail closed，不把结果交给 Worker |
| DAG Artifact Contract 或版本不兼容 | DAG 校验阶段拒绝连接 |
| 写/破坏性工具缺少可信声明 | fail closed |
| Proposal 已过期或版本变化 | 拒绝执行，要求重新确认 |
| 相同幂等键重复提交 | 返回既有结果，不重复写入 |
| 长模型任务尚未完成 | 由 Task Runtime 状态表达，不在 MCP 内同步等待 |

## 11. 验收结果

已完成的针对性验证包括：

- 本轮 Runtime Registry、MCP Schema、Artifact Contract、ContextBundle、Worker/DAG/Handoff 及 Stage 6.2～6.5 相关测试合并执行：132 个通过，1 个既有 `datetime.utcnow()` 弃用警告。
- Stage 6.5 正式验收核心子集：40 个通过。
- Stage 6.0～6.5 合同与架构检查：0 violation。
- 前端 TypeScript 类型检查：通过。
- React 生产构建：通过。
- Task Runtime smoke test：通过。
- Docker Compose 配置检查：通过，只包含正式 `api` 和 `frontend` 服务。
- Python `compileall`：通过。
- `git diff --check`：通过，仅存在既有行尾风格提示。
- 真实调用原 Worker ID `internal.ranking.get_latest`，经 Model MCP 返回 `000001` 排名结果：通过。
- 扩大范围的历史单测中，排除 9 个已经引用下线模块、无法收集的旧测试后：965 个通过，110 个失败。

最后一项的 110 个失败主要来自已经下线的旧合同或旧行为假设，例如：旧 CSV 回退、旧 confirmation token、旧 MCP 示例模块、旧 Intent Router、已移除模块和当前不可用的 Neo4j。没有为了让这些过时测试变绿而恢复旧业务链路。

在后续维护中，应选择更新或删除这些失效测试，使测试表达当前唯一架构；不应重新引入已经删除的旧实现。

## 12. 后续维护规则

后续继续开发时需要遵守以下规则：

1. 新的内部能力优先进入现有 Data、RAG 或 Model MCP；只有边界确实独立时才增加新 Server。
2. MCP Tool 不能直接绕过 Application Service、Repository 或安全写链路访问业务数据。
3. 所有正式业务运行数据继续以数据库为唯一权威来源。
4. 文件只能用于训练、缓存、回测、导入、导出或明确镜像场景。
5. 任何写操作继续使用 Proposal → Approval → Execute。
6. 任何长任务继续进入 Task Runtime，不塞进普通同步 MCP call。
7. 需要兼容旧 Tool ID 时只增加薄 Adapter，不复制业务实现。
8. 如果发现新旧逻辑完成同一个功能，应删除旧执行链，并同步更新过时测试。
9. MCP Discovery 只发现；任何新 Tool 必须依次完成 Admission、Registration 和 Worker Projection。
10. 原始 MCP Tool 默认保持 `system_private`，LLM 只看到 Runtime 投影的 Worker Tool ID。
11. Artifact 和 DAG 数据必须使用统一 Tool Contract，不允许按 Tool 名称猜测业务语义。
12. Phase 5 外部 MCP 必须经过显式评审后再启用，不能因为配置框架存在就默认连接。
13. 页面和文档必须继续保留非投资建议与不用于实盘交易的声明。
