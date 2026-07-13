import hashlib
import json
import os
import shutil
import signal
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
    unsupported = []

    for path in video_paths:
        if not path.exists():
            missing.append(str(path))
        elif not is_image_file(path) and not is_video_file(path):
            unsupported.append(path.name)

    if not voice_path.exists():
        missing.append(str(voice_path))

    if subtitle_path and not subtitle_path.exists():
        missing.append(str(subtitle_path))

    if music_path and not music_path.exists():
        missing.append(str(music_path))

    if missing:
        raise FileNotFoundError("Arquivos ausentes: " + " | ".join(missing))

    if unsupported:
        raise RuntimeError(
            "Cenas com formato não suportado: " + " | ".join(unsupported)
        )


def build_scene_filter(
    scene_duration: float,
    width: int,
    height: int,
    auto_zoom: bool,
    fade: bool,
) -> str:
    filters = [
        f"scale={width}:{height}:force_original_aspect_ratio=increase",
        f"crop={width}:{height}",
        "setsar=1",
    ]

    if auto_zoom:
        zoom_frame_count = max(int(round(scene_duration * 30)) - 1, 1)
        zoom_step = 0.08 / zoom_frame_count

        filters.extend(
            [
                (
                    "zoompan="
                    f"z='min(1+{zoom_step:.10f}*on,1.08)':"
                    "d=1:"
                    "x='iw/2-(iw/zoom/2)':"
                    "y='ih/2-(ih/zoom/2)':"
                    f"s={width}x{height}:fps=30"
                ),
            ]
        )
    else:
        filters.append("fps=30")

    if fade and scene_duration > 1.0:
        fade_out_start = max(scene_duration - 0.35, 0)
        filters.append("fade=t=in:st=0:d=0.25")
        filters.append(f"fade=t=out:st={fade_out_start}:d=0.35")

    filters.extend(["setsar=1", "format=yuv420p"])

    return ",".join(filters)


def ffmpeg_base_command() -> list[str]:
    return [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "warning",
        "-stats_period",
        "2",
        "-progress",
        "pipe:2",
    ]


def build_scene_command(
    source_path: Path,
    output_path: Path,
    scene_duration: float,
    width: int,
    height: int,
    auto_zoom: bool,
    fade: bool,
) -> list[str]:
    cmd = ffmpeg_base_command()

    if is_image_file(source_path):
        cmd += ["-loop", "1", "-framerate", "30", "-i", safe_path(source_path)]
    else:
        cmd += ["-stream_loop", "-1", "-i", safe_path(source_path)]

    cmd += [
        "-t",
        f"{scene_duration:.6f}",
        "-an",
        "-vf",
        build_scene_filter(
            scene_duration=scene_duration,
            width=width,
            height=height,
            auto_zoom=auto_zoom,
            fade=fade,
        ),
        "-filter_threads",
        "1",
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
        "-r",
        "30",
        "-g",
        "60",
        "-movflags",
        "+faststart",
        safe_path(output_path),
    ]

    return cmd


def build_concat_command(concat_path: Path, output_path: Path) -> list[str]:
    return ffmpeg_base_command() + [
        "-fflags",
        "+genpts",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        safe_path(concat_path),
        "-map",
        "0:v:0",
        "-an",
        "-c:v",
        "copy",
        "-movflags",
        "+faststart",
        safe_path(output_path),
    ]


def build_finalize_command(
    visual_path: Path,
    voice_path: Path,
    output_path: Path,
    voice_duration: float,
    subtitle_path: Optional[Path],
    music_path: Optional[Path],
    options: dict,
) -> list[str]:
    settings = get_settings()
    cmd = ffmpeg_base_command() + [
        "-i",
        safe_path(visual_path),
        "-i",
        safe_path(voice_path),
    ]

    has_music = music_path is not None

    if has_music:
        cmd += [
            "-stream_loop",
            "-1",
            "-t",
            f"{voice_duration:.6f}",
            "-i",
            safe_path(music_path),
        ]

    filter_parts = [f"[1:a]volume={settings.voice_volume}[voice]"]

    if has_music:
        filter_parts.extend(
            [
                f"[2:a]volume={options['music_volume']}[music]",
                "[voice][music]amix=inputs=2:duration=first:normalize=0[aout]",
            ]
        )
    else:
        filter_parts.append("[voice]anull[aout]")

    cmd += [
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        "0:v:0",
        "-map",
        "[aout]",
    ]

    burn_subtitles = subtitle_path is not None and options["subtitle_enabled"]

    if burn_subtitles:
        cmd += [
            "-vf",
            f"subtitles='{escape_subtitle_path(subtitle_path)}'",
            "-filter_threads",
            "1",
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
        ]
    else:
        cmd += ["-c:v", "copy"]

    cmd += [
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-t",
        f"{voice_duration:.6f}",
        "-movflags",
        "+faststart",
        safe_path(output_path),
    ]

    return cmd


def terminate_process(process: subprocess.Popen):
    if process.poll() is not None:
        return

    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)
    except Exception:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except Exception:
            process.kill()


def run_command_with_logs(
    cmd: list[str],
    job_dir: Path,
    stage: str,
    progress_start: int,
    progress_end: int,
    expected_duration: Optional[float] = None,
    timeout_seconds: Optional[int] = None,
):
    log_job(job_dir, f"[FFMPEG][{stage}] Iniciando processo")
    log_job(job_dir, f"[FFMPEG][{stage}] {' '.join(cmd)}")

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        start_new_session=True,
    )

    stderr_lines = []
    last_update = time.time()
    started_at = time.time()
    rendered_seconds = 0.0

    try:
        while True:
            line = process.stderr.readline()

            if line:
                clean_line = line.strip()
                stderr_lines.append(clean_line)

                if len(stderr_lines) > 300:
                    stderr_lines = stderr_lines[-300:]

                if clean_line.startswith(("out_time_ms=", "out_time_us=")):
                    try:
                        rendered_seconds = float(clean_line.split("=", 1)[1]) / 1_000_000
                    except (TypeError, ValueError):
                        rendered_seconds = 0.0

                progress_keys = (
                    "frame=",
                    "fps=",
                    "bitrate=",
                    "total_size=",
                    "out_time_",
                    "dup_frames=",
                    "drop_frames=",
                    "speed=",
                    "progress=",
                )

                if clean_line and not clean_line.startswith(progress_keys):
                    log_job(job_dir, f"[FFMPEG][{stage}] {clean_line}")

                now = time.time()

                if now - last_update >= 2:
                    progress = progress_start

                    if expected_duration and expected_duration > 0:
                        ratio = min(max(rendered_seconds / expected_duration, 0.0), 1.0)
                        progress = int(progress_start + ((progress_end - progress_start) * ratio))

                    update_job(
                        job_dir,
                        status="processing",
                        progress=progress,
                        stage=stage,
                        message=f"FFmpeg executando: {stage}",
                        ffmpeg_pid=process.pid,
                        last_ffmpeg_log=clean_line[-1000:],
                    )
                    last_update = now

            if timeout_seconds and time.time() - started_at > timeout_seconds:
                raise TimeoutError(
                    f"FFmpeg excedeu o limite de {timeout_seconds}s em {stage}"
                )

            if process.poll() is not None:
                break

        stdout, stderr_rest = process.communicate()

        if stderr_rest:
            for line in stderr_rest.splitlines():
                clean_line = line.strip()
                stderr_lines.append(clean_line)

                if clean_line:
                    log_job(job_dir, f"[FFMPEG][{stage}] {clean_line}")

        if stdout:
            log_job(job_dir, f"[FFMPEG][{stage}][STDOUT] {stdout[-4000:]}")

        full_stderr = "\n".join(stderr_lines)

        if process.returncode != 0:
            raise RuntimeError(
                full_stderr[-8000:] or f"FFmpeg falhou em {stage} sem stderr"
            )

        update_job(job_dir, ffmpeg_pid=None, progress=progress_end)
        log_job(job_dir, f"[FFMPEG][{stage}] Finalizado com sucesso")
    except Exception:
        terminate_process(process)
        update_job(job_dir, ffmpeg_pid=None)
        raise


def is_valid_segment(path: Path, expected_duration: float) -> bool:
    if not path.exists() or path.stat().st_size <= 0:
        return False

    try:
        actual_duration = get_media_duration(path)
    except Exception:
        return False

    tolerance = max(0.25, expected_duration * 0.10)
    return abs(actual_duration - expected_duration) <= tolerance


def concat_file_line(path: Path) -> str:
    escaped = safe_path(path).replace("'", "'\\''")
    return f"file '{escaped}'"


def ensure_free_space(job_dir: Path, minimum_bytes: int = 2 * 1024 ** 3) -> int:
    free_bytes = shutil.disk_usage(job_dir).free

    if free_bytes < minimum_bytes:
        free_gb = free_bytes / (1024 ** 3)
        required_gb = minimum_bytes / (1024 ** 3)
        raise RuntimeError(
            f"Espaço livre insuficiente: {free_gb:.2f} GB; "
            f"mínimo requerido {required_gb:.2f} GB"
        )

    return free_bytes


def build_render_signature(
    video_paths: list[Path],
    scene_durations: list[float],
    options: dict,
    width: int,
    height: int,
) -> tuple[str, dict]:
    sources = []

    for path in video_paths:
        stat = path.stat()
        sources.append(
            {
                "name": path.name,
                "size": stat.st_size,
                "modified_ns": stat.st_mtime_ns,
            }
        )

    payload = {
        "renderer_version": "sequential-v2-visible-zoom",
        "sources": sources,
        "scene_durations": [round(value, 6) for value in scene_durations],
        "format": options["format"],
        "auto_zoom": options["auto_zoom"],
        "fade": options["fade"],
        "width": width,
        "height": height,
        "fps": 30,
        "crf": 21,
        "preset": "veryfast",
    }

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest(), payload


def run_ffmpeg(job_dir: Path):
    stage = "startup"

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
        output_temp_path = job_dir / "output.part.mp4"
        thumbnail_path = job_dir / "thumbnail.jpg"
        segments_dir = job_dir / "segments"
        visual_path = job_dir / "visual.mp4"
        visual_temp_path = job_dir / "visual.part.mp4"
        concat_path = job_dir / "segments.txt"

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

        stage = "preflight"

        validate_input_files(
            video_paths=video_paths,
            voice_path=voice_path,
            subtitle_path=subtitle_path,
            music_path=music_path,
        )

        free_disk_bytes = ensure_free_space(job_dir)

        update_job(
            job_dir,
            status="processing",
            progress=10,
            stage=stage,
            message="Arquivos encontrados. Calculando duração da narração",
            free_disk_bytes=free_disk_bytes,
        )

        log_job(job_dir, "[RUN] Calculando duração da voz")
        voice_duration = get_media_duration(voice_path)

        if voice_duration <= 0:
            raise RuntimeError("Duração da narração inválida")

        scene_duration = voice_duration / len(video_paths)
        scene_durations = [scene_duration] * len(video_paths)
        scene_durations[-1] = voice_duration - sum(scene_durations[:-1])
        width, height = get_canvas_size(options["format"])

        log_job(job_dir, f"[RUN] Duração da voz: {voice_duration:.2f}s")
        log_job(job_dir, f"[RUN] Duração média por cena: {scene_duration:.2f}s")

        update_job(
            job_dir,
            status="processing",
            progress=20,
            stage="render_scenes",
            message=f"Narração detectada: {voice_duration:.2f} segundos",
            voice_duration=voice_duration,
            scene_count=len(video_paths),
            scene_duration=scene_duration,
            render_format=options["format"],
            render_width=width,
            render_height=height,
            render_strategy="sequential_segments",
        )

        stage = "render_scenes"
        segments_dir.mkdir(parents=True, exist_ok=True)
        signature_path = segments_dir / "render_signature.json"
        render_signature, signature_payload = build_render_signature(
            video_paths=video_paths,
            scene_durations=scene_durations,
            options=options,
            width=width,
            height=height,
        )

        previous_signature = None

        if signature_path.exists():
            try:
                previous_signature = json.loads(
                    signature_path.read_text(encoding="utf-8")
                ).get("signature")
            except Exception:
                previous_signature = None

        if previous_signature != render_signature:
            log_job(
                job_dir,
                "[RUN] Configuração de render nova; descartando segmentos incompatíveis",
            )

            for old_segment in segments_dir.glob("scene_*.mp4"):
                old_segment.unlink(missing_ok=True)

            for old_temp in segments_dir.glob("scene_*.part.mp4"):
                old_temp.unlink(missing_ok=True)

        signature_path.write_text(
            json.dumps(
                {
                    "signature": render_signature,
                    "payload": signature_payload,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        update_job(job_dir, render_signature=render_signature)
        segment_paths = []
        resumed_segments = 0

        for index, (source_path, current_duration) in enumerate(
            zip(video_paths, scene_durations),
            start=1,
        ):
            segment_path = segments_dir / f"scene_{index:03d}.mp4"
            segment_temp_path = segments_dir / f"scene_{index:03d}.part.mp4"
            segment_paths.append(segment_path)

            progress_start = 20 + int(((index - 1) / len(video_paths)) * 55)
            progress_end = 20 + int((index / len(video_paths)) * 55)

            update_job(
                job_dir,
                status="processing",
                progress=progress_start,
                stage=stage,
                current_scene=index,
                total_scenes=len(video_paths),
                message=f"Renderizando cena {index} de {len(video_paths)}",
            )

            if is_valid_segment(segment_path, current_duration):
                resumed_segments += 1
                log_job(
                    job_dir,
                    f"[RUN] Cena {index}/{len(video_paths)} já válida; reutilizando segmento",
                )
                continue

            segment_path.unlink(missing_ok=True)
            segment_temp_path.unlink(missing_ok=True)

            cmd = build_scene_command(
                source_path=source_path,
                output_path=segment_temp_path,
                scene_duration=current_duration,
                width=width,
                height=height,
                auto_zoom=options["auto_zoom"],
                fade=options["fade"],
            )

            update_job(job_dir, ffmpeg_command=" ".join(cmd))

            scene_timeout = min(
                3600,
                max(300, int(current_duration * 20)),
            )

            run_command_with_logs(
                cmd=cmd,
                job_dir=job_dir,
                stage=f"scene_{index:03d}",
                progress_start=progress_start,
                progress_end=progress_end,
                expected_duration=current_duration,
                timeout_seconds=scene_timeout,
            )

            if not is_valid_segment(segment_temp_path, current_duration):
                raise RuntimeError(
                    f"Cena {index} foi renderizada, mas o segmento final é inválido"
                )

            segment_temp_path.replace(segment_path)

        update_job(
            job_dir,
            progress=76,
            stage="concat_segments",
            current_scene=len(video_paths),
            resumed_segments=resumed_segments,
            message="Cenas prontas. Concatenando segmentos",
        )

        stage = "concat_segments"
        concat_path.write_text(
            "\n".join(concat_file_line(path) for path in segment_paths) + "\n",
            encoding="utf-8",
        )

        visual_path.unlink(missing_ok=True)
        visual_temp_path.unlink(missing_ok=True)

        concat_cmd = build_concat_command(
            concat_path=concat_path,
            output_path=visual_temp_path,
        )

        update_job(job_dir, ffmpeg_command=" ".join(concat_cmd))

        run_command_with_logs(
            cmd=concat_cmd,
            job_dir=job_dir,
            stage=stage,
            progress_start=76,
            progress_end=84,
            expected_duration=voice_duration,
            timeout_seconds=max(600, int(voice_duration * 5)),
        )

        if not visual_temp_path.exists():
            raise RuntimeError("Concatenação terminou, mas visual.part.mp4 não foi criado")

        visual_temp_path.replace(visual_path)

        stage = "finalize_output"
        output_path.unlink(missing_ok=True)
        output_temp_path.unlink(missing_ok=True)

        finalize_cmd = build_finalize_command(
            visual_path=visual_path,
            voice_path=voice_path,
            output_path=output_temp_path,
            voice_duration=voice_duration,
            subtitle_path=subtitle_path,
            music_path=music_path,
            options=options,
        )

        update_job(
            job_dir,
            progress=85,
            stage=stage,
            message="Aplicando áudio, música e legendas",
            ffmpeg_command=" ".join(finalize_cmd),
        )

        run_command_with_logs(
            cmd=finalize_cmd,
            job_dir=job_dir,
            stage=stage,
            progress_start=85,
            progress_end=94,
            expected_duration=voice_duration,
            timeout_seconds=max(900, int(voice_duration * 10)),
        )

        if not output_temp_path.exists():
            raise RuntimeError("Finalização terminou, mas output.part.mp4 não foi criado")

        output_temp_path.replace(output_path)
        final_duration = get_media_duration(output_path)

        if abs(final_duration - voice_duration) > 1.0:
            raise RuntimeError(
                f"Duração final fora da tolerância: esperado {voice_duration:.2f}s, "
                f"obtido {final_duration:.2f}s"
            )

        stage = "thumbnail"

        update_job(
            job_dir,
            status="processing",
            progress=95,
            stage=stage,
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
            final_duration=final_duration,
            scene_count=len(video_paths),
            scene_duration=scene_duration,
            render_options=options,
            render_strategy="sequential_segments",
            stage="completed",
            current_scene=len(video_paths),
            total_scenes=len(video_paths),
        )

        log_job(job_dir, "[RUN] Job marcado como completed")

        return str(output_path)

    except Exception as exc:
        fail_job(job_dir, stage, exc)
        raise
