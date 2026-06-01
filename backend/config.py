from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_url: str = "redis://redis:6379/0"
    data_dir: Path = Path("/data")
    output_dir: Path = Path("/data/jobs")
    chunks_dir: Path = Path("/data/chunks")
    max_file_size: int = 2_147_483_648
    chunk_size: int = 10 * 1024 * 1024
    cleanup_after_hours: int = 24
    voice_volume: float = 1.0
    music_volume: float = 0.18
    cors_origins: str = "*"

    allowed_video_ext: set[str] = {"mp4", "mov", "mkv", "webm"}
    allowed_audio_ext: set[str] = {"mp3", "wav", "m4a", "aac"}
    allowed_subtitle_ext: set[str] = {"srt", "ass"}

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    settings.chunks_dir.mkdir(parents=True, exist_ok=True)
    return settings