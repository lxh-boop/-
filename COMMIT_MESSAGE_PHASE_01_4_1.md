# Git Commit

```text
修复(agent)：明确 Worker 参数与语义输入合同

将 MainAgent 可见的 input_schema 拆分为 args_schema 与 semantic_inputs_schema，避免普通业务参数被错误写入 inputs。

为规划字段归属错误提供精确诊断和 Repair 指引，并将模型预测与排名的默认 TopK 确定为10。

保持 MainAgent 对 Worker DAG 的控制权，不放宽语义输入 Schema，也不改变模型超时和重试次数。
```
