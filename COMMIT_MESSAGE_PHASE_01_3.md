# 推荐 Commit

```powershell
git commit -m "refactor(agent): derive worker dependencies from semantic inputs" -m "Let MainAgent declare typed upstream input bindings, compile dependency_task_ids deterministically from from_task_id references, validate Worker input roles and output contracts, preserve planner diagnostics, and restrict API reload watching to source directories."
```

中文含义：

```text
MainAgent 只生成带语义的上游 inputs；
程序根据 from_task_id 确定性生成执行依赖；
避免 LLM 重复生成两份依赖关系而产生不一致；
保留 Planner 实时追踪、失败候选归档和准确错误映射；
修复 Uvicorn 监听 runtime 引发的 WatchFiles 异常。
```
