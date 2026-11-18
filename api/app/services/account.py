"""Immediate, irreversible account deletion.

Order: (1) remove every stored file (materials + generated assets) — on failure nothing else is
touched; (2) delete the Supabase auth user, which cascades profile -> workspaces -> every derived
row (documents, chunks, topics, quizzes, reports, plans, explanations, assets, audit/ai runs);
(3) if the auth service is unreachable, delete the profile row directly so no study data remains,
and report the account record as still pending so the student can retry.
"""

import logging
from typing import Protocol
from uuid import UUID

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Document, GeneratedAsset, Profile
from app.services.storage import ASSET_BUCKET, SupabaseStorage

logger = logging.getLogger("gapfinder.account")


class AuthAdmin(Protocol):
    def delete_user(self, user_id: UUID) -> None: ...


class SupabaseAuthAdmin:
    def __init__(self, settings: Settings) -> None:
        if not settings.supabase_service_role_key or not settings.supabase_url:
            raise RuntimeError("Supabase admin access is not configured")
        self._url = f"{str(settings.supabase_url).rstrip('/')}/auth/v1/admin/users"
        self._headers = {
            "authorization": f"Bearer {settings.supabase_service_role_key}",
            "apikey": settings.supabase_service_role_key,
        }

    def delete_user(self, user_id: UUID) -> None:
        response = httpx.delete(f"{self._url}/{user_id}", headers=self._headers, timeout=20)
        if response.status_code not in (200, 204, 404):  # 404: already gone
            response.raise_for_status()


class AccountDeletionIncomplete(RuntimeError):
    """Study data is gone, but the sign-in record could not be removed yet."""


def storage_paths(session: Session, student_id: UUID) -> tuple[list[str], list[str]]:
    materials = list(
        session.scalars(select(Document.storage_key).where(Document.student_id == student_id))
    )
    assets = [
        p
        for p in session.scalars(
            select(GeneratedAsset.storage_path).where(
                GeneratedAsset.student_id == student_id, GeneratedAsset.storage_path.is_not(None)
            )
        )
        if p
    ]
    return materials, assets


async def delete_account(
    session: Session, student_id: UUID, storage: SupabaseStorage, admin: AuthAdmin | None
) -> dict[str, int]:
    materials, assets = storage_paths(session, student_id)
    if materials:
        await storage.delete_many(materials)
    if assets:
        await storage.delete_many(assets, bucket=ASSET_BUCKET)
    session.rollback()  # release the read snapshot before the cascade
    try:
        if admin is None:
            raise RuntimeError("admin unavailable")
        admin.delete_user(student_id)
    except Exception as error:
        logger.warning("Auth user deletion failed for %s; deleting study data directly", student_id)
        session.execute(delete(Profile).where(Profile.id == student_id))
        session.commit()
        raise AccountDeletionIncomplete() from error
    # The auth cascade removes the profile in Supabase. Locally (stub auth schema) and as a safety
    # net, make sure no profile row survives.
    session.execute(delete(Profile).where(Profile.id == student_id))
    session.commit()
    return {"files": len(materials), "assets": len(assets)}
