import json
import subprocess
import time
import traceback
from pathlib import Path
from typing import Optional

from config import get_settings


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}


def safe_path(path: Path) -> str:
    return str(path.resolve())


def log_job(job_dir: Path, message: str):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"{timestamp} {message}"

    print(line, flush=True)

    try:
        job_dir.mkdir(parents=True, exist_ok=True)
        with (job_dir / "worker.log").open("a", encoding="utf-8") as file:
            file.write(line + "\n")
    except Exception:
        pass


def escape_subtitle_path(path: Path) -> str:
    return (
        safe_path(path)
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
    )


def update_job(job_dir: Path, **updates):
    job_dir.mkdir(parents=True, exist_ok=True)

    meta_path = job_dir / "job.json"
    data = {}

    if meta_path.exists():
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    data.update(updates)
    data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    temp_path = job_dir / "job.json.tmp"

    temp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    temp_path.replace(meta_path)


def fail_job(job_dir: Path, stage: str, exc: Exception):
    error_text = str(exc)
    traceback_text = traceback.format_exc()

    log_job(job_dir, f"[ERRO][{stage}] {error_text}")
    log_job(job_dir, traceback_text)

    update_job(
        job_dir,
        status="error",
        progress=100,
        message=f"Falha no processamento: {stage}",
        error=error_text[-4000:],
        traceback=traceback_text[-8000:],
        error_stage=stage,
    )


def get_media_duration(path: Path) -> float:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado para ffprobe: {path}")

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
        timeout=120,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Erro ao obter duração de {path.name}: {result.stderr}")

    output = result.stdout.strip()

    if not output:
        raise RuntimeError(f"ffprobe não retornou duração para {path.name}")

    return float(output)


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
        timeout=180,
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


def is_image_file(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def is_video_file(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def validate_input_files(
    video_paths: list[Path],
    voice_path: Path,
    subtitle_path: Optional[Path],
    music_path: Optional[Path],
):
    if not video_paths:
        raise RuntimeError("Nenhuma cena encontrada para renderizar")

    missing = []

    for path in video_paths:
        if not path.exists():
            missing.append(str(path))

    if not voice_path.exists():
        missing.append(str(voice_path))

    if subtitle_path and not subtitle_path.exists():
        missing.append(str(subtitle_path))

    if music_path and not music_path.exists():
        missing.append(str(music_path))

    if missing:
        raise FileNotFoundError("Arquivos ausentes: " + " | ".join(missing))


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
        filters.extend(
            [
                f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase",
                f"crop={width * 2}:{height * 2}",
                (
                    "zoompan="
                    "z='min(zoom+0.00045,1.045)':"
                    "d=1:"
                    "x='iw/2-(iw/zoom/2)':"
                    "y='ih/2-(ih/zoom/2)':"
                    f"s={width}x{height}:fps=30"
                ),
                "setsar=1",
            ]
        )

    if fade and scene_duration > 1.0:
        fade_out_start = max(scene_duration - 0.35, 0)
        filters.append("fade=t=in:st=0:d=0.25")
        filters.append(f"fade=t=out:st={fade_out_start}:d=0.35")

    return f"[{input_index}:v]" + ",".join(filters) + f"[{output_label}]"


def build_ffmpeg_command(
    video_paths: list[Path],
    voice_path: Path,
    output_path: Path,
    voice_duration: float,
    scene_duration: float,
    subtitle_path: Optional[Path] = None,
    music_path: Optional[Path] = None,
    options: Optional[dict] = None,
) -> list[str]:
    settings = get_settings()
    render_options = normalize_options(options)

    width, height = get_canvas_size(render_options["format"])

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
    ]

    for video_path in video_paths:
        if is_image_file(video_path):
            cmd += [
                "-loop",
                "1",
                "-t",
                str(scene_duration),
                "-i",
                safe_path(video_path),
            ]
        else:
            cmd += [
                "-stream_loop",
                "-1",
                "-t",
                str(scene_duration),
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
            "-t",
            str(voice_duration),
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

    concat_inputs = "".join(f"[v{index}]" for index in range(len(video_paths)))

    filter_parts.append(
        f"{concat_inputs}concat=n={len(video_paths)}:v=1:a=0[vcat]"
    )

    if subtitle_path and render_options["subtitle_enabled"]:
        subtitle_escaped = escape_subtitle_path(subtitle_path)
        filter_parts.append(f"[vcat]subtitles='{subtitle_escaped}'[vout]")
    else:
        filter_parts.append("[vcat]null[vout]")

    if has_music:
        filter_parts.append(f"[{voice_input_index}:a]volume={settings.voice_volume}[voice]")
        filter_parts.append(f"[{music_input_index}:a]volume={render_options['music_volume']}[music]")
        filter_parts.append("[voice][music]amix=inputs=2:duration=first:normalize=0[aout]")
    else:
        filter_parts.append(f"[{voice_input_index}:a]volume={settings.voice_volume}[aout]")

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
        "2",
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


def run_command_with_logs(cmd: list[str], job_dir: Path, voice_duration: float):
    log_job(job_dir, "[FFMPEG] Iniciando processo FFmpeg")
    log_job(job_dir, "[FFMPEG] Comando montado:")
    log_job(job_dir, " ".join(cmd))

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    stderr_lines = []
    last_update = time.time()

    while True:
        line = process.stderr.readline()

        if line:
            clean_line = line.strip()
            stderr_lines.append(clean_line)

            if len(stderr_lines) > 300:
                stderr_lines = stderr_lines[-300:]

            log_job(job_dir, f"[FFMPEG] {clean_line}")

            now = time.time()

            if now - last_update >= 10:
                update_job(
                    job_dir,
                    status="processing",
                    progress=50,
                    message="FFmpeg renderizando vídeo",
                    last_ffmpeg_log=clean_line[-1000:],
                )
                last_update = now

        if process.poll() is not None:
            break

    stdout, stderr_rest = process.communicate()

    if stderr_rest:
        for line in stderr_rest.splitlines():
            clean_line = line.strip()
            stderr_lines.append(clean_line)
            log_job(job_dir, f"[FFMPEG] {clean_line}")

    if stdout:
        log_job(job_dir, f"[FFMPEG][STDOUT] {stdout[-4000:]}")

    full_stderr = "\n".join(stderr_lines)

    if process.returncode != 0:
        raise RuntimeError(full_stderr[-8000:] or "FFmpeg falhou sem stderr")

    log_job(job_dir, "[FFMPEG] Processo finalizado com sucesso")


def run_ffmpeg(job_dir: Path):
    try:
        log_job(job_dir, "[RUN] Entrou no run_ffmpeg")

        update_job(
            job_dir,
            status="processing",
            progress=2,
            message="Iniciando processamento no worker",
            error=None,
            error_stage=None,
        )

        meta_path = job_dir / "job.json"

        log_job(job_dir, f"[RUN] Lendo job.json: {meta_path}")

        if not meta_path.exists():
            raise FileNotFoundError(f"job.json não encontrado em {meta_path}")

        meta = json.loads(meta_path.read_text(encoding="utf-8"))

        update_job(
            job_dir,
            status="processing",
            progress=5,
            message="job.json lido com sucesso",
        )

        files = meta.get("files")

        if not isinstance(files, dict):
            raise RuntimeError("Campo files ausente ou inválido no job.json")

        options = normalize_options(meta.get("options", {}))

        video_files = files.get("videos") or [files.get("video")]
        video_files = [item for item in video_files if item]

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

        log_job(job_dir, f"[RUN] Cenas encontradas no job.json: {len(video_paths)}")
        log_job(job_dir, f"[RUN] Voz: {voice_path}")
        log_job(job_dir, f"[RUN] Música: {music_path}")
        log_job(job_dir, f"[RUN] Legenda: {subtitle_path}")

        update_job(
            job_dir,
            status="processing",
            progress=8,
            message="Verificando arquivos do job",
            render_options=options,
            scene_count=len(video_paths),
        )

        validate_input_files(
            video_paths=video_paths,
            voice_path=voice_path,
            subtitle_path=subtitle_path,
            music_path=music_path,
        )

        update_job(
            job_dir,
            status="processing",
            progress=10,
            message="Arquivos encontrados. Calculando duração da narração",
        )

        log_job(job_dir, "[RUN] Calculando duração da voz")
        voice_duration = get_media_duration(voice_path)

        if voice_duration <= 0:
            raise RuntimeError("Duração da narração inválida")

        scene_duration = voice_duration / len(video_paths)

        log_job(job_dir, f"[RUN] Duração da voz: {voice_duration:.2f}s")
        log_job(job_dir, f"[RUN] Duração por cena: {scene_duration:.2f}s")

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

        log_job(job_dir, "[RUN] Montando comando FFmpeg")

        cmd = build_ffmpeg_command(
            video_paths=video_paths,
            voice_path=voice_path,
            subtitle_path=subtitle_path,
            music_path=music_path,
            output_path=output_path,
            voice_duration=voice_duration,
            scene_duration=scene_duration,
            options=options,
        )

        update_job(
            job_dir,
            status="processing",
            progress=30,
            message="Comando FFmpeg montado. Iniciando render",
            ffmpeg_command=" ".join(cmd),
        )

        run_command_with_logs(
            cmd=cmd,
            job_dir=job_dir,
            voice_duration=voice_duration,
        )

        if not output_path.exists():
            raise RuntimeError("FFmpeg terminou, mas output.mp4 não foi criado")

        update_job(
            job_dir,
            status="processing",
            progress=95,
            message="Vídeo renderizado. Gerando thumbnail automática",
        )

        log_job(job_dir, "[RUN] Gerando thumbnail")

        try:
            generate_thumbnail(
                video_path=output_path,
                thumbnail_path=thumbnail_path,
                duration=voice_duration,
            )
            thumbnail_file = "thumbnail.jpg"
            thumbnail_url = f"/thumbnail/{meta['job_id']}"
            thumbnail_error = None
            log_job(job_dir, "[RUN] Thumbnail gerada com sucesso")
        except Exception as exc:
            thumbnail_file = None
            thumbnail_url = None
            thumbnail_error = str(exc)
            log_job(job_dir, f"[RUN][THUMBNAIL ERRO] {thumbnail_error}")

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

        log_job(job_dir, "[RUN] Job marcado como completed")

        return str(output_path)

    except Exception as exc:
        fail_job(job_dir, "run_ffmpeg", exc)
        raise