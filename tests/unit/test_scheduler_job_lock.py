import json
import os

import pytest

from scheduler.job_lock import JobLock, JobLockError


def test_job_lock_acquire_and_release(tmp_path) -> None:
    lock_path = tmp_path / "runtime" / "locks" / "daily_update.lock"
    lock = JobLock(lock_path=lock_path, job_id="job1", trade_date="2026-06-11")

    payload = lock.acquire()

    assert lock_path.exists()
    assert payload["job_id"] == "job1"

    lock.release()

    assert not lock_path.exists()


def test_job_lock_rejects_live_lock(tmp_path) -> None:
    lock_path = tmp_path / "daily_update.lock"
    lock_path.write_text(json.dumps({"pid": os.getpid(), "job_id": "live"}), encoding="utf-8")

    with pytest.raises(JobLockError):
        JobLock(lock_path=lock_path, job_id="next", trade_date="2026-06-11").acquire()


def test_job_lock_clears_stale_lock(tmp_path) -> None:
    lock_path = tmp_path / "daily_update.lock"
    lock_path.write_text(json.dumps({"pid": 999999999, "job_id": "stale"}), encoding="utf-8")

    payload = JobLock(lock_path=lock_path, job_id="new", trade_date="2026-06-11").acquire()

    assert payload["job_id"] == "new"
