"""Configuration settings using pydantic-settings for environment variable loading."""

from pathlib import Path
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.
    
    Automatically reads from .env file and environment variables.
    Environment variables take precedence over .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Spotify OAuth
    spotify_client_id: str
    spotify_client_secret: str
    spotify_redirect_uri: str = "http://127.0.0.1:8888/callback"

    # Google Gemini
    gemini_api_key: str

    # Setlist.fm
    setlist_fm_api_key: str

    # Paths
    cache_path: Path = Field(default_factory=lambda: Path.home() / ".venue2playlist" / "cache.db")
    token_cache_path: Path = Field(default_factory=lambda: Path.home() / ".venue2playlist" / ".spotify_cache")

    # Logging
    log_level: str = "INFO"
    log_format: Literal["console", "json"] = "console"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.
    
    Uses lru_cache to ensure settings are only loaded once.
    """
    return Settings()
