import json
from functools import lru_cache
from typing import Annotated, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "FinSight AI"
    environment: str = "development"
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./stock_ai.db"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://localhost:4173",
            "http://localhost:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:4173",
            "http://127.0.0.1:3000",
        ]
    )

    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"
    openai_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    openai_max_tokens: int = Field(default=300, ge=64, le=4000)
    openai_timeout_seconds: float = Field(default=4.0, gt=0.0, le=30.0)
    twelve_data_api_key: Optional[str] = None
    enable_transformers_sentiment: bool = False
    finbert_model_name: str = "ProsusAI/finbert"

    rate_limit_requests: int = 30
    rate_limit_window_seconds: int = 60
    news_limit: int = 8
    news_fetch_timeout_seconds: float = Field(default=1.0, gt=0.0, le=30.0)
    news_retry_attempts: int = Field(default=2, ge=1, le=5)
    market_data_timeout_seconds: float = Field(default=4.0, gt=0.0, le=30.0)
    market_data_retry_attempts: int = Field(default=2, ge=1, le=5)
    auth_secret: str = "dev-secret-change-me"
    auth_session_hours: int = Field(default=24, ge=1, le=720)
    default_watchlist: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["INFY.NS"]
    )
    admin_emails: Annotated[list[str], NoDecode] = Field(default_factory=list)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return cls._parse_string_list(value)
        return value

    @field_validator("default_watchlist", mode="before")
    @classmethod
    def parse_default_watchlist(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.upper() for item in cls._parse_string_list(value)]
        return [item.upper() for item in value]

    @field_validator("admin_emails", mode="before")
    @classmethod
    def parse_admin_emails(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.lower() for item in cls._parse_string_list(value)]
        return [item.lower() for item in value]

    @staticmethod
    def _parse_string_list(value: str) -> list[str]:
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        return [item.strip() for item in stripped.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
