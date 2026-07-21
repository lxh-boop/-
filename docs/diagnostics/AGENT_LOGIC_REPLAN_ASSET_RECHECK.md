# Agent 流程、Replan 与资产口径复核记录

复核日期：2026-07-18  
范围：资产快照、持仓/风控输入、Completion/Critic 的只读 Replan 路径，以及模拟盘预览安全边界。

## 结论

`112000` 与 `122000` 不是同一份资产快照的相互矛盾计算结果，而是两套不同测试夹具的正确结果。两者的 `cash` 均表示**尚未投入持仓的可用现金**，不得再将已持仓市值从现金中扣减，也不得把市值重复加入总资产。

| 夹具 | 来源 | 现金 | 活跃持仓市值 | 正确总资产 | 结论 |
| --- | --- | ---: | ---: | ---: | --- |
| 单一持仓 | `test_portfolio_snapshot_recomputes_stale_summary.py`、`test_portfolio_risk_uses_normalized_snapshot.py` | 100000 | 1000 × 12 = 12000 | 112000 | 单一持仓的快照与风控夹具 |
| 两个持仓 | `test_portfolio_stability_write_closed_loop.py` | 100000 | 1000 × 12 + 1000 × 10 = 22000 | 122000 | 稳定性调仓闭环夹具 |

因此根因分类为 **B：不同夹具**。此前容易造成误读的部分是两套夹具都使用了相同的现金数额；本次修复会把现金语义、计算过程和快照标识显式输出，避免再以账户旧汇总字段推断总资产。

## 当前基线

使用唯一允许的解释器执行：

```powershell
& D:\stock_daily_app\.venv\Scripts\python.exe -m pytest -q <资产快照、风控、稳定写入、Replan 相关用例>
```

结果：`25 passed in 113.33s`。

基线命令中曾引用不存在的 `tests/unit/test_replan_canonical_action.py`；经实际文件清单核对后已改为当前仓库已有的 Replan 测试集。这是测试清单漂移，不是功能测试失败。

## 后续修复约束

1. 唯一资产公式为 `total_assets = uninvested_cash + sum(active_position.quantity * current_price)`。
2. 账户摘要历史字段只作为原始对照，不得覆盖派生结果。
3. 数据缺失、跨账户/跨时间、非有限数或不可能的负资产必须以确定性逻辑错误阻断推荐、Replan 与写入。
4. Replan 仅可执行受注册表约束的只读任务；重复计划、重复结果或没有新证据时立即停止。
5. 不调用模型来推翻上述安全判定；本项目不执行实盘交易。

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。
