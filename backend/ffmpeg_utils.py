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


def generate_thumbnail(video_path: Path, thumbnail_path: Path, duration: float):
    seek_time = min(3.0, max(duration / 2, 0.5))

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-ss",
        str(seek_time),
        "-i",
        safe_path(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        safe_path(thumbnail_path),
    ]

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Erro ao gerar thumbnail: {result.stderr}")

    return str(thumbnail_path)


def normalize_options(options: Optional[dict]) -> dict:
    if not isinstance(options, dict):
        options = {}

    format_value = options.get("format", "youtube")

    if format_value not in {"youtube", "shorts"}:
        format_value = "youtube"

    try:
        music_volume = float(options.get("music_volume", 0.18))
    except (TypeError, ValueError):
        music_volume = 0.18

    music_volume = max(0.0, min(music_volume, 1.0))

    return {
        "format": format_value,
        "auto_zoom": bool(options.get("auto_zoom", False)),
        "fade": bool(options.get("fade", False)),
        "music_volume": music_volume,
        "subtitle_enabled": bool(options.get("subtitle_enabled", True)),
    }


def get_canvas_size(format_value: str) -> tuple[int, int]:
    if format_value == "shorts":
        return 1080, 1920

    return 1920, 1080


def build_video_filter(
    input_index: int,
    output_label: str,
    scene_duration: float,
    width: int,
    height: int,
    auto_zoom: bool,
    fade: bool,
) -> str:
    filters = [
        f"trim=duration={scene_duration}",
        "setpts=PTS-STARTPTS",
        f"scale={width}:{height}:force_original_aspect_ratio=increase",
        f"crop={width}:{height}",
        "setsar=1",
        "fps=30",
    ]

    if auto_zoom:
        filters.extend([
            "scale=8000:-1",
            f"zoompan=z='min(zoom+0.0008,1.08)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps=30",
            "setsar=1",
        ])

    if fade and scene_duration > 1.0:
        fade_out_start = max(scene_duration - 0.35, 0)
        filters.append("fade=t=in:st=0:d=0.25")
        filters.append(f"fade=t=out:st={fade_out_start}:d=0.35")

    return f"[{input_index}:v]" + ",".join(filters) + f"[{output_label}]"


def build_ffmpeg_command(
    video_paths: list[Path],
    voice_path: Path,
    output_path: Path,
    subtitle_path: Optional[Path] = None,
    music_path: Optional[Path] = None,
    options: Optional[dict] = None,
) -> list[str]:

    if not video_paths:
        raise RuntimeError("Nenhuma cena encontrada para renderizar")

    settings = get_settings()
    render_options = normalize_options(options)

    width, height = get_canvas_size(render_options["format"])

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
            build_video_filter(
                input_index=index,
                output_label=f"v{index}",
                scene_duration=scene_duration,
                width=width,
                height=height,
                auto_zoom=render_options["auto_zoom"],
                fade=render_options["fade"],
            )
        )

    concat_inputs = "".join(
        f"[v{index}]" for index in range(len(video_paths))
    )

    filter_parts.append(
        f"{concat_inputs}concat=n={len(video_paths)}:v=1:a=0[vcat]"
    )

    if subtitle_path and render_options["subtitle_enabled"]:
        subtitle_escaped = escape_subtitle_path(subtitle_path)
        filter_parts.append(
            f"[vcat]subtitles='{subtitle_escaped}'[vout]"
        )
    else:
        filter_parts.append(
            "[vcat]null[vout]"
        )

    if has_music:
        filter_parts.append(
            f"[{voice_input_index}:a]volume={settings.voice_volume}[voice]"
        )

        filter_parts.append(
            f"[{music_input_index}:a]volume={render_options['music_volume']}[music]"
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
    options = normalize_options(meta.get("options", {}))

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
    thumbnail_path = job_dir / "thumbnail.jpg"

    update_job(
        job_dir,
        status="processing",
        progress=10,
        message="Verificando duração da narração",
        render_options=options,
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
        render_format=options["format"],
    )

    cmd = build_ffmpeg_command(
        video_paths=video_paths,
        voice_path=voice_path,
        subtitle_path=subtitle_path,
        music_path=music_path,
        output_path=output_path,
        options=options,
    )

    update_job(
        job_dir,
        status="processing",
        progress=30,
        message="Renderizando vídeo com configurações personalizadas",
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
        status="processing",
        progress=95,
        message="Gerando thumbnail automática",
    )

    try:
        generate_thumbnail(
            video_path=output_path,
            thumbnail_path=thumbnail_path,
            duration=voice_duration,
        )
        thumbnail_file = "thumbnail.jpg"
        thumbnail_url = f"/thumbnail/{meta['job_id']}"
        thumbnail_error = None
    except Exception as exc:
        thumbnail_file = None
        thumbnail_url = None
        thumbnail_error = str(exc)

    update_job(
        job_dir,
        status="completed",
        progress=100,
        message="Vídeo gerado com sucesso",
        output_file="output.mp4",
        download_url=f"/download/{meta['job_id']}",
        thumbnail_file=thumbnail_file,
        thumbnail_url=thumbnail_url,
        thumbnail_error=thumbnail_error,
        final_duration=voice_duration,
        scene_count=len(video_paths),
        scene_duration=scene_duration,
        render_options=options,
    )

    return str(output_path)