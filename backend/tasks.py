import traceback

from celery import Celery

from config import get_settings
from ffmpeg_utils import log_job, run_ffmpeg, update_job
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
    task_id = process_video_task.request.id

    try:
        log_job(job_dir, f"[TASK] Entrou no process_video_task | job_id={job_id} | task_id={task_id}")

        update_job(
            job_dir,
            status="processing",
            progress=1,
            message="Worker recebeu a tarefa",
            celery_task_id=task_id,
            error=None,
            error_stage=None,
        )

        log_job(job_dir, "[TASK] Chamando run_ffmpeg")
        result = run_ffmpeg(job_dir)

        log_job(job_dir, f"[TASK] Finalizado com sucesso: {result}")
        return result

    except Exception as exc:
        error_text = str(exc)
        traceback_text = traceback.format_exc()

        log_job(job_dir, f"[TASK][ERRO] {error_text}")
        log_job(job_dir, traceback_text)

        update_job(
            job_dir,
            status="error",
            progress=100,
            message="Falha no processamento",
            error=error_text[-4000:],
            traceback=traceback_text[-8000:],
            error_stage="process_video_task",
        )

        raise


@celery_app.task(name="tasks.cleanup_old_jobs_task")
def cleanup_old_jobs_task():
    return cleanup_old_jobs()