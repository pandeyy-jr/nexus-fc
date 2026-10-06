from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "NEXUS FC Backend"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "staging", "production"] = "development"
    database_url: str = "postgresql+psycopg://nexus:nexus@localhost:5432/nexus"
    jwt_secret_key: SecretStr
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = Field(default=30, gt=0, le=1440)
    cors_origins: list[str] = Field(default_factory=list)
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = Field(default="club_memory", min_length=1, max_length=100)
    qdrant_api_key: SecretStr | None = None
    qdrant_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    copilot_model: str = Field(default="gpt-4o-mini", min_length=1, max_length=100)
    copilot_api_key: SecretStr | None = None
    copilot_base_url: str = "https://api.openai.com/v1"
    copilot_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    copilot_max_output_tokens: int = Field(default=1024, ge=1, le=8192)
    copilot_rate_limit_requests: int = Field(default=20, ge=1, le=1000)
    copilot_rate_limit_window_seconds: float = Field(default=60.0, gt=0, le=3600)

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
