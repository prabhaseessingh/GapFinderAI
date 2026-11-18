"""Quiz + attempt lifecycle. Answers/rubrics/citations are never returned before submission."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, invalid_state, not_found
from app.db.models import (
    Attempt,
    Chunk,
    Document,
    GapReport,
    JobRun,
    Quiz,
    QuizQuestion,
    Response,
    Topic,
    Workspace,
)
from app.schemas.quiz import (
    AttemptOut,
    CreateQuizRequest,
    QuizSummaryOut,
    ReviewQuestionOut,
    StudentQuestionOut,
)
from app.schemas.topics import CitationOut
from app.services.quiz_policy import QUIZ_POLICY_VERSION
from app.services.workspaces import require_workspace_owner

ANSWER_ROLES = ("textbook", "notes")
GRACE_SECONDS = 5  # network slack after a timed deadline


def _owned_workspace(session: Session, student_id: UUID, workspace_id: UUID) -> Workspace:
    try:
        return require_workspace_owner(session, student_id, workspace_id)
    except LookupError as error:
        raise not_found("Workspace") from error


def prepare_quiz(session: Session, student_id: UUID, request: CreateQuizRequest) -> Quiz:
    workspace = _owned_workspace(session, student_id, request.workspace_id)
    if request.kind == "retest" and not session.scalar(
        select(func.count())
        .select_from(GapReport)
        .where(GapReport.workspace_id == workspace.id, GapReport.student_id == student_id)
    ):
        raise AppError(
            409,
            "INVALID_STATE",
            "Take a diagnostic first; a re-test targets the gaps in your Gap Report.",
        )
    approved = session.scalar(
        select(func.count())
        .select_from(Topic)
        .where(Topic.workspace_id == workspace.id, Topic.status == "approved")
    )
    if not approved:
        raise AppError(409, "INVALID_STATE", "Approve at least one topic in your topic map first.")
    if request.topic_ids:
        valid = session.scalar(
            select(func.count())
            .select_from(Topic)
            .where(
                Topic.workspace_id == workspace.id,
                Topic.status == "approved",
                Topic.id.in_(request.topic_ids),
            )
        )
        if valid != len(set(request.topic_ids)):
            raise not_found("Topic")
    answer_material = session.scalar(
        select(func.count())
        .select_from(Document)
        .where(
            Document.workspace_id == workspace.id,
            Document.student_id == student_id,
            Document.state == "ready",
            Document.material_role.in_(ANSWER_ROLES),
        )
    )
    if not answer_material:
        raise AppError(
            409,
            "INSUFFICIENT_WORKSPACE_EVIDENCE",
            "Questions are written only from your textbook chapters or notes. Upload one and wait until it is ready.",
            next_action="upload_or_select_material",
        )
    quiz = Quiz(
        workspace_id=workspace.id,
        student_id=student_id,
        state="blueprint_draft",
        question_count=request.question_count,
        locale=workspace.selected_locale,
        timer_mode=request.timer_mode,
        time_limit_seconds=request.time_limit_minutes * 60 if request.time_limit_minutes else None,
        blueprint={"requested_topic_ids": [str(t) for t in request.topic_ids or []]},
        policy_version=QUIZ_POLICY_VERSION,
        kind=request.kind,
    )
    session.add(quiz)
    session.flush()
    return quiz


def require_quiz(session: Session, student_id: UUID, quiz_id: UUID) -> Quiz:
    quiz = session.scalar(select(Quiz).where(Quiz.id == quiz_id, Quiz.student_id == student_id))
    if not quiz:
        raise not_found("Quiz")
    return quiz


def summary(session: Session, quiz: Quiz) -> QuizSummaryOut:
    latest = session.scalar(
        select(Attempt)
        .where(Attempt.quiz_id == quiz.id)
        .order_by(Attempt.created_at.desc())
        .limit(1)
    )
    slots = quiz.blueprint.get("slots", []) if isinstance(quiz.blueprint, dict) else []
    units = list(dict.fromkeys(str(s.get("unit_title")) for s in slots))
    return QuizSummaryOut(
        id=quiz.id,
        workspace_id=quiz.workspace_id,
        state=quiz.state,  # type: ignore[arg-type]
        kind=quiz.kind,  # type: ignore[arg-type]
        question_count=quiz.question_count,
        locale=quiz.locale,
        timer_mode=quiz.timer_mode,  # type: ignore[arg-type]
        time_limit_seconds=quiz.time_limit_seconds,
        failure_code=quiz.failure_code,
        created_at=quiz.created_at,
        not_tested=quiz.blueprint.get("not_tested", []) if isinstance(quiz.blueprint, dict) else [],
        unit_titles=units,
        latest_attempt_id=latest.id if latest else None,
        latest_attempt_state=latest.state if latest else None,
        latest_attempt_score=_attempt_percent(session, latest.id)
        if latest and latest.state == "evaluated"
        else None,
        progress_done=_progress(session, quiz),
    )


def _attempt_percent(session: Session, attempt_id: UUID) -> float | None:
    row = session.execute(
        select(func.sum(Response.score), func.sum(Response.max_score)).where(
            Response.attempt_id == attempt_id, Response.score.is_not(None)
        )
    ).one()
    return round(100 * float(row[0] or 0) / float(row[1]), 1) if row[1] else None


def _progress(session: Session, quiz: Quiz) -> int:
    if quiz.state != "generating":
        return quiz.question_count if quiz.state == "ready" else 0
    result = session.scalar(
        select(JobRun.result).where(
            JobRun.task_name == "gapfinder.generate_quiz", JobRun.idempotency_key == str(quiz.id)
        )
    )
    return int((result or {}).get("done", 0))


def list_quizzes(session: Session, student_id: UUID, workspace_id: UUID) -> list[QuizSummaryOut]:
    _owned_workspace(session, student_id, workspace_id)
    quizzes = session.scalars(
        select(Quiz)
        .where(Quiz.workspace_id == workspace_id, Quiz.student_id == student_id)
        .order_by(Quiz.created_at.desc())
    )
    return [summary(session, quiz) for quiz in quizzes]


# ---- attempts ------------------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def require_attempt(session: Session, student_id: UUID, attempt_id: UUID) -> Attempt:
    attempt = session.scalar(
        select(Attempt).where(Attempt.id == attempt_id, Attempt.student_id == student_id)
    )
    if not attempt:
        raise not_found("Attempt")
    return attempt


def start_attempt(session: Session, student_id: UUID, quiz_id: UUID) -> Attempt:
    quiz = require_quiz(session, student_id, quiz_id)
    if quiz.state != "ready":
        raise invalid_state("This quiz is not ready yet.")
    open_attempt = session.scalar(
        select(Attempt).where(
            Attempt.quiz_id == quiz.id,
            Attempt.student_id == student_id,
            Attempt.state == "in_progress",
        )
    )
    if open_attempt:
        return open_attempt  # resume, never fork a second open attempt
    if session.scalar(select(func.count()).select_from(Attempt).where(Attempt.quiz_id == quiz.id)):
        raise invalid_state("This diagnostic was already submitted. Start a new one to test again.")
    now = _now()
    attempt = Attempt(
        quiz_id=quiz.id,
        workspace_id=quiz.workspace_id,
        student_id=student_id,
        state="in_progress",
        started_at=now,
        deadline_at=now + timedelta(seconds=quiz.time_limit_seconds)
        if quiz.time_limit_seconds
        else None,
    )
    session.add(attempt)
    try:
        session.flush()
    except (
        IntegrityError
    ) as error:  # concurrent start: the partial unique index keeps one open attempt
        session.rollback()
        raise invalid_state("An attempt is already open for this quiz.") from error
    return attempt


def _expired(attempt: Attempt) -> bool:
    return attempt.deadline_at is not None and _now() > attempt.deadline_at + timedelta(
        seconds=GRACE_SECONDS
    )


def _finalise(session: Session, attempt: Attempt, reason: str) -> bool:
    """Compare-and-set in_progress -> submitted. Returns False if another request won."""
    submitted_at = (
        min(_now(), attempt.deadline_at)
        if reason == "time_limit" and attempt.deadline_at
        else _now()
    )
    result = session.execute(
        update(Attempt)
        .where(Attempt.id == attempt.id, Attempt.state == "in_progress")
        .values(
            state="submitted",
            submitted_at=submitted_at,
            submit_reason=reason,
            elapsed_seconds=max(0, int((submitted_at - attempt.started_at).total_seconds())),
            updated_at=func.now(),
        )
    )
    session.flush()
    session.refresh(attempt)
    return bool(result.rowcount)  # type: ignore[attr-defined]


def queue_evaluation(session: Session, attempt: Attempt) -> None:
    """Hand a locked attempt to the worker. A broker outage is visible and retryable."""
    from app.core.config import get_settings
    from app.services.jobs import EVALUATE_ATTEMPT, QueueUnavailable, enqueue

    try:
        enqueue(
            session,
            get_settings().redis_url,
            task_name=EVALUATE_ATTEMPT,
            idempotency_key=str(attempt.id),
            args=[str(attempt.id)],
            student_id=attempt.student_id,
            workspace_id=attempt.workspace_id,
        )
    except QueueUnavailable:
        session.execute(
            update(Attempt)
            .where(Attempt.id == attempt.id, Attempt.state == "submitted")
            .values(
                state="evaluation_failed", failure_code="QUEUE_UNAVAILABLE", updated_at=func.now()
            )
        )
        session.commit()
        session.refresh(attempt)


def enforce_deadline(session: Session, attempt: Attempt) -> None:
    if attempt.state == "in_progress" and _expired(attempt):
        won = _finalise(session, attempt, "time_limit")
        session.commit()
        if won:
            queue_evaluation(session, attempt)


def _validate_answer(question: QuizQuestion, answer: Any) -> Any:
    if answer is None:
        return None
    if question.question_type == "mcq":
        ids = {o["id"] for o in question.options or []}
        if not isinstance(answer, str) or answer not in ids:
            raise AppError(422, "VALIDATION_ERROR", "Choose one of the options.")
    elif question.question_type == "true_false":
        if not isinstance(answer, bool):
            raise AppError(422, "VALIDATION_ERROR", "Choose true or false.")
    else:
        if not isinstance(answer, str) or len(answer) > 5000:
            raise AppError(422, "VALIDATION_ERROR", "Answers can be up to 5,000 characters.")
    return answer


def save_response(
    session: Session, student_id: UUID, attempt_id: UUID, question_id: UUID, answer: Any
) -> None:
    attempt = require_attempt(session, student_id, attempt_id)
    enforce_deadline(session, attempt)
    if attempt.state != "in_progress":
        raise invalid_state("This attempt is locked; answers can no longer change.")
    question = session.scalar(
        select(QuizQuestion).where(
            QuizQuestion.id == question_id, QuizQuestion.quiz_id == attempt.quiz_id
        )
    )
    if not question:
        raise not_found("Question")
    value = _validate_answer(question, answer)
    session.execute(
        text("""
        INSERT INTO responses (attempt_id, question_id, workspace_id, answer, updated_at)
        VALUES (:attempt, :question, :workspace, CAST(:answer AS jsonb), now())
        ON CONFLICT (attempt_id, question_id) DO UPDATE SET answer = excluded.answer, updated_at = now()
        """),
        {
            "attempt": attempt.id,
            "question": question.id,
            "workspace": attempt.workspace_id,
            "answer": None if value is None else json.dumps(value),
        },
    )
    session.commit()


def submit_attempt(session: Session, student_id: UUID, attempt_id: UUID) -> Attempt:
    """Idempotent: a second submit returns the already-locked attempt."""
    attempt = require_attempt(session, student_id, attempt_id)
    if attempt.state == "in_progress":
        won = _finalise(session, attempt, "time_limit" if _expired(attempt) else "student")
        session.commit()
        if won:
            queue_evaluation(session, attempt)
    return attempt


def retry_evaluation(session: Session, student_id: UUID, attempt_id: UUID) -> Attempt:
    attempt = require_attempt(session, student_id, attempt_id)
    if attempt.state != "evaluation_failed":
        raise invalid_state("Only a failed evaluation can be retried.")
    session.execute(
        update(Attempt)
        .where(Attempt.id == attempt.id, Attempt.state == "evaluation_failed")
        .values(state="submitted", failure_code=None, updated_at=func.now())
    )
    session.commit()
    session.refresh(attempt)
    queue_evaluation(session, attempt)
    return attempt


def attempt_view(session: Session, student_id: UUID, attempt_id: UUID) -> AttemptOut:
    attempt = require_attempt(session, student_id, attempt_id)
    enforce_deadline(session, attempt)
    quiz = require_quiz(session, student_id, attempt.quiz_id)
    questions = list(
        session.scalars(
            select(QuizQuestion)
            .where(QuizQuestion.quiz_id == quiz.id)
            .order_by(QuizQuestion.position)
        )
    )
    responses = {
        r.question_id: r
        for r in session.scalars(select(Response).where(Response.attempt_id == attempt.id))
    }
    answers = {str(qid): r.answer for qid, r in responses.items()}
    locked = attempt.state != "in_progress"
    shown: list[StudentQuestionOut] | list[ReviewQuestionOut]
    if locked:
        shown = [_review(session, q, student_id, responses.get(q.id)) for q in questions]
    else:
        shown = [
            StudentQuestionOut(
                id=q.id,
                position=q.position,
                topic_title=q.topic_title,
                question_type=q.question_type,  # type: ignore[arg-type]
                cognitive_level=q.cognitive_level,  # type: ignore[arg-type]
                prompt=q.prompt,
                options=q.options,  # type: ignore[arg-type]
                max_score=q.max_score,
            )
            for q in questions
        ]
    return AttemptOut(
        id=attempt.id,
        quiz_id=quiz.id,
        workspace_id=attempt.workspace_id,
        state=attempt.state,
        started_at=attempt.started_at,
        deadline_at=attempt.deadline_at,
        submitted_at=attempt.submitted_at,
        submit_reason=attempt.submit_reason,
        elapsed_seconds=attempt.elapsed_seconds,
        server_now=_now(),
        timer_mode=quiz.timer_mode,  # type: ignore[arg-type]
        questions=shown,
        answers=answers,
        quiz_kind=quiz.kind,
        failure_code=attempt.failure_code,
        score=_sum([r.score for r in responses.values()]) if attempt.state == "evaluated" else None,
        max_score=sum(q.max_score for q in questions) if attempt.state == "evaluated" else None,
        report_id=session.scalar(select(GapReport.id).where(GapReport.attempt_id == attempt.id)),
    )


def _sum(values: list[float | None]) -> float:
    return round(sum(v for v in values if v is not None), 2)


def resolve_citations(
    session: Session, workspace_id: UUID, student_id: UUID, refs: list[dict[str, str]]
) -> list[CitationOut]:
    """Cited chunks still owned by the student; deleted sources are dropped (invariant 7)."""
    citations: list[CitationOut] = []
    for ref in refs:
        row = session.execute(
            select(Chunk, Document)
            .join(Document, Document.id == Chunk.document_id)
            .where(
                Chunk.id == UUID(ref["chunk_id"]),
                Document.student_id == student_id,
                Chunk.workspace_id == workspace_id,
            )
        ).first()
        if row is None:
            continue
        chunk, document = row
        citations.append(
            CitationOut(
                chunk_id=chunk.id,
                document_id=document.id,
                document_name=document.filename,
                document_version=document.version,
                material_role=document.material_role,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                heading_path=list(chunk.heading_path or []),
                original_quote=ref["quote"],
                source_language=chunk.source_language,
                score=1.0,
            )
        )
    return citations


def _review(
    session: Session, question: QuizQuestion, student_id: UUID, response: Response | None = None
) -> ReviewQuestionOut:
    citations = resolve_citations(session, question.workspace_id, student_id, question.citations)
    key = question.correct_answer or {}
    return ReviewQuestionOut(
        id=question.id,
        position=question.position,
        topic_title=question.topic_title,
        question_type=question.question_type,  # type: ignore[arg-type]
        cognitive_level=question.cognitive_level,  # type: ignore[arg-type]
        prompt=question.prompt,
        options=question.options,  # type: ignore[arg-type]
        max_score=question.max_score,
        correct_option_id=key.get("option_id"),
        correct_boolean=key.get("boolean"),
        model_answer=key.get("model_answer"),
        rubric=question.rubric,  # type: ignore[arg-type]
        explanation=question.explanation,
        citations=citations,
        **_graded(session, question, student_id, response),
    )


def _graded(
    session: Session, question: QuizQuestion, student_id: UUID, response: Response | None
) -> dict[str, Any]:
    if response is None or response.evaluated_at is None:
        return {}
    detail = response.evaluation or {}
    return {
        "score": response.score,
        "verdict": response.verdict,
        "evaluator": response.evaluator,
        "confidence": response.confidence,
        "feedback": detail.get("feedback"),
        "criteria": detail.get("criteria", []),
        "evaluation_citations": resolve_citations(
            session, question.workspace_id, student_id, detail.get("citations", [])
        ),
    }
