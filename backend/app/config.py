"""Application settings loaded from environment / .env.

Variable names match Title Intelligence Hub per docs/TechStack.md §14 so
engineers moving between the two products don't re-learn environment setup.
Loading is strict: required values missing from the environment raise at
startup rather than failing silently later.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)

INSECURE_JWT_DEFAULT = "dev-insecure-change-me-before-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = Field(alias="DATABASE_URL")

    # Temporal
    temporal_address: str = Field(alias="TEMPORAL_ADDRESS", default="localhost:7234")

    # Auth
    jwt_secret: str = Field(alias="JWT_SECRET")
    jwt_expiration_minutes: int = Field(alias="JWT_EXPIRATION_MINUTES", default=1440)

    # Storage
    storage_provider: Literal["local", "s3"] = Field(
        alias="STORAGE_PROVIDER", default="local"
    )
    storage_path: str = Field(alias="STORAGE_PATH", default="./storage")

    # Pipeline orchestration
    pipeline_backend: Literal["temporal", "background_tasks"] = Field(
        alias="PIPELINE_BACKEND", default="temporal"
    )

    # AI provider selection; individual keys are checked at call sites in Phase 3
    ai_provider: Literal["claude", "gemini", "hybrid"] = Field(
        alias="AI_PROVIDER", default="claude"
    )


settings = Settings()  # type: ignore[call-arg]


if settings.jwt_secret == INSECURE_JWT_DEFAULT:
    log.warning(
        "JWT_SECRET is using the insecure development default. "
        "Override in .env for any environment other than local development."
    )
