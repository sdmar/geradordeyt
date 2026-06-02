import json
import subprocess
from pathlib import Path
from typing import Optional

from config import get_settings


def safe_path(path: Path) -> str:
    return str(path.resolve())


def escape_subtitle_path(path: Path) -> str:
    return (
        safe_path(path)
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
    )


def update_job(job_dir: Path, **updates):
    meta_path = job_dir / "job.json"
    data = {}

    if meta_path.exists():
        data = json.loads(meta_path.read_text(encoding="utf-8"))

    data.update(updates)

    meta_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_media_duration(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        safe_path(path),
    ]

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Erro ao obter duração: {result.stderr}")

    return float(result.stdout.strip())


def build_ffmpeg_command(
    video_paths: list[Path],
    voice_path: Path,
    output_path: Path,
    subtitle_path: Optional[Path] = None,
    music_path: Optional[Path] = None,
) -> list[str]:

    if not video_paths:
        raise RuntimeError("Nenhuma cena encontrada para renderizar")

    settings = get_settings()
    voice_duration = get_media_duration(voice_path)
    scene_duration = voice_duration / len(video_paths)

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
    ]

    for video_path in video_paths:
        cmd += [
            "-stream_loop",
            "-1",
            "-i",
            safe_path(video_path),
        ]

    voice_input_index = len(video_paths)

    cmd += [
        "-i",
        safe_path(voice_path),
    ]

    has_music = music_path is not None
    music_input_index = voice_input_index + 1

    if has_music:
        cmd += [
            "-stream_loop",
            "-1",
            "-i",
            safe_path(music_path),
        ]

    filter_parts = []

    for index in range(len(video_paths)):
        filter_parts.append(
            f"[{index}:v]"
            f"trim=duration={scene_duration},"
            f"setpts=PTS-STARTPTS,"
            f"scale=1920:1080:force_original_aspect_ratio=decrease,"
            f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
            f"setsar=1,"
            f"fps=30"
            f"[v{index}]"
        )

    concat_inputs = "".join(
        f"[v{index}]" for index in range(len(video_paths))
    )

    filter_parts.append(
        f"{concat_inputs}concat=n={len(video_paths)}:v=1:a=0[vcat]"
    )

    if subtitle_path:
        subtitle_escaped = escape_subtitle_path(subtitle_path)
        filter_parts.append(
            f"[vcat]subtitles='{subtitle_escaped}'[vout]"
        )
    else:
        filter_parts.append(
            "[vcat]copy[vout]"
        )

    if has_music:
        filter_parts.append(
            f"[{voice_input_index}:a]volume={settings.voice_volume}[voice]"
        )

        filter_parts.append(
            f"[{music_input_index}:a]volume=0.18[music]"
        )

        filter_parts.append(
            "[voice][music]amix=inputs=2:duration=first:normalize=0[aout]"
        )
    else:
        filter_parts.append(
            f"[{voice_input_index}:a]volume={settings.voice_volume}[aout]"
        )

    filter_complex = ";".join(filter_parts)

    cmd += [
        "-filter_complex",
        filter_complex,

        "-map",
        "[vout]",

        "-map",
        "[aout]",

        "-t",
        str(voice_duration),

        "-threads",
        "0",

        "-c:v",
        "libx264",

        "-preset",
        "veryfast",

        "-crf",
        "21",

        "-pix_fmt",
        "yuv420p",

        "-c:a",
        "aac",

        "-b:a",
        "192k",

        "-movflags",
        "+faststart",

        safe_path(output_path),
    ]

    return cmd


def run_ffmpeg(job_dir: Path):

    meta = json.loads(
        (job_dir / "job.json").read_text(
            encoding="utf-8"
        )
    )

    files = meta["files"]

    video_files = files.get("videos") or [files["video"]]
    video_paths = [job_dir / video_file for video_file in video_files]

    voice_path = job_dir / files["voice"]

    subtitle_path = (
        job_dir / files["subtitle"]
        if files.get("subtitle")
        else None
    )

    music_path = (
        job_dir / files["music"]
        if files.get("music")
        else None
    )

    output_path = job_dir / "output.mp4"

    update_job(
        job_dir,
        status="processing",
        progress=10,
        message="Verificando duração da narração",
    )

    voice_duration = get_media_duration(voice_path)
    scene_duration = voice_duration / len(video_paths)

    update_job(
        job_dir,
        status="processing",
        progress=20,
        message=f"Narração detectada: {voice_duration:.2f} segundos",
        voice_duration=voice_duration,
        scene_count=len(video_paths),
        scene_duration=scene_duration,
    )

    cmd = build_ffmpeg_command(
        video_paths=video_paths,
        voice_path=voice_path,
        subtitle_path=subtitle_path,
        music_path=music_path,
        output_path=output_path,
    )

    update_job(
        job_dir,
        status="processing",
        progress=30,
        message="Renderizando vídeo com múltiplas cenas",
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
        final_duration=voice_duration,
        scene_count=len(video_paths),
        scene_duration=scene_duration,
    )

    return str(output_path)