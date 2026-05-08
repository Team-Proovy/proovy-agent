"""Application settings."""

from functools import lru_cache

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
    database_url: str = ""

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
