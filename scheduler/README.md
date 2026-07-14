# Scheduler

Stage 5H separates the daily update worker from the Streamlit APP.

The Streamlit APP only displays results, status, and manual controls. The background worker can run from Windows Task Scheduler even when the browser and Streamlit are closed.

Main entry points:

```powershell
python -m scheduler.scheduler_cli health
python -m scheduler.scheduler_cli run --all-users --source scheduled
python -m scheduler.scheduler_cli status
```

State and logs:

```text
runtime/jobs/latest_job_status.json
runtime/jobs/history/
runtime/locks/daily_update.lock
logs/scheduler/
```

No real trading or broker API is implemented.
