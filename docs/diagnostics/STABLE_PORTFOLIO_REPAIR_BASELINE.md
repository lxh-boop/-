# 稳健持仓流程修复：Phase 0 基线

## 范围与安全边界

本次基线复现仅使用临时输出目录、临时 SQLite 数据库和项目虚拟环境解释器
`D:\stock_daily_app\.venv\Scripts\python.exe`。未提交订单、未调用真实交易接口、未写入生产模拟盘。

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。

## 真实链路复现

复现请求：`推荐一个更稳健的持仓`。

复现日期：2026-07-18。使用无 LLM 密钥的降级路径，且沿用当时入口默认 `top_k=50`，以暴露真实的默认读取行为。

观察到的结果：

- 请求最终被标记为 `completed`，但 Completion 评估为 `invalid`。
- 用户画像的单票上限为 `8%`，目标组合仍出现单票 `70%`，目标组合 HHI 为 `0.49`。
- 目标组合的行业覆盖率为 `0.0`；输出只标注“参考”，没有把行业约束不可验证转换为不可执行状态。
- Completion 已给出 `next_action=report_limitation`，随后 Critic 仍给出并执行 `REPLAN_READONLY`，使 `replan_count=2`。
- 排名工具的 `source_read_limit` 和 `top_k` 均为 `50`，尽管本次目标组合只需要少量候选标的。
- 最终用户回复仍是泛化的“更稳健”成功表述，未反映目标组合无效这一终止事实。

结论：问题不是单点工具失败，而是约束校验、终止状态优先级、Replan 状态来源和候选池 TopK 决策未统一。

## 现有针对性回归基线

执行命令：

```powershell
& D:\stock_daily_app\.venv\Scripts\python.exe -m pytest -q \
  tests\unit\test_runtime_reliability_fault_injection.py \
  tests\unit\test_replan_*.py \
  tests\unit\test_logic_integrity_*.py \
  tests\unit\test_top_k_*.py
```

PowerShell 将通配符展开为实际测试文件后执行，结果为：`62 passed in 12.46s`。

这些测试通过说明已有局部防护可用；它们尚未覆盖本报告所述的跨 Completion、Critic、通用恢复和候选池读取的组合故障，因此后续阶段会增加跨链路回归用例。
