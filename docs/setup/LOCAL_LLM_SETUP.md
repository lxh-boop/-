# 本地 Ollama 模型安装与切换

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。

## 安装

使用 Ollama 官方 Windows 安装程序：<https://ollama.com/download/windows>。安装完成后，在项目根目录使用项目虚拟环境所在的 PowerShell 执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_ollama_qwen3_4b.ps1
```

脚本只使用官方 Ollama 命令，下载 `qwen3:4b` 并创建 `stock-agent-qwen3-4b`；可以重复执行，不会删除用户已有模型。

## UI 切换

1. 打开侧栏“AI 接口设置”。
2. 手动选择“本地模型”。
3. 点击“刷新模型列表”，选择 `stock-agent-qwen3-4b`。
4. 点击“验证本地模型”，成功后点击“保存并应用”。

远程 API 与本地模型的配置独立保存。保存或验证失败不会切换当前模式；任何模型失败都不会自动回退到另一种模式。切换只影响下一次 Agent 请求。

本地服务地址为 `http://127.0.0.1:11434/v1`，Qwen3 自动附加一次 `/no_think` 指令，且不会修改调用方传入的消息对象。
