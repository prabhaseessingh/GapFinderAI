from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import AnyHttpUrl, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env", extra="ignore"
    )
    environment: str = "development"
    database_url: str = "postgresql+psycopg://gapfinder:gapfinder@localhost:5432/gapfinder"
    redis_url: str = "redis://localhost:6379/0"
    # "celery" = separate worker over Redis (local). "inline" = run jobs on threads inside
    # the API process (Render free tier: no free background worker, 512 MB RAM).
    task_runner: str = "celery"
    inline_workers: int = 2
    db_pool_size: int = 2
    db_max_overflow: int = 2
    # Embeddings: open-source Qwen3-Embedding-0.6B through the Cloudflare Worker's /embed route (same
    # Worker URL + shared secret as illustrations). See app/providers/embeddings.py.
    ocr_languages: str = "eng+hin+pan+tel"
    supabase_url: AnyHttpUrl | None = Field(
        default=None, validation_alias="NEXT_PUBLIC_SUPABASE_URL"
    )
    supabase_service_role_key: str | None = Field(
        default=None, validation_alias="SUPABASE_SERVICE_ROLE_KEY", repr=False
    )
    supabase_jwt_issuer: str | None = None
    supabase_jwt_audience: str = "authenticated"
    supabase_jwks_url: AnyHttpUrl | None = None
    app_signing_secret: str | None = Field(default=None, repr=False)
    groq_api_key: str | None = Field(default=None, repr=False)
    # Fast model: topic proposal, segmentation, mapping, translation, explain, plan wording.
    groq_model: str | None = None
    # Quality model: quiz generation and short-answer evaluation.
    groq_model_quality: str | None = None
    groq_timeout_seconds: float = 90.0
    groq_max_completion_tokens: int = 16_384
    # Total time one call may spend waiting out tokens-per-minute limits before failing.
    groq_rate_limit_wait_seconds: float = 180.0
    # Voice for Explain only: TTS eleven_v3 lists hi/pa/te; STT scribe_v2.
    elevenlabs_api_key: str | None = Field(default=None, repr=False)
    elevenlabs_voice_id: str | None = None
    elevenlabs_model_id: str = "eleven_v3"
    elevenlabs_stt_model_id: str = "scribe_v2"
    elevenlabs_base_url: str = "https://api.elevenlabs.io"
    # The Cloudflare Worker (HMAC-signed): illustrations at "/", embeddings at "/embed". Required:
    # without it documents cannot be embedded.
    cloudflare_image_worker_url: str | None = None
    cloudflare_image_worker_shared_secret: str | None = Field(default=None, repr=False)

    @field_validator("database_url")
    @classmethod
    def use_psycopg3_driver(cls, value: str) -> str:
        """Supabase hands out `postgresql://` URLs; this project ships psycopg 3 only."""
        for prefix in ("postgresql://", "postgres://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value.removeprefix(prefix)
        return value

    @field_validator("elevenlabs_model_id", "elevenlabs_stt_model_id", mode="before")
    @classmethod
    def blank_model_uses_default(cls, value: object, info: Any) -> object:
        """`ELEVENLABS_MODEL_ID=` (blank in .env) means "use the documented default", not ""."""
        if value is None or (isinstance(value, str) and not value.strip()):
            return cls.model_fields[info.field_name].default
        return value

    @model_validator(mode="after")
    def jwt_pair_is_complete(self) -> "Settings":
        if bool(self.supabase_jwt_issuer) != bool(self.supabase_jwks_url):
            raise ValueError("SUPABASE_JWT_ISSUER and SUPABASE_JWKS_URL must be set together")
        return self

    @property
    def groq_configured(self) -> bool:
        return bool(self.groq_api_key and self.groq_model)

    @property
    def voice_configured(self) -> bool:
        return bool(self.elevenlabs_api_key and self.elevenlabs_voice_id)

    @property
    def visual_configured(self) -> bool:
        return bool(self.cloudflare_image_worker_url and self.cloudflare_image_worker_shared_secret)

    @property
    def quality_model(self) -> str | None:
        return self.groq_model_quality or self.groq_model

    @property
    def storage_api_url(self) -> str:
        if not self.supabase_url:
            raise RuntimeError("NEXT_PUBLIC_SUPABASE_URL is not configured")
        return f"{str(self.supabase_url).rstrip('/')}/storage/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
