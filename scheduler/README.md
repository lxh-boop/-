# Scheduler Runtime

阶段 6.7 起，正式自动更新由 FastAPI 进程内的 APScheduler 托管，不依赖浏览器、Streamlit 或额外 Docker 服务。

## 正式运行链路

```text
FastAPI lifespan
  -> scheduler.runtime_scheduler
  -> 按 local_app_config.json 注册 Cron
  -> scheduler.daily_worker.run_scheduled_daily_update
  -> daily_incremental_update.py
  -> ranking_latest.csv
  -> 新闻 / 用户推荐 / 模拟盘
```

配置字段：

```text
auto_retrain_enabled
auto_retrain_hour
auto_retrain_minute
auto_retrain_timezone
auto_retrain_catch_up
```

状态文件：

```text
runtime/jobs/scheduler_runtime_status.json
runtime/jobs/latest_job_status.json
runtime/jobs/history/
logs/scheduler/
```

如果 API 在计划时间未运行，且 `auto_retrain_catch_up=true`，下一次 API 启动会检测最近交易日排名是否缺失，并自动补跑。

## 手动运行

```powershell
python -m scheduler.scheduler_cli run --all-users --source manual --force
```

系统设置页的“立即运行完整日更”通过 Task API 提交同一条完整链路。

## Windows 计划任务

`scripts/install_windows_daily_task.ps1` 仅作为可选后备方案。正式主调度器仍是 FastAPI 进程内调度器。
