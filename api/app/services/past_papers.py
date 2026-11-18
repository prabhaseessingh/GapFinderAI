"""Past-paper segmentation (questions with marks/year) and mapping to approved topics.

Groq proposes; code verifies: every question text must be a quote of its cited chunk, every
mapped topic must be an approved topic of the same workspace, and student mappings always win.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Document, PastPaperQuestion, PastPaperQuestionTopic, Topic
from app.providers.groq import UNTRUSTED_SOURCE_RULE, AiCallContext, GroqProvider, source_block
from app.schemas.topics import PastPaperMapping, PastPaperQuestionOut, PastPaperSegmentation
from app.services.retrieval import (
    EvidenceItem,
    normalize_text,
    quote_in_source,
    retrieve_role_evidence,
)
from app.services.topics import batch_evidence, recompute_importance
from app.services.workspaces import require_workspace_owner

SEGMENT_PROMPT_VERSION = "segment-past-paper-v1"
MAP_PROMPT_VERSION = "map-past-paper-v1"
SEGMENT_BATCH_CHARS = 12_000
MAP_BATCH_QUESTIONS = 40


def validate_segmentation(result: PastPaperSegmentation, batch: Sequence[EvidenceItem]) -> None:
    chunks = {item.chunk_id: item.original_quote for item in batch}
    for question in result.questions:
        source = chunks.get(question.chunk_id)
        if source is None or not quote_in_source(question.quote, source):
            raise ValueError("INVALID_QUESTION_QUOTE")
        if question.marks is not None and not 0 < question.marks <= 1000:
            raise ValueError("INVALID_QUESTION_MARKS")
        if question.year is not None and not 1900 <= question.year <= 2200:
            raise ValueError("INVALID_QUESTION_YEAR")


def segment_document(
    session: Session,
    provider: GroqProvider,
    student_id: UUID,
    workspace_id: UUID,
    document_id: UUID,
) -> int:
    document = session.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.workspace_id == workspace_id,
            Document.student_id == student_id,
            Document.material_role == "past_paper",
        )
    )
    if not document:
        return 0
    evidence = retrieve_role_evidence(
        session,
        student_id,
        workspace_id,
        "past_paper",
        states=("mapping", "ready"),
        document_ids=[document_id],
    )
    seen: set[str] = set()
    rows: list[PastPaperQuestion] = []
    for batch in batch_evidence(evidence, SEGMENT_BATCH_CHARS):
        context = AiCallContext(
            "segment_past_paper",
            SEGMENT_PROMPT_VERSION,
            student_id,
            workspace_id,
            [item.chunk_id for item in batch],
        )
        result = provider.structured(
            context,
            output=PastPaperSegmentation,
            system=f"You segment exam papers into individual questions. {UNTRUSTED_SOURCE_RULE}",
            user=(
                "Split the exam paper excerpts below into individual questions. For each question "
                "return the chunk_id of the <source> it appears in, its label as printed (e.g. "
                "'Q3(b)') or null, `quote`: the question text copied EXACTLY from that source "
                "(do not paraphrase, do not merge text across sources), marks only if printed next "
                "to the question, and the exam year only if printed in the paper. Ignore cover "
                "pages, instructions and answer spaces. Return an empty list if there are no "
                "questions.\n\n"
                + source_block(
                    [
                        {
                            "chunk_id": str(i.chunk_id),
                            "page": i.page_start,
                            "text": i.original_quote,
                        }
                        for i in batch
                    ]
                )
            ),
            validate=lambda r, b=batch: validate_segmentation(r, b),  # type: ignore[misc]
        )
        pages = {item.chunk_id: item.page_start for item in batch}
        for question in result.questions:
            key = normalize_text(question.quote).casefold()
            if key in seen:
                continue  # chunk overlap can surface the same question twice
            seen.add(key)
            rows.append(
                PastPaperQuestion(
                    workspace_id=workspace_id,
                    document_id=document.id,
                    document_version=document.version,
                    chunk_id=question.chunk_id,
                    position=len(rows),
                    question_label=question.label,
                    question_text=normalize_text(question.quote),
                    page=pages.get(question.chunk_id),
                    marks=question.marks,
                    year=question.year,
                )
            )
    session.execute(delete(PastPaperQuestion).where(PastPaperQuestion.document_id == document.id))
    session.add_all(rows)
    session.flush()
    return len(rows)


def validate_mapping(
    result: PastPaperMapping, question_ids: set[UUID], topic_ids: set[UUID]
) -> None:
    for assignment in result.assignments:
        if assignment.question_id not in question_ids:
            raise ValueError("UNKNOWN_QUESTION")
        if any(topic_id not in topic_ids for topic_id in assignment.topic_ids):
            raise ValueError("UNKNOWN_TOPIC")


def map_questions_to_topics(
    session: Session, provider: GroqProvider, student_id: UUID, workspace_id: UUID
) -> int:
    require_workspace_owner(session, student_id, workspace_id)
    topics = list(
        session.scalars(
            select(Topic).where(Topic.workspace_id == workspace_id, Topic.status == "approved")
        )
    )
    questions = list(
        session.scalars(
            select(PastPaperQuestion)
            .where(PastPaperQuestion.workspace_id == workspace_id)
            .order_by(PastPaperQuestion.document_id, PastPaperQuestion.position)
        )
    )
    question_ids = {q.id for q in questions}
    # Student mappings win: those questions are not re-mapped by the model.
    student_mapped = (
        set(
            session.scalars(
                select(PastPaperQuestionTopic.question_id).where(
                    PastPaperQuestionTopic.question_id.in_(question_ids),
                    PastPaperQuestionTopic.method == "student",
                )
            )
        )
        if question_ids
        else set()
    )
    session.execute(
        delete(PastPaperQuestionTopic).where(
            PastPaperQuestionTopic.question_id.in_(question_ids),
            PastPaperQuestionTopic.method == "model",
        )
    )
    pending = [q for q in questions if q.id not in student_mapped]
    linked = 0
    if topics and pending:
        topic_ids = {t.id for t in topics}
        topic_list = "\n".join(f"- id={t.id} title={t.title!r}" for t in topics)
        for start in range(0, len(pending), MAP_BATCH_QUESTIONS):
            batch = pending[start : start + MAP_BATCH_QUESTIONS]
            batch_ids = {q.id for q in batch}
            result = provider.structured(
                AiCallContext(
                    "map_past_paper",
                    MAP_PROMPT_VERSION,
                    student_id,
                    workspace_id,
                    [q.chunk_id for q in batch],
                ),
                output=PastPaperMapping,
                system=f"You classify exam questions into a student's approved syllabus topics. {UNTRUSTED_SOURCE_RULE}",
                user=(
                    "Approved topics:\n" + topic_list + "\n\nAssign each question below to the 1–3 "
                    "topics it actually assesses, using only the ids listed above. Use an empty "
                    "list when no topic fits. Return one assignment per question_id.\n\n"
                    + source_block(
                        [{"question_id": str(q.id), "text": q.question_text} for q in batch]
                    )
                ),
                validate=lambda r, ids=batch_ids: validate_mapping(r, ids, topic_ids),  # type: ignore[misc]
            )
            for assignment in result.assignments:
                for topic_id in dict.fromkeys(assignment.topic_ids):
                    session.add(
                        PastPaperQuestionTopic(
                            question_id=assignment.question_id, topic_id=topic_id, method="model"
                        )
                    )
                    linked += 1
    session.flush()
    recompute_importance(session, workspace_id)
    return linked


def list_questions(
    session: Session, student_id: UUID, workspace_id: UUID
) -> list[PastPaperQuestionOut]:
    require_workspace_owner(session, student_id, workspace_id)
    rows = session.execute(
        select(PastPaperQuestion, Document.filename)
        .join(Document, Document.id == PastPaperQuestion.document_id)
        .where(PastPaperQuestion.workspace_id == workspace_id, Document.student_id == student_id)
        .order_by(Document.created_at, PastPaperQuestion.position)
    ).all()
    links: dict[UUID, list[UUID]] = {}
    for question_id, topic_id in session.execute(
        select(PastPaperQuestionTopic.question_id, PastPaperQuestionTopic.topic_id).where(
            PastPaperQuestionTopic.question_id.in_([q.id for q, _ in rows])
        )
    ).all():
        links.setdefault(question_id, []).append(topic_id)
    return [
        PastPaperQuestionOut(
            id=q.id,
            document_id=q.document_id,
            document_name=name,
            label=q.question_label,
            question_text=q.question_text,
            page=q.page,
            marks=q.marks,
            year=q.year,
            topic_ids=links.get(q.id, []),
        )
        for q, name in rows
    ]
