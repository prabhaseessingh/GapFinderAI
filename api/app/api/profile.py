from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_auth_admin, get_session, get_storage
from app.core.auth import Actor, require_actor
from app.core.errors import AppError, provider_unavailable
from app.db.models import Profile
from app.schemas.profile import PRIVACY_POLICY_VERSION, ProfileOut, UpdateProfileRequest
from app.services.account import AccountDeletionIncomplete, AuthAdmin, delete_account
from app.services.jobs import audit
from app.services.storage import SupabaseStorage
from app.services.workspaces import ensure_profile

router = APIRouter(prefix="/profile", tags=["profile"])


def _load(session: Session, actor: Actor) -> Profile:
    ensure_profile(session, actor.user_id)
    profile = session.get(Profile, actor.user_id)
    assert profile is not None
    # Acceptance ticked on the signup form arrives via Supabase user metadata.
    if (
        profile.privacy_policy_version != PRIVACY_POLICY_VERSION
        and actor.signup_privacy_version == PRIVACY_POLICY_VERSION
    ):
        _accept(session, actor, profile)
    session.commit()
    return profile


def _accept(session: Session, actor: Actor, profile: Profile) -> None:
    profile.privacy_policy_version = PRIVACY_POLICY_VERSION
    profile.privacy_accepted_at = func.now()
    audit(
        session,
        action="privacy.accept",
        resource_type="profile",
        student_id=actor.user_id,
        resource_id=actor.user_id,
        metadata={"version": PRIVACY_POLICY_VERSION},
    )


def _out(session: Session, profile: Profile) -> ProfileOut:
    session.refresh(profile)
    return ProfileOut.model_validate(profile, from_attributes=True)


@router.get("", response_model=ProfileOut)
def get_profile(
    actor: Actor = Depends(require_actor), session: Session = Depends(get_session)
) -> ProfileOut:
    return _out(session, _load(session, actor))


@router.patch("", response_model=ProfileOut)
def update_profile(
    request: UpdateProfileRequest,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
) -> ProfileOut:
    profile = _load(session, actor)
    if request.accept_privacy_policy_version is not None:
        if request.accept_privacy_policy_version != PRIVACY_POLICY_VERSION:
            raise AppError(409, "INVALID_STATE", "Please accept the current Privacy Policy.")
        _accept(session, actor, profile)
    if request.display_name is not None:
        profile.display_name = request.display_name.strip() or None
    if request.selected_locale is not None:
        profile.selected_locale = request.selected_locale
    if request.timezone is not None:
        profile.timezone = request.timezone
    session.commit()
    return _out(session, profile)


class DeleteAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: Literal["DELETE"]


@router.post("/delete-account", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_account(
    request: DeleteAccountRequest,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
    storage: SupabaseStorage = Depends(get_storage),
    admin: AuthAdmin | None = Depends(get_auth_admin),
) -> Response:
    """Immediate and irreversible: files first, then the account and every derived record."""
    try:
        await delete_account(session, actor.user_id, storage, admin)
    except httpx.HTTPError as error:
        raise provider_unavailable(
            "Files could not be deleted right now; nothing was removed."
        ) from error
    except AccountDeletionIncomplete as error:
        raise AppError(
            503,
            "PROVIDER_UNAVAILABLE",
            "Your study data was deleted, but the sign-in record could not be removed yet. Try again.",
            retryable=True,
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
