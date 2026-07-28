# 阶段 01：安装、重启与启动后验收

阶段 01 不只验证源码，还必须验证正式 Docker 环境中的代码已经重新构建并加载。

完整门禁：

```text
安装前哈希检查
→ 自动备份
→ 精确替换
→ Python 语法检查
→ 阶段功能测试
→ 数据库持久化测试
→ Worker 与 Tool Runtime 回归
→ 架构检查
→ Docker 镜像重建
→ api/frontend 强制重启
→ 三个 HTTP 健康检查
→ API 容器模块导入
→ API 容器内 Worker DAG 持久化验收
→ Stage 6.5/6.6 浏览器回归
→ Git 差异检查
→ 生成结果 ZIP
```

任一阻断项失败时，安装器恢复本次修改的文件，并尝试使用恢复后的代码重新构建和启动服务。

Git 只读，不执行 add、commit 或 push。
