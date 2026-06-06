import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger


BASE_DIR = Path(__file__).resolve().parent
ROLLING_UPDATE_SCRIPT = BASE_DIR / "daily_incremental_update.py"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
TORCH_MLP_BACKEND = "torch_mlp_alpha158"
DFT_UNET_BACKEND = "dft_unet_external"


def write_log(text: str):
    log_path = LOG_DIR / "auto_retrain.log"

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(text)
        f.write("\n")


def run_command(cmd):
    child_env = os.environ.copy()
    child_env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        cmd,
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        env=child_env,
    )

    return result


def mask_sensitive_command(cmd):
    masked = []

    for i, part in enumerate(cmd):
        if i > 0 and cmd[i - 1] == "--token":
            masked.append("***")
        else:
            masked.append(part)

    return masked


def auto_retrain_job(
    token: str,
    version: str = "latest",
    model_backend: str = TORCH_MLP_BACKEND,
    checkpoint_path: str | None = None,
):
    """
    每日自动任务：基于已有模型执行增量更新并刷新最新排名。
    """

    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    write_log("=" * 100)
    write_log(f"[Auto Daily Update Start] {start_time}")

    if not token:
        write_log("[Error] Tushare token is empty. Skip auto daily update.")
        return

    update_cmd = [
        sys.executable,
        str(ROLLING_UPDATE_SCRIPT),
        "--token",
        token,
        "--base-version",
        version,
        "--model-backend",
        model_backend,
    ]
    if model_backend == DFT_UNET_BACKEND and checkpoint_path:
        update_cmd.extend(["--checkpoint-path", checkpoint_path])

    write_log(f"[Run] {' '.join(mask_sensitive_command(update_cmd))}")

    update_result = run_command(update_cmd)

    write_log("[Daily Update STDOUT]")
    write_log(update_result.stdout)

    if update_result.stderr:
        write_log("[Daily Update STDERR]")
        write_log(update_result.stderr)

    if update_result.returncode != 0:
        write_log(
            f"[Error] daily_incremental_update.py failed, "
            f"returncode={update_result.returncode}"
        )
        return

    write_log("[Daily Update Success]")

    end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    write_log(f"[Auto Daily Update Finished] {end_time}")
    write_log("=" * 100)


def create_scheduler():
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    scheduler.start()
    return scheduler


def set_daily_retrain_job(
    scheduler: BackgroundScheduler,
    token: str,
    hour: int,
    minute: int,
    enabled: bool,
    model_backend: str = TORCH_MLP_BACKEND,
    checkpoint_path: str | None = None,
):
    """
    注册或移除每日自动更新任务。
    """

    job_id = "daily_auto_retrain"

    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    if not enabled:
        return None

    trigger = CronTrigger(hour=hour, minute=minute)

    job = scheduler.add_job(
        auto_retrain_job,
        trigger=trigger,
        args=[token, "latest", model_backend, checkpoint_path],
        id=job_id,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    return job


def get_scheduler_jobs(scheduler: BackgroundScheduler):
    jobs = []

    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "next_run_time": str(job.next_run_time),
            "name": job.name,
        })

    return jobs


def read_auto_retrain_log(max_chars: int = 12000) -> str:
    log_path = LOG_DIR / "auto_retrain.log"

    if not log_path.exists():
        return ""

    text = log_path.read_text(encoding="utf-8", errors="ignore")

    if len(text) > max_chars:
        return text[-max_chars:]

    return text
