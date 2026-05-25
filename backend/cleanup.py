import shutil
import time
from pathlib import Path

from config import get_settings


def cleanup_old_jobs() -> dict:
    settings = get_settings()
    now = time.time()
    max_age_seconds = settings.cleanup_after_hours * 3600

    removed = []
    settings.output_dir.mkdir(parents=True, exist_ok=True)

    for job_dir in settings.output_dir.iterdir():
        if not job_dir.is_dir():
            continue

        age = now - job_dir.stat().st_mtime
        if age > max_age_seconds:
            shutil.rmtree(job_dir, ignore_errors=True)
            removed.append(job_dir.name)

    return {"removed": removed, "count": len(removed)}
