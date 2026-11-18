"""Explain jobs: grounded answer, voice audio, AI illustration. Every terminal state is visible;
a voice or visual failure never touches the written, cited answer."""

import logging
from typing import Any
from uuid import UUID

from app.core.config import get_settings
from app.db.models import Explanation, GeneratedAsset
from app.db.session import SessionLocal
from app.providers.elevenlabs import ElevenLabsProvider, VoiceNotConfigured
from app.providers.groq import GroqNotConfigured, GroqProvider
from app.providers.image_worker import ImageWorkerClient, VisualNotConfigured
from app.services.explain import render_audio as run_audio
from app.services.explain import render_visual as run_visual
from app.services.explain import run_explanation
from app.services.jobs import EXPLAIN, RENDER_AUDIO, RENDER_VISUAL
from app.services.storage import SupabaseStorage
from sqlalchemy import func, update
from tasks.common import advisory_lock, bind_correlation, job_done, job_running
from tasks.ingest import embed_query

from worker.app import celery_app

logger = logging.getLogger("gapfinder.explain")


def _fail_explanation(explanation_id: str) -> Any:
    return lambda session: session.execute(
        update(Explanation)
        .where(
            Explanation.id == UUID(explanation_id),
            Explanation.state.in_(["queued", "running"]),
        )
        .values(state="failed", failure_code="EXPLAIN_ERROR", updated_at=func.now())
    )


def _fail_asset(asset_id: str) -> Any:
    return lambda session: session.execute(
        update(GeneratedAsset)
        .where(
            GeneratedAsset.id == UUID(asset_id),
            GeneratedAsset.state.in_(["queued", "rendering"]),
        )
        .values(state="failed", failure_code="RENDER_ERROR", updated_at=func.now())
    )


def _groq() -> GroqProvider | None:
    try:
        return GroqProvider(get_settings())
    except GroqNotConfigured:
        return None


def _storage() -> SupabaseStorage | None:
    try:
        return SupabaseStorage(get_settings())
    except RuntimeError:
        return None


def _run(task: Any, name: str, key: str, work: Any, on_crash: Any) -> str:
    bind_correlation(task)
    with SessionLocal() as session, advisory_lock(session, f"{name}:{key}") as acquired:
        if not acquired:
            return "busy"
        job_running(session, name, key)
        try:
            state = str(work(session))
        except Exception:
            session.rollback()
            logger.exception("%s crashed for %s", name, key)
            on_crash(session)
            session.commit()
            state = "failed"
        ok = state in {"answered", "insufficient", "ready", "not_eligible"}
        job_done(
            session,
            name,
            key,
            "succeeded" if ok else "failed",
            None if ok else state[:80],
            result={"state": state},
        )
        return state


@celery_app.task(name=EXPLAIN, bind=True, acks_late=True)
def explain(self: Any, explanation_id: str, job_key: str | None = None) -> str:
    return _run(
        self,
        EXPLAIN,
        job_key or explanation_id,
        lambda session: run_explanation(
            session, _groq(), UUID(explanation_id), embed_query
        ),
        _fail_explanation(explanation_id),
    )


@celery_app.task(name=RENDER_AUDIO, bind=True, acks_late=True)
def render_audio(self: Any, asset_id: str, job_key: str | None = None) -> str:
    def work(session: Any) -> str:
        try:
            voice: ElevenLabsProvider | None = ElevenLabsProvider(get_settings())
        except VoiceNotConfigured:
            voice = None
        return run_audio(session, voice, _storage(), UUID(asset_id))

    return _run(self, RENDER_AUDIO, job_key or asset_id, work, _fail_asset(asset_id))


@celery_app.task(name=RENDER_VISUAL, bind=True, acks_late=True)
def render_visual(self: Any, asset_id: str, job_key: str | None = None) -> str:
    def work(session: Any) -> str:
        try:
            image: ImageWorkerClient | None = ImageWorkerClient(get_settings())
        except VisualNotConfigured:
            image = None
        return run_visual(session, _groq(), image, _storage(), UUID(asset_id))

    return _run(self, RENDER_VISUAL, job_key or asset_id, work, _fail_asset(asset_id))
