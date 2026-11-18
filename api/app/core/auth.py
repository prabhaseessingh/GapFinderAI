from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

import httpx
import jwt
from fastapi import Depends, Request

from app.core.config import Settings, get_settings
from app.core.errors import AppError


@dataclass(frozen=True)
class Actor:
    user_id: UUID
    # Privacy-policy version the student accepted at signup (Supabase user_metadata), if any.
    signup_privacy_version: str | None = None


@lru_cache(maxsize=4)
def _jwks(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)


def _unauthenticated(message: str) -> AppError:
    return AppError(401, "UNAUTHENTICATED", message, next_action="sign_in")


def verify_supabase_jwt(token: str, settings: Settings) -> Actor:
    """Identity comes only from a verified Supabase access token."""
    try:
        key = _jwks(str(settings.supabase_jwks_url)).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=["ES256", "RS256"],
            audience=settings.supabase_jwt_audience,
            issuer=settings.supabase_jwt_issuer,
            options={"require": ["exp", "sub", "iss", "aud"]},
        )
        metadata = claims.get("user_metadata") or {}
        version = metadata.get("privacy_policy_version") if isinstance(metadata, dict) else None
        return Actor(
            user_id=UUID(str(claims["sub"])),
            signup_privacy_version=version if isinstance(version, str) else None,
        )
    except (jwt.PyJWTError, ValueError, KeyError, httpx.HTTPError) as error:
        raise _unauthenticated(
            "Your session is invalid or has expired. Please sign in again."
        ) from error


async def require_actor(request: Request, settings: Settings = Depends(get_settings)) -> Actor:
    if not settings.supabase_jwks_url or not settings.supabase_jwt_issuer:
        raise AppError(503, "PROVIDER_UNAVAILABLE", "Authentication is not configured.")
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise _unauthenticated("Sign in is required.")
    return verify_supabase_jwt(header.removeprefix("Bearer "), settings)
