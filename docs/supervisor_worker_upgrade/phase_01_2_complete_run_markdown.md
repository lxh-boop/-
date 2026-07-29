# 阶段 01.2：完整 Agent 运行 Markdown

## 修改前

`outputs/agent_flow/*.md` 依赖主动调用 `flow_event`。新的 Supervisor–Worker 主链路只在入口写入 `GRAPH_REQUEST`，结束时使用的 `trace_event` 又受 `AGENT_CONSOLE_TRACE=0` 控制，因此保存文件可能只有请求入口，没有 Worker DAG、执行结果和最终状态。

## 修改后

每次 Agent 请求结束时，无论成功、部分完成、等待上下文或失败，都会追加一个幂等的完整运行快照，包括：

- Run、会话、状态和完成统计；
- 脱敏后的 LLM 运行配置；
- MainAgent 规划元数据；
- 完整 Worker DAG、结构化 `args`、依赖和预期输出；
- 执行批次与并行状态；
- 每个公开 WorkerResult 的状态、耗时、摘要、错误、缺参、发现、证据、产物和业务输出；
- WorkerResult 中允许公开的私有 Tool 执行摘要；
- GraphRef 与解析审计；
- 最终回答、全局警告和错误。

## 安全边界

不会写入密钥、本地路径、数据库路径、原始 Tool 参数、原始 Tool 响应、新闻全文、内部推理或 traceback。

## 同时修复

`FinalReport.content` 是 W06 的公开业务输出，也是 `FinalReport` Schema 的必填字段。此前通用脱敏函数把所有名为 `content` 的字段删除，导致 W06 生成报告后仍被输出合同拒绝。现在只为 `FinalReport` 保留公开正文，其他 Worker 的 `content/body/full_text` 仍然过滤。

## 不改变

- MainAgent 仍直接选择 Worker 并生成 Worker DAG；
- Validator 仍只校验，不拆分、合并、补充或修改 DAG；
- Worker 内部私有 Tool DAG 不变；
- 不修改本地 LLM timeout；
- 不修改 Docker 依赖或前端业务逻辑。
