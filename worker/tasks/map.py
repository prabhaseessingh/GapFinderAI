"""Topic proposal, past-paper segmentation and mapping jobs. All failures are visible in job_runs."""

import logging
from typing import Any
from uuid import UUID

from app.core.config import get_settings
from app.db.models import Document, Topic, Workspace
from app.db.session import SessionLocal
from app.providers.groq import (
    GroqDailyLimit,
    GroqNotConfigured,
    GroqOutputRejected,
    GroqProvider,
)
from app.services.jobs import MAP_PAST_PAPERS, PROPOSE_TOPIC_MAP, SEGMENT_PAST_PAPER
from app.services.past_papers import map_questions_to_topics, segment_document
from app.services.topic_proposal import InsufficientSyllabusEvidence
from app.services.topic_proposal import propose_topic_map as propose
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from tasks.common import advisory_lock, bind_correlation, job_done, job_running

from worker.app import celery_app

logger = logging.getLogger("gapfinder.map")


def _finish_mapping(
    session: Session, workspace_id: UUID, role: str, document_id: UUID | None = None
) -> None:
    """Documents leave the `mapping` state whether or not the AI step succeeded."""
    query = update(Document).where(
        Document.workspace_id == workspace_id,
        Document.material_role == role,
        Document.state == "mapping",
    )
    if document_id is not None:
        query = query.where(Document.id == document_id)
    session.execute(query.values(state="ready", updated_at=func.now()))
    session.commit()


def _error_code(error: Exception) -> str:
    if isinstance(error, GroqOutputRejected):
        return f"AI_OUTPUT_REJECTED:{error.code}"[:80]
    if isinstance(error, InsufficientSyllabusEvidence):
        return "INSUFFICIENT_WORKSPACE_EVIDENCE"
    if isinstance(error, GroqNotConfigured):
        return "GROQ_NOT_CONFIGURED"
    if isinstance(error, GroqDailyLimit):
        return GroqDailyLimit.code
    name = type(error).__name__
    if name in {
        "RateLimitError",
        "APIConnectionError",
        "APITimeoutError",
        "InternalServerError",
    }:
        return "PROVIDER_UNAVAILABLE"
    return "MAPPING_ERROR"


@celery_app.task(name=PROPOSE_TOPIC_MAP, bind=True, acks_late=True)
def propose_topic_map(
    self: Any, workspace_id: str, document_id: str = "", job_key: str | None = None
) -> str:
    bind_correlation(self)
    key = job_key or workspace_id
    with SessionLocal() as session:
        workspace = session.get(Workspace, UUID(workspace_id))
        if not workspace:
            return "missing"
        with advisory_lock(session, f"topics:{workspace_id}") as acquired:
            if not acquired:
                job_done(session, PROPOSE_TOPIC_MAP, key, "failed", "ALREADY_RUNNING")
                return "busy"
            job_running(session, PROPOSE_TOPIC_MAP, key)
            try:
                created = propose(
                    session,
                    GroqProvider(get_settings()),
                    workspace.student_id,
                    workspace.id,
                )
                job_done(
                    session,
                    PROPOSE_TOPIC_MAP,
                    key,
                    "succeeded",
                    result={"created": created},
                )
                return "succeeded"
            except Exception as error:  # noqa: BLE001
                session.rollback()
                logger.warning(
                    "Topic proposal failed for %s: %s",
                    workspace_id,
                    type(error).__name__,
                )
                job_done(session, PROPOSE_TOPIC_MAP, key, "failed", _error_code(error))
                return "failed"
            finally:
                _finish_mapping(
                    session,
                    workspace.id,
                    "syllabus",
                    UUID(document_id) if document_id else None,
                )


@celery_app.task(name=SEGMENT_PAST_PAPER, bind=True, acks_late=True)
def segment_past_paper(self: Any, document_id: str, job_key: str | None = None) -> str:
    bind_correlation(self)
    key = job_key or document_id
    with SessionLocal() as session:
        document = session.get(Document, UUID(document_id))
        if not document:
            return "missing"
        with advisory_lock(session, f"pastpaper:{document.workspace_id}") as acquired:
            if not acquired:
                self.retry(countdown=15, max_retries=8)
            job_running(session, SEGMENT_PAST_PAPER, key)
            try:
                provider = GroqProvider(get_settings())
                questions = segment_document(
                    session,
                    provider,
                    document.student_id,
                    document.workspace_id,
                    document.id,
                )
                mapped = 0
                has_approved = session.scalar(
                    select(func.count()).where(
                        Topic.workspace_id == document.workspace_id,
                        Topic.status == "approved",
                    )
                )
                if questions and has_approved:
                    mapped = map_questions_to_topics(
                        session, provider, document.student_id, document.workspace_id
                    )
                session.commit()
                job_done(
                    session,
                    SEGMENT_PAST_PAPER,
                    key,
                    "succeeded",
                    result={"questions": questions, "mapped_links": mapped},
                )
                return "succeeded"
            except Exception as error:  # noqa: BLE001
                session.rollback()
                logger.warning(
                    "Segmentation failed for %s: %s", document_id, type(error).__name__
                )
                job_done(session, SEGMENT_PAST_PAPER, key, "failed", _error_code(error))
                return "failed"
            finally:
                _finish_mapping(
                    session, document.workspace_id, "past_paper", document.id
                )


@celery_app.task(name=MAP_PAST_PAPERS, bind=True, acks_late=True)
def map_past_papers(self: Any, workspace_id: str, job_key: str | None = None) -> str:
    bind_correlation(self)
    key = job_key or workspace_id
    with SessionLocal() as session:
        workspace = session.get(Workspace, UUID(workspace_id))
        if not workspace:
            return "missing"
        with advisory_lock(session, f"pastpaper:{workspace_id}") as acquired:
            if not acquired:
                job_done(session, MAP_PAST_PAPERS, key, "failed", "ALREADY_RUNNING")
                return "busy"
            job_running(session, MAP_PAST_PAPERS, key)
            try:
                links = map_questions_to_topics(
                    session,
                    GroqProvider(get_settings()),
                    workspace.student_id,
                    workspace.id,
                )
                session.commit()
                job_done(
                    session, MAP_PAST_PAPERS, key, "succeeded", result={"links": links}
                )
                return "succeeded"
            except Exception as error:  # noqa: BLE001
                session.rollback()
                job_done(session, MAP_PAST_PAPERS, key, "failed", _error_code(error))
                return "failed"
