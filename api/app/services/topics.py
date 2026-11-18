"""Topic map: cited proposal, student edits/approval, deterministic importance."""

from collections.abc import Iterable, Sequence
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError, invalid_state, not_found
from app.db.models import (
    Chunk,
    Document,
    PastPaperQuestion,
    PastPaperQuestionTopic,
    Topic,
    TopicChunkLink,
)
from app.schemas.topics import (
    CitationOut,
    CreateTopicRequest,
    ProposedTopic,
    TopicOut,
    TopicProposal,
    UpdateTopicRequest,
)
from app.services.importance_policy import MappedQuestion, compute_importance
from app.services.jobs import audit
from app.services.retrieval import EvidenceItem, quote_in_source
from app.services.workspaces import require_workspace_owner

# Characters of syllabus evidence per Groq proposal call (gpt-oss-20b has a 128k context).
PROPOSAL_BATCH_CHARS = 40_000


# ---- read model ---------------------------------------------------------------------------------


def _counts(session: Session, topic_ids: Sequence[UUID]) -> tuple[dict[UUID, int], dict[UUID, int]]:
    if not topic_ids:
        return {}, {}
    citations = dict(
        session.execute(
            select(TopicChunkLink.topic_id, func.count())
            .where(TopicChunkLink.topic_id.in_(topic_ids))
            .group_by(TopicChunkLink.topic_id)
        ).all()
    )
    questions = dict(
        session.execute(
            select(PastPaperQuestionTopic.topic_id, func.count())
            .where(PastPaperQuestionTopic.topic_id.in_(topic_ids))
            .group_by(PastPaperQuestionTopic.topic_id)
        ).all()
    )
    return citations, questions


def _out(topic: Topic, citations: dict[UUID, int], questions: dict[UUID, int]) -> TopicOut:
    return TopicOut.model_validate(
        {
            **{
                c: getattr(topic, c)
                for c in (
                    "id",
                    "workspace_id",
                    "parent_id",
                    "title",
                    "status",
                    "importance",
                    "importance_source",
                    "importance_basis",
                    "position",
                    "origin",
                )
            },
            "citation_count": citations.get(topic.id, 0),
            "past_paper_question_count": questions.get(topic.id, 0),
        }
    )


def topic_out(session: Session, topic: Topic) -> TopicOut:
    citations, questions = _counts(session, [topic.id])
    return _out(topic, citations, questions)


def list_topics(session: Session, student_id: UUID, workspace_id: UUID) -> list[TopicOut]:
    require_workspace_owner(session, student_id, workspace_id)
    topics = session.scalars(
        select(Topic)
        .where(Topic.workspace_id == workspace_id)
        .order_by(Topic.position, Topic.title)
    ).all()
    citations, questions = _counts(session, [t.id for t in topics])
    return [_out(topic, citations, questions) for topic in topics]


def require_topic_owner(session: Session, student_id: UUID, topic_id: UUID) -> Topic:
    topic = session.scalar(select(Topic).where(Topic.id == topic_id))
    if not topic:
        raise not_found("Topic")
    try:
        require_workspace_owner(session, student_id, topic.workspace_id)
    except LookupError as error:  # do not reveal that the id exists in another workspace
        raise not_found("Topic") from error
    return topic


# ---- proposal ------------------------------------------------------------------------------------


def batch_evidence(
    evidence: Sequence[EvidenceItem], budget: int = PROPOSAL_BATCH_CHARS
) -> list[list[EvidenceItem]]:
    batches: list[list[EvidenceItem]] = [[]]
    size = 0
    for item in evidence:
        if batches[-1] and size + len(item.original_quote) > budget:
            batches.append([])
            size = 0
        batches[-1].append(item)
        size += len(item.original_quote)
    return [batch for batch in batches if batch]


def validate_proposal(proposal: TopicProposal, evidence: Iterable[EvidenceItem]) -> None:
    """Every citation must quote supplied evidence; parents must be top-level proposal topics."""
    indexed = {item.chunk_id: item.original_quote for item in evidence}
    top_level = {t.title.casefold() for t in proposal.topics if not t.parent_title}
    for topic in proposal.topics:
        if topic.parent_title and topic.parent_title.casefold() not in top_level:
            raise ValueError("INVALID_TOPIC_PARENT")
        for citation in topic.citations:
            source = indexed.get(citation.chunk_id)
            if source is None or not quote_in_source(citation.quote, source):
                raise ValueError("INVALID_TOPIC_CITATION")


def merge_proposals(proposals: Sequence[TopicProposal]) -> TopicProposal:
    """Merge per-batch proposals; same-titled topics combine their citations (max 6)."""
    merged: dict[str, ProposedTopic] = {}
    for proposal in proposals:
        for topic in proposal.topics:
            key = topic.title.casefold()
            if key not in merged:
                merged[key] = topic.model_copy(deep=True)
                continue
            existing = merged[key]
            seen = {(c.chunk_id, c.quote) for c in existing.citations}
            extra = [c for c in topic.citations if (c.chunk_id, c.quote) not in seen]
            existing.citations = (existing.citations + extra)[:6]
            if existing.parent_title is None and topic.parent_title:
                existing.parent_title = topic.parent_title
    topics = list(merged.values())
    titles = {t.title.casefold() for t in topics if not t.parent_title}
    for topic in topics:  # a parent that only exists in another batch as a child becomes root
        if topic.parent_title and topic.parent_title.casefold() not in titles:
            topic.parent_title = None
    return TopicProposal(topics=topics)


def replace_draft_proposal(
    session: Session, workspace_id: UUID, proposal: TopicProposal, evidence: list[EvidenceItem]
) -> int:
    """Replace only untouched draft proposal topics.

    Approved and student-edited topics are never deleted or duplicated; their manual children
    survive (re-attached by title to the new proposal topic, otherwise promoted to top level).
    """
    validate_proposal(proposal, evidence)
    existing = session.scalars(select(Topic).where(Topic.workspace_id == workspace_id)).all()
    disposable = {t.id for t in existing if t.origin == "proposal" and t.status == "draft"}
    disposable_titles = {t.id: t.title.casefold() for t in existing if t.id in disposable}
    keep = {t.title.casefold(): t for t in existing if t.id not in disposable}
    orphans = [t for t in existing if t.id not in disposable and t.parent_id in disposable]
    old_parent_title = {
        child.id: disposable_titles[child.parent_id] for child in orphans if child.parent_id
    }
    for child in orphans:
        child.parent_id = None
    session.flush()
    session.execute(delete(Topic).where(Topic.id.in_(disposable)))

    position = (
        session.scalar(
            select(func.coalesce(func.max(Topic.position), -1) + 1).where(
                Topic.workspace_id == workspace_id
            )
        )
        or 0
    )
    by_title: dict[str, Topic] = dict(keep)
    created = 0
    ordered = sorted(proposal.topics, key=lambda t: t.parent_title is not None)
    for item in ordered:
        key = item.title.casefold()
        topic = by_title.get(key)
        if topic is None:
            parent = by_title.get(item.parent_title.casefold()) if item.parent_title else None
            if parent is not None and parent.parent_id is not None:
                parent = None  # keep the tree two levels deep
            topic = Topic(
                workspace_id=workspace_id,
                parent_id=parent.id if parent else None,
                title=item.title,
                position=position,
                origin="proposal",
            )
            position += 1
            session.add(topic)
            session.flush()
            by_title[key] = topic
            created += 1
        linked = set(
            session.scalars(
                select(TopicChunkLink.chunk_id).where(TopicChunkLink.topic_id == topic.id)
            )
        )
        for citation in item.citations:
            if citation.chunk_id in linked:
                continue
            linked.add(citation.chunk_id)
            session.add(
                TopicChunkLink(
                    topic_id=topic.id,
                    chunk_id=citation.chunk_id,
                    confidence=1.0,
                    method="proposal",
                    quote=citation.quote,
                )
            )
    for child in orphans:  # re-attach to the re-proposed parent of the same title, if any
        old_title = old_parent_title.get(child.id)
        if old_title and old_title in by_title and by_title[old_title].parent_id is None:
            child.parent_id = by_title[old_title].id
    recompute_importance(session, workspace_id)
    session.commit()
    return created


# ---- student edits --------------------------------------------------------------------------------


def _require_valid_parent(
    session: Session, topic: Topic | None, workspace_id: UUID, parent_id: UUID
) -> Topic:
    parent = session.scalar(
        select(Topic).where(Topic.id == parent_id, Topic.workspace_id == workspace_id)
    )
    if not parent:
        raise not_found("Parent topic")
    if topic is not None and parent.id == topic.id:
        raise invalid_state("A topic cannot be its own parent.")
    if parent.parent_id is not None:
        raise invalid_state("Topics can be nested only one level deep.")
    if topic is not None and session.scalar(
        select(func.count()).where(Topic.parent_id == topic.id)
    ):
        raise invalid_state("A topic with subtopics cannot become a subtopic.")
    return parent


def create_topic(session: Session, student_id: UUID, request: CreateTopicRequest) -> TopicOut:
    require_workspace_owner(session, student_id, request.workspace_id)
    if request.parent_id:
        _require_valid_parent(session, None, request.workspace_id, request.parent_id)
    position = session.scalar(
        select(func.coalesce(func.max(Topic.position), -1) + 1).where(
            Topic.workspace_id == request.workspace_id
        )
    )
    topic = Topic(
        workspace_id=request.workspace_id,
        parent_id=request.parent_id,
        title=request.title,
        position=position or 0,
        origin="manual",
    )
    session.add(topic)
    session.flush()
    recompute_importance(session, request.workspace_id)
    audit(
        session,
        action="topic.create",
        resource_type="topic",
        student_id=student_id,
        workspace_id=request.workspace_id,
        resource_id=topic.id,
    )
    session.commit()
    session.refresh(topic)
    return topic_out(session, topic)


def update_topic(
    session: Session, student_id: UUID, topic_id: UUID, request: UpdateTopicRequest
) -> TopicOut:
    topic = require_topic_owner(session, student_id, topic_id)
    if "parent_id" in request.model_fields_set:
        if request.parent_id is None:
            topic.parent_id = None
        else:
            topic.parent_id = _require_valid_parent(
                session, topic, topic.workspace_id, request.parent_id
            ).id
    if request.title is not None and request.title != topic.title:
        topic.title = request.title
        topic.origin = "manual"  # an edited proposal is the student's now; reruns keep it
    if request.importance is not None:
        topic.importance = request.importance
        topic.importance_source = "student"
    elif request.reset_importance:
        topic.importance_source = "default"
    topic.updated_at = func.now()
    session.flush()
    recompute_importance(session, topic.workspace_id)
    audit(
        session,
        action="topic.update",
        resource_type="topic",
        student_id=student_id,
        workspace_id=topic.workspace_id,
        resource_id=topic.id,
        metadata={"fields": sorted(request.model_fields_set)},
    )
    session.commit()
    session.refresh(topic)
    return topic_out(session, topic)


def set_topic_status(session: Session, student_id: UUID, topic_id: UUID, status: str) -> TopicOut:
    topic = require_topic_owner(session, student_id, topic_id)
    topic.status = status
    topic.updated_at = func.now()
    audit(
        session,
        action=f"topic.{status}",
        resource_type="topic",
        student_id=student_id,
        workspace_id=topic.workspace_id,
        resource_id=topic.id,
    )
    session.commit()
    session.refresh(topic)
    return topic_out(session, topic)


def approve_all(session: Session, student_id: UUID, workspace_id: UUID) -> int:
    require_workspace_owner(session, student_id, workspace_id)
    result = session.execute(
        update(Topic)
        .where(Topic.workspace_id == workspace_id, Topic.status == "draft")
        .values(status="approved", updated_at=func.now())
    )
    audit(
        session,
        action="topic.approve_all",
        resource_type="workspace",
        student_id=student_id,
        workspace_id=workspace_id,
        resource_id=workspace_id,
    )
    session.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


def delete_topic(session: Session, student_id: UUID, topic_id: UUID) -> None:
    topic = require_topic_owner(session, student_id, topic_id)
    workspace_id = topic.workspace_id
    session.delete(topic)
    session.flush()
    recompute_importance(session, workspace_id)
    audit(
        session,
        action="topic.delete",
        resource_type="topic",
        student_id=student_id,
        workspace_id=workspace_id,
        resource_id=topic_id,
    )
    session.commit()


# ---- importance ----------------------------------------------------------------------------------


def recompute_importance(session: Session, workspace_id: UUID) -> None:
    topics = session.scalars(select(Topic).where(Topic.workspace_id == workspace_id)).all()
    question_count = (
        session.scalar(
            select(func.count())
            .select_from(PastPaperQuestion)
            .where(PastPaperQuestion.workspace_id == workspace_id)
        )
        or 0
    )
    parent_of = {t.id: t.parent_id for t in topics}
    # A question examining a subtopic also examines its parent unit; count it once per topic.
    seen: set[tuple[UUID, UUID]] = set()
    mapped: list[MappedQuestion] = []
    for question_id, topic_id, marks, year in session.execute(
        select(
            PastPaperQuestionTopic.question_id,
            PastPaperQuestionTopic.topic_id,
            PastPaperQuestion.marks,
            PastPaperQuestion.year,
        )
        .join(PastPaperQuestion, PastPaperQuestion.id == PastPaperQuestionTopic.question_id)
        .where(PastPaperQuestion.workspace_id == workspace_id)
    ).all():
        for target in (topic_id, parent_of.get(topic_id)):
            if target is not None and (target, question_id) not in seen:
                seen.add((target, question_id))
                mapped.append(MappedQuestion(topic_id=target, marks=marks, year=year))
    decisions = compute_importance(
        [t.id for t in topics],
        mapped,
        workspace_question_count=question_count,
        student_overrides={t.id: t.importance for t in topics if t.importance_source == "student"},
    )
    for topic in topics:
        decision = decisions[topic.id]
        topic.importance = decision.importance
        topic.importance_source = decision.source
        topic.importance_basis = decision.basis


# ---- citations -------------------------------------------------------------------------------------


def list_topic_citations(session: Session, student_id: UUID, topic_id: UUID) -> list[CitationOut]:
    topic = require_topic_owner(session, student_id, topic_id)
    rows = session.execute(
        select(TopicChunkLink, Chunk, Document)
        .join(Chunk, Chunk.id == TopicChunkLink.chunk_id)
        .join(Document, Document.id == Chunk.document_id)
        .where(
            TopicChunkLink.topic_id == topic_id,
            Chunk.workspace_id == topic.workspace_id,
            Document.workspace_id == topic.workspace_id,
            Document.student_id == student_id,
        )
        .order_by(Document.filename, Chunk.chunk_index)
    ).all()
    return [
        CitationOut(
            chunk_id=chunk.id,
            document_id=document.id,
            document_name=document.filename,
            document_version=document.version,
            material_role=document.material_role,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            heading_path=list(chunk.heading_path or []),
            original_quote=link.quote or chunk.text_content,
            source_language=chunk.source_language,
            score=link.confidence,
        )
        for link, chunk, document in rows
    ]


def ensure_approved_topics(session: Session, workspace_id: UUID) -> list[Topic]:
    topics = list(
        session.scalars(
            select(Topic).where(Topic.workspace_id == workspace_id, Topic.status == "approved")
        )
    )
    if not topics:
        raise AppError(409, "INVALID_STATE", "Approve at least one topic first.")
    return topics
