# 真实 LLM Agent 能力测评报告（L1）

- 数据集版本：`l1-agent-capability-20260718.1`
- 模型配置哈希：`380d6c463aa543f2`（模型：`deepseek-v4-flash`；温度：0.0）
- 统计范围：hidden test set: zero real-LLM samples (provider/blocker; official metrics unavailable)；样本数：0；案例数：0
- 真实模型要求：每个计分样本通过正式 `run_agent_request` 入口；未记录规划器与复核器真实调用的样本计为失败。
- 隔离：每个 case × iteration 均为新的 SQLite、用户、会话与 synthetic paper fixture；不会读取生产数据库或提交真实/模拟盘订单。

## 核心结果

| 指标 | 值 |
|---|---:|
| real_llm_run_rate | N/A |
| task_success_rate | N/A |
| pass_at_1 | N/A |
| pass_at_3 | N/A |
| pass_at_5 | N/A |
| intent_action_accuracy | N/A |
| intent_macro_f1 | N/A |
| intent_object_f1 | N/A |
| constraint_precision | N/A |
| constraint_recall | N/A |
| constraint_f1 | N/A |
| clarification_decision_accuracy | N/A |
| write_intent_accuracy | N/A |
| planning_task_recall | N/A |
| planning_task_precision | N/A |
| planning_dependency_validity | N/A |
| planning_output_validity | N/A |
| forbidden_capability_rate | 1 |
| tool_precision | N/A |
| tool_recall | N/A |
| tool_f1 | N/A |
| tool_argument_exactness | N/A |
| tool_argument_field_accuracy | N/A |
| invalid_tool_rate | N/A |
| duplicate_tool_rate | N/A |
| excessive_tool_rate | N/A |
| normalized_step_efficiency | N/A |
| tool_call_count | {"average": null, "p50": null, "p95": null} |
| replan_trigger_precision | N/A |
| replan_trigger_recall | N/A |
| replan_success_rate | N/A |
| replan_no_progress_rate | N/A |
| replan_duplicate_rate | N/A |
| replan_limit_violation_rate | N/A |
| average_replan_count | N/A |
| context_carryover_accuracy | N/A |
| context_reference_resolution | N/A |
| context_parameter_override_accuracy | N/A |
| pending_action_handling_accuracy | N/A |
| cross_conversation_isolation | N/A |
| context_state_consistency | N/A |
| failure_detector_accuracy | N/A |
| failure_recovery_rate | N/A |
| unsupported_disclosure_rate | N/A |
| terminal_state_correctness | N/A |
| final_state_consistency | N/A |
| false_success_rate | N/A |
| failure_disclosure_rate | N/A |
| no_write_disclosure_rate | N/A |
| unauthorized_write_rate | N/A |
| approval_bypass_rate | N/A |
| cross_user_access_rate | N/A |
| expired_confirmation_accepted_rate | N/A |
| duplicate_commit_rate | N/A |
| terminal_write_rate | N/A |

## 类别结果

| 类别 | Task Success | Tool F1 | Final state |
|---|---:|---:|---:|

## 质量门禁

- 结论：未通过，已生成自动诊断报告。
- `task_success_rate`：实际 `None`，阈值 `0.8`。
- `pass_at_1`：实际 `None`，阈值 `0.8`。
- `pass_at_3`：实际 `None`，阈值 `0.65`。
- `pass_at_5`：实际 `None`，阈值 `0.5`。
- `intent_macro_f1`：实际 `None`，阈值 `0.9`。
- `planning_capability_recall`：实际 `None`，阈值 `0.85`。
- `tool_f1`：实际 `None`，阈值 `0.9`。
- `tool_argument_exactness`：实际 `None`，阈值 `0.9`。
- `replan_trigger_precision`：实际 `None`，阈值 `0.8`。
- `replan_trigger_recall`：实际 `None`，阈值 `0.8`。
- `replan_success_rate`：实际 `None`，阈值 `0.7`。
- `replan_no_progress_rate`：实际 `None`，阈值 `0.95`。
- `context_carryover_accuracy`：实际 `None`，阈值 `0.85`。
- `final_state_consistency`：实际 `None`，阈值 `0.95`。

## 运行与限制

- 延迟：平均 Nones，P50 Nones，P95 Nones。
- 重试上限：1；单案例超时：150s；Replan 上限：2；工具上限：24。
- 成本：兼容 API 没有返回可核验 token/cost，因此报告为 `N/A`，不估算或伪造。

## 可恢复继续

1. 直接运行 `python -m benchmarks.agent_capability.resume --split hidden --iterations 5` 会按 case + iteration + model config hash 跳过已记录运行。
2. `raw_runs.jsonl` 和 `failures.jsonl` 保留失败轨迹；修复后可用相同命令续跑，不会清除证据。
3. 只有隐藏集的真实 LLM 结果会写为最终 `metrics.json` 与本报告的正式统计范围。

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。
