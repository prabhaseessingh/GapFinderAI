from collections.abc import Iterator
from functools import lru_cache
from typing import TYPE_CHECKING

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AppError, provider_unavailable
from app.core.fair_use import FairUse, MemoryCounter, RedisCounter
from app.db.session import SessionLocal
from app.providers.groq import GroqNotConfigured, GroqProvider
from app.services.storage import SupabaseStorage

if TYPE_CHECKING:
    from app.services.account import SupabaseAuthAdmin


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def get_storage(settings: Settings = Depends(get_settings)) -> SupabaseStorage:
    try:
        return SupabaseStorage(settings)
    except RuntimeError as error:
        raise provider_unavailable("File storage is not configured.") from error


def get_optional_storage(settings: Settings = Depends(get_settings)) -> SupabaseStorage | None:
    try:
        return SupabaseStorage(settings)
    except RuntimeError:
        return None


@lru_cache
def _fair_use(redis_url: str) -> FairUse:
    if not redis_url:  # no Redis configured: per-process counters (reset on restart)
        return FairUse(MemoryCounter())
    return FairUse(RedisCounter(redis_url))


def get_fair_use(settings: Settings = Depends(get_settings)) -> FairUse:
    return _fair_use(settings.redis_url)


def get_auth_admin(settings: Settings = Depends(get_settings)) -> "SupabaseAuthAdmin | None":
    from app.services.account import SupabaseAuthAdmin

    try:
        return SupabaseAuthAdmin(settings)
    except RuntimeError:
        return None


def get_optional_groq(settings: Settings = Depends(get_settings)) -> GroqProvider | None:
    try:
        return GroqProvider(settings)
    except GroqNotConfigured:
        return None


def require_groq_configured(settings: Settings = Depends(get_settings)) -> Settings:
    if not settings.groq_configured:
        raise AppError(
            503, "PROVIDER_UNAVAILABLE", "AI features are not configured on this server."
        )
    return settings
