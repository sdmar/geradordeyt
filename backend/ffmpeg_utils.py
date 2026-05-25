import json
import os
import subprocess
from pathlib import Path
from typing import Optional

from config import get_settings


def safe_path(path: Path) -> str:
    return str(path.resolve())


def update_job(job_dir: Path, **updates):
    meta_path = job_dir / "job.json"
    data = {}
    if meta_path.exists():
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    data.update(updates)
    meta_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_ffmpeg_command(
    video_path: Path,
    voice_path: Path,
    output_path: Path,
    subtitle_path: Optional[Path] = None,
    music_path: Optional[Path] = None,
) -> list[str]:
    """
    Monta o comando FFmpeg para 4 cenários:
    1) vídeo + narração
    2) vídeo + narração + legenda
    3) vídeo + narração + música
    4) vídeo + narração + música + legenda

    Filtros usados:
    - scale/pad: converte para 1920x1080 sem distorcer
    - subtitles: queima legenda no vídeo quando houver .srt ou .ass
    - volume: ajusta narração e música
    - amix: mistura narração e música
    - libx264/aac: saída MP4 compatível com YouTube
    """
    settings = get_settings()

    cmd = ["ffmpeg", "-y", "-hide_banner"]

    cmd += ["-i", safe_path(video_path)]
    cmd += ["-i", safe_path(voice_path)]

    has_music = music_path is not None
    if has_music:
        cmd += ["-stream_loop", "-1", "-i", safe_path(music_path)]

    video_filter = (
        "scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
        "setsar=1"
    )

    if subtitle_path:
        subtitle_escaped = safe_path(subtitle_path).replace("\\", "\\\\").replace(":", "\\:")
        video_filter += f",subtitles='{subtitle_escaped}'"

    filter_parts = [f"[0:v]{video_filter}[vout]"]

    if has_music:
        filter_parts.append(f"[1:a]volume={settings.voice_volume}[voice]")
        filter_parts.append(f"[2:a]volume={settings.music_volume}[music]")
        filter_parts.append("[voice][music]amix=inputs=2:duration=first:dropout_transition=2[aout]")
    else:
        filter_parts.append(f"[1:a]volume={settings.voice_volume}[aout]")

    filter_complex = ";".join(filter_parts)

    cmd += [
        "-filter_complex",
        filter_complex,
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        "-movflags",
        "+faststart",
        safe_path(output_path),
    ]

    return cmd


def run_ffmpeg(job_dir: Path):
    meta = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))

    video_path = job_dir / meta["files"]["video"]
    voice_path = job_dir / meta["files"]["voice"]
    subtitle_path = job_dir / meta["files"]["subtitle"] if meta["files"].get("subtitle") else None
    music_path = job_dir / meta["files"]["music"] if meta["files"].get("music") else None
    output_path = job_dir / "output.mp4"

    update_job(job_dir, status="processing", progress=10, message="Preparando FFmpeg")

    cmd = build_ffmpeg_command(
        video_path=video_path,
        voice_path=voice_path,
        subtitle_path=subtitle_path,
        music_path=music_path,
        output_path=output_path,
    )

    update_job(
        job_dir,
        status="processing",
        progress=30,
        message="Renderizando vídeo",
        ffmpeg_command=" ".join(cmd),
    )

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    _, stderr = process.communicate()

    if process.returncode != 0:
        update_job(
            job_dir,
            status="error",
            progress=100,
            message="Erro ao processar vídeo com FFmpeg",
            error=stderr[-4000:],
        )
        raise RuntimeError(stderr)

    update_job(
        job_dir,
        status="completed",
        progress=100,
        message="Vídeo gerado com sucesso",
        output_file="output.mp4",
        download_url=f"/download/{meta['job_id']}",
    )

    return str(output_path)
