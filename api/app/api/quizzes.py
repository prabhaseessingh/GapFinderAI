from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_fair_use, get_session, require_groq_configured
from app.core.auth import Actor, require_actor
from app.core.config import Settings
from app.core.errors import provider_unavailable
from app.core.fair_use import FairUse
from app.schemas.quiz import AttemptOut, CreateQuizRequest, QuizSummaryOut, SubmitResponseRequest
from app.services.jobs import GENERATE_QUIZ, QueueUnavailable, audit, enqueue
from app.services.quizzes import (
    attempt_view,
    list_quizzes,
    prepare_quiz,
    require_quiz,
    retry_evaluation,
    save_response,
    start_attempt,
    submit_attempt,
    summary,
)

router = APIRouter(tags=["quizzes"])


@router.post("/quizzes", response_model=QuizSummaryOut, status_code=status.HTTP_202_ACCEPTED)
def create_quiz(
    request: CreateQuizRequest,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
    settings: Settings = Depends(require_groq_configured),
    fair_use: FairUse = Depends(get_fair_use),
) -> QuizSummaryOut:
    from app.api.explain import student_timezone

    quiz = prepare_quiz(session, actor.user_id, request)
    # Counted only once the request is valid (student-local day); refunded if the queue is down.
    fair_use.consume(actor.user_id, "diagnostic", student_timezone(session, actor.user_id))
    audit(
        session,
        action="quiz.create",
        resource_type="quiz",
        student_id=actor.user_id,
        workspace_id=quiz.workspace_id,
        resource_id=quiz.id,
        metadata={
            "question_count": quiz.question_count,
            "timer_mode": quiz.timer_mode,
            "kind": quiz.kind,
        },
    )
    session.commit()
    try:
        enqueue(
            session,
            settings.redis_url,
            task_name=GENERATE_QUIZ,
            idempotency_key=str(quiz.id),
            args=[str(quiz.id)],
            student_id=actor.user_id,
            workspace_id=quiz.workspace_id,
        )
    except QueueUnavailable as error:
        quiz.state, quiz.failure_code = "generation_failed", "QUEUE_UNAVAILABLE"
        session.commit()
        fair_use.refund(actor.user_id, "diagnostic", student_timezone(session, actor.user_id))
        raise provider_unavailable(
            "The background worker is unavailable. Try again shortly."
        ) from error
    session.refresh(quiz)
    return summary(session, quiz)


@router.get("/quizzes/workspace/{workspace_id}", response_model=list[QuizSummaryOut])
def quizzes_for_workspace(
    workspace_id: UUID,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
) -> list[QuizSummaryOut]:
    return list_quizzes(session, actor.user_id, workspace_id)


@router.get("/quizzes/{quiz_id}", response_model=QuizSummaryOut)
def quiz_status(
    quiz_id: UUID, actor: Actor = Depends(require_actor), session: Session = Depends(get_session)
) -> QuizSummaryOut:
    return summary(session, require_quiz(session, actor.user_id, quiz_id))


@router.post(
    "/quizzes/{quiz_id}/attempts", response_model=AttemptOut, status_code=status.HTTP_201_CREATED
)
def begin_attempt(
    quiz_id: UUID, actor: Actor = Depends(require_actor), session: Session = Depends(get_session)
) -> AttemptOut:
    attempt = start_attempt(session, actor.user_id, quiz_id)
    session.commit()
    return attempt_view(session, actor.user_id, attempt.id)


@router.get("/attempts/{attempt_id}", response_model=AttemptOut)
def get_attempt(
    attempt_id: UUID, actor: Actor = Depends(require_actor), session: Session = Depends(get_session)
) -> AttemptOut:
    return attempt_view(session, actor.user_id, attempt_id)


@router.put(
    "/attempts/{attempt_id}/responses/{question_id}", status_code=status.HTTP_204_NO_CONTENT
)
def autosave(
    attempt_id: UUID,
    question_id: UUID,
    request: SubmitResponseRequest,
    actor: Actor = Depends(require_actor),
    session: Session = Depends(get_session),
) -> Response:
    save_response(session, actor.user_id, attempt_id, question_id, request.answer)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/attempts/{attempt_id}/submit", response_model=AttemptOut)
def submit(
    attempt_id: UUID, actor: Actor = Depends(require_actor), session: Session = Depends(get_session)
) -> AttemptOut:
    attempt = submit_attempt(session, actor.user_id, attempt_id)
    audit(
        session,
        action="attempt.submit",
        resource_type="attempt",
        student_id=actor.user_id,
        workspace_id=attempt.workspace_id,
        resource_id=attempt.id,
        metadata={"reason": attempt.submit_reason},
    )
    session.commit()
    return attempt_view(session, actor.user_id, attempt_id)


@router.post("/attempts/{attempt_id}/evaluate", response_model=AttemptOut)
def evaluate_again(
    attempt_id: UUID, actor: Actor = Depends(require_actor), session: Session = Depends(get_session)
) -> AttemptOut:
    attempt = retry_evaluation(session, actor.user_id, attempt_id)
    audit(
        session,
        action="attempt.evaluate_retry",
        resource_type="attempt",
        student_id=actor.user_id,
        workspace_id=attempt.workspace_id,
        resource_id=attempt.id,
    )
    session.commit()
    return attempt_view(session, actor.user_id, attempt_id)
