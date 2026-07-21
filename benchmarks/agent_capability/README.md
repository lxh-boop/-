# Real-LLM Agent Capability Benchmark (L1)

This benchmark measures the Agent workflow—not investment recommendations, expected returns, or live trading quality. It always invokes `agent.executor.run_agent_request` with a configured real LLM, in a fresh synthetic paper-trading fixture.

```powershell
D:\stock_daily_app\.venv\Scripts\python.exe -m benchmarks.agent_capability.run_benchmark --split development --iterations 5
D:\stock_daily_app\.venv\Scripts\python.exe -m benchmarks.agent_capability.resume --split hidden --iterations 5
```

The corpus contains 180 cases: six categories with 30 cases each, split 108 development / 36 validation / 36 hidden. Hidden gold lives in `cases/hidden_gold.jsonl`, is never included in an Agent prompt, and is joined only after a trace has been recorded. Failed raw traces are retained and redacted. All outputs are under `outputs/benchmarks/agent_capability/`.

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。
