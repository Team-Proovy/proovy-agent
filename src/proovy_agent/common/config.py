"""Application settings."""

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven application settings."""

    app_name: str = "Proovy Agent"
    app_version: str = "0.1.0"
    debug: bool = False
    allowed_origins: str = "http://localhost:3000"

    openrouter_api_key: str = ""
    daytona_api_key: str = ""
    daytona_api_url: str = "https://app.daytona.io/api"
    daytona_target: str | None = None
    daytona_snapshot: str = "proovy-math-sandbox"
    daytona_sandbox_cpu: int = 2
    daytona_sandbox_memory: int = 2
    daytona_sandbox_disk: int = 5
    daytona_auto_stop_interval: int = 5
    daytona_code_timeout: int = 60
    daytona_max_output_chars: int = 10_000
    sandbox_preamble_name: str = "math_v1"
    database_url: str = ""
    credit_hold_ttl_seconds: int = Field(default=1200, gt=0)
    inworld_tts_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("INWORLD_TTS_API_KEY", "INWORLD_API_KEY"),
    )
    video_tts_model: str = Field(
        default="inworld-tts-1.5-max",
        validation_alias=AliasChoices("VIDEO_TTS_MODEL", "INWORLD_TTS_MODEL_ID"),
    )
    video_tts_voice: str = Field(
        default="Hyunwoo",
        validation_alias=AliasChoices("VIDEO_TTS_VOICE", "INWORLD_TTS_VOICE_ID"),
    )
    video_tts_speaking_rate: float = 0.95
    video_tts_temperature: float = 0.9
    video_tts_timestamp_type: Literal["WORD"] = "WORD"
    video_tts_timeout_seconds: float = 60.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origins(self) -> list[str]:
        """Return parsed CORS origins."""
        origins = [origin.strip() for origin in self.allowed_origins.split(",")]
        return [origin for origin in origins if origin]


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()


settings = get_settings()
