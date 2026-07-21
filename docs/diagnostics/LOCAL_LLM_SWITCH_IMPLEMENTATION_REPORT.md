# 本地 Ollama 与远程 API 手动切换：实施报告

日期：2026-07-20

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。

## 已实施内容

- `core/llm/runtime_settings.py` 定义不可变 `LLMRuntimeSettings`。每次 `run_agent_request` 仅解析一次配置快照，并把同一快照传给 Planner、Completion、Report、Critic、Replan 和目标组合设计工具。
- 远程与本地配置分离保存：`llm_mode`、`llm_api_key`、`llm_api_base_url`、`llm_api_model`、`llm_local_base_url`、`llm_local_model`、`llm_local_disable_thinking`。旧 `llm_base_url`、`llm_model` 会迁移到 API profile，不会覆盖 Token。
- API 模式使用真实 API Key；本地模式固定 `provider=ollama_local`、`api_key=ollama`、`base_url=http://127.0.0.1:11434/v1`、默认模型 `stock-agent-qwen3-4b`。任何调用失败都会明确说明未执行自动回退。
- Streamlit 侧边栏提供“远程 API / 本地模型”手动选择、连通性验证、模型列表刷新、推荐模型下载与“保存并应用”。验证或保存失败不会改变当前生效模式；保存只影响下一次 Agent 请求。
- `LLMClient` 仅在远程 DeepSeek v4 调用中发送 `extra_body.thinking.disabled`；本地 Qwen3 只在复制后的 system message 中补充一次 `/no_think`，不修改调用方消息。
- `agent/llm_audit.py` 收据和运行元数据增加 `deployment_mode`、provider、model、配置哈希与 endpoint scope；不记录 API Key、完整 prompt 或完整 response。
- `core/llm/ollama_manager.py` 只使用参数数组调用固定 Ollama 子命令，限制模型名、超时和回环 HTTP 检查；不会执行用户提供的 shell 命令。
- 已提供 `models/ollama/Modelfile.stock-agent-qwen3-4b`、`scripts/setup_ollama_qwen3_4b.ps1` 与 `docs/setup/LOCAL_LLM_SETUP.md`。脚本在未安装 Ollama 时仅显示官方下载地址，可重复运行，拉取 `qwen3:4b` 后创建项目模型并验证 `/v1/models` 与 `/v1/chat/completions`。
- L1 Benchmark 继承当前 profile；本地模式强制单并发、每案例 600 秒、零重试，且把部署模式、provider、model 和 timeout 纳入可复现哈希。

## 验证

使用 `D:\stock_daily_app\.venv\Scripts\python.exe` 执行了定向回归：

```text
22 passed
```

覆盖配置迁移、双 profile 隔离、固定 loopback、本地 dummy key、禁止回退、审计脱敏、Qwen3 `/no_think`、DeepSeek 请求差异、Ollama 参数安全、Benchmark 哈希与既有 Agent 流程。

## 当前运行条件

已通过官方 `Ollama.Ollama` Windows 包安装 Ollama 0.32.1，服务位于 `127.0.0.1:11434`。`qwen3:4b` 与 `stock-agent-qwen3-4b:latest` 已存在，安装脚本已成功完成 `/v1/models` 与 `/v1/chat/completions` 实际验证；项目客户端以无标签名称 `stock-agent-qwen3-4b` 调用时同样验证成功。

在临时 SQLite 和输出目录中运行了一次真实本地 Agent 请求（只读“查看当前模拟盘持仓”）：请求成功，生成 4 条 LLM 收据，全部为 `deployment_mode=local`、`provider=ollama_local` 且共用一个配置哈希；收据中未发现密钥。该次完整链路耗时约 496 秒，说明这台机器的 4B 本地模型适合单并发、长时限任务，不适合高并发交互。

该机器的 4B 模型首轮推理会产生 reasoning 字段且约需数十秒；客户端只使用正常 content，`/no_think` 指令仍只追加到复制后的 system message 一次，绝不把 reasoning 或输入消息改写回调用方。远程 API 的实际连通性取决于用户已保存的凭据与账户状态，系统不会以本地模型替代失败的远程调用。

## Web 部署

部署前已终止原先占用 8501 的监听进程。新版服务使用 `D:\stock_daily_app\.venv\Scripts\python.exe -m streamlit run app.py` 启动，监听 `127.0.0.1:8501`；`/_stcore/health` 返回 `ok`，根页面返回 HTTP 200。虚拟环境的基础解释器位于 D 盘，未使用 C 盘 Python。
