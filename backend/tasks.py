from pathlib import Path

from celery import Celery

from config import get_settings
from ffmpeg_utils import run_ffmpeg, update_job
from cleanup import cleanup_old_jobs


settings = get_settings()

celery_app = Celery(
    "video_generator",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    timezone="UTC",
    beat_schedule={
        "cleanup-old-jobs-every-hour": {
            "task": "tasks.cleanup_old_jobs_task",
            "schedule": 3600.0,
        }
    },
)


@celery_app.task(name="tasks.process_video_task")
def process_video_task(job_id: str):
    job_dir = settings.output_dir / job_id
    try:
        update_job(job_dir, celery_task_id=process_video_task.request.id)
        return run_ffmpeg(job_dir)
    except Exception as exc:
        update_job(
            job_dir,
            status="error",
            progress=100,
            message="Falha no processamento",
            error=str(exc)[-4000:],
        )
        raise


@celery_app.task(name="tasks.cleanup_old_jobs_task")
def cleanup_old_jobs_task():
    return cleanup_old_jobs()
