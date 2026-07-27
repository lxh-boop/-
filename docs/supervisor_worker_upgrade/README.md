# Supervisor–Worker 分阶段升级留存

本目录记录基于 `D:\stock_daily_app` 真实代码执行的 Supervisor–Worker 增量升级。

## 基线

- 分支：`codex/backend-agent-boundary-refactor`
- HEAD：`47be09c199190fc46446a1ff84911a626ec17c45`
- 基线包时间：2026-07-27 18:27:46
- 当前工作区存在 Stage 6.6 未提交修改，因此所有交付均采用目标文件 SHA-256 校验、逐文件备份和精确暂存。

## 原则

1. 不覆盖与当前阶段无关的未提交文件。
2. 不重建第二套 GraphRef、ToolResult、Artifact 或后台任务平台。
3. 每阶段只修改明确列出的文件。
4. 阶段测试失败时自动恢复本阶段文件。
5. 阶段测试通过后只暂存本阶段文件并创建 Git 提交。
6. 安装、测试、Git 和推送结果统一写入 `D:\google\supervisor_worker_delivery`。
