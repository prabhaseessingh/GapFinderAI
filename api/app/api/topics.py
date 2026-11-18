import hashlib
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_optional_groq, get_session, require_groq_configured
from app.core.auth import Actor, require_actor
from app.core.config import Settings
from app.core.errors import AppError, not_found, provider_unavailable
from app.db.models import Document
from app.providers.groq import GroqProvider
from app.schemas.shared import Locale
from app.schemas.topics import (
    CitationOut,
    CreateTopicRequest,
    JobStatusOut,
    PastPaperQuestionOut,
    TopicOut,
    UpdateTopicRequest,
)
from app.services.jobs import (
    MAP_PAST_PAPERS,
    PROPOSE_TOPIC_MAP,
    SEGMENT_PAST_PAPER,
    QueueUnavailable,
    enqueue,
    latest_job,
)
from app.services.past_papers import list_questions
from app.services.retrieval import retrieve_syllabus_evidence
from app.services.topics import (
    approve_all,
    create_topic,
    delete_topic,
    ensure_approved_topics,
    list_topic_citations,
    list_topics,
    require_topic_owner,
    set_topic_status,
    update_topic,
)
from app.services.translation import translate_citations
from app.services.workspaces import require_workspace_owner

router = APIRouter(prefix="/topics", tags=["topics"])
JobName = Literal["propose", "map_past_papers", "segment_past_paper"]
_JOB_TASKS: dict[str, str] = {
    "propose": PROPOSE_TOPIC_MAP,
    "map_past_papers": MAP_PAST_PAPERS,
    "segment_past_paper": SEGMENT_PAST_PAPER,
}


def _owned(session: Session, actor: Actor, workspace_id: UUID) -> None:
    try:
        require_workspace_owner(session, actor.user_id, workspace_id)
    except LookupError as error:
        raise not_found("Workspace") from error


def _role_version_key(session: Session, workspace_id: UUID, role: str) -> str:
    """Idempotency key = workspace + exact set of ready document versions of a role."""
    rows = session.execute(
        select(Document.id, Document.version)
        .where(
            Document.workspace_id == workspace_id,
            Document.material_role == role,
            Document.state == "ready",
        )
        .order_by(Document.id)
    ).all()
    digest = hashlib.sha256("|".join(f"{i}:{v}" for i, v in rows).encode()).hexdigest()[:16]
    return f"{workspace_id}:{digest}"


@router.get("/workspace/{workspace_id}", response_model=list[TopicOut])
def topics_for_workspace(
    workspace_id: UUID,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
) -> list[TopicOut]:
    try:
        return list_topics(session, actor.user_id, workspace_id)
    except LookupError as error:
        raise not_found("Workspace") from error


@router.post(
    "/workspace/{workspace_id}/propose",
    response_model=JobStatusOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def propose_workspace_topics(
    workspace_id: UUID,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
    settings: Settings = Depends(require_groq_configured),
) -> JobStatusOut:
    _owned(session, actor, workspace_id)
    if not retrieve_syllabus_evidence(session, actor.user_id, workspace_id):
        raise AppError(
            409,
            "INSUFFICIENT_WORKSPACE_EVIDENCE",
            "Upload a syllabus and wait until it is ready before proposing a topic map.",
            next_action="upload_or_select_material",
        )
    try:
        enqueue(
            session,
            settings.redis_url,
            task_name=PROPOSE_TOPIC_MAP,
            idempotency_key=_role_version_key(session, workspace_id, "syllabus"),
            args=[str(workspace_id)],
            student_id=actor.user_id,
            workspace_id=workspace_id,
        )
    except QueueUnavailable as error:
        raise provider_unavailable(
            "The background worker is unavailable. Try again shortly."
        ) from error
    return job_status(workspace_id, "propose", actor, session)


@router.post(
    "/workspace/{workspace_id}/map-past-papers",
    response_model=JobStatusOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def map_workspace_past_papers(
    workspace_id: UUID,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
    settings: Settings = Depends(require_groq_configured),
) -> JobStatusOut:
    _owned(session, actor, workspace_id)
    approved = sorted(str(t.id) for t in ensure_approved_topics(session, workspace_id))
    key = (
        _role_version_key(session, workspace_id, "past_paper")
        + ":"
        + hashlib.sha256(",".join(approved).encode()).hexdigest()[:12]
    )
    try:
        enqueue(
            session,
            settings.redis_url,
            task_name=MAP_PAST_PAPERS,
            idempotency_key=key,
            args=[str(workspace_id)],
            student_id=actor.user_id,
            workspace_id=workspace_id,
        )
    except QueueUnavailable as error:
        raise provider_unavailable(
            "The background worker is unavailable. Try again shortly."
        ) from error
    return job_status(workspace_id, "map_past_papers", actor, session)


@router.get("/workspace/{workspace_id}/jobs/{job}", response_model=JobStatusOut)
def job_status(
    workspace_id: UUID,
    job: JobName,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
) -> JobStatusOut:
    _owned(session, actor, workspace_id)
    run = latest_job(session, workspace_id, _JOB_TASKS[job])
    if run is None:
        return JobStatusOut(task=job, state="none")
    return JobStatusOut(
        task=job,
        state=run.state,  # type: ignore[arg-type]
        error_code=run.error_code,
        updated_at=run.updated_at.isoformat(),
        result=run.result or {},
    )


@router.post("/workspace/{workspace_id}/approve-all")
def approve_all_topics(
    workspace_id: UUID,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
) -> dict[str, int]:
    _owned(session, actor, workspace_id)
    return {"approved": approve_all(session, actor.user_id, workspace_id)}


@router.get(
    "/workspace/{workspace_id}/past-paper-questions", response_model=list[PastPaperQuestionOut]
)
def past_paper_questions(
    workspace_id: UUID,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
) -> list[PastPaperQuestionOut]:
    _owned(session, actor, workspace_id)
    return list_questions(session, actor.user_id, workspace_id)


@router.post("", response_model=TopicOut, status_code=status.HTTP_201_CREATED)
def create_manual_topic(
    request: CreateTopicRequest,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
) -> TopicOut:
    _owned(session, actor, request.workspace_id)
    return create_topic(session, actor.user_id, request)


@router.patch("/{topic_id}", response_model=TopicOut)
def edit_topic(
    topic_id: UUID,
    request: UpdateTopicRequest,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
) -> TopicOut:
    return update_topic(session, actor.user_id, topic_id, request)


@router.post("/{topic_id}/approve", response_model=TopicOut)
def approve(
    topic_id: UUID, actor: Actor = Depends(require_actor), session: Session = Depends(get_session)
) -> TopicOut:
    return set_topic_status(session, actor.user_id, topic_id, "approved")


@router.post("/{topic_id}/unapprove", response_model=TopicOut)
def unapprove(
    topic_id: UUID, actor: Actor = Depends(require_actor), session: Session = Depends(get_session)
) -> TopicOut:
    return set_topic_status(session, actor.user_id, topic_id, "draft")


@router.get("/{topic_id}/citations", response_model=list[CitationOut])
def citations_for_topic(
    topic_id: UUID,
    locale: Locale = "en",
    translate: bool = True,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
    groq: GroqProvider | None = Depends(get_optional_groq),
) -> list[CitationOut]:
    topic = require_topic_owner(session, actor.user_id, topic_id)
    citations = list_topic_citations(session, actor.user_id, topic_id)
    if not translate:  # originals only: instant, never waits on the provider
        return citations
    return translate_citations(session, groq, actor.user_id, topic.workspace_id, citations, locale)


@router.delete("/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_topic(
    topic_id: UUID, actor: Actor = Depends(require_actor), session: Session = Depends(get_session)
) -> Response:
    delete_topic(session, actor.user_id, topic_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
