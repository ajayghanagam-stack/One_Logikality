"""Application settings loaded from environment / .env.

Variable names match Title Intelligence Hub per docs/TechStack.md §14 so
engineers moving between the two products don't re-learn environment setup.
Loading is strict: required values missing from the environment raise at
startup rather than failing silently later.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)

INSECURE_JWT_DEFAULT = "dev-insecure-change-me-before-production"

# Repo root is two parents up from backend/app/config.py. Anchoring on __file__
# means the same .env is found no matter what cwd the process was started in
# (uvicorn from backend/, pytest from backend/, worker from backend/, etc).
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database — Replit provides postgresql:// but asyncpg requires postgresql+asyncpg://
    database_url: str = Field(alias="DATABASE_URL")

    @field_validator("database_url", mode="before")
    @classmethod
    def ensure_asyncpg_scheme(cls, v: str) -> str:
        # Convert plain postgresql:// to asyncpg dialect
        if v.startswith("postgresql://") or v.startswith("postgres://"):
            v = v.replace("://", "+asyncpg://", 1)
        # Strip sslmode query param — asyncpg uses ssl=True/False, not sslmode
        parsed = urlparse(v)
        params = parse_qs(parsed.query, keep_blank_values=True)
        params.pop("sslmode", None)
        new_query = urlencode({k: vv[0] for k, vv in params.items()})
        v = urlunparse(parsed._replace(query=new_query))
        return v

    # Temporal
    temporal_address: str = Field(alias="TEMPORAL_ADDRESS", default="localhost:7234")

    # Auth
    jwt_secret: str = Field(alias="JWT_SECRET", default=INSECURE_JWT_DEFAULT)
    jwt_expiration_minutes: int = Field(alias="JWT_EXPIRATION_MINUTES", default=1440)

    # Storage
    storage_provider: Literal["local", "s3"] = Field(alias="STORAGE_PROVIDER", default="local")
    storage_path: str = Field(alias="STORAGE_PATH", default="./storage")

    # Pipeline orchestration
    pipeline_backend: Literal["temporal", "background_tasks"] = Field(
        alias="PIPELINE_BACKEND", default="temporal"
    )

    # AI provider selection; individual keys are checked at call sites in Phase 3
    ai_provider: Literal["claude", "gemini", "hybrid"] = Field(
        alias="AI_PROVIDER", default="claude"
    )

    # Anthropic (validation + reasoning — Claude Sonnet)
    anthropic_api_key: str | None = Field(alias="ANTHROPIC_API_KEY", default=None)
    anthropic_model: str = Field(alias="ANTHROPIC_MODEL", default="claude-sonnet-4-6")

    # Google Vertex AI (classification + extraction — Gemini 2.5 Flash / Pro)
    # Auth is via Application Default Credentials, not an API key — run
    # `gcloud auth application-default login` or set GOOGLE_APPLICATION_CREDENTIALS.
    google_cloud_project: str | None = Field(alias="GOOGLE_CLOUD_PROJECT", default=None)
    google_cloud_region: str = Field(alias="GOOGLE_CLOUD_REGION", default="us-central1")
    vertex_classify_model: str = Field(alias="VERTEX_CLASSIFY_MODEL", default="gemini-2.5-flash")
    vertex_extract_model: str = Field(alias="VERTEX_EXTRACT_MODEL", default="gemini-2.5-pro")


settings = Settings()  # type: ignore[call-arg]


if settings.jwt_secret == INSECURE_JWT_DEFAULT:
    log.warning(
        "JWT_SECRET is using the insecure development default. "
        "Override in .env for any environment other than local development."
    )
