"""Routes: Explain, voice, assets, fair-use limits, provider status."""

import base64
import binascii
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_fair_use, get_optional_groq, get_optional_storage, get_session
from app.core.auth import Actor, require_actor
from app.core.config import Settings, get_settings
from app.core.errors import AppError, provider_unavailable
from app.core.fair_use import FairUse
from app.db.models import Profile
from app.providers.elevenlabs import (
    AUDIO_MIME_TYPES,
    ElevenLabsProvider,
    VoiceNotConfigured,
    VoiceProviderError,
    VoiceUnsupportedLanguage,
    voice_language,
)
from app.providers.groq import GroqProvider
from app.schemas.explain import (
    AssetOut,
    CreateExplanationRequest,
    ExplanationOut,
    ExplanationSummaryOut,
    LimitsOut,
    ProviderStatusOut,
    TranscribeOut,
    TranscribeRequest,
    UsageOut,
)
from app.schemas.shared import Locale
from app.services import explain
from app.services.jobs import EXPLAIN, RENDER_AUDIO, RENDER_VISUAL, QueueUnavailable, audit, enqueue
from app.services.storage import SupabaseStorage
from app.services.workspaces import require_workspace_owner

router = APIRouter(tags=["explain"])


def student_timezone(session: Session, student_id: UUID) -> str | None:
    return session.scalar(select(Profile.timezone).where(Profile.id == student_id))


def _enqueue_or_refund(
    session: Session,
    settings: Settings,
    fair_use: FairUse,
    actor: Actor,
    task: str,
    key: str,
    workspace_id: UUID,
    action: Literal["explain", "voice", "visual"] | None,
) -> None:
    try:
        enqueue(
            session,
            settings.redis_url,
            task_name=task,
            idempotency_key=key,
            args=[key],
            student_id=actor.user_id,
            workspace_id=workspace_id,
        )
    except QueueUnavailable as error:
        if action:
            fair_use.refund(actor.user_id, action, student_timezone(session, actor.user_id))
        raise provider_unavailable(
            "The background worker is unavailable. Try again shortly."
        ) from error


@router.post("/explanations", response_model=ExplanationOut, status_code=status.HTTP_202_ACCEPTED)
def create_explanation(
    request: CreateExplanationRequest,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    fair_use: FairUse = Depends(get_fair_use),
) -> ExplanationOut:
    if not settings.groq_configured:
        raise AppError(
            503, "PROVIDER_UNAVAILABLE", "AI features are not configured on this server."
        )
    explanation = explain.create_explanation(
        session, actor.user_id, request, fair_use, student_timezone(session, actor.user_id)
    )
    audit(
        session,
        action="explanation.create",
        resource_type="explanation",
        student_id=actor.user_id,
        workspace_id=explanation.workspace_id,
        resource_id=explanation.id,
        metadata={"origin": request.origin},
    )
    session.commit()
    _enqueue_or_refund(
        session,
        settings,
        fair_use,
        actor,
        EXPLAIN,
        str(explanation.id),
        explanation.workspace_id,
        "explain",
    )
    return explain.explanation_out(session, explanation, settings)


@router.get("/explanations/workspace/{workspace_id}", response_model=list[ExplanationSummaryOut])
def list_explanations(
    workspace_id: UUID,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
) -> list[ExplanationSummaryOut]:
    return explain.list_explanations(session, actor.user_id, workspace_id)


@router.get("/explanations/{explanation_id}", response_model=ExplanationOut)
def get_explanation(
    explanation_id: UUID,
    locale: Locale | None = Query(default=None),
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    groq: GroqProvider | None = Depends(get_optional_groq),
) -> ExplanationOut:
    explanation = explain.require_explanation(session, actor.user_id, explanation_id)
    return explain.explanation_out(session, explanation, settings, groq, locale)


@router.post(
    "/explanations/{explanation_id}/audio",
    response_model=AssetOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_audio(
    explanation_id: UUID,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    fair_use: FairUse = Depends(get_fair_use),
) -> AssetOut:
    asset, render = explain.request_audio(
        session,
        actor.user_id,
        explanation_id,
        settings,
        fair_use,
        student_timezone(session, actor.user_id),
    )
    session.commit()
    if render:
        _enqueue_or_refund(
            session,
            settings,
            fair_use,
            actor,
            RENDER_AUDIO,
            str(asset.id),
            asset.workspace_id,
            "voice",
        )
    return explain.asset_out(asset)


@router.post(
    "/explanations/{explanation_id}/visual",
    response_model=AssetOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_visual(
    explanation_id: UUID,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    fair_use: FairUse = Depends(get_fair_use),
) -> AssetOut:
    asset, render = explain.request_visual(
        session,
        actor.user_id,
        explanation_id,
        settings,
        fair_use,
        student_timezone(session, actor.user_id),
    )
    session.commit()
    if render:
        _enqueue_or_refund(
            session,
            settings,
            fair_use,
            actor,
            RENDER_VISUAL,
            str(asset.id),
            asset.workspace_id,
            "visual",
        )
    return explain.asset_out(asset)


@router.get("/assets/{asset_id}", response_model=AssetOut)
async def get_asset(
    asset_id: UUID,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
    storage: SupabaseStorage | None = Depends(get_optional_storage),
) -> AssetOut:
    return await explain.asset_with_url(session, actor.user_id, asset_id, storage)


@router.post("/voice/transcribe", response_model=TranscribeOut)
def transcribe(
    request: TranscribeRequest,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    fair_use: FairUse = Depends(get_fair_use),
) -> TranscribeOut:
    try:
        require_workspace_owner(session, actor.user_id, request.workspace_id)
    except LookupError as error:
        raise AppError(404, "NOT_FOUND", "Workspace not found.") from error
    mime = request.mime_type.split(";")[0].strip().lower()
    if mime not in AUDIO_MIME_TYPES:
        raise AppError(422, "VALIDATION_ERROR", "Unsupported audio format.")
    try:
        audio = base64.b64decode(request.audio_base64, validate=True)
    except (binascii.Error, ValueError) as error:
        raise AppError(422, "VALIDATION_ERROR", "The recording could not be read.") from error
    try:
        provider = ElevenLabsProvider(settings)
        voice_language(request.locale)
    except VoiceNotConfigured as error:
        raise AppError(409, "INVALID_STATE", "Voice is not configured on this server.") from error
    except VoiceUnsupportedLanguage as error:
        raise AppError(
            409, "INVALID_STATE", "Voice is not available in this language yet."
        ) from error
    fair_use.consume(actor.user_id, "voice", student_timezone(session, actor.user_id))
    try:
        text = provider.transcribe(audio, mime, request.locale)
    except VoiceProviderError as error:
        if error.code == "NO_SPEECH_DETECTED":
            raise AppError(
                422, "VALIDATION_ERROR", "No speech was detected. Please try again."
            ) from error
        raise provider_unavailable(
            "The voice service is unavailable right now. Type your question instead."
        ) from error
    audit(
        session,
        action="voice.transcribe",
        resource_type="workspace",
        student_id=actor.user_id,
        workspace_id=request.workspace_id,
        metadata={"bytes": len(audio), "locale": request.locale},
    )
    session.commit()
    return TranscribeOut(text=text)


@router.get("/limits", response_model=LimitsOut)
def limits(
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
    fair_use: FairUse = Depends(get_fair_use),
) -> LimitsOut:
    timezone = student_timezone(session, actor.user_id)
    return LimitsOut(
        timezone=timezone or "UTC",
        actions=[
            UsageOut(action=u.action, used=u.used, limit=u.limit, resets_at=u.resets_at)
            for u in fair_use.usage(actor.user_id, timezone)
        ],
    )


@router.get("/health/providers", response_model=ProviderStatusOut)
def provider_status(settings: Settings = Depends(get_settings)) -> ProviderStatusOut:
    """Booleans only — never configuration values."""
    return ProviderStatusOut(
        groq=settings.groq_configured,
        voice=settings.voice_configured,
        visual=settings.visual_configured,
    )
