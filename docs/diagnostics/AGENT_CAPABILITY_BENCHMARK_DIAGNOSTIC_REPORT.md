# L1 Agent 能力测评低分自动诊断

模型配置哈希：`380d6c463aa543f2`。本报告仅基于保留的真实 LLM 失败轨迹；没有足够直接证据时只标注阶段，不宣称代码根因。

## 门禁失败

- `task_success_rate`：actual=None threshold=0.8。
- `pass_at_1`：actual=None threshold=0.8。
- `pass_at_3`：actual=None threshold=0.65。
- `pass_at_5`：actual=None threshold=0.5。
- `intent_macro_f1`：actual=None threshold=0.9。
- `planning_capability_recall`：actual=None threshold=0.85。
- `tool_f1`：actual=None threshold=0.9。
- `tool_argument_exactness`：actual=None threshold=0.9。
- `replan_trigger_precision`：actual=None threshold=0.8。
- `replan_trigger_recall`：actual=None threshold=0.8。
- `replan_success_rate`：actual=None threshold=0.7。
- `replan_no_progress_rate`：actual=None threshold=0.95。
- `context_carryover_accuracy`：actual=None threshold=0.85。
- `final_state_consistency`：actual=None threshold=0.95。

## latency_or_provider（180）

- `L1-A-025` / iteration 1：The formal entry point did not record both real LLM planner and reviewer calls.
  - 证据关联代码路径：`agent/intent_decomposition/layered_decomposer.py:decompose_intent`。
  - 最小复现：`python -m benchmarks.agent_capability.run_benchmark --case-id L1-A-025 --iterations 1`
  - 建议：Add this isolated case to the affected-stage regression selection after the code path is changed.
- `L1-A-025` / iteration 4：The formal entry point did not record both real LLM planner and reviewer calls.
  - 证据关联代码路径：`agent/intent_decomposition/layered_decomposer.py:decompose_intent`。
  - 最小复现：`python -m benchmarks.agent_capability.run_benchmark --case-id L1-A-025 --iterations 1`
  - 建议：Add this isolated case to the affected-stage regression selection after the code path is changed.
- `L1-A-025` / iteration 5：The formal entry point did not record both real LLM planner and reviewer calls.
  - 证据关联代码路径：`agent/intent_decomposition/layered_decomposer.py:decompose_intent`。
  - 最小复现：`python -m benchmarks.agent_capability.run_benchmark --case-id L1-A-025 --iterations 1`
  - 建议：Add this isolated case to the affected-stage regression selection after the code path is changed.
- `L1-A-026` / iteration 1：The formal entry point did not record both real LLM planner and reviewer calls.
  - 证据关联代码路径：`agent/intent_decomposition/layered_decomposer.py:decompose_intent`。
  - 最小复现：`python -m benchmarks.agent_capability.run_benchmark --case-id L1-A-026 --iterations 1`
  - 建议：Add this isolated case to the affected-stage regression selection after the code path is changed.
- `L1-A-025` / iteration 3：The formal entry point did not record both real LLM planner and reviewer calls.
  - 证据关联代码路径：`agent/intent_decomposition/layered_decomposer.py:decompose_intent`。
  - 最小复现：`python -m benchmarks.agent_capability.run_benchmark --case-id L1-A-025 --iterations 1`
  - 建议：Add this isolated case to the affected-stage regression selection after the code path is changed.
- `L1-A-025` / iteration 2：The formal entry point did not record both real LLM planner and reviewer calls.
  - 证据关联代码路径：`agent/intent_decomposition/layered_decomposer.py:decompose_intent`。
  - 最小复现：`python -m benchmarks.agent_capability.run_benchmark --case-id L1-A-025 --iterations 1`
  - 建议：Add this isolated case to the affected-stage regression selection after the code path is changed.
- `L1-A-026` / iteration 3：The formal entry point did not record both real LLM planner and reviewer calls.
  - 证据关联代码路径：`agent/intent_decomposition/layered_decomposer.py:decompose_intent`。
  - 最小复现：`python -m benchmarks.agent_capability.run_benchmark --case-id L1-A-026 --iterations 1`
  - 建议：Add this isolated case to the affected-stage regression selection after the code path is changed.
- `L1-A-026` / iteration 2：The formal entry point did not record both real LLM planner and reviewer calls.
  - 证据关联代码路径：`agent/intent_decomposition/layered_decomposer.py:decompose_intent`。
  - 最小复现：`python -m benchmarks.agent_capability.run_benchmark --case-id L1-A-026 --iterations 1`
  - 建议：Add this isolated case to the affected-stage regression selection after the code path is changed.
- `L1-A-026` / iteration 5：The formal entry point did not record both real LLM planner and reviewer calls.
  - 证据关联代码路径：`agent/intent_decomposition/layered_decomposer.py:decompose_intent`。
  - 最小复现：`python -m benchmarks.agent_capability.run_benchmark --case-id L1-A-026 --iterations 1`
  - 建议：Add this isolated case to the affected-stage regression selection after the code path is changed.
- `L1-A-026` / iteration 4：The formal entry point did not record both real LLM planner and reviewer calls.
  - 证据关联代码路径：`agent/intent_decomposition/layered_decomposer.py:decompose_intent`。
  - 最小复现：`python -m benchmarks.agent_capability.run_benchmark --case-id L1-A-026 --iterations 1`
  - 建议：Add this isolated case to the affected-stage regression selection after the code path is changed.

重复模式（同阶段 ≥3）应优先按上述最小复现建立回归；若只有阶段证据，先补充可观测性再改 Agent 行为。

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。
