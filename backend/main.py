import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiofiles
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from config import get_settings
from tasks import process_video_task


settings = get_settings()
app = FastAPI(title="YouTube Video Generator", version="1.0.0")

origins = ["*"] if settings.cors_origins == "*" else [
    origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def sanitize_filename(filename: str) -> str:
    name = Path(filename).name
    return re.sub(r"[^a-zA-Z0-9._-]", "_", name)


def validate_file(upload: UploadFile, allowed: set[str], label: str):
    file_ext = ext(upload.filename or "")
    if file_ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"{label} inválido. Extensões permitidas: {', '.join(sorted(allowed))}",
        )


async def save_upload_stream(upload: UploadFile, destination: Path, max_size: int):
    size = 0
    chunk_size = 1024 * 1024

    async with aiofiles.open(destination, "wb") as out:
        while True:
            chunk = await upload.read(chunk_size)
            if not chunk:
                break
            size += len(chunk)
            if size > max_size:
                destination.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Arquivo excede o limite de 2GB")
            await out.write(chunk)

    return size


def read_job(job_id: str) -> dict:
    if not re.fullmatch(r"[a-f0-9-]{36}", job_id):
        raise HTTPException(status_code=400, detail="job_id inválido")

    meta_path = settings.output_dir / job_id / "job.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="Job não encontrado")

    return json.loads(meta_path.read_text(encoding="utf-8"))


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/upload")
async def upload(
    video: UploadFile = File(...),
    voice: UploadFile = File(...),
    subtitle: Optional[UploadFile] = File(None),
    music: Optional[UploadFile] = File(None),
    script: Optional[str] = Form(None),
):
    validate_file(video, settings.allowed_video_ext, "Vídeo")
    validate_file(voice, settings.allowed_audio_ext, "Áudio de narração")

    if subtitle and subtitle.filename:
        validate_file(subtitle, settings.allowed_subtitle_ext, "Legenda")

    if music and music.filename:
        validate_file(music, settings.allowed_audio_ext, "Música")

    job_id = str(uuid.uuid4())
    job_dir = settings.output_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=False)

    files = {}

    try:
        video_name = "video." + ext(video.filename)
        voice_name = "voice." + ext(voice.filename)

        await save_upload_stream(video, job_dir / video_name, settings.max_file_size)
        await save_upload_stream(voice, job_dir / voice_name, settings.max_file_size)

        files["video"] = video_name
        files["voice"] = voice_name

        if subtitle and subtitle.filename:
            subtitle_name = "subtitle." + ext(subtitle.filename)
            await save_upload_stream(subtitle, job_dir / subtitle_name, settings.max_file_size)
            files["subtitle"] = subtitle_name
        else:
            files["subtitle"] = None

        if music and music.filename:
            music_name = "music." + ext(music.filename)
            await save_upload_stream(music, job_dir / music_name, settings.max_file_size)
            files["music"] = music_name
        else:
            files["music"] = None

        if script:
            (job_dir / "script.txt").write_text(script, encoding="utf-8")

        meta = {
            "job_id": job_id,
            "status": "pending",
            "progress": 0,
            "message": "Job recebido e aguardando processamento",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": files,
            "download_url": None,
        }

        (job_dir / "job.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        task = process_video_task.delay(job_id)
        meta["celery_task_id"] = task.id
        (job_dir / "job.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        return {"job_id": job_id, "status": "pending"}

    except Exception:
        if job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)
        raise


@app.get("/status/{job_id}")
def status(job_id: str):
    return read_job(job_id)


@app.get("/download/{job_id}")
def download(job_id: str):
    read_job(job_id)
    output = settings.output_dir / job_id / "output.mp4"

    if not output.exists():
        raise HTTPException(status_code=404, detail="Vídeo ainda não foi gerado")

    return FileResponse(
        output,
        media_type="video/mp4",
        filename=f"video-{job_id}.mp4",
    )


@app.delete("/job/{job_id}")
def delete_job(job_id: str):
    read_job(job_id)
    job_dir = settings.output_dir / job_id
    shutil.rmtree(job_dir, ignore_errors=True)
    return JSONResponse({"ok": True, "message": "Job removido"})
