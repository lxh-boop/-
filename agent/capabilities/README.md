# 渐进式 Worker / Tool 运行层 V21.0

主链：

```text
Request → Context/GraphRef → 全部 Worker 摘要 → 候选 Worker 详情
→ MainAgent 显式选择 Worker 并生成合同 DAG
→ Runtime 只校验 Worker 分配与 Slot 绑定
→ 兼容 Tool 摘要 → 候选 Tool 详情 → Worker 私有 Tool DAG
→ Slot 发布 → 合同验收 → 局部修复或 WorkerError → MainAgent PlanPatch
```

已删除旧的 CapabilityResolver 黑箱 Worker 选择和 WorkerResult 类型匹配。
