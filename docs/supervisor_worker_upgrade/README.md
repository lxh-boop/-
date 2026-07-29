# Supervisor–Worker 分阶段升级记录

本目录保存 Supervisor–Worker 运行时改造的设计、文件变更、测试与验收记录。

## 固定执行规则

1. 每阶段只修改 Manifest 声明的文件；
2. 安装前校验项目文件与交付文件 SHA-256；
3. 安装前自动备份本阶段受影响文件；
4. 依次执行语法、导入、架构、单元、数据库、回归和差异检查；
5. 安装器本次实际修改的文件在测试失败时自动恢复；
6. 所有日志和结果保存到 `D:\google\supervisor_worker_delivery`；
7. 安装器不执行 `git add`、`git commit`、`git push`、`git reset`、`git restore` 或 `git stash`；
8. 测试通过后由用户检查 `git diff` 并手动提交。

## 当前阶段

- Phase 00：真实项目基线核对；
- Phase 01：Worker DAG 运行记录接线；
- 下一阶段：Tool 调用、Artifact、Source 与后台 Task 关联。
