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
                raise HTTPException(status_code=413, detail="Arquivo excede o limite permitido")

            await out.write(chunk)

    return size


def validate_upload_id(upload_id: str):
    if not re.fullmatch(r"[a-f0-9-]{36}", upload_id):
        raise HTTPException(status_code=400, detail="upload_id inválido")


def safe_chunk_path(upload_id: str, chunk_index: int) -> Path:
    validate_upload_id(upload_id)

    if chunk_index < 0:
        raise HTTPException(status_code=400, detail="chunk_index inválido")

    upload_dir = settings.chunks_dir / upload_id
    return upload_dir / f"{chunk_index:08d}.part"


def get_upload_meta_path(upload_id: str) -> Path:
    validate_upload_id(upload_id)
    return settings.chunks_dir / upload_id / "upload.json"


def read_upload_meta(upload_id: str) -> dict:
    meta_path = get_upload_meta_path(upload_id)

    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="Upload não encontrado")

    return json.loads(meta_path.read_text(encoding="utf-8"))


def write_upload_meta(upload_id: str, meta: dict):
    meta_path = get_upload_meta_path(upload_id)
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_job(job_id: str) -> dict:
    if not re.fullmatch(r"[a-f0-9-]{36}", job_id):
        raise HTTPException(status_code=400, detail="job_id inválido")

    meta_path = settings.output_dir / job_id / "job.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="Job não encontrado")

    return json.loads(meta_path.read_text(encoding="utf-8"))


async def assemble_chunks(upload_id: str, destination: Path) -> int:
    meta = read_upload_meta(upload_id)
    total_chunks = int(meta["total_chunks"])
    received_chunks = set(meta.get("received_chunks", []))

    missing = [i for i in range(total_chunks) if i not in received_chunks]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Upload incompleto. Chunks faltando: {missing[:20]}",
        )

    total_size = 0

    async with aiofiles.open(destination, "wb") as final_file:
        for index in range(total_chunks):
            chunk_path = safe_chunk_path(upload_id, index)

            if not chunk_path.exists():
                raise HTTPException(
                    status_code=400,
                    detail=f"Chunk ausente no disco: {index}",
                )

            async with aiofiles.open(chunk_path, "rb") as part:
                while True:
                    data = await part.read(1024 * 1024)
                    if not data:
                        break

                    total_size += len(data)

                    if total_size > settings.max_file_size:
                        destination.unlink(missing_ok=True)
                        raise HTTPException(
                            status_code=413,
                            detail="Arquivo final excede o limite permitido",
                        )

                    await final_file.write(data)

    expected_size = int(meta.get("total_size", 0))
    if expected_size > 0 and total_size != expected_size:
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=f"Tamanho final inválido. Esperado {expected_size}, gerado {total_size}",
        )

    meta["status"] = "assembled"
    meta["assembled_at"] = datetime.now(timezone.utc).isoformat()
    meta["assembled_size"] = total_size
    write_upload_meta(upload_id, meta)

    return total_size


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/upload/start")
async def upload_start(
    filename: str = Form(...),
    file_type: str = Form(...),
    total_size: int = Form(...),
    total_chunks: int = Form(...),
):
    if file_type not in {"video", "voice", "subtitle", "music"}:
        raise HTTPException(status_code=400, detail="file_type inválido")

    if total_size <= 0 or total_size > settings.max_file_size:
        raise HTTPException(status_code=413, detail="Arquivo excede o limite permitido")

    if total_chunks <= 0:
        raise HTTPException(status_code=400, detail="total_chunks inválido")

    fake_upload = type("FakeUpload", (), {"filename": filename})()

    if file_type == "video":
        validate_file(fake_upload, settings.allowed_video_ext, "Vídeo")
    elif file_type in {"voice", "music"}:
        validate_file(fake_upload, settings.allowed_audio_ext, "Áudio")
    elif file_type == "subtitle":
        validate_file(fake_upload, settings.allowed_subtitle_ext, "Legenda")

    upload_id = str(uuid.uuid4())
    upload_dir = settings.chunks_dir / upload_id
    upload_dir.mkdir(parents=True, exist_ok=False)

    meta = {
        "upload_id": upload_id,
        "filename": sanitize_filename(filename),
        "original_filename": filename,
        "file_type": file_type,
        "total_size": total_size,
        "total_chunks": total_chunks,
        "received_chunks": [],
        "received_count": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "receiving",
    }

    write_upload_meta(upload_id, meta)

    return {
        "upload_id": upload_id,
        "chunk_size": settings.chunk_size,
        "status": "receiving",
    }


@app.post("/upload/chunk")
async def upload_chunk(
    upload_id: str = Form(...),
    chunk_index: int = Form(...),
    chunk: UploadFile = File(...),
):
    meta = read_upload_meta(upload_id)
    total_chunks = int(meta["total_chunks"])

    if chunk_index < 0 or chunk_index >= total_chunks:
        raise HTTPException(status_code=400, detail="chunk_index fora do intervalo")

    destination = safe_chunk_path(upload_id, chunk_index)

    size = await save_upload_stream(
        chunk,
        destination,
        settings.chunk_size + 1024,
    )

    received = set(meta.get("received_chunks", []))
    received.add(chunk_index)

    meta["received_chunks"] = sorted(received)
    meta["received_count"] = len(received)
    meta["last_chunk_at"] = datetime.now(timezone.utc).isoformat()

    write_upload_meta(upload_id, meta)

    return {
        "upload_id": upload_id,
        "chunk_index": chunk_index,
        "chunk_size": size,
        "received_count": len(received),
        "total_chunks": total_chunks,
        "done": len(received) == total_chunks,
    }


@app.post("/upload/finish")
async def upload_finish(
    video_upload_id: str = Form(...),
    voice_upload_id: str = Form(...),
    subtitle_upload_id: Optional[str] = Form(None),
    music_upload_id: Optional[str] = Form(None),
    script: Optional[str] = Form(None),
):
    video_meta = read_upload_meta(video_upload_id)
    voice_meta = read_upload_meta(voice_upload_id)

    if video_meta.get("file_type") != "video":
        raise HTTPException(status_code=400, detail="video_upload_id não é vídeo")

    if voice_meta.get("file_type") != "voice":
        raise HTTPException(status_code=400, detail="voice_upload_id não é narração")

    subtitle_meta = None
    music_meta = None

    if subtitle_upload_id:
        subtitle_meta = read_upload_meta(subtitle_upload_id)
        if subtitle_meta.get("file_type") != "subtitle":
            raise HTTPException(status_code=400, detail="subtitle_upload_id não é legenda")

    if music_upload_id:
        music_meta = read_upload_meta(music_upload_id)
        if music_meta.get("file_type") != "music":
            raise HTTPException(status_code=400, detail="music_upload_id não é música")

    job_id = str(uuid.uuid4())
    job_dir = settings.output_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=False)

    files = {
        "video": None,
        "voice": None,
        "subtitle": None,
        "music": None,
    }

    upload_ids_to_cleanup = [
        video_upload_id,
        voice_upload_id,
        subtitle_upload_id,
        music_upload_id,
    ]

    try:
        video_name = "video." + ext(video_meta["filename"])
        voice_name = "voice." + ext(voice_meta["filename"])

        await assemble_chunks(video_upload_id, job_dir / video_name)
        await assemble_chunks(voice_upload_id, job_dir / voice_name)

        files["video"] = video_name
        files["voice"] = voice_name

        if subtitle_meta and subtitle_upload_id:
            subtitle_name = "subtitle." + ext(subtitle_meta["filename"])
            await assemble_chunks(subtitle_upload_id, job_dir / subtitle_name)
            files["subtitle"] = subtitle_name

        if music_meta and music_upload_id:
            music_name = "music." + ext(music_meta["filename"])
            await assemble_chunks(music_upload_id, job_dir / music_name)
            files["music"] = music_name

        if script:
            (job_dir / "script.txt").write_text(script, encoding="utf-8")

        meta = {
            "job_id": job_id,
            "status": "pending",
            "progress": 0,
            "message": "Upload completo. Job aguardando processamento",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": files,
            "download_url": None,
        }

        (job_dir / "job.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        task = process_video_task.delay(job_id)
        meta["celery_task_id"] = task.id

        (job_dir / "job.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        for old_upload_id in upload_ids_to_cleanup:
            if old_upload_id:
                shutil.rmtree(settings.chunks_dir / old_upload_id, ignore_errors=True)

        return {
            "job_id": job_id,
            "status": "pending",
        }

    except Exception:
        if job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)
        raise


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

        (job_dir / "job.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        task = process_video_task.delay(job_id)
        meta["celery_task_id"] = task.id

        (job_dir / "job.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

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