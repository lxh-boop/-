# 真实 LLM Agent 能力测评基线（L1）

## 范围与时间点

- 基线提交：`4a7afff`；工作树在建立基线时已有 247 项未提交修改/新增文件，均保留，不以本测评覆盖或回滚。
- L1 只测 Agent 的理解、规划、工具、重规划、状态与安全合同；不测股票收益、选股质量、投资建议质量或真实交易能力。
- 当前默认预测模型路径仍为外部模型：`zoo:chronos_bolt_small` 与 `dft_unet_external`；本基准不训练、替换或调用旧本地 MLP 链路。

## 正式入口与真实模型条件

- 唯一执行入口：`agent.executor.run_agent_request`。它经过 `UserGoal → TaskPlan → Goal Review → Plan Review → Tool Execution → Completion → Critic → Replan → Final Response` 的现有普通 Agent 管线；安全终止时缺失的后段会作为能力失败记录，而不是用模板补齐。
- 本机本地配置已检测到 API Key、Base URL 和模型名，配置模型为 `deepseek-v4-flash`。凭据、Base URL 和任何 Token 不会写入基准输出。
- 已做一次独立临时 SQLite 实探：非规则的“读取持仓、风险、排名并给出只读组合建议”请求进入 `llm_first`，并记录 `llm_used`、`llm_planner_called` 与真实规划/复核调用。该次运行因 `user_profile` 能力未集成和持仓快照一致性检查而以 `feature_unavailable` 安全终止；这是待测的真实基线问题，不是通过结果。

## L0 既有基线与已知失败

- L0 稳健持仓工作流合同基准：84 cases、300 runs、100% 通过；结果位于 `outputs/benchmarks/agent/`。
- 目标回归集：77 passed。
- 全量单测最近一次：`1021 passed, 13 failed, 255 warnings`。13 个失败是旧的非当前 L0 合同（旧 harness、旧多 Agent/MCP 和历史 Phase 预期），不应混入 L1 成功率。
- L0 与 L1 输出、计分和门禁完全分离；L1 不改写 L0 的报告或分数。

## L1 隔离与不可变安全边界

- 每个 `case × iteration` 创建新的 synthetic paper user、conversation、SQLite 与 ranking/portfolio fixture，路径在 `outputs/benchmarks/agent_capability/isolated_workspaces/`。
- 不读取 `data/agent_quant.db`，不复用生产用户、输出或 pending plan；不连接券商，也不确认/提交模拟盘订单。
- 痕迹经脱敏后保留。失败样本不会删除；续跑键为 `case_id + iteration + model_config_hash`。
- L1 的自动诊断仅在有直接轨迹证据时关联代码路径；否则只报告首先偏离的阶段。

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。
