# 本地 Ollama 与远程 API 手动切换：排查基线

日期：2026-07-20

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。

## 排查结论

- 开发模式的本地配置文件为 `D:\stock_daily_app\local_app_config.json`；冻结发布模式为 `%LOCALAPPDATA%\StockDailyApp\config\local_app_config.json`。密钥仅允许来自页面输入、本地配置或环境变量，本文不记录任何实际密钥。
- 原有配置只有 `llm_api_key`、`llm_base_url` 与 `llm_model` 三个远程 API 字段。侧边栏也只有一组 API 表单，不能独立保存本地模型配置。
- 原有 `LLMClient` 只按 OpenAI-compatible API 构造客户端；Agent 的 Planner、Completion、Report、Critic 与目标组合设计工具分别接收旧参数，运行期间可能重新读取本地设置。
- 原有 L1 能力测评只描述远程 API 参数，没有“本地单并发、600 秒、零重试”的明确运行策略，也没有把部署模式写入模型配置哈希。
- 初始检查结果：未发现 `ollama` 命令，因此当时不能把本地模型验证误报为成功；`http://127.0.0.1:11434` 也不应被视为可用。实施过程中已通过官方 `winget` 包完成安装，结果见实施报告。

## 风险与边界

- 不允许 API 与本地模型之间自动回退；切换必须由用户在 UI 中手动保存并应用。
- 日志、运行轨迹、Benchmark 收据和 UI 不得写出 API Key、完整提示词、完整模型回复或本机绝对路径。
- 本地模式只能访问固定的 loopback 地址 `http://127.0.0.1:11434/v1`，不会借“本地模式”访问远程 API。
- 系统只管理 Ollama 的固定推荐模型 `qwen3:4b` 与项目模型 `stock-agent-qwen3-4b`，不接受来自 UI 的任意命令。
